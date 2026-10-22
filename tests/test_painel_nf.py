"""Dados dos dashboards de NFs e Atividade (cruzar_nf/painel_nf.py) e os comandos no maestro."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest

from cruzar_nf import painel_nf as PN
from cruzar_nf.cruzar import cruzar
from cruzar_nf.maestro import registrar

HOJE = dt.date(2026, 10, 15)
AGORA = dt.datetime(2026, 10, 15, 14, 0, 0)


def gravar(pasta, nome, dados):
    arq = pasta / nome
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def sem_nf(pedido, entrega, rfq="R1"):
    return {"posicao": 1, "pedido": pedido, "oc": str(pedido), "status": "nao_encontrado", "nfs": [],
            "rfq": rfq, "entrega": entrega, "cidade": "ITABIRA - MG", "produto": "MONITOR <b>24</b>"}


@pytest.fixture
def dados(tmp_path):
    d = tmp_path / "sync_nf"
    gravar(d, "sync_nf.json", {
        "ultima": {"rodou_em": "2026-10-15T12:30:21", "origem": "linha de comando", "de": "04/10/2026",
                   "ate": "15/10/2026", "nfs_gravadas": 2, "pedidos": 581, "pedidos_com_nf": 507,
                   "sem_nf": 74, "divergencias": 8, "aviso": None},
        "cobertura": [["01/01/2025", "15/10/2026"]],
        "historico": [
            {"inicio": "2026-10-15T12:30:01", "rodou_em": "2026-10-15T12:30:21", "origem": "linha de comando",
             "sucesso": True, "gravou": True, "nfs_gravadas": 2, "sem_nf": 74, "divergencias": 8, "aviso": None},
            {"rodou_em": "2026-10-14T07:30:00", "origem": "agendado", "sucesso": False, "erro": "HSE fora do ar"},
            {"rodou_em": "2026-10-01T07:30:00", "origem": "agendado", "sucesso": True, "gravou": True,
             "nfs_gravadas": 5, "sem_nf": 80},
        ]})
    gravar(d, "cruzamento_nf/RELATORIO_NF_ultimo.json", {
        "gerado_em": "2026-10-15T12:30:21",
        "nao_encontrados": [sem_nf(1, "10/10/2026"), sem_nf(2, "24-Jun"), sem_nf(3, "01/09/2026")],
        "sem_nf": [], "pedido_invalido": [],
        "divergencia_valor": [{"pedido": 9, "produto": "MOUSE", "nf_anterior": None, "nf_gravada": "15730",
                               "nfs": ["15730"], "valor_planilha": "100.00", "valor_erp": "90.00",
                               "diferenca_valor": "-10.00"}],
        "nf_alterada": [], "so_no_erp": [{"oc": "x"}] * 3})
    gravar(d, "conferencia_planilha.json", {
        "gerado_em": "15/10/2026 12:37:06", "nf_so_no_portal": 1,
        "nf_so_no_portal_lista": [{"linha": 4, "pedido": "3", "produto": "MOUSE", "nf_portal": "300"}]})
    gravar(d, "cadastro_pedidos.json", {
        "vistos": ["a"], "verificado_em": "15/10/2026 13:52:01",
        "historico": [
            {"rodou_em": "15/10/2026 10:02:01", "primeira_vez": False, "novas": 2, "ja_no_portal": 0,
             "gravados": 2, "pedidos": ["4513664056 - MONITOR", "4513664057 - MOUSE"], "repetidas": []},
            {"rodou_em": "14/10/2026 10:02:01", "primeira_vez": False, "novas": 1, "ja_no_portal": 0,
             "gravados": 0, "pedidos": [], "repetidas": ["77 - TECLADO"]},
        ],
        "erro": {"em": "15/10/2026 13:42:01", "mensagem": "Planilha aberta " + "x" * 200}})
    gravar(d, "sync_planilha_portal_historico.json", {"rodadas": [
        {"em": "15/10/2026 12:37:00", "resultado": "gravou", "aviso": None, "contagens": {"acoes": 3, "conflitos": 0}},
        {"em": "15/10/2026 13:07:00", "resultado": "adiado", "aviso": "Planilha aberta por FULANO",
         "contagens": {"acoes": 1}},
    ]})
    return d


def hashes(pasta):
    return {str(a): hashlib.sha256(a.read_bytes()).hexdigest() for a in sorted(pasta.rglob("*")) if a.is_file()}


# -- painel de NFs ---------------------------------------------------------------

def test_painel_traz_cada_parte_no_formato_da_tela(dados):
    p = PN.painel_para_tela(dados, hoje=HOJE)
    ind = p["indicadores"]
    assert (ind["com_nf"], ind["total"], ind["sem_nf"], ind["divergencias"]) == (507, 581, 74, 8)
    assert ind["periodo"] == {"de": "01/01/2025", "ate": "15/10/2026"} and ind["proxima_janela"]["de"]
    rel = p["relatorio"]
    assert rel["total_sem_nf"] == 3 and rel["total_divergencias"] == 1
    assert set(rel["sem_nf"][0]) == {"pedido", "rfq", "produto", "cidade", "entrega", "dias_desde_entrega", "motivo"}
    div = rel["divergencias"][0]
    assert div["nf_portal"] == "15730" and div["nf_hse"] == "15730" and "100.00" in div["motivo"]
    assert p["nf_so_no_portal"] == {"gerado_em": "15/10/2026 12:37:06", "total": 1,
                                    "itens": [{"linha": 4, "pedido": "3", "produto": "MOUSE", "nf_portal": "300"}]}
    assert p["rodadas"][0]["inicio"] == "2026-10-15T12:30:01" and p["rodadas"][1]["erro"] == "HSE fora do ar"
    assert p["cadastro"]["ultimo_cadastro"]["gravados"] == 2 and p["cadastro"]["erro"]["mensagem"]


def test_sem_nf_mais_antigo_primeiro_e_data_ilegivel_no_fim(dados):
    lista = PN.painel_para_tela(dados, hoje=HOJE)["relatorio"]["sem_nf"]
    assert [i["pedido"] for i in lista] == ["3", "1", "2"]
    assert [i["dias_desde_entrega"] for i in lista] == [44, 5, None]
    assert lista[2]["entrega"] == "24-Jun"         # texto cru continua visível


def test_fonte_quebrada_vira_erro_e_nao_zero(dados):
    (dados / "cruzamento_nf" / "RELATORIO_NF_ultimo.json").write_text("{quebrado", encoding="utf-8")
    (dados / "conferencia_planilha.json").unlink()
    p = PN.painel_para_tela(dados, hoje=HOJE)
    assert "erro" in p["relatorio"] and "total_sem_nf" not in p["relatorio"]
    assert p["nf_so_no_portal"] == {"erro": "Ainda não gerado."}
    assert p["indicadores"]["com_nf"] == 507          # as outras partes continuam


def test_conferencia_antiga_sem_lista_nao_finge_lista_vazia(dados):
    gravar(dados, "conferencia_planilha.json", {"gerado_em": "x", "nf_so_no_portal": 507})
    assert PN.painel_para_tela(dados, hoje=HOJE)["nf_so_no_portal"]["itens"] is None


def test_cruzamento_leva_rfq_e_entrega_para_o_relatorio():
    _, rel = cruzar([{"PEDIDO": 4513664056, "NMR DA RFQ": "R9", "DATA DE ENTREGA": "10/10/2026"}], [])
    assert rel["nao_encontrados"][0]["rfq"] == "R9" and rel["nao_encontrados"][0]["entrega"] == "10/10/2026"


# -- eventos ---------------------------------------------------------------------

def test_eventos_no_contrato_e_mais_novos_primeiro(dados):
    r = PN.eventos(dados, agora=AGORA)
    assert r["erros"] == {}
    for e in r["eventos"]:
        assert set(e) == {"em", "servico", "tipo", "nivel", "resumo", "ref", "detalhe"}
        assert e["servico"] in {"gerenciador", "coupa", "vale", "cadastro", "nf", "sync_planilha"}
        assert e["nivel"] in {"ok", "info", "aviso", "erro"} and len(e["resumo"]) <= 140
        assert dt.datetime.fromisoformat(e["em"]).tzinfo is not None
    ems = [e["em"] for e in r["eventos"]]
    assert ems == sorted(ems, reverse=True)
    primeiro = r["eventos"][0]
    assert primeiro["servico"] == "cadastro" and primeiro["nivel"] == "erro" and primeiro["resumo"].endswith("…")
    niveis = {(e["servico"], e["nivel"]) for e in r["eventos"]}
    assert {("nf", "ok"), ("nf", "erro"), ("sync_planilha", "ok"), ("sync_planilha", "aviso"),
            ("cadastro", "ok"), ("cadastro", "aviso")} <= niveis
    cad = next(e for e in r["eventos"] if e["servico"] == "cadastro" and e["nivel"] == "ok")
    assert cad["ref"] == "4513664056" and len(cad["detalhe"]["pedidos"]) == 2


def test_eventos_cortam_7_dias(dados):
    r = PN.eventos(dados, agora=AGORA)
    assert not any(e["em"].startswith("2026-10-01") for e in r["eventos"])
    assert any(e["em"].startswith("2026-10-14") for e in r["eventos"])
    depois = PN.eventos(dados, agora=AGORA + dt.timedelta(days=7))["eventos"]
    assert not any(e["em"].startswith("2026-10-14") for e in depois)


def test_eventos_desde_e_limite(dados):
    desde = PN.eventos(dados, agora=AGORA, desde="2026-10-15T12:37:00")["eventos"]
    assert desde and all(e["em"][:19] > "2026-10-15T12:37:00" for e in desde)
    assert len(PN.eventos(dados, agora=AGORA, limite=2)["eventos"]) == 2
    assert len(PN.eventos(dados, agora=AGORA, limite=99999)["eventos"]) <= PN.MAX_EVENTOS
    assert len(PN.eventos(dados, agora=AGORA, limite="lixo")["eventos"]) > 0


def test_uma_fonte_quebrada_nao_esconde_as_outras(dados):
    (dados / "sync_planilha_portal_historico.json").write_text("[", encoding="utf-8")
    r = PN.eventos(dados, agora=AGORA)
    assert "sync_planilha" in r["erros"] and any(e["servico"] == "nf" for e in r["eventos"])


def test_pasta_vazia_nao_quebra(tmp_path):
    assert PN.eventos(tmp_path, agora=AGORA) == {"eventos": [], "total": 0, "erros": {}}
    p = PN.painel_para_tela(tmp_path, hoje=HOJE)
    assert "erro" in p["indicadores"] and "erro" in p["relatorio"]


def test_leituras_nao_alteram_nenhum_arquivo(dados):
    antes = hashes(dados)
    PN.painel_para_tela(dados, hoje=HOJE)
    PN.eventos(dados, agora=AGORA)
    assert hashes(dados) == antes


# -- comandos no serviço -------------------------------------------------------------

class Sio:
    def __init__(self):
        self.handlers, self.emitidos = {}, []

    def on(self, evento, handler):
        self.handlers[evento] = handler

    def emit(self, evento, dados=None):
        self.emitidos.append((evento, dados))


class Log:
    def info(self, *_):
        pass

    error = info


def test_comandos_respondem_com_o_client_id(dados, monkeypatch):
    # Os eventos são "dos últimos 7 dias": sem relógio fixo o teste vencia uma
    # semana depois das datas do `dados` (falhou em 22/10/2026).
    eventos = PN.eventos
    monkeypatch.setattr(PN, "eventos", lambda pasta, limite=200, desde=None, agora=None:
                        eventos(pasta, limite, desde, agora=agora or AGORA))
    sio = Sio()
    registrar(sio, {"caminho_banco_dados": str(dados)}, Log(), manager=object(), em_thread=False)
    sio.handlers["comando_nf_painel"]({"clientId": "c1"})
    sio.handlers["comando_eventos_nf"]({"clientId": "c2", "limite": 3})
    sio.handlers["comando_eventos_nf"](None)
    (ev1, r1), (ev2, r2), (_, r3) = sio.emitidos
    assert ev1 == "retorno_nf_painel" and r1["sucesso"] and r1["clientId"] == "c1"
    assert r1["painel"]["rodando"] is False and r1["painel"]["indicadores"]["com_nf"] == 507
    assert ev2 == "retorno_eventos_nf" and r2["clientId"] == "c2" and len(r2["resultado"]["eventos"]) == 3
    assert r3["sucesso"] and r3["clientId"] is None


def test_comando_com_erro_responde_sem_derrubar(dados, monkeypatch):
    sio = Sio()
    registrar(sio, {"caminho_banco_dados": str(dados)}, Log(), manager=object(), em_thread=False)
    monkeypatch.setattr(PN, "eventos", lambda *a, **k: 1 / 0)
    sio.handlers["comando_eventos_nf"]({"clientId": "c"})
    assert sio.emitidos[-1][1] == {"sucesso": False, "erro": "division by zero", "clientId": "c"}
