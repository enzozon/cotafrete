"""O script do Tampermonkey: o formulário da Della Volpe abre já preenchido.

Decidido em 23/09/2026 (todos no Chrome, com permissão para extensão): no
lugar de "arraste o favorito, abra a aba, clique no favorito nela", o
vendedor instala o script uma vez e só clica em "Abrir formulário".

O navegador de teste faz o papel do Tampermonkey: abre o formulário de
teste (fixtures/dellavolpe_formulario.html, o DOM real do site) SERVIDO
COMO https://dellavolpe.com.br, e roda o script depois do load — o mesmo
momento do `@run-at document-idle`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from carriers.dellavolpe import bookmarklet as dv
from core.banco import Banco
from tests.apoio import entrar
from tests.test_dellavolpe_bookmarklet import COTACAO

FORMULARIO = (Path(__file__).parent / "fixtures"
              / "dellavolpe_formulario.html").read_text(encoding="utf-8")
SCRIPT = dv.userscript("http://cotafrete.local/extensao/"
                       "cotafrete-dellavolpe.user.js")


# ------------------------------------------------------------- o arquivo
def test_o_cabecalho_e_o_que_o_tampermonkey_le():
    cabecalho = SCRIPT.split("// ==/UserScript==")[0]

    assert cabecalho.startswith("// ==UserScript==")
    assert f"@version      {dv.VERSAO_USERSCRIPT}" in cabecalho
    assert "@match        https://dellavolpe.com.br/*" in cabecalho
    assert "@match        https://www.dellavolpe.com.br/*" in cabecalho
    assert "@grant        none" in cabecalho


def test_ele_se_atualiza_sozinho_pelo_cotafrete():
    """Uma correção no script chega a todas as máquinas sem reinstalar."""
    url = "http://cotafrete.local/extensao/cotafrete-dellavolpe.user.js"

    assert f"@updateURL    {url}" in SCRIPT
    assert f"@downloadURL  {url}" in SCRIPT


def test_preenche_com_o_mesmo_codigo_do_favorito():
    """Dois preenchimentos seriam dois lugares para o site quebrar."""
    assert dv.SCRIPT_JS in SCRIPT


# -------------------------------------------------------------- a rota
@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    return modulo


def test_a_rota_entrega_o_script_sem_login(app_web):
    """O Tampermonkey busca a versão nova sozinho, sem o cookie do
    vendedor."""
    resposta = TestClient(app_web.app).get(
        "/extensao/cotafrete-dellavolpe.user.js")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/javascript")
    assert resposta.text.startswith("// ==UserScript==")
    assert ("@updateURL    http://testserver/extensao/"
            "cotafrete-dellavolpe.user.js") in resposta.text


def test_o_botao_usa_um_endereco_por_versao_e_nenhum_cache(app_web):
    """23/09/2026: o botão abriu a 1.0.0 com a 1.1.0 no servidor, e sem
    "Atualizar" não havia como sair dela. Endereço novo a cada versão, e
    proibido guardar."""
    cliente = TestClient(app_web.app)
    versionado = cliente.get(f"/extensao/cotafrete-dellavolpe-"
                             f"{dv.VERSAO_USERSCRIPT}.user.js")
    fixo = cliente.get("/extensao/cotafrete-dellavolpe.user.js")

    assert versionado.status_code == 200
    assert versionado.text == fixo.text
    for resposta in (versionado, fixo):
        assert "no-store" in resposta.headers["cache-control"]


def test_o_update_url_e_sempre_o_fixo(app_web):
    """O Tampermonkey guarda o @updateURL para sempre. Se fosse o endereço
    da versão, toda máquina ficaria olhando um arquivo que nunca muda de
    nome — e nunca veria a versão seguinte."""
    texto = TestClient(app_web.app).get(
        "/extensao/cotafrete-dellavolpe-0.9.0.user.js").text

    assert ("@updateURL    http://testserver/extensao/"
            "cotafrete-dellavolpe.user.js") in texto
    assert f"@version      {dv.VERSAO_USERSCRIPT}" in texto


def test_o_script_nao_carrega_dado_de_cotacao(app_web):
    """Sem login e cacheado pelo Tampermonkey: não pode ter CNPJ nem nada
    de cliente. Os dados vão no link de CADA cotação, não no script."""
    app_web.banco.salvar_cotacao("enzo", COTACAO)

    texto = TestClient(app_web.app).get(
        "/extensao/cotafrete-dellavolpe.user.js").text

    assert COTACAO["cnpj_remetente"] not in texto
    assert COTACAO["email"] not in texto


def test_a_tela_ensina_a_instalar(app_web):
    c = entrar(TestClient(app_web.app), app_web)
    cid = app_web.banco.salvar_cotacao("enzo", COTACAO)

    html = " ".join(c.get(f"/dellavolpe/{cid}").text.split())

    assert (f'href="/extensao/cotafrete-dellavolpe-{dv.VERSAO_USERSCRIPT}'
            f'.user.js"') in html
    assert "chromewebstore.google.com/detail/tampermonkey" in html
    assert "Permitir scripts do usuário" in html
    # o favorito continua como plano B
    assert "javascript:" in html


# ------------------------------------------------- no navegador de verdade
@pytest.fixture
def navegador():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def aba(navegador):
    """Uma aba em que https://dellavolpe.com.br é o formulário de teste."""
    contexto = navegador.new_context(locale="pt-BR")
    contexto.route("https://dellavolpe.com.br/**", lambda rota: rota.fulfill(
        status=200, content_type="text/html; charset=utf-8",
        body=FORMULARIO))
    pg = contexto.new_page()
    pg.set_default_timeout(8_000)
    pg.avisos = []
    pg.on("dialog", lambda d: (pg.avisos.append(d.message), d.accept()))
    yield pg
    contexto.close()


def _abrir(aba, url: str) -> None:
    aba.goto(url, wait_until="load")
    aba.evaluate(SCRIPT)              # o Tampermonkey, em document-idle
    aba.wait_for_timeout(3_500)


def test_a_aba_nasce_preenchida(aba):
    _abrir(aba, dv.url_formulario(COTACAO))

    assert aba.locator('[name="nome"]').input_value() == "Enzo Zon"
    assert aba.locator('[name="servico"]').input_value() == "Fracionado -LTL"
    assert aba.locator('[name="cidade_origem"]').input_value() == "Vila Velha"
    assert aba.locator('[name="cidade_destino"]').input_value() == "São Paulo"
    assert aba.locator('[name="peso"]').input_value() == "13"


def test_avisa_que_preencheu_e_que_o_captcha_e_com_voce(aba):
    _abrir(aba, dv.url_formulario(COTACAO))

    assert any("preencheu os campos" in a for a in aba.avisos)


def test_visita_normal_ao_site_nao_mexe_em_nada(aba):
    """Sem dados no link o vendedor está só navegando no site deles: nem
    preenche, nem mostra aviso."""
    _abrir(aba, "https://dellavolpe.com.br/")

    assert aba.locator('[name="nome"]').input_value() == ""
    assert aba.avisos == []


def test_na_tela_do_cotafrete_so_marca_que_esta_instalado(navegador):
    """Lá ele não preenche nada: só marca o <html>, e a tela esconde o passo
    a passo da instalação."""
    pg = navegador.new_page()
    pg.set_content(
        '<html><body><div class="so-sem">instale</div>'
        '<div class="so-com">instalado</div>'
        '<style>body:not(.com-script) .so-com{display:none}'
        'body.com-script .so-sem{display:none}</style>'
        '<script>(function(){var v=15;(function o(){'
        'if(document.documentElement.getAttribute("data-cotafrete-dv"))'
        '{document.body.classList.add("com-script")}'
        'else if(v-->0){setTimeout(o,200)}})()})()</script>'
        '</body></html>')

    pg.evaluate(SCRIPT)
    pg.wait_for_timeout(600)

    assert (pg.locator("html").get_attribute("data-cotafrete-dv")
            == dv.VERSAO_USERSCRIPT)
    assert pg.locator(".so-sem").is_hidden()
    assert pg.locator(".so-com").is_visible()


def test_a_tela_real_troca_de_versao_com_o_script(navegador, app_web):
    """A mesma checagem, com o HTML que a rota /dellavolpe/N entrega de
    verdade (sem o servidor: o HTML vai direto para a aba)."""
    c = entrar(TestClient(app_web.app), app_web)
    cid = app_web.banco.salvar_cotacao("enzo", COTACAO)
    html = c.get(f"/dellavolpe/{cid}").text
    pg = navegador.new_page()
    pg.route("**/*", lambda rota: rota.fulfill(status=204))  # sem CSS/imagens
    pg.set_content(html)

    antes = pg.locator("text=Instalar o script do Cotafrete").is_visible()
    pg.evaluate(SCRIPT)
    pg.wait_for_timeout(800)

    assert antes is True
    assert pg.locator("text=Instalar o script do Cotafrete").is_hidden()
    assert pg.locator("text=está instalado neste navegador").is_visible()


# ------------------------------- o site real: vários formulários no HTML
# O formulário de teste tem UM formulário. O site da Della Volpe tem uns dez
# no mesmo HTML (um por serviço, mais o "fale conosco" do rodapé), com campos
# de mesmo name. É isso que fazia o nome aparecer "às vezes sim, às vezes
# não" (23/09/2026): o preenchimento ia para o primeiro campo da página, num
# formulário escondido.
FORMULARIO_ESCONDIDO_ANTES = """() => {
    const f = document.createElement('form');
    f.style.display = 'none';
    f.innerHTML = '<select name="servico"><option value="">x</option>'
                + '<option>Fracionado -LTL</option></select>'
                + '<input name="nome"><input name="email">'
                + '<input name="whatsapp">';
    document.body.prepend(f);
}"""

# A re-renderização do Contact Form 7: escolher o serviço revela os campos
# condicionais e, logo depois, zera o que estava no formulário.
SITE_APAGA_DEPOIS_DO_SERVICO = """() => {
    const visivel = [...document.querySelectorAll('select[name="servico"]')]
        .find(s => s.offsetWidth || s.offsetHeight);
    const form = visivel.closest('form');
    visivel.addEventListener('change', () => setTimeout(() => {
        form.querySelector('[name="nome"]').value = '';
        form.querySelector('[name="whatsapp"]').value = '';
    }, 300), { once: true });
}"""


def _abrir_como_o_site_real(aba, url: str, *preparos: str) -> None:
    aba.goto(url, wait_until="load")
    for preparo in preparos:
        aba.evaluate(preparo)
    aba.evaluate(SCRIPT)
    aba.wait_for_timeout(3_500)


def _no_formulario_visivel(aba, nome: str) -> str:
    return aba.evaluate("""nome => {
        const s = [...document.querySelectorAll('select[name="servico"]')]
            .find(x => x.offsetWidth || x.offsetHeight);
        return s.closest('form').querySelector(`[name="${nome}"]`).value;
    }""", nome)


def test_preenche_o_formulario_visivel_e_nao_o_escondido(aba):
    _abrir_como_o_site_real(aba, dv.url_formulario(COTACAO),
                            FORMULARIO_ESCONDIDO_ANTES)

    assert _no_formulario_visivel(aba, "nome") == "Enzo Zon"
    assert _no_formulario_visivel(aba, "email") == "vendas@ventura.com.br"
    assert _no_formulario_visivel(aba, "whatsapp") == "(27) 99988-7766"
    escondido = aba.locator('form[style*="none"] [name="nome"]')
    assert escondido.input_value() == ""


def test_campo_que_o_site_apaga_e_preenchido_de_novo(aba):
    _abrir_como_o_site_real(aba, dv.url_formulario(COTACAO),
                            SITE_APAGA_DEPOIS_DO_SERVICO)

    assert _no_formulario_visivel(aba, "nome") == "Enzo Zon"
    assert _no_formulario_visivel(aba, "whatsapp") == "(27) 99988-7766"
    assert not any("não consegui preencher" in a for a in aba.avisos)


def test_as_duas_coisas_juntas(aba):
    _abrir_como_o_site_real(aba, dv.url_formulario(COTACAO),
                            FORMULARIO_ESCONDIDO_ANTES,
                            SITE_APAGA_DEPOIS_DO_SERVICO)

    assert _no_formulario_visivel(aba, "nome") == "Enzo Zon"
    assert _no_formulario_visivel(aba, "servico") == "Fracionado -LTL"
    assert _no_formulario_visivel(aba, "cidade_destino") == "São Paulo"


def test_o_que_nao_deu_para_preencher_e_dito_no_aviso(aba):
    """Se o site insistir em apagar, o vendedor precisa saber QUAL campo
    digitar — e não descobrir quando a Della Volpe recusar o envio."""
    teimoso = """() => {
        const nome = document.querySelector('[name="nome"]');
        setInterval(() => { nome.value = ''; }, 50);
    }"""
    _abrir_como_o_site_real(aba, dv.url_formulario(COTACAO), teimoso)

    assert any("não consegui preencher nome" in a for a in aba.avisos)


def test_cotacao_sem_nome_gravado_usa_o_login_do_vendedor():
    """Cotação anterior a 20/08/2026 não tem nome_solicitante. "Nome
    completo" é obrigatório no site: vazio, o envio é recusado."""
    antiga = {k: v for k, v in COTACAO.items() if k != "nome_solicitante"}

    campos = dv.campos_por_name({**antiga, "id": 42, "usuario": "lucas"})

    assert campos["nome"] == "lucas (cot. 42)"


def test_script_velho_no_navegador_ganha_o_botao_de_atualizar(navegador,
                                                               app_web):
    """A tela compara a versão que o script instalado anuncia com a do
    servidor, e oferece a atualização sem esperar o Tampermonkey."""
    c = entrar(TestClient(app_web.app), app_web)
    cid = app_web.banco.salvar_cotacao("enzo", COTACAO)
    html = c.get(f"/dellavolpe/{cid}").text
    pg = navegador.new_page()
    pg.route("**/*", lambda rota: rota.fulfill(status=204))
    pg.set_content(html)

    velho = SCRIPT.replace(f"'data-cotafrete-dv', '{dv.VERSAO_USERSCRIPT}'",
                           "'data-cotafrete-dv', '1.0.0'")
    assert velho != SCRIPT
    pg.evaluate(velho)
    pg.wait_for_timeout(800)

    assert pg.locator("text=Atualizar o script").is_visible()
    assert pg.locator("#versao-instalada").inner_text() == "1.0.0"
    assert pg.locator("text=Instalar o script do Cotafrete").is_hidden()


def test_script_em_dia_nao_pede_atualizacao(navegador, app_web):
    c = entrar(TestClient(app_web.app), app_web)
    cid = app_web.banco.salvar_cotacao("enzo", COTACAO)
    pg = navegador.new_page()
    pg.route("**/*", lambda rota: rota.fulfill(status=204))
    pg.set_content(c.get(f"/dellavolpe/{cid}").text)

    pg.evaluate(SCRIPT)
    pg.wait_for_timeout(800)

    assert pg.locator("text=Atualizar o script").is_hidden()
    assert pg.locator(f"text=versão {dv.VERSAO_USERSCRIPT}").first.is_visible()
