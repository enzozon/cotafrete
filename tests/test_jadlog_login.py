"""O que o adapter da Jadlog pode e não pode chamar de "senha recusada".

A cotação #56 (28/08/2026) parou com "Precisa de alguém — a senha desta
transportadora precisa ser conferida". O Enzo entrou à mão com a MESMA senha
do .env e o painel abriu normalmente.

O print que o próprio sistema guardou mostra por quê: os dois campos
preenchidos, os dois com o ✓ verde de validação do site, o botão Entrar com
foco — e nenhuma mensagem de erro na tela. O site não recusou nada; ele só
não saiu do lugar. A acusação era um chute do adapter, tirado de "a URL ainda
tem /login e o campo de e-mail não está vazio".

Medido em 28/08/2026 com as credenciais reais: a autenticação é um
`POST .../api/Usuario/LoginJWT` que responde **200 com token em 1 segundo**.
Esse status é a única prova de recusa que existe — a tela não diz nada.

Estes testes rodam contra um login de mentira servido por `page.route`, na
mesma origem da Jadlog. Não tocam no site nem na conta da Ventura: um login
recusado de verdade custaria uma tentativa na conta, e é justamente a conta
que a `CredencialRecusada` existe para proteger.
"""

from __future__ import annotations

import pytest

from carriers.base import CredencialRecusada
from carriers.jadlog import painel as p

PAGINA_LOGIN = """<!doctype html><meta charset="utf-8"><title>Entrar</title>
<form>
  <label>E-mail <input type="email"></label>
  <label>Senha <input type="password"></label>
  <button type="button" id="entrar">Entrar</button>
</form>
<script>
  document.getElementById('entrar').addEventListener('click', async () => {
    const r = await fetch('/api/Usuario/LoginJWT', {method: 'POST', body: '{}'});
    // O painel só abre quando o site MANDA abrir. Um 200 que não navega é o
    // caso da #56: autenticou e a tela ficou parada.
    if (r.ok && document.body.dataset.navega === 'sim') location.href = '/painel';
  });
</script>
"""


@pytest.fixture
def navegador():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p_:
        browser = p_.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(autouse=True)
def credenciais(monkeypatch):
    monkeypatch.setenv("JADLOG_PAINEL_USUARIO", "adm2@exemplo.com.br")
    monkeypatch.setenv("JADLOG_PAINEL_SENHA", "senha-de-mentira")


@pytest.fixture(autouse=True)
def relogio_curto(monkeypatch):
    """Encurta só as ESPERAS. A decisão testada não depende delas.

    Sem isto cada tentativa que falha custa os 15s reais do timeout de login,
    e o arquivo inteiro passaria de um minuto."""
    monkeypatch.setattr(p, "TIMEOUT_LOGIN_MS", 1_200)
    monkeypatch.setattr(p, "ESPERA_HIDRATACAO_MS", 60)


def _entrar(navegador, *, status_login: int, navega: bool):
    """Roda `_entrar` contra o login de mentira e devolve o que aconteceu."""
    page = navegador.new_context().new_page()
    page.set_default_timeout(5_000)

    corpo = PAGINA_LOGIN.replace(
        "<form>", f'<body data-navega="{"sim" if navega else "nao"}"><form>')

    def rotear(route):
        url = route.request.url
        if "Usuario/LoginJWT" in url:
            route.fulfill(status=status_login, content_type="application/json",
                          body='{"token":"eyJfake"}' if status_login == 200
                               else '{"erro":"nao autorizado"}')
        elif url.rstrip("/").endswith("/painel"):
            route.fulfill(status=200, content_type="text/html",
                          body="<!doctype html><title>Painel</title><h1>ok</h1>")
        else:
            route.fulfill(status=200, content_type="text/html", body=corpo)

    page.route("https://jadlogentregas.com.br/**", rotear)
    try:
        p.JadlogPainelAdapter()._entrar(page)
        return None                      # entrou, sem exceção
    except Exception as exc:
        return exc


# ----------------------------------------------------------------- o bug #56
def test_login_que_autenticou_nao_pode_virar_senha_recusada(navegador):
    """200 com token e a tela parada NÃO é senha errada.

    É exatamente a #56: a Jadlog autenticou e o painel não abriu. Chamar isso
    de credencial recusada manda o vendedor avisar que a senha está errada —
    e, pior, `CredencialRecusada` BLOQUEIA a retentativa, então um travamento
    passageiro mata a transportadora na cotação inteira. Medido em
    28/08/2026: a tentativa seguinte entrou em 1 segundo."""
    erro = _entrar(navegador, status_login=200, navega=False)

    assert erro is not None, "a tela não navegou; tinha que falhar de algum jeito"
    assert not isinstance(erro, CredencialRecusada), (
        f"acusou a senha sem o site ter recusado nada: {erro}")


def test_a_falha_de_painel_que_nao_abre_conta_o_que_viu(navegador):
    """A mensagem tem que dizer o que foi observado, não o que se imagina.

    "senha trocada, conta bloqueada, ou outra sessão aberta" eram três
    palpites; nenhum deles foi medido. O que se sabe é o status HTTP."""
    erro = _entrar(navegador, status_login=200, navega=False)

    assert "200" in str(erro), f"a mensagem não diz o que a Jadlog respondeu: {erro}"


# --------------------------------------------- a recusa de verdade continua
def test_senha_recusada_de_verdade_continua_bloqueando(navegador):
    """401 é o site dizendo não. Aí repetir martela a conta da Ventura.

    Este é o caso para o qual `CredencialRecusada` foi criada, e ele tem que
    continuar valendo depois do conserto."""
    erro = _entrar(navegador, status_login=401, navega=False)

    assert isinstance(erro, CredencialRecusada), (
        f"401 é recusa provada e tem que bloquear a retentativa: {erro!r}")


def test_clique_que_nao_submeteu_pode_repetir(navegador):
    """Sem nenhuma resposta de autenticação, o formulário nem foi enviado.

    A própria docstring de `CredencialRecusada` em carriers/base.py manda
    repetir esse caso: "Login que não chegou a ser enviado (campo vazio,
    página que não carregou) é erro comum e deve repetir"."""
    page = navegador.new_context().new_page()
    page.set_default_timeout(5_000)
    # Botão sem nenhum handler: clica e não acontece nada.
    page.route("https://jadlogentregas.com.br/**", lambda r: r.fulfill(
        status=200, content_type="text/html",
        body="""<!doctype html><meta charset="utf-8"><form>
                <input type="email"><input type="password">
                <button type="button">Entrar</button></form>"""))

    with pytest.raises(Exception) as capturado:
        p.JadlogPainelAdapter()._entrar(page)

    assert not isinstance(capturado.value, CredencialRecusada), (
        "clique que não gerou requisição nenhuma não prova recusa de senha")


# ------------------------------------------------------------ caminho feliz
def test_login_que_da_certo_entra_sem_erro(navegador):
    assert _entrar(navegador, status_login=200, navega=True) is None
