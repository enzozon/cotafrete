"""Conferência planilha dos estagiários x portal (cruzar_nf/planilha_portal.py)."""

from __future__ import annotations

import datetime as dt
import json

from cruzar_nf.cadastro_pedidos import chave
from cruzar_nf.planilha_portal import conferir, main, nf_de, nfs, parear, resumo_para_tela

NF = "Nº NOTA FISCAL"


def lin(pedido, produto, nf=None, cidade="ITABIRA - MG", valor=100.0, rfq=None):
    d = {"CIDADE": cidade, "PEDIDO": pedido, "VALOR ": valor, "PRODUTO": produto}
    if rfq:
        d["NMR DA RFQ"] = rfq
    if nf:
        d[NF] = nf
    return d


def test_nf_de_acha_o_campo_mesmo_com_espaco():
    assert nf_de({"Nº NOTA FISCAL ": 15730}) == "15730"
    assert nf_de({"PEDIDO": 1}) == ""
    assert nfs("15020 / 15031") == nfs("15031/15020") == {"15020", "15031"}
    assert nfs("015730") == nfs(15730.0) == {"15730"}


def test_pareia_pela_mesma_regra_do_cadastro():
    linhas = [(2, lin(1, "MONITOR")), (3, lin(2, "TECLADO")), (4, lin(9, "SEM PAR", valor=5))]
    pedidos = [lin("2", "TECLADO USB"), lin(1, "MONITOR 24")]
    assert parear(linhas, pedidos) == {2: [1], 3: [0], 4: []}


def test_conferencia_lista_o_que_so_esta_de_um_lado_e_nf_diferente():
    linhas = [(2, lin(1, "MONITOR", nf="100", valor=1)), (3, lin(2, "TECLADO", nf="200", valor=2)),
              (4, lin(3, "MOUSE", valor=3)), (5, lin(9, "SEM PAR", valor=9)),
              (6, lin(8, "CANCELADO", valor=8))]
    pedidos = [lin(1, "MONITOR", nf="100", valor=1), lin(2, "TECLADO", nf="201", valor=2),
               lin(3, "MOUSE", nf="300", valor=3), lin(7, "SO NO PORTAL", valor=7)]
    rel = conferir(linhas, pedidos, ignorar={chave(linhas[4][1])})
    assert [x["linha"] for x in rel["planilha_sem_portal"]] == [5]
    assert [x["pedido"] for x in rel["portal_sem_planilha"]] == ["7"]
    assert rel["nf_divergente"] == [{"linha": 3, "pedido": "2", "produto": "TECLADO",
                                     "nf_planilha": "200", "nf_portal": "201"}]
    assert rel["nf_so_no_portal"] == 1 and rel["ignoradas"] == 1


def test_linha_cancelada_tambem_some_do_lado_do_portal():
    linhas = [(2, lin(8, "CANCELADO"))]
    rel = conferir(linhas, [lin(8, "CANCELADO")], ignorar={chave(linhas[0][1])})
    assert rel["planilha_sem_portal"] == [] and rel["portal_sem_planilha"] == []


def test_cli_grava_o_relatorio_uma_vez_por_dia(tmp_path, monkeypatch):
    import cruzar_nf.planilha_portal as pp
    monkeypatch.setattr(pp, "ler_planilha_com_linhas", lambda _c: [(2, lin(9, "SEM PAR", valor=9))])
    pedidos = tmp_path / "PEDIDOS.json"
    pedidos.write_text(json.dumps({"PEDIDOS": [lin(1, "X")]}), encoding="utf-8")
    dados = tmp_path / "dados"
    dados.mkdir()
    (dados / "conferencia_ignorar.json").write_text(json.dumps(
        [{"chave": "1||X", "motivo": "cancelado"}]), encoding="utf-8")
    args = ["--planilha", "x.xlsx", "--pedidos", str(pedidos), "--dados", str(dados)]
    assert main(args + ["--diario"]) == 0
    rel = json.loads((dados / "conferencia_planilha.json").read_text(encoding="utf-8"))
    assert len(rel["planilha_sem_portal"]) == 1 and rel["portal_sem_planilha"] == []
    monkeypatch.setattr(pp, "ler_planilha_com_linhas", lambda _c: 1 / 0)   # não pode ler de novo hoje
    assert main(args + ["--diario"]) == 0
    tela = resumo_para_tela(str(dados))
    assert tela["planilha_sem_portal"] == 1 and tela["gerado_em"].startswith(dt.date.today().strftime("%d/%m/%Y"))


def test_tela_sem_relatorio_ainda():
    assert resumo_para_tela("pasta_que_nao_existe") is None


def test_nf_so_no_excel_tambem_e_divergencia():
    rel = conferir([(2, lin(1, 'MONITOR', nf='123'))], [lin(1, 'MONITOR')], ignorar=set())
    assert rel['nf_divergente'][0]['nf_planilha'] == '123'
    assert rel['nf_divergente'][0]['nf_portal'] == ''
