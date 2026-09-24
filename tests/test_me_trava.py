"""Trava de envio do robô do Mercado Eletrônico — sem navegador, sem ME.

O robô pode SALVAR (Acao=9) e paginar (Acao=4, 11..19: também salvam o
rascunho da página). Nunca Confirmar (Acao=1, envia ao comprador), nunca
Recusar (Acao=2 / RespCotaGrava.asp). Salvar e Confirmar vão para a mesma
URL com o mesmo form — só o corpo do POST distingue, então é ele que se testa.
"""

from __future__ import annotations

import pytest

from mercado_eletronico import trava as T

URL_FORM = "https://www.me.com.br/RespostaCotaItem.asp?Cotacao=23039029&FID="
URL_BUSCA = "https://api.web.mercadoe.com/supplier/transactions/v1/transactions/search"


# ------------------------------------------------------------ camada de rede
@pytest.mark.parametrize("acao", ["9", "4", "11", "12", "13"])
def test_salvar_e_paginar_passam(acao):
    assert T.motivo_bloqueio("POST", URL_FORM, f"x=1&Acao={acao}&Cotacao=1") is None


@pytest.mark.parametrize("acao", ["1", "2", "5", "6", "0", "", "10", "20", "9 ", "09"])
def test_confirmar_recusar_e_resto_bloqueados(acao):
    assert T.motivo_bloqueio("POST", URL_FORM, f"Acao={acao}") is not None


def test_acao_duplicada_bloqueia_mesmo_com_9():
    assert T.motivo_bloqueio("POST", URL_FORM, "Acao=9&Acao=1") is not None


def test_sem_acao_bloqueia():
    assert T.motivo_bloqueio("POST", URL_FORM, "Cotacao=1") is not None


def test_corpo_vazio_bloqueia():
    assert T.motivo_bloqueio("POST", URL_FORM, None) is not None


@pytest.mark.parametrize("url", [
    "https://www.me.com.br/RespCotaGrava.asp?Cotacao=1",
    "https://www.me.com.br/do/Excel.mvc/Ler?Cotacao=1",
    "https://www.me.com.br/RespostaCotaItem.asp.evil?Cotacao=1",
    "https://api.web.mercadoe.com/supplier/transactions/v1/transactions/answer",
])
def test_outros_posts_do_me_bloqueados_mesmo_com_acao_9(url):
    assert T.motivo_bloqueio("POST", url, "Acao=9") is not None


@pytest.mark.parametrize("metodo", ["PUT", "PATCH", "DELETE"])
def test_outros_metodos_de_escrita_bloqueados(metodo):
    assert T.motivo_bloqueio(metodo, URL_FORM, "Acao=9") is not None


def test_busca_da_lista_passa():
    assert T.motivo_bloqueio("POST", URL_BUSCA, '{"filters":[]}') is None


def test_login_so_passa_antes_de_logar():
    url = "https://www.me.com.br/do/Login.mvc/Login"
    assert T.motivo_bloqueio("POST", url, "LoginName=x", logado=False) is None
    assert T.motivo_bloqueio("POST", url, "LoginName=x", logado=True) is not None


def test_get_passa_e_fora_do_me_nao_interessa():
    assert T.motivo_bloqueio("GET", URL_FORM, None) is None
    assert T.motivo_bloqueio("POST", "https://www.google-analytics.com/g/collect", "") is None


def test_host_parecido_nao_engana():
    assert T.motivo_bloqueio("POST", "https://me.com.br.evil.io/RespostaCotaItem.asp", "Acao=1") is None
    assert T.motivo_bloqueio("POST", "https://evilme.com.br/RespostaCotaItem.asp", "Acao=1") is None
    assert T.motivo_bloqueio("POST", "https://x.me.com.br/RespostaCotaItem.asp", "Acao=1") is not None


# ------------------------------------------------------- camada do formulário
def test_js_do_form_so_libera_respcota_com_acoes_permitidas():
    js = T.JS_TRAVA_FORM
    assert "RespCota" in js
    for acao in T.ACOES_LIBERADAS:
        assert f"'{acao}'" in js
    assert "'1'" not in js and "'2'" not in js


_FORM_HTML = """
<form name="RespCota" method="post"
      action="https://www.me.com.br/RespostaCotaItem.asp?Cotacao=1&FID=">
  <input type="hidden" name="Acao" value="0"><input name="Preco1" value="1,00">
</form>
<form name="RespRecusa" method="post" action="https://www.me.com.br/RespCotaGrava.asp?Cotacao=1">
  <input type="hidden" name="Acao" value="2">
</form>"""


@pytest.fixture(scope="module")
def navegador():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


def _submeter(navegador, form: str, acao: str) -> list[str]:
    """Chama form.submit() como o JS do ME faz; devolve os POSTs que saíram."""
    ctx = navegador.new_context()
    ctx.add_init_script(T.JS_TRAVA_FORM)
    saidas: list[str] = []

    def rota(route, request):
        if request.method == "POST":
            saidas.append(request.post_data or "")
        route.fulfill(status=200, body="ok")  # nada chega ao ME de verdade

    ctx.route("**/*", rota)
    page = ctx.new_page()
    page.goto("https://www.me.com.br/teste")
    page.set_content(_FORM_HTML)
    page.evaluate(f"document.forms['{form}'].Acao.value = '{acao}'; document.forms['{form}'].submit()")
    page.wait_for_timeout(500)
    ctx.close()
    return saidas


@pytest.mark.parametrize("acao", ["1", "2", "5", "0"])
def test_form_submit_de_envio_nao_sai_do_navegador(navegador, acao):
    assert _submeter(navegador, "RespCota", acao) == []


def test_form_de_recusa_nunca_sai(navegador):
    assert _submeter(navegador, "RespRecusa", "9") == []


@pytest.mark.parametrize("acao", ["9", "12"])
def test_form_submit_de_salvar_sai(navegador, acao):
    saidas = _submeter(navegador, "RespCota", acao)
    assert len(saidas) == 1 and f"Acao={acao}" in saidas[0]


# ----------------------------------------------------------- camada de clique
@pytest.mark.parametrize("titulo, texto", [
    ("Salvar informações para enviar mais tarde", "Salvar"),
])
def test_botao_salvar_reconhecido(titulo, texto):
    assert T.botao_e_salvar(titulo, texto)


@pytest.mark.parametrize("titulo, texto", [
    ("Finalizar a resposta da cotação e enviar ao comprador", "Confirmar"),
    ("Recusar todos os itens da cotação", "Recusar"),
    ("Salvar informações para enviar mais tarde", "Confirmar"),
    ("Salvar e enviar ao comprador", "Salvar"),
    ("", "Salvar"),
    ("Salvar informações para enviar mais tarde", ""),
])
def test_qualquer_outro_botao_recusado(titulo, texto):
    assert not T.botao_e_salvar(titulo, texto)


def test_so_o_confirm_do_salvar_e_aceito_e_so_durante_o_salvar():
    msg = "Você verificou todas as informações digitadas?"
    assert T.confirm_aceito(msg, salvando=True)
    assert not T.confirm_aceito(msg, salvando=False)
    assert not T.confirm_aceito("A cotação será recusada.Deseja continuar?", salvando=True)
    assert not T.confirm_aceito("Você está recusando todos os itens da cotaçao. Deseja continuar?",
                                salvando=True)
