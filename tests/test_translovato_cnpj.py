"""O alerta que a Translovato mostra depois do CNPJ do remetente.

Na cotação #56 (28/08/2026) a Translovato respondeu em ~3 segundos, com um
sweet-alert em letras garrafais: **"Oops! CNPJ não cadastrado."** — o CNPJ
41.747.639/0001-12 é um fornecedor, não a Ventura.

O que o vendedor leu no cartão foi isto:

    TimeoutError: Locator.click: Timeout 45000ms exceeded ...
    <div tabindex="-1" class="sweet-overlay"></div> intercepts pointer events

O adapter digitava o CNPJ, esperava o `get-cnpj`, e ia DIRETO para o campo de
CEP — o alerta nasce no meio, cobre o formulário, e o clique seguinte bate no
overlay até o timeout estourar. Três vezes, porque `ERRO` é repetível.

A função que lê e fecha o alerta (`_limpar_tela`) já existia e já devolvia o
texto: só estava sendo chamada uma etapa tarde demais. O próprio cabeçalho do
adapter manda "Fecha alerta e banner de cookies ANTES DE CADA ETAPA".

Fixture servida por `page.route`, com o overlay real bloqueando cliques de
verdade: sem ele o teste passaria mesmo com o bug, porque o bug É o overlay.
"""

from __future__ import annotations

import pytest

from carriers.translovato import mapping as m
from carriers.translovato.adapter import SemTabela, TranslovatoAdapter

CNPJ_FORNECEDOR = "41.747.639/0001-12"      # o da #56

FORMULARIO = """<!doctype html><meta charset="utf-8"><title>Cotação</title>
<style>
  .sweet-overlay {position: fixed; inset: 0; background: rgba(0,0,0,.4);
                  z-index: 1000;}
  .sweet-alert {position: fixed; top: 25%; left: 30%; width: 40%;
                background: #fff; z-index: 1001; padding: 2em;
                text-align: center;}
  .escondido {display: none;}
</style>
<form>
  <input name="value[sender_cpnj]">
  <input name="value[sender_zipcode]">
  <input name="value[receiver_cnpj_cpf]">
  <input name="value[receiver_zipcode]">
</form>
<div class="sweet-overlay escondido" tabindex="-1"></div>
<div class="sweet-alert escondido">
  <h2>Oops!</h2><p>__AVISO__</p>
  <button class="confirm" type="button">OK</button>
</div>
<script>
  const overlay = document.querySelector('.sweet-overlay');
  const alerta = document.querySelector('.sweet-alert');
  const mostrar = () => {
    overlay.classList.remove('escondido');
    alerta.classList.add('visible');
    alerta.classList.remove('escondido');
  };
  document.querySelector('[name="value[sender_cpnj]"]')
      .addEventListener('blur', async () => {
        await fetch('/portal-do-cliente/get-cnpj', {method: 'POST', body: '{}'});
        if (__ALERTA__) mostrar();
      });
  document.querySelector('.confirm').addEventListener('click', () => {
    overlay.classList.add('escondido');
    alerta.classList.add('escondido');
    alerta.classList.remove('visible');
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


def _preencher(navegador, *, aviso: str | None):
    """Roda `_preencher` contra o formulário de mentira. Devolve a exceção."""
    page = navegador.new_context().new_page()
    # Curto de propósito: com o bug, o clique bloqueado tem que estourar
    # rápido em vez de segurar o teste pelos 45s reais.
    page.set_default_timeout(2_500)

    corpo = (FORMULARIO
             .replace("__AVISO__", aviso or "")
             .replace("__ALERTA__", "true" if aviso else "false"))
    page.route("https://www.translovato.com.br/**", lambda route: route.fulfill(
        status=200,
        content_type=("application/json" if "get-cnpj" in route.request.url
                      else "text/html"),
        body=('{"status":false}' if "get-cnpj" in route.request.url else corpo)))
    page.goto("https://www.translovato.com.br/portal-do-cliente/"
              "solicitacao-de-cotacao")

    campos = {"value[sender_cpnj]": CNPJ_FORNECEDOR,
              "value[sender_zipcode]": "42702400",
              "value[receiver_cnpj_cpf]": "08.310.365/0001-24",
              "value[receiver_zipcode]": "29105770"}
    try:
        TranslovatoAdapter()._preencher(page, campos)
        return None
    except Exception as exc:
        return exc


# --------------------------------------------------------------- o bug #56
def test_cnpj_nao_cadastrado_vira_recusa_e_nao_timeout(navegador):
    """O site respondeu. O cartão tem que repetir a resposta dele.

    Antes: 45s batendo no overlay e um stack trace do Playwright no cartão,
    três vezes seguidas. A Translovato tinha respondido em 3 segundos."""
    erro = _preencher(navegador, aviso="CNPJ não cadastrado.")

    assert isinstance(erro, SemTabela), (
        f"o alerta do site tinha que virar recusa, veio: {erro!r}")


def test_a_recusa_diz_ao_vendedor_o_que_fazer(navegador):
    """Nomeia o CNPJ usado e diz para onde ir — a mesma frase do `get-products`.

    Reaproveitar `recusa_sem_tabela` não é economia: é o MESMO fato comercial
    (a Translovato só cota carga saindo da Ventura), só descoberto uma etapa
    antes. Duas frases diferentes para o mesmo "não" confundiriam quem lê."""
    erro = _preencher(navegador, aviso="CNPJ não cadastrado.")

    assert CNPJ_FORNECEDOR in str(erro)
    assert "WhatsApp" in str(erro)


# ------------------------------------------------------------ caminho feliz
def test_sem_alerta_o_preenchimento_segue_normal(navegador):
    """Sem alerta nenhum, nada muda: tem que passar do CNPJ e continuar.

    Guarda contra o conserto virar uma trava que recusa cotação boa. Ele
    segue e só para adiante, no <select> de produto que a fixture não tem."""
    erro = _preencher(navegador, aviso=None)

    assert not isinstance(erro, SemTabela), (
        f"recusou sem o site ter reclamado de nada: {erro!r}")


def test_a_frase_do_site_esta_reconhecida_no_mapping():
    """A marca vem do texto real medido em 28/08/2026, no print da #56."""
    assert m.AVISO_CNPJ_NAO_CADASTRADO in "Oops! CNPJ não cadastrado. OK"
