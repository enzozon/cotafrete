"""NCM no ME: do comprador, da memória e sugerido pela IA (passo 2).

Base: as cópias reais. A UNIÃO 23052403 traz o NCM do comprador nos Campos
Adicionais ("NCM: 4821.90.00"); a VENTURA 23039029 tem 18 itens genéricos
("POSTO DUPLO", "TV65"...) com "NCM:" vazio — é para esses que a IA serve.
A IA é o provedor falso de tests/test_ia.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core import ia
from core.banco import Banco
from mercado_eletronico import lista
from mercado_eletronico import ncm as sn
from mercado_eletronico import painel as pn
from mercado_eletronico import regras as rg
from tests.apoio import entrar
from tests.test_ia import Provedor, Resp
from web import app as app_web
from web import me_ui

FIX = Path(__file__).resolve().parent / "fixtures" / "me_real"


# ------------------------------------------------ o NCM que o comprador pediu
@pytest.mark.parametrize("texto, ncm", [
    ("NCM: 8507.60.00\nData de Remessa: 29.11.2026", "8507.60.00"),
    ("NCM: 48219000 CNPJ: 16628281000323", "4821.90.00"),
    ("NCM:\nData de Remessa: 02.11.2026", None),       # item genérico
    ("NCM: 123", None),
    ("", None),
])
def test_ncm_do_comprador(texto, ncm):
    assert rg.ncm_do_comprador(texto) == ncm


# ---------------------------------------------------------------- a tela
@pytest.fixture
def prov(monkeypatch):
    p = Provedor()
    monkeypatch.setattr(ia, "POST", p)
    monkeypatch.setattr(ia, "_castigo", {})
    monkeypatch.setattr(ia, "REGISTRO", None)
    monkeypatch.setenv("IA_MODELOS", "groq:melhor")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    return p


@pytest.fixture
def cliente(monkeypatch, tmp_path, prov):
    b = Banco(tmp_path / "t.db")
    monkeypatch.setattr(app_web, "banco", b)
    monkeypatch.setattr(me_ui, "banco", b)
    monkeypatch.setattr(me_ui, "FONTE", lambda c: lista.ler_busca(
        json.loads((FIX / f"lista_{c}.json").read_text(encoding="utf-8"))))
    monkeypatch.setattr(me_ui, "LEITOR", lambda c, n: [
        p.read_text(encoding="utf-8") for p in sorted(FIX.glob(f"{n}_p*.html"))])
    monkeypatch.setattr(me_ui, "DISPARAR", lambda fn, *a: fn(*a))
    monkeypatch.setattr(me_ui, "VARREDURA", me_ui.EstadoVarredura())
    me_ui.atualizar(["ventura", "uniao"])
    return entrar(TestClient(app_web.app), app_web)


def _id(numero):
    return next(c["id"] for c in me_ui.banco.me_cotacoes() if c["numero"] == numero)


def _itens(cid):
    return {i["numero"]: i for i in me_ui.banco.me_cotacao(cid)["itens"]}


def test_ler_itens_preenche_o_ncm_do_comprador(cliente):
    cid = _id(23052403)
    cliente.post(f"/me/{cid}/ler")
    it = _itens(cid)
    assert [(it[n]["ncm"], it[n]["ncm_origem"]) for n in (10, 20, 30)] == [
        ("4821.90.00", "comprador"), ("4202.92.00", "comprador"), ("8504.90.40", "comprador")]
    html = cliente.get(f"/me/{cid}").text
    assert html.count('class="me-ncm">do comprador') == 3
    assert "Sugerir NCM com IA" not in html          # nada sem NCM


def test_ncm_do_comprador_vem_antes_da_memoria(cliente):
    cid = _id(23052403)
    cliente.post(f"/me/{cid}/ler")
    desc = _itens(cid)[10]["descricao"]
    me_ui.banco.me_lembrar_material(pn.chave_material(desc), ncm="9999.99.99", marca="3M", origem=0)
    me_ui.banco.me_gravar_entrada(cid, 10, ncm="", ncm_origem=None, marca="")
    cliente.post(f"/me/{cid}/ler")
    i = _itens(cid)[10]
    assert (i["ncm"], i["ncm_origem"], i["marca"]) == ("4821.90.00", "comprador", "3M")


def test_ncm_diferente_do_pedido_pelo_comprador_avisa(cliente):
    cid = _id(23052403)
    cliente.post(f"/me/{cid}/ler")
    cliente.post(f"/me/{cid}", data={"acao": "conferir", "validade_dias": "30",
                                     "preco_10": "", "ncm_10": "48211000"})
    i = _itens(cid)[10]
    assert i["ncm_origem"] is None                    # mexeu: é dele
    assert "o comprador pediu 4821.90.00" in cliente.get(f"/me/{cid}").text


# ---------------------------------------------------------- IA: limpar()
def test_so_passa_sugestao_que_faz_sentido():
    dados = {"sugestoes": [
        {"item": 10, "ncm": "9403.30.00", "descricao_ncm": "Móveis de madeira p/ escritório",
         "confianca": "alta", "motivo": "mesa de trabalho"},
        {"item": 20, "ncm": "9403300", "descricao_ncm": "x", "confianca": "alta", "motivo": ""},   # 7 dígitos
        {"item": 30, "ncm": "7700.00.00", "descricao_ncm": "x", "confianca": "alta", "motivo": ""},  # cap. 77
        {"item": 40, "ncm": "9901.00.00", "descricao_ncm": "x", "confianca": "alta", "motivo": ""},  # cap. 99
        {"item": 999, "ncm": "8528.72.00", "descricao_ncm": "TV", "confianca": "alta", "motivo": ""},  # não pedido
        {"item": 10, "ncm": "9401.30.00", "descricao_ncm": "dup", "confianca": "alta", "motivo": ""},  # repetido
        {"item": "50", "ncm": "85287200", "descricao_ncm": "Televisores", "confianca": "Média", "motivo": ""},
    ]}
    s = sn.limpar(dados, {10, 20, 30, 40, 50})
    assert set(s) == {10, 50}
    assert s[10].ncm == "9403.30.00" and s[50].ncm == "8528.72.00" and s[50].confianca == "media"
    assert s[10].nota() == "Móveis de madeira p/ escritório — confiança alta. mesa de trabalho"


def test_cotacao_grande_vai_em_lotes(prov):
    itens = [{"numero": n * 10, "descricao": f"item {n}"} for n in range(1, 31)]

    def responde(url, chave, corpo, provedor):
        prov.pedidos.append(corpo)
        pedidos = json.loads(corpo["messages"][1]["content"].split("\n\n", 1)[1])
        return Resp(conteudo=json.dumps({"sugestoes": [
            {"item": p["item"], "ncm": "9403.30.00", "descricao_ncm": "Móveis", "confianca": "media",
             "motivo": ""} for p in pedidos]}))
    import core.ia as m
    m.POST = responde
    s, modelo = sn.sugerir(itens)
    assert len(s) == 30 and len(prov.pedidos) == 2 and modelo == "groq:melhor"


# -------------------------------------------------------------- IA: tela
def _ia_responde(prov, sugestoes):
    prov.roteiro["melhor"] = [Resp(conteudo=json.dumps({"sugestoes": [
        {"item": n, "ncm": ncm, "descricao_ncm": d, "confianca": c, "motivo": "confira o material"}
        for n, ncm, d, c in sugestoes]}))]


def test_botao_sugere_so_os_vazios_e_etiqueta(cliente, prov):
    cid = _id(23039029)
    cliente.post(f"/me/{cid}/ler")
    html = cliente.get(f"/me/{cid}").text
    assert "Sugerir NCM com IA (18)" in html
    me_ui.banco.me_gravar_entrada(cid, 10, ncm="9403.30.00")   # o vendedor já sabia este
    _ia_responde(prov, [(20, "9403.70.00", "Móveis de plástico", "baixa"),
                        (170, "8528.72.00", "Televisores em cores", "alta")])
    html = cliente.post(f"/me/{cid}", data={"acao": "ncm", "validade_dias": "30"}).text
    (corpo,) = [c for _, _, c in prov.pedidos]
    enviados = [p["item"] for p in json.loads(corpo["messages"][1]["content"].split("\n\n", 1)[1])]
    assert 10 not in enviados and len(enviados) == 17
    it = _itens(cid)
    assert (it[10]["ncm"], it[10]["ncm_origem"]) == ("9403.30.00", None)       # não sobrescreve
    assert (it[170]["ncm"], it[170]["ncm_origem"]) == ("8528.72.00", "ia")
    assert "IA · Televisores em cores — confiança alta" in html
    assert "A IA sugeriu o NCM de 2 de 17 itens" in html
    hist = me_ui.banco.me_historico(cid)[-1]
    assert hist["evento"] == "NCM sugerido pela IA: 2 itens" and "groq:melhor · 15 sem sugestão" in hist["detalhe"]


def test_ia_fora_do_ar_nao_mexe_em_nada(cliente, prov):
    cid = _id(23039029)
    cliente.post(f"/me/{cid}/ler")
    prov.roteiro["melhor"] = [Resp(503)]
    html = cliente.post(f"/me/{cid}", data={"acao": "ncm", "validade_dias": "30"}).text
    assert "A IA está indisponível agora" in html
    assert all(not i["ncm"] for i in _itens(cid).values())


def test_palpite_da_ia_so_vira_memoria_depois_de_conferido(cliente, prov, monkeypatch):
    cid = _id(23039029)
    cliente.post(f"/me/{cid}/ler")
    _ia_responde(prov, [(170, "8528.72.00", "Televisores", "alta")])
    cliente.post(f"/me/{cid}", data={"acao": "ncm", "validade_dias": "30"})
    chave = pn.chave_material(_itens(cid)[170]["descricao"])
    form = {"acao": "conferir", "validade_dias": "30", "preco_170": "5000", "ncm_170": "8528.72.00",
            "prazo_170": "30", "marca_170": "LG", "origem_170": "0"}
    cliente.post(f"/me/{cid}", data=form)                   # guardou sem mexer no NCM
    assert me_ui.banco.me_material(chave)["ncm"] is None    # palpite: não lembrado
    assert _itens(cid)[170]["ncm_origem"] == "ia"
    # salvou no ME com ele: agora é resposta dada
    monkeypatch.setattr(me_ui, "ROBO", lambda *a: SimpleNamespace(ok=True, divergencias=[], prints=[],
                                                                  erro=None, avisos=[]))
    outros = {f"obs_{n}": "fora de linha" for n in _itens(cid) if n != 170}
    outros |= {f"preco_{n}": "" for n in _itens(cid) if n != 170}
    html = cliente.post(f"/me/{cid}", data={**form, **outros, "acao": "salvar"}).text
    assert "Salva no ME" in html
    assert me_ui.banco.me_material(chave)["ncm"] == "8528.72.00"


def test_editar_o_ncm_sugerido_vira_do_vendedor(cliente, prov):
    cid = _id(23039029)
    cliente.post(f"/me/{cid}/ler")
    _ia_responde(prov, [(170, "8528.72.00", "Televisores", "alta")])
    cliente.post(f"/me/{cid}", data={"acao": "ncm", "validade_dias": "30"})
    cliente.post(f"/me/{cid}", data={"acao": "conferir", "validade_dias": "30",
                                     "preco_170": "", "ncm_170": "8528.71.90"})
    i = _itens(cid)[170]
    assert (i["ncm"], i["ncm_origem"], i["ncm_nota"]) == ("8528.71.90", None, None)
    assert me_ui.banco.me_material(pn.chave_material(i["descricao"]))["ncm"] == "8528.71.90"


def test_memoria_vazia_nao_apaga_o_que_ja_se_sabia(tmp_path):
    b = Banco(tmp_path / "t.db")
    b.me_lembrar_material("x", ncm="8528.72.00", marca="LG", origem=0)
    b.me_lembrar_material("x", ncm=None, marca="Samsung", origem=None)
    assert {k: b.me_material("x")[k] for k in ("ncm", "marca", "origem")} == {
        "ncm": "8528.72.00", "marca": "Samsung", "origem": 0}


def test_sem_ia_configurada_nao_ha_botao(cliente, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    cid = _id(23039029)
    cliente.post(f"/me/{cid}/ler")
    assert "Sugerir NCM com IA" not in cliente.get(f"/me/{cid}").text


def test_banco_antigo_ganha_as_colunas(tmp_path):
    import sqlite3
    caminho = tmp_path / "velho.db"
    Banco(caminho)
    with sqlite3.connect(caminho) as con:
        for col in ("ncm_pedido", "ncm_origem", "ncm_nota"):
            con.execute(f"ALTER TABLE me_item DROP COLUMN {col}")
    Banco(caminho)
    with sqlite3.connect(caminho) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(me_item)")}
    assert {"ncm_pedido", "ncm_origem", "ncm_nota"} <= cols
