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
  // As classes do SweetAlert de VERDADE, na ordem em que o site as aplica.
  // Medidas nos logs de erro de producao (18 cotacoes entre 24/08 e
  // 02/09/2026): o Playwright registrou o elemento que engolia o clique ora
  // como "sweet-alert showSweetAlert", ora como "sweet-alert showSweetAlert
  // visible". Ou seja, `visible` chega DEPOIS — e a fixture que o adicionava
  // junto estava testando a suposicao de quem escreveu o codigo, nao o site.
  const mostrar = () => {
    overlay.classList.remove('escondido');
    alerta.classList.remove('escondido');
    alerta.classList.add('showSweetAlert');
    setTimeout(() => alerta.classList.add('visible'), 500);
  };
  // O site real dispara get-cnpj no blur de QUALQUER campo de CNPJ — o
  // adapter espera essa resposta especificamente depois do remetente
  // (page.expect_response). Os dois campos disparam sempre; só o campo sob
  // teste (__CAMPO__) mostra o alerta.
  // __ATRASO__ ms entre a resposta e o alerta aparecer na tela. Zero e o
  // laboratorio; o que producao vive e a VM de 4 vCPU rodando seis Chromium
  // ao mesmo tempo, onde o navegador demora para executar o callback e
  // animar o popup. E nesse intervalo que o adapter clicava no campo
  // seguinte e levava o clique na cara do overlay.
  const disparar = (nome) => async () => {
    await fetch('/portal-do-cliente/get-cnpj', {method: 'POST', body: '{}'});
    if (nome === '__CAMPO__' && __ALERTA__) setTimeout(mostrar, __ATRASO__);
  };
  document.querySelector('[name="value[sender_cpnj]"]')
      .addEventListener('blur', disparar('value[sender_cpnj]'));
  document.querySelector('[name="value[receiver_cnpj_cpf]"]')
      .addEventListener('blur', disparar('value[receiver_cnpj_cpf]'));
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


def _preencher(navegador, *, aviso: str | None,
               campo_evento: str = "value[sender_cpnj]",
               atraso_ms: int = 0):
    """Roda `_preencher` contra o formulário de mentira. Devolve a exceção.

    `campo_evento` é o campo cujo `blur` dispara o alerta — o remetente por
    padrão (o bug original, #56), ou o destinatário para reproduzir a #117.

    `atraso_ms` é quanto o alerta demora a aparecer DEPOIS da resposta. Zero
    é o laboratório; produção é uma VM disputada, onde o navegador executa o
    callback e anima o popup com atraso — e era nessa fresta que o adapter
    clicava no campo seguinte."""
    page = navegador.new_context().new_page()
    # Curto de propósito: com o bug, o clique bloqueado tem que estourar
    # rápido em vez de segurar o teste pelos 45s reais.
    page.set_default_timeout(2_500)

    corpo = (FORMULARIO
             .replace("__CAMPO__", campo_evento)
             .replace("__AVISO__", aviso or "")
             .replace("__ATRASO__", str(atraso_ms))
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


# ------------------------------------------- o alerta que chega atrasado
# O modo de falha DOMINANTE da Translovato em produção: 18 das 21 cotações
# com erro, entre 24/08 e 02/09/2026, morreram assim —
#
#   TimeoutError: Locator.click: Timeout 45000ms exceeded.
#     waiting for locator("input[name=\"value[receiver_zipcode]\"]")
#     <div class="sweet-alert showSweetAlert"> subtree intercepts pointer events
#
# O `_limpar_tela` ERA chamado antes desse campo. Ele só não achava nada:
# corria num instante em que o alerta ainda não tinha aparecido, e o clique
# seguinte pegava o overlay em cheio. O vendedor recebia um rastro de
# Playwright de 45 segundos no lugar da frase que a Translovato escreveu.
#
# Não é caso raro: o alerta do destinatário dispara sempre que o CNPJ de
# quem recebe não é cliente da Translovato, que é a maioria das cargas.
# O que varia é só se ele chega antes ou depois do clique — e numa VM
# carregada, chega depois. Daí quatro erros seguidos sem nenhum acerto.
# A CONTA que define a janela mortal, e que este arquivo existe para travar:
#
#   T+0      blur do campo de CNPJ, o site dispara get-cnpj
#   T+400    `_digitar` termina (wait_for_timeout(400))
#   T+2900   `_limpar_tela` olha a tela (ESPERA_AJAX_MS = 2500)
#   T+2900   `_digitar` do campo seguinte CLICA
#
# O SweetAlert entra em duas etapas: `showSweetAlert` quando aparece e
# `visible` meio segundo DEPOIS, no fim da animação. Ele já engole cliques
# desde a primeira. Então, se o alerta aparece entre T+2400 e T+2900, na hora
# em que o adapter olha ele está na tela mas ainda sem `visible` — e o adapter
# exigia `visible` para enxergá-lo. Resultado: passa batido, o clique seguinte
# bate no overlay, e o Playwright fica 45 segundos tentando.
#
# 2700 cai no meio dessa janela de propósito.
ATRASO_NA_JANELA_MORTAL = 2_700


def test_alerta_sem_a_classe_visible_ainda_assim_e_fechado(navegador):
    """O caso de produção, em laboratório.

    18 das 21 cotações com erro da Translovato morreram exatamente assim,
    entre 24/08 e 02/09/2026:

        TimeoutError: Locator.click: Timeout 45000ms exceeded.
          waiting for locator("input[name=\"value[receiver_zipcode]\"]")
          <div class="sweet-alert showSweetAlert"> intercepts pointer events

    Repare a classe no log: `showSweetAlert`, SEM `visible`. O `_limpar_tela`
    era chamado antes desse campo — ele só não enxergava o alerta."""
    erro = _preencher(navegador, aviso="CNPJ não cadastrado.",
                      campo_evento="value[receiver_cnpj_cpf]",
                      atraso_ms=ATRASO_NA_JANELA_MORTAL)

    assert "intercepts pointer events" not in str(erro), (
        f"o alerta engoliu o clique em vez de ser fechado: {erro!r}")


def test_recusa_do_remetente_na_janela_mortal_chega_ao_vendedor(navegador):
    """Do lado do remetente o alerta É a recusa de negócio da Translovato.

    Perdido na janela, ele não vira só um clique bloqueado: vira um vendedor
    lendo um stack trace de 45 segundos no lugar de "CNPJ não cadastrado" —
    e repetindo a cotação três vezes atrás de um preço que não vem."""
    erro = _preencher(navegador, aviso="CNPJ não cadastrado.",
                      atraso_ms=ATRASO_NA_JANELA_MORTAL)

    assert isinstance(erro, SemTabela), (
        f"a recusa da Translovato virou outra coisa: {erro!r}")


def test_a_frase_do_site_esta_reconhecida_no_mapping():
    """A marca vem do texto real medido em 28/08/2026, no print da #56."""
    assert m.AVISO_CNPJ_NAO_CADASTRADO in "Oops! CNPJ não cadastrado. OK"


# --------------------------------------------------------------- o bug #117
def test_cnpj_do_destinatario_nao_cadastrado_nao_trava_no_overlay(navegador):
    """A cotação #117 (02/09/2026): o MESMO alerta, mas depois do CNPJ do
    DESTINATÁRIO — que não é cliente da Translovato, só recebe a carga, e
    isso não é recusa nenhuma. O adapter ia direto para o campo de CEP
    seguinte e o clique batia no overlay até estourar os 45s, três vezes —
    a Translovato já tinha respondido em segundos.

    Fechando o alerta e preenchendo o CEP que o vendedor já digitou no
    formulário, a cotação segue: foi o que a #117 provou ao repetir na mão
    (fechar a mensagem, preencher o CEP, cotação saiu). Diferente do
    remetente (recusa de verdade: só a Ventura tem tabela como origem), aqui
    não pode virar SemTabela nem travar no overlay — só seguir."""
    erro = _preencher(navegador, aviso="CNPJ não cadastrado.",
                       campo_evento="value[receiver_cnpj_cpf]")

    assert not isinstance(erro, SemTabela), (
        f"destinatário sem cadastro não é recusa: {erro!r}")
    # O sintoma do bug era exatamente isto — clique bloqueado até estourar
    # o timeout batendo no overlay do alerta.
    texto_erro = str(erro)
    assert "Timeout" not in texto_erro and "sweet-overlay" not in texto_erro, (
        f"ainda travou no alerta: {erro!r}")


def test_sem_alerta_no_destinatario_continua_normal(navegador):
    """Guarda contra o conserto do destinatário virar uma trava nova: sem
    alerta nenhum, nada pode mudar de comportamento."""
    erro = _preencher(navegador, aviso=None,
                       campo_evento="value[receiver_cnpj_cpf]")

    assert not isinstance(erro, SemTabela)
