"""O robô nos formulários de cada comprador e o anexo da proposta (28/09/2026).

Offline: as páginas reais copiadas (EDP) e a do ME geral, abertas num
navegador de verdade com toda a rede respondida aqui; a janela de anexo é
falsa, com os mesmos ids do ME, para provar que o upload passa pelas travas
e que o resto da janela (excluir) não passa.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from mercado_eletronico import formulario as F
from mercado_eletronico import mapa as M
from mercado_eletronico import pagina as P
from mercado_eletronico import robo as B
from mercado_eletronico import trava as T
from mercado_eletronico.regras import Conta, EntradaItem, PedidoDoComprador

FIX = Path(__file__).parent / "fixtures" / "me_real"
HOJE = date(2026, 9, 28)


@pytest.fixture(scope="module")
def navegador():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


def _form_da(navegador, arquivo: str) -> F.Formulario:
    ctx = navegador.new_context(java_script_enabled=False)
    ctx.route("**/*", lambda r: r.abort())
    pg = ctx.new_page()
    pg.set_content((FIX / arquivo).read_text(encoding="utf-8"), wait_until="domcontentloaded")
    try:
        return F.ler(pg)
    finally:
        ctx.close()


def _item(numero=10, **muda):
    base = dict(numero=numero, preco="12,34", ncm="85365090", prazo_dias=30, marca="WEG",
                origem=0, ref_fabricante="REF-1", pedido=PedidoDoComprador("SP"))
    return EntradaItem(**{**base, **muda})


# ------------------------------------------------------------- adaptação
def test_no_me_geral_a_adaptacao_nao_muda_nada(navegador):
    form = _form_da(navegador, "23052403_p1.html")
    plano = M.plano_pagina(Conta.UNIAO, {1: _item(10), 2: None, 3: None}, 30, HOJE, frete="FOB")
    adaptado = F.adaptar(plano.campos, plano.marcar, form, empresa=Conta.UNIAO)
    assert {k: v for k, v in adaptado.items() if k in plano.campos} == plano.campos
    assert set(adaptado) - set(plano.campos) <= {"NomeContato"}


def test_edp_ncm_vira_nbm_sai_o_que_ela_nao_pede_e_entram_contato_e_ref(navegador):
    form = _form_da(navegador, "edp_23050183.html")
    plano = M.plano_pagina(Conta.VENTURA, {1: _item(10)}, 30, HOJE, frete="CIF")
    c = F.adaptar(plano.campos, plano.marcar, form, empresa=Conta.VENTURA,
                  itens={1: _item(10)}, unidades={1: "UN"})
    assert c["NBM1"] == "8536.50.90" and "NCM1" not in c
    assert not {"PIS1", "COFINS1", "OrigMat1", "DataEntregaItemAux1"} & set(c)
    assert c["IcoTerms"] == "CIF" and c["CondicaoPagamento"] == "60 DDL"   # a da EDP
    assert c["MoedaCot"] == "R$"
    assert c["atrib_Email_1_1_0_8"] == F.EMAIL
    assert c["atrib_ContatoPrincipal_1_1_0_0"] == F.CONTATO == c["NomeContato"]
    assert c["itatrib01_RefFabricante_1_1"] == "REF-1"


def test_edp_sem_ref_fabricante_para(navegador):
    form = _form_da(navegador, "edp_23050183.html")
    plano = M.plano_pagina(Conta.VENTURA, {1: _item(10)}, 30, HOJE)
    with pytest.raises(F.FormularioDesconhecido, match="Ref. Fabricante"):
        F.adaptar(plano.campos, plano.marcar, form, empresa=Conta.VENTURA,
                  itens={1: _item(10, ref_fabricante="")})


def _campo(**kw):
    return F.Campo(**{"tipo": "text", **kw})


def test_obrigatorio_desconhecido_para_e_diz_qual():
    form = {"atrib_0TIPOPAGAMENTO_1_5_0_0": _campo(
                tipo="select", opcoes=(("", ""), ("Boleto Bancário", "Boleto Bancário")),
                rotulo="* Tipo de Pagamento:"),
            "atrib_1COMUNICADO_1_5_0_0": _campo(
                tipo="select", opcoes=(("", ""), ("Sim", "Sim"), ("Não", "Não")),
                rotulo="* Estou de acordo com o Comunicado aos Fornecedores")}
    with pytest.raises(F.FormularioDesconhecido, match="Tipo de Pagamento"):
        F.adaptar({}, [], form, empresa=Conta.VENTURA)
    del form["atrib_0TIPOPAGAMENTO_1_5_0_0"]
    assert F.adaptar({}, [], form, empresa=Conta.VENTURA) == {"atrib_1COMUNICADO_1_5_0_0": "Sim"}


def test_lugar_de_entrega_da_weg_e_o_endereco_da_empresa():
    form = {"atrib_LOCALFRETE_1_1_0_0": _campo(tipo="textarea", rotulo="* LUGAR DE ENTREGA:")}
    c = F.adaptar({}, [], form, empresa=Conta.ALIANCA)
    assert c["atrib_LOCALFRETE_1_1_0_0"].startswith("R. Sete, nº 560 - Cocal, Vila Velha - ES")


@pytest.mark.parametrize("campo, esperado", [
    (_campo(tipo="select", valor="C028", opcoes=(("C028", "28 dias"), ("C060", "60 dias"))), "C028"),
    (_campo(tipo="select", opcoes=(("", ""), ("1", "30 DDL (30 dias da data líquida)"))), "1"),
    (_campo(tipo="select", opcoes=(("", ""), ("C028", "28 dias"), ("C060", "60 dias"))), "C060"),
    (_campo(tipo="select", opcoes=(("", ""), ("F030", "30DDL"), ("F060", "60DDL"))), "F060"),
])
def test_condicao_de_pagamento_do_comprador_ou_60_dias(campo, esperado):
    assert F.condicao_pagamento(campo, "F060") == esperado


def test_ipi_sem_isento_vira_nao_e_select_desligado_sai():
    form = {"IPIIncluso1": _campo(tipo="select", opcoes=(("", ""), ("S", "Sim"), ("N", "Não"))),
            "ICMSIncluso1": _campo(tipo="select", opcoes=(("", ""),)),
            "Preco1": _campo(), "Prazo1": _campo(), "NBM1": _campo()}
    c = F.adaptar({"IPIIncluso1": "I", "ICMSIncluso1": "S", "Preco1": "1", "Prazo1": "5",
                   "NCM1": "8536.50.90"}, [1], form, empresa=Conta.UNIAO)
    assert c == {"IPIIncluso1": "N", "Preco1": "1", "Prazo1": "5", "NBM1": "8536.50.90"}


def test_sem_campo_de_preco_para():
    with pytest.raises(F.FormularioDesconhecido, match="Preco1"):
        F.adaptar({"Preco1": "1"}, [1], {}, empresa=Conta.UNIAO)


def test_anexos_obrigatorios_lidos_do_html_salvo():
    edp = (FIX / "edp_23050183.html").read_text(encoding="utf-8")
    assert P.ler_anexos_obrigatorios(edp) == [{"nome": "Anexo Comercial", "tipo": "RDC", "qtd": 0}]
    assert P.ler_anexos_obrigatorios((FIX / "23052403_p1.html").read_text(encoding="utf-8")) == []


# -------------------------------------------------------- anexo (upload)
JANELA = """<html><body><form method="post" id="aspnetForm" enctype="multipart/form-data">
<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="">
<div id="lista">{lista}</div>
<input type="file" id="fuArquivo" name="ctl00$conteudo$formUpload$fuArquivo" multiple>
<button type="button" id="ctl00_conteudo_formUpload_btn_ctl00_conteudo_formUpload_btnEnviar"
 onclick="document.getElementById('__EVENTTARGET').value='ctl00$conteudo$formUpload$btnEnviar';
 document.getElementById('aspnetForm').submit(); return false;">Enviar</button>
<button type="button" id="excluir"
 onclick="document.getElementById('__EVENTTARGET').value='ctl00$conteudo$grdAnexos$excluir';
 document.getElementById('aspnetForm').submit(); return false;">Excluir</button>
</form></body></html>"""


class MeFalso:
    def __init__(self):
        self.posts: list[tuple[str, bytes]] = []
        self.arquivo = ""

    def __call__(self, route, request):
        if request.method == "POST":
            corpo = request.post_data_buffer or b""
            self.posts.append((request.url, corpo))
            if b'filename="' in corpo:
                self.arquivo = corpo.split(b'filename="')[1].split(b'"')[0].decode()
        if "RespostaCotaItem.asp" in request.url:
            html = (FIX / "edp_23050183.html").read_text(encoding="utf-8")
            if self.arquivo:
                html = html.replace('anexoqtd="0">Nenhum anexo existente', 'anexoqtd="1">1 anexo', 1)
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        if "MEAnexo.aspx" in request.url:
            return route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                 body=JANELA.format(lista=self.arquivo or "Nenhum anexo foi encontrado."))
        return route.fulfill(status=200, body="")


def _sessao(navegador, tmp_path):
    me = MeFalso()
    return B.Sessao("nestle_ventura", pasta=tmp_path, seguir=me, browser=navegador,
                    timeout_ms=5_000), me


def test_anexo_sobe_pela_janela_do_me_e_so_o_enviar_passa(navegador, tmp_path):
    pdf = tmp_path / "proposta_edp.pdf"
    pdf.write_bytes(b"%PDF-1.4 teste \xe2\xff binario")
    s, me = _sessao(navegador, tmp_path)
    with s:
        s.abrir(23050183)
        [anexo] = F.anexos_obrigatorios(s.page)
        assert (anexo.nome, anexo.tipo, anexo.qtd) == ("Anexo Comercial", "RDC", 0)
        B.anexar(s, anexo, pdf)
        # O excluir da mesma janela morre na trava do form: nenhum POST sai.
        pg = s.ctx.new_page()
        pg.goto("https://www.me.com.br/" + anexo.url)
        antes = len(me.posts)
        pg.click("#excluir")
        pg.wait_for_timeout(500)
        assert len(me.posts) == antes
    [(url, corpo)] = me.posts
    assert "MEAnexo.aspx" in url and "TipoAnexo=RDC" in url
    # O Chromium não mostra os BYTES do arquivo a quem intercepta um upload (só
    # nome e tipo); eles vão ao servidor quando a requisição segue. A trava só
    # precisa do __EVENTTARGET, que vem inteiro.
    assert T.UPLOAD_ALVO.encode() in corpo and b'filename="proposta_edp.pdf"' in corpo
    assert me.arquivo == "proposta_edp.pdf"


def test_salvar_sem_o_arquivo_do_anexo_obrigatorio_para_antes_de_digitar(navegador, tmp_path):
    s, me = _sessao(navegador, tmp_path)
    with s:
        r = B.salvar_cotacao("nestle_ventura", 23050183, [_item(1, pedido=PedidoDoComprador())],
                             30, dry_run=False, hoje=HOJE, sessao=s, frete="CIF")
    assert "exige anexo" in r.erro and "Anexo Comercial" in r.erro
    assert me.posts == [] and not r.salvo


def test_teste_sem_salvar_da_edp_confere_tudo_e_avisa_o_anexo(navegador, tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF")
    itens = [_item(n, pedido=PedidoDoComprador()) for n in (1, 2, 3, 4, 5)]
    s, me = _sessao(navegador, tmp_path)
    with s:
        r = B.salvar_cotacao("nestle_ventura", 23050183, itens, 30, dry_run=True, hoje=HOJE,
                             sessao=s, frete="CIF", anexos={"RDC": pdf})
    assert r.ok and r.divergencias == [] and me.posts == []
    assert any("vai anexar p.pdf em Anexo Comercial" in a for a in r.avisos)


# ------------------------------------------------------------------- tela
from tests.test_me_tela import cliente, robo  # noqa: E402,F401  (fixtures)
from web import me_ui  # noqa: E402


@pytest.fixture
def edp(cliente, monkeypatch, tmp_path):
    """A cotação real da EDP lida na tela, com a pasta de anexos num tmp."""
    monkeypatch.setattr(me_ui, "PASTA_ANEXOS", tmp_path / "anexos")
    monkeypatch.setattr(me_ui, "LEITOR", lambda conta, n: [
        (FIX / "edp_23050183.html").read_text(encoding="utf-8")])
    cid = me_ui.banco.me_criar("nestle_ventura", 23050183, status="pendente",
                               empresa="EDP - Outsourcing")
    me_ui.carregar_itens(cid)
    return cid


def _preencher_item_1(cliente, cid, **extra):
    form = {"validade_dias": "30", "preco_1": "10,00", "ncm_1": "85365090", "prazo_1": "20",
            "marca_1": "WEG", "obs_1": "", "origem_1": "0", **extra}
    return cliente.post(f"/me/{cid}", data={**form, "acao": "conferir"})


def test_anexo_sobe_pela_tela_com_nome_seguro_e_so_do_tipo_pedido(cliente, edp):
    r = cliente.post(f"/me/{edp}/anexo", data={"tipo": "RDC"},
                     files={"arquivo": ("../Proposta Comercial Nº 7.PDF", b"%PDF-1.4", "application/pdf")})
    assert "Proposta_Comercial_N_7.pdf guardado" in r.text
    locais = me_ui.anexos_locais(me_ui.banco.me_cotacao(edp))
    arq = Path(locais["RDC"]["arquivo"])
    assert arq.read_bytes() == b"%PDF-1.4" and arq.parent.parent.name == str(edp)
    assert "Este comprador não pede" in cliente.post(
        f"/me/{edp}/anexo", data={"tipo": "RDCT"}, files={"arquivo": ("a.pdf", b"x")}).text
    assert "não aceito" in cliente.post(
        f"/me/{edp}/anexo", data={"tipo": "RDC"}, files={"arquivo": ("a.exe", b"x")}).text
    assert "vazio" in cliente.post(
        f"/me/{edp}/anexo", data={"tipo": "RDC"}, files={"arquivo": ("a.pdf", b"")}).text


def test_sem_o_anexo_o_salvar_nem_chama_o_robo_e_com_ele_o_robo_recebe_o_arquivo(cliente, edp, robo):
    _preencher_item_1(cliente, edp, ref_1="3SU1")
    msg = me_ui.mandar_robo(edp, "enzo", dry_run=False)
    assert "exige anexo para salvar: Anexo Comercial" in msg and robo.chamadas == []
    cliente.post(f"/me/{edp}/anexo", data={"tipo": "RDC"}, files={"arquivo": ("p.pdf", b"%PDF")})
    c = me_ui.banco.me_cotacao(edp)
    me_ui._rodar_robo(edp, "enzo", False, "pendente")   # direto: os outros itens seguem sem preço
    assert robo.chamadas and robo.frete == "CIF"
    html = cliente.get(f"/me/{edp}").text
    assert "p.pdf — o robô anexa no ME ao salvar" in html


def test_ref_fabricante_so_para_quem_exige_e_e_gravada(cliente, edp):
    html = _preencher_item_1(cliente, edp).text
    assert 'name="ref_1"' in html and "exige a Ref. Fabricante" in html
    _preencher_item_1(cliente, edp, ref_1="3SU1-100")
    item = me_ui.banco.me_cotacao(edp)["itens"][0]
    assert item["ref_fabricante"] == "3SU1-100"


def test_uf_de_entrega_escolhida_na_tela_quando_a_pagina_nao_diz(cliente, monkeypatch, tmp_path):
    cid = me_ui.banco.me_criar("edp_alianca", 7, status="pendente", empresa="WLI - WEG Linhares")
    me_ui.banco.me_gravar_itens_do_me(cid, [{"numero": 10, "pagina": 1, "indice": 1,
                                            "descricao": "RELE", "quantidade": "5,00", "unidade": "UN"}])
    html = cliente.get(f"/me/{cid}").text
    assert 'name="uf_entrega"' in html
    cliente.post(f"/me/{cid}", data={"uf_entrega": "ES", "preco_10": "1", "origem_10": "0",
                                    "acao": "conferir"})
    c = me_ui.banco.me_cotacao(cid)
    assert c["uf_entrega"] == "ES"
    assert "<small>ICMS</small> 17,00%" in me_ui.linha_previa(c, c["itens"][0], HOJE)  # dentro do ES
    cliente.post(f"/me/{cid}", data={"uf_entrega": "XX", "acao": "conferir"})
    assert me_ui.banco.me_cotacao(cid)["uf_entrega"] is None
