"""Robô do Mercado Eletrônico, offline: nada aqui toca o ME de verdade.

Duas bancadas:
- as páginas REAIS copiadas pelo recon (tests/fixtures/me_real): leitura dos
  itens e preenchimento campo a campo, com toda a rede respondida localmente;
- uma página FALSA mínima com os botões do ME (mesmos ids, titles e o mesmo
  confirm) para provar que o robô salva com UM POST Acao=9 e que, se o ME
  mudar e o "Salvar" passar a mandar Acao=1, nada sai do navegador.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from mercado_eletronico import mapa as M
from mercado_eletronico import robo as B
from mercado_eletronico.regras import Conta, EntradaItem

FIX = Path(__file__).parent / "fixtures" / "me_real"
HOJE = date(2026, 9, 23)

pytestmark = pytest.mark.skipif(not FIX.exists(), reason="sem cópias do recon")


@pytest.fixture(scope="module")
def navegador():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


class Servidor:
    """Faz o papel do ME: GET da cotação devolve `html`; POSTs ficam gravados."""

    def __init__(self, html: str):
        self.html, self.posts, self.corpos = html, [], []

    def __call__(self, route, request):
        if request.method == "POST":
            self.posts.append(parse_qs(request.post_data or "").get("Acao"))
            self.corpos.append(parse_qs(request.post_data or "", keep_blank_values=True))
        if "RespostaCotaItem.asp" in request.url:
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=self.html)
        return route.fulfill(status=200, body="")


def _sessao(navegador, tmp_path, html, timeout_ms=5_000):
    srv = Servidor(html)
    s = B.Sessao(Conta.UNIAO, pasta=tmp_path, seguir=srv, browser=navegador, timeout_ms=timeout_ms)
    return s, srv


def _item(numero, **muda):
    base = dict(numero=numero, preco="12,34", ncm="48219000", prazo_dias=30, marca="MARCA",
                obs="teste offline", origem=0)
    base.update(muda)
    return EntradaItem(**base)


# ------------------------------------------------------ páginas reais: leitura
def test_le_itens_da_pagina_real_com_uf_e_ncm_do_comprador(navegador, tmp_path):
    html = (FIX / "23052403_p1.html").read_text(encoding="utf-8")
    s, _ = _sessao(navegador, tmp_path, html)
    with s:
        s.abrir(23052403)
        itens = B.ler_itens(s.page)
        assert B.paginas(s.page) == 1
    assert [i.numero for i in itens] == [10, 20, 30]
    assert [i.indice for i in itens] == [1, 2, 3]
    assert all(i.pedido.uf_destino == "MG" and i.pedido.origem == 0 for i in itens)
    assert "ETIQUETA" in itens[0].descricao
    assert "NCM: 4821.90.00" in itens[0].campos_adicionais


def test_pagina_2_real_recomeca_os_indices(navegador, tmp_path):
    html = (FIX / "23039029_p2.html").read_text(encoding="utf-8")
    s, _ = _sessao(navegador, tmp_path, html)
    with s:
        s.abrir(23039029)
        itens = B.ler_itens(s.page)
    assert [i.numero for i in itens] == [110, 120, 130, 140, 150, 160, 170, 180]
    assert itens[0].indice == 1
    assert all(i.pedido.uf_destino == "ES" for i in itens)


def test_cotacao_com_18_itens_tem_2_paginas(navegador, tmp_path):
    html = (FIX / "23039029_p1.html").read_text(encoding="utf-8")
    s, _ = _sessao(navegador, tmp_path, html)
    with s:
        s.abrir(23039029)
        assert B.paginas(s.page) == 2


# -------------------------------------------- páginas reais: dry-run completo
def test_dry_run_na_pagina_real_preenche_confere_e_nao_manda_nada(navegador, tmp_path):
    html = (FIX / "23052403_p1.html").read_text(encoding="utf-8")
    s, srv = _sessao(navegador, tmp_path, html)
    with s:
        r = B.salvar_cotacao(Conta.UNIAO, 23052403, [_item(10), _item(30, origem=2)], 45,
                             dry_run=True, hoje=HOJE, sessao=s)
        valores = B.ler_valores(s.page, ["Preco1", "ICMS1", "OrigMat3", "ICMS3", "BaseCalculo2",
                                         "InscricaoEstadual", "DataEntregaItemAux1"])
    assert r.erro is None and r.divergencias == [] and r.ok
    assert not r.salvo and srv.posts == [] and r.posts_liberados == 0
    # item 30 é origem 2 entregando em MG: 4%, não 12%
    assert valores == {"Preco1": "12,34", "ICMS1": "12,00", "OrigMat3": "994", "ICMS3": "4,00",
                       "BaseCalculo2": "", "InscricaoEstadual": "083049428",
                       "DataEntregaItemAux1": "23/10/2026"}


def test_item_que_nao_existe_na_cotacao_vira_aviso(navegador, tmp_path):
    html = (FIX / "23052403_p1.html").read_text(encoding="utf-8")
    s, _ = _sessao(navegador, tmp_path, html)
    with s:
        r = B.salvar_cotacao(Conta.UNIAO, 23052403, [_item(10), _item(999)], 45,
                             hoje=HOJE, sessao=s)
    assert any("999" in a for a in r.avisos)


def test_entrada_invalida_para_antes_de_tocar_a_pagina(navegador, tmp_path):
    html = (FIX / "23052403_p1.html").read_text(encoding="utf-8")
    s, srv = _sessao(navegador, tmp_path, html)
    with s:
        r = B.salvar_cotacao(Conta.UNIAO, 23052403, [_item(10, ncm="12")], 45,
                             dry_run=False, hoje=HOJE, sessao=s)
    assert "NCM" in r.erro and not r.salvo and srv.posts == []


# ------------------------------------------------ página falsa: salvar/enviar
_SELECTS = {"UnidadeResp": ["", "UN"], "TipoImposto": ["0", "1"],
            "IPIIncluso": ["", "I", "S"], "ICMSIncluso": ["", "I", "S"],
            "PISIncluso": ["", "I", "S"], "COFINSIncluso": ["", "I", "S"],
            "OrigMat": ["", "992", "994"], "SubstituicaoTributaria": ["", "N"],
            "BaseCalculoImposto": ["", "S"]}


def _pagina_falsa(acao_do_salvar="9", titulo="Salvar informações para enviar mais tarde"):
    campos = "".join(f'<input name="{n}1">' for n in M.NOMES_ITEM.values() if n not in _SELECTS)
    selects = "".join(
        f'<select name="{n}1">' + "".join(f'<option value="{v}">{v}</option>' for v in ops)
        + "</select>" for n, ops in _SELECTS.items())
    cab = ('<select name="IcoTerms"><option></option><option>FOB</option></select>'
           '<textarea name="atrib_CidadeEstado_1_1_0_0 "></textarea>'
           '<select name="CondicaoPagamento"><option value="F060">60DDL</option></select>'
           '<input name="NumFoneCota"><input name="ValidadePropostaAux"><textarea name="ObsForn"></textarea>'
           '<select name="MoedaCot"><option></option><option value="BRL">Real</option></select>'
           '<select name="InscricaoEstadual"><option></option>'
           '<option value="083049428">083049428 - ES</option></select>')
    js = ("if(confirm('Você verificou todas as informações digitadas?')){"
          f"document.RespCota.Acao.value='{acao_do_salvar}';document.RespCota.submit();}}")
    return f"""<html><body>
<button id="MEComponentManager_MEButton_5" title="{titulo}" onclick="{js}">Salvar</button>
<button id="MEComponentManager_MEButton_6" title="Finalizar a resposta da cotação e enviar ao comprador"
  onclick="document.RespCota.Acao.value='1';document.RespCota.submit();">Confirmar</button>
<form name="RespCota" method="post" action="RespostaCotaItem.asp?Cotacao=1&FID=">
  <input type="hidden" name="Acao" value="0"><input type="hidden" name="MaxItem" value="1">
  {cab}<span id="spanItem_1">10.</span> PRODUTO TESTE
  Quantidade: 2,00 <input type="checkbox" id="chkItem_1" name="chkItem_1">
  {campos}{selects}
  Campos Adicionais: End. entrega: Rua X, 1 - Vitoria - ES - 29000-000 Origem do Material: 0
</form></body></html>"""


def test_salva_com_um_unico_post_acao_9_e_confere_depois(navegador, tmp_path):
    s, srv = _sessao(navegador, tmp_path, _pagina_falsa())
    with s:
        r = B.salvar_cotacao(Conta.UNIAO, 1, [_item(10)], 30, dry_run=False, hoje=HOJE, sessao=s)
    assert r.salvo, r.erro
    assert srv.posts == [["9"]]
    # a página falsa "esquece" o que foi salvo: a conferência TEM de acusar
    assert r.divergencias and not r.ok


def test_salvar_adulterado_para_enviar_nao_sai_do_navegador(navegador, tmp_path):
    # se o ME mudar e o botão Salvar passar a mandar Acao=1, a trava do form segura
    s, srv = _sessao(navegador, tmp_path, _pagina_falsa(acao_do_salvar="1"), timeout_ms=2_000)
    with s:
        r = B.salvar_cotacao(Conta.UNIAO, 1, [_item(10)], 30, dry_run=False, hoje=HOJE, sessao=s)
    assert not r.salvo and r.erro
    assert "Timeout" in r.erro or "Salvar não gerou" in r.erro  # parou NO clique, não antes
    assert srv.posts == []


def test_botao_com_outro_title_nao_e_clicado(navegador, tmp_path):
    s, srv = _sessao(navegador, tmp_path, _pagina_falsa(titulo="Salvar e enviar ao comprador"))
    with s:
        r = B.salvar_cotacao(Conta.UNIAO, 1, [_item(10)], 30, dry_run=False, hoje=HOJE, sessao=s)
    assert "Salvar esperado" in r.erro and srv.posts == []


def test_confirmar_clicado_por_engano_nao_sai(navegador, tmp_path):
    s, srv = _sessao(navegador, tmp_path, _pagina_falsa())
    with s:
        s.abrir(1)
        s.page.click("#MEComponentManager_MEButton_6")
        s.page.wait_for_timeout(500)
    assert srv.posts == []


def test_confirm_de_recusa_e_cancelado_mesmo_durante_o_salvar(navegador, tmp_path):
    s, _ = _sessao(navegador, tmp_path, _pagina_falsa())
    with s:
        s.abrir(1)
        s.acao_em_curso = True
        resposta = s.page.evaluate("confirm('A cotação será recusada.Deseja continuar?')")
    assert resposta is False


# ----------------------------------------------------- recusar item sem preço
# Cópia, em JS puro, do HabilitarRecusa do ME (o original usa jQuery, que
# offline não carrega): alterna o botão, limpa e trava os campos do item e
# mostra a justificativa. Nenhuma requisição — como no ME.
JS_RECUSA_FALSA = """
function HabilitarRecusa(id){
  const b = document.getElementById('btnNaoResponder_' + id);
  const campos = document.querySelectorAll('#tdItem_' + id + ' input, #tdItem_' + id + ' select');
  const just = document.getElementById('txtJustificativaRecusa_' + id);
  if (b.value == 'Responder item') {
    campos.forEach(c => c.removeAttribute('readonly'));
    just.value = ''; just.style.display = 'none';
    b.value = 'Deseja Recusar o Item? Clique Aqui';
  } else {
    campos.forEach(c => { c.value = ''; c.setAttribute('readonly', 'readonly'); });
    just.style.display = 'inline'; just.removeAttribute('readonly');
    b.value = 'Responder item';
  }
  return false;
}"""


def _pagina_dois_itens(item2_ja_recusado=False):
    """A página falsa com os itens 10 (índice 1) e 20 (índice 2)."""
    html = _pagina_falsa()
    campos2 = "".join(f'<input name="{n}2">' for n in M.NOMES_ITEM.values() if n not in _SELECTS)
    selects2 = "".join(
        f'<select name="{n}2">' + "".join(f'<option value="{v}">{v}</option>' for v in ops)
        + "</select>" for n, ops in _SELECTS.items())
    valor_btn = "Responder item" if item2_ja_recusado else "Deseja Recusar o Item? Clique Aqui"
    item2 = f"""<span id="spanItem_2">20.</span> OUTRO PRODUTO
  Quantidade: 1,00 <input type="checkbox" id="chkItem_2" name="chkItem_2">
  <table><tr><td id="tdItem_2">{campos2}{selects2}</td></tr></table>
  <input type="button" id="btnNaoResponder_2" value="{valor_btn}" onclick="HabilitarRecusa('2')">
  <input type="text" name="txtJustificativaRecusa_2" id="txtJustificativaRecusa_2" maxlength="200"
    value="{'antiga' if item2_ja_recusado else ''}">
  Campos Adicionais: End. entrega: Rua X, 1 - Vitoria - ES - 29000-000 Origem do Material: 0"""
    btn1 = '<input type="button" id="btnNaoResponder_1" value="Deseja Recusar o Item? Clique Aqui">'
    html = html.replace('name="MaxItem" value="1"', 'name="MaxItem" value="2"')
    html = html.replace("</form>", f"{btn1}{item2}</form>")
    return html.replace("<html><body>", f"<html><head><script>{JS_RECUSA_FALSA}</script></head><body>")


def test_item_sem_preco_vai_recusado_no_mesmo_post_do_salvar(navegador, tmp_path):
    s, srv = _sessao(navegador, tmp_path, _pagina_dois_itens())
    with s:
        r = B.salvar_cotacao(Conta.UNIAO, 1, [_item(10), _item(20, preco="", obs="fora de linha")],
                             30, dry_run=False, hoje=HOJE, sessao=s)
    assert r.salvo, r.erro
    assert srv.posts == [["9"]]                      # um POST só, e é o Salvar
    (corpo,) = srv.corpos
    assert corpo["txtJustificativaRecusa_2"] == ["fora de linha"]
    assert corpo["Preco2"] == [""] and corpo["Preco1"] == ["12,34"]
    assert "chkItem_2" not in corpo and corpo.get("chkItem_1")


def test_item_recusado_num_rascunho_antigo_volta_a_ser_respondido(navegador, tmp_path):
    s, srv = _sessao(navegador, tmp_path, _pagina_dois_itens(item2_ja_recusado=True))
    with s:
        r = B.salvar_cotacao(Conta.UNIAO, 1, [_item(10), _item(20)], 30,
                             dry_run=False, hoje=HOJE, sessao=s)
    assert r.salvo, r.erro
    (corpo,) = srv.corpos
    assert corpo["txtJustificativaRecusa_2"] == [""] and corpo["Preco2"] == ["12,34"]


def test_recusa_ja_feita_nao_e_desfeita_por_engano(navegador, tmp_path):
    """Chamar HabilitarRecusa de novo DESFAZ a recusa: só chama se o estado
    for o oposto do desejado."""
    s, srv = _sessao(navegador, tmp_path, _pagina_dois_itens(item2_ja_recusado=True))
    with s:
        r = B.salvar_cotacao(Conta.UNIAO, 1, [_item(10), _item(20, preco="", obs="nova justificativa")],
                             30, dry_run=False, hoje=HOJE, sessao=s)
    assert r.salvo, r.erro
    (corpo,) = srv.corpos
    assert corpo["txtJustificativaRecusa_2"] == ["nova justificativa"]
