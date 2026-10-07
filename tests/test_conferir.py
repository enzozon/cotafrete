"""Conferência da planilha (cruzar_nf/conferir.py): cada verificação vira correção exata."""

from __future__ import annotations

import json

from cruzar_nf.conferir import conferir, main, verificar_qualidade


def ped(oc, valor=100, **extra):
    return {"CIDADE": "X - MG", "PEDIDO": oc, "VALOR ": valor, "PRODUTO": "ITEM",
            "REQUISITANTE ": "FULANO", **extra}


def erp(oc, nf, valor):
    return {"Tipo": "VEN", "Código": 1, "Ordem Compra": oc, "NF": nf, "Filial": "VENTURA MATRIZ",
            "Cliente": "CLIENTE", "CNPJ/CPF": 33592510000100, "Total Líq.": valor}


def campos(achados):
    return [(a["linha"], a["campo"], a["sugerido"]) for a in achados]


def test_valor_em_texto_vira_numero():
    pedidos = [ped(1, "39.589,12"), ped(2, "3,961.46"), ped(3, "3290"), ped(4, 10.5)]
    assert campos(verificar_qualidade(pedidos, [])) == [
        (1, "VALOR ", 39589.12), (2, "VALOR ", 3961.46), (3, "VALOR ", 3290)]


def test_valor_vazio_ou_zero():
    achados = verificar_qualidade([ped(1, 0), ped(2, None)], [])
    assert [(a["linha"], a["certeza"]) for a in achados] == [(1, "verificar"), (2, "verificar")]


def test_espaco_invisivel_no_pedido():
    assert campos(verificar_qualidade([ped("4513542628\xa0")], [])) == [(1, "PEDIDO", "4513542628")]


def test_nf_que_no_erp_e_de_outra_oc():
    # caso real: 4513612720 recebeu a NF 15016, que no ERP é da OC 4101141499
    achados = verificar_qualidade([ped(4513612720, NF="15016")], [erp(4101141499, 15016, 1740)])
    assert campos(achados) == [(1, "NF", "")]
    assert "4101141499" in achados[0]["motivo"]


def test_nf_da_propria_oc_nao_e_problema():
    assert verificar_qualidade([ped(1, NF="15")], [erp(1, 15, 100)]) == []


def test_email_que_ficou_no_status():
    achados = verificar_qualidade([ped(1, STATUS="fulano@exemplo.com")], [])
    assert campos(achados) == [(1, "EMAIL REQUSITAN", "fulano@exemplo.com")]


def test_divergencia_positiva_sugere_o_valor_do_erp_e_negativa_vira_pendencia():
    pedidos = [ped(1, 100), ped(2, 300), ped(3, 50.5)]
    comparar = [erp(1, 10, 150), erp(2, 20, 200), erp(3, 30, 50)]
    res = conferir(pedidos, comparar)
    assert [(c["pedido"], c["sugerido"]) for c in res["correcoes"]] == [(1, 150)]
    assert [d["oc"] for d in res["falta_nf"]] == ["2"]          # 3 é arredondamento


def test_main_grava_relatorio_e_correcoes(tmp_path):
    (tmp_path / "PEDIDOS.json").write_text(json.dumps({"PEDIDOS": [ped(1, "1.234,50")]}), encoding="utf-8")
    (tmp_path / "comparar.json").write_text(json.dumps([erp(1, 10, 1234.5)]), encoding="utf-8")
    assert main(["--pedidos", str(tmp_path / "PEDIDOS.json"), "--comparar", str(tmp_path / "comparar.json"),
                 "--saida", str(tmp_path / "saida")]) == 0
    correcoes = json.loads((tmp_path / "saida" / "CORRECOES.json").read_text(encoding="utf-8"))
    assert correcoes[0]["sugerido"] == 1234.5
    assert "Correções sugeridas" in (tmp_path / "saida" / "CONFERENCIA.md").read_text(encoding="utf-8")
