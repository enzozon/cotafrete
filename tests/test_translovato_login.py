"""O login da Translovato, e o que ele faz com um "não".

Medido no site real em 22/09/2026, com a conta de produção, enquanto se
investigavam as cotações #200 a #203 — quatro erros seguidos, nenhum acerto
entre eles. A resposta do portal ao login era esta:

    {"status":false,"alterar_senha":true,"class":"warning",
     "title":"Oops!","message":"Alterar senha"}

E a tela, em letras garrafais: "SUA SENHA EXPIROU! PREENCHA OS CAMPOS ABAIXO
PARA ALTERÁ-LA."

O adapter esperava essa resposta e NUNCA a lia. Seguia como se tivesse
entrado, ia para o formulário, era devolvido para /home e relatava "sessão
não persistiu até o formulário" — uma frase que manda procurar rede, cookie e
timeout quando a Translovato tinha dito o problema em português.

Pior que a frase errada era a classificação: erro genérico REPETE (ver
`core.retentativa.vale_repetir`). Cada cotação fazia três logins recusados;
as quatro fizeram doze. É assim que uma conta é bloqueada — e aí não é uma
transportadora que falha, são todas as cotações dessa conta.

Nada aqui toca o site: o formulário é de mentira e a resposta é servida por
`page.route`.
"""

from __future__ import annotations

import pytest

from carriers.base import CredencialRecusada
from carriers.translovato.adapter import TranslovatoAdapter

# As respostas REAIS do portal, copiadas do diagnóstico de 22/09/2026.
SENHA_EXPIRADA = ('{"status":false,"alterar_senha":true,"class":"warning",'
                  '"title":"Oops!","message":"Alterar senha"}')
SENHA_ERRADA = ('{"status":false,"class":"warning","title":"Oops!",'
                '"message":"Usuário ou senha inválidos"}')
LOGIN_OK = '{"status":true}'

FORMULARIO = """<!doctype html><meta charset="utf-8"><title>Portal</title>
<form id="login-portal">
  <input id="cnpj" name="cnpj">
  <input id="user" name="user">
  <input name="password" type="password">
  <button class="common-button" type="button">Entrar</button>
</form>
<script>
  document.querySelector('#login-portal button.common-button')
    .addEventListener('click', () => {
      fetch('/portal-do-cliente/login', {method: 'POST', body: '{}'});
    });
</script>
"""


@pytest.fixture
def navegador():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def _entrar(navegador, resposta: str, monkeypatch):
    """Roda `_entrar` contra o portal de mentira. Devolve a exceção, ou None.

    As credenciais são de fachada: o que está sob teste é o que o adapter faz
    com a RESPOSTA, não o que ele manda."""
    monkeypatch.setenv("TRANSLOVATO_CNPJ", "08.310.365/0001-24")
    monkeypatch.setenv("TRANSLOVATO_USUARIO", "PROVA")
    monkeypatch.setenv("TRANSLOVATO_SENHA", "segredo12")

    page = navegador.new_context().new_page()
    page.set_default_timeout(5_000)
    page.route("https://www.translovato.com.br/**", lambda rota: rota.fulfill(
        status=200,
        content_type=("application/json"
                      if "/portal-do-cliente/login" in rota.request.url
                      else "text/html"),
        body=(resposta if "/portal-do-cliente/login" in rota.request.url
              else FORMULARIO)))
    try:
        TranslovatoAdapter()._entrar(page)
        return None
    except Exception as exc:
        return exc


# -------------------------------------------------- a senha que expirou
def test_senha_expirada_vira_credencial_recusada(navegador, monkeypatch):
    """O caso das #200 a #203.

    `CredencialRecusada` e não RuntimeError: é o TIPO que decide se a cotação
    vai ser repetida. Erro genérico ganha três tentativas, ou seja, três
    logins recusados por cotação — o caminho mais curto para a conta da
    Ventura ser bloqueada."""
    erro = _entrar(navegador, SENHA_EXPIRADA, monkeypatch)

    assert isinstance(erro, CredencialRecusada), (
        f"a senha expirada tinha que parar o login aqui, veio: {erro!r}")


def test_a_mensagem_diz_o_que_aconteceu_e_o_que_fazer(navegador, monkeypatch):
    """"sessão não persistiu até o formulário" mandava procurar rede e cookie.

    Quem lê precisa de duas coisas: que a senha expirou, e que a solução é
    entrar no site à mão e trocá-la — o robô não pode fazer isso sozinho."""
    erro = str(_entrar(navegador, SENHA_EXPIRADA, monkeypatch))

    assert "senha" in erro.lower()
    assert "expir" in erro.lower()
    assert "TRANSLOVATO_SENHA" in erro, (
        "a mensagem precisa dizer qual variável do .env atualizar depois")


def test_a_mensagem_nao_mostra_a_senha(navegador, monkeypatch):
    """O texto vai para o banco, para a tela e para o print. A senha, não."""
    erro = str(_entrar(navegador, SENHA_EXPIRADA, monkeypatch))

    assert "segredo12" not in erro


# ----------------------------------------------------- a senha recusada
def test_senha_invalida_tambem_nao_repete(navegador, monkeypatch):
    """Qualquer `status:false` é a Translovato dizendo não. Repetir dá o
    mesmo não, três vezes mais perto do bloqueio."""
    erro = _entrar(navegador, SENHA_ERRADA, monkeypatch)

    assert isinstance(erro, CredencialRecusada)


def test_a_recusa_repete_as_palavras_do_site(navegador, monkeypatch):
    """Quem for investigar precisa da frase da Translovato, não da nossa
    paráfrase dela."""
    erro = str(_entrar(navegador, SENHA_ERRADA, monkeypatch))

    assert "Usuário ou senha inválidos" in erro


# -------------------------------------------------------- caminho feliz
def test_login_aceito_segue_normal(navegador, monkeypatch):
    """A guarda não pode virar uma trava que derruba login bom."""
    assert _entrar(navegador, LOGIN_OK, monkeypatch) is None


def test_resposta_que_nao_e_json_nao_derruba_o_login(navegador, monkeypatch):
    """Se a Translovato mudar o formato da resposta, o certo é SEGUIR e deixar
    a checagem da URL decidir — e não recusar um login que talvez tenha dado
    certo. Na dúvida o adapter tenta; só o "não" explícito para tudo."""
    assert _entrar(navegador, "<html>manutenção</html>", monkeypatch) is None
