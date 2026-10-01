"""Buscas locais no ERP para os pedidos sem NF e as divergências (cruzar_nf/investigar.py)."""

from __future__ import annotations

import json

import pytest

from cruzar_nf.investigar import investigar, main, um_digito_de_diferenca


@pytest.mark.parametrize("a,b,esperado", [
    ("4500249590", "45002495990", True),   # dígito sobrando (caso real da NF 13768)
    ("4101211034", "41014211034", True),   # dígito sobrando (caso real da NF 15677)
    ("4101092629", "4101091629", True),    # dígito trocado
    ("4101127296", "4101127396", True),
    ("4101235178", "4101239978", False),   # duas trocas
    ("4101235178", "4101231278", False),
    ("123456", "123465", True),            # vizinhos invertidos
    ("123456", "123456", False),           # igual não é "parecida"
    ("123456", "12345678", False),
])
def test_um_digito_de_diferenca(a, b, esperado):
    assert um_digito_de_diferenca(a, b) is esperado


def venda(oc, nf, valor, cnpj=33592510000100, filial="VENTURA MATRIZ", codigo=1):
    return {"Tipo": "VEN", "Código": codigo, "Ordem Compra": oc, "NF": nf, "Filial": filial,
            "Cliente": "CLIENTE", "CNPJ/CPF": cnpj, "Emissão": "8/11/2025", "Total Líq.": valor}


def relatorio(nao_encontrados=(), divergencias=(), bateram=()):
    return {"bateram": list(bateram), "mais_de_uma_nf": [], "sem_nf": [],
            "nao_encontrados": list(nao_encontrados), "divergencia_valor": list(divergencias)}


def test_divergencia_acha_a_nf_com_oc_digitada_errada():
    comparar = [venda(4500249590, 13653, 48412.35), venda(45002495990, 13768, 28230, codigo=1704)]
    rel = relatorio(bateram=[{"oc": "4500249590"}],
                    divergencias=[{"oc": "4500249590", "cidade": "MARIANA - MG", "diferenca_valor": "-28230.00"}])
    bloco = investigar(comparar, rel)["divergencias"][0]
    assert bloco["oc_parecida"][0]["oc_no_erp"] == "45002495990"
    assert bloco["oc_parecida"][0]["total"] == "28230.00"
    assert bloco["oc_parecida"][0]["mesmo_cliente"] is True
    assert [v["nf"] for v in bloco["mesmo_valor"]] == ["13768"]
    assert bloco["mesmo_valor"][0]["mesmo_cliente"] is True


def test_pedido_sem_nf_acha_venda_pelo_valor():
    comparar = [venda(4101091629, 14524, 380.01)]
    rel = relatorio(nao_encontrados=[{"oc": "4101092629", "cidade": "SAO LUIS-MA", "valor_planilha": "380.01"}])
    bloco = investigar(comparar, rel)["sem_nf"][0]
    assert bloco["oc_parecida"][0]["oc_no_erp"] == "4101091629"
    assert bloco["mesmo_valor"][0]["nf"] == "14524"
    assert bloco["mesmo_valor"][0]["mesmo_cliente"] is None   # pedido sem NF: cliente desconhecido


def test_venda_ja_ligada_a_outro_pedido_nao_entra():
    comparar = [venda(4101091629, 14524, 380.01)]
    rel = relatorio(bateram=[{"oc": "4101091629"}],
                    nao_encontrados=[{"oc": "4101092629", "valor_planilha": "380.01"}])
    bloco = investigar(comparar, rel)["sem_nf"][0]
    assert bloco["oc_parecida"] == [] and bloco["mesmo_valor"] == []


def test_valor_igual_de_outro_cliente_vem_marcado():
    comparar = [venda(4101000001, 1, 100, cnpj=33592510000100),
                venda(999999, 2, 50, cnpj=11111111000100)]
    rel = relatorio(bateram=[{"oc": "4101000001"}],
                    divergencias=[{"oc": "4101000001", "diferenca_valor": "-50.00"}])
    achada = investigar(comparar, rel)["divergencias"][0]["mesmo_valor"][0]
    assert achada["nf"] == "2" and achada["mesmo_cliente"] is False


def test_oc_curta_nao_compara():
    comparar = [venda(15121, 1, 10)]
    rel = relatorio(nao_encontrados=[{"oc": "15120", "valor_planilha": "99"}])
    assert investigar(comparar, rel)["sem_nf"][0]["oc_parecida"] == []


def test_main_grava_o_json(tmp_path):
    (tmp_path / "comparar.json").write_text(json.dumps([venda(4101091629, 14524, 380.01)]), encoding="utf-8")
    (tmp_path / "RELATORIO_NF.json").write_text(json.dumps(
        relatorio(nao_encontrados=[{"oc": "4101092629", "valor_planilha": "380.01"}])), encoding="utf-8")
    assert main(["--pasta", str(tmp_path)]) == 0
    dados = json.loads((tmp_path / "INVESTIGACAO_ERP.json").read_text(encoding="utf-8"))
    assert dados["sem_nf"][0]["mesmo_valor"][0]["valor"] == "380.01"
