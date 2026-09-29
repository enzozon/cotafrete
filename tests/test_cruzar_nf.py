"""Cruzamento PEDIDOS.json x comparar.json (cruzar_nf/)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cruzar_nf.__main__ import main
from cruzar_nf.cruzar import (
    BATEU, MAIS_DE_UMA_NF, NAO_ENCONTRADO, PEDIDO_INVALIDO, SEM_NF,
    cruzar, ler_json, normalizar_nf, normalizar_oc, relatorio_markdown, rodar, valor_decimal,
)

# o exemplo que veio da planilha real (e-mail trocado)
PEDIDO_EXEMPLO = {
    "CIDADE": "OURO PRETO - MG",
    "FRETE": "EXW",
    "PEDIDO": 4101141499,
    "VALOR ": 1740,
    "PRODUTO": "PAR HELICE ORIGINAL DRONE DJI MAVIC 3 ENTERPRISE -entregue em 22/12",
    "DATA DE ENTREGA": "31-Dec",
    "REQUISITANTE ": "MICHELI",
    "EMAIL REQUSITAN": "requisitante@exemplo.com",
}
ERP_EXEMPLO = {
    "Tipo": "VEN", "Código": 2635, "Ordem Compra": 4101141499,
    "Cliente": "MINA DE CAPANEMA/VALE S.A.", "Emissão": "26/12/2025",
    "Total Bruto": "1.740,000000", "Total Líq.": "1.740,000000", "NF": 15016,
}


def erp(oc, nf, total="100,00"):
    return {**ERP_EXEMPLO, "Ordem Compra": oc, "NF": nf, "Total Líq.": total}


def ped(oc, valor=100, **extra):
    return {**PEDIDO_EXEMPLO, "PEDIDO": oc, "VALOR ": valor, **extra}


def status(rel, secao):
    return [p["oc"] for p in rel[secao]]


def test_exemplo_da_planilha_ganha_a_nf_no_fim_como_texto():
    atualizados, rel = cruzar([PEDIDO_EXEMPLO], [ERP_EXEMPLO])
    assert atualizados == [{**PEDIDO_EXEMPLO, "NF": "15016"}]
    assert list(atualizados[0])[-1] == "NF"
    assert rel["resumo"]["bateram_1_nf"] == 1
    assert rel["resumo"]["divergencia_de_valor"] == 0


def test_nao_altera_a_lista_recebida():
    pedidos = [dict(PEDIDO_EXEMPLO)]
    cruzar(pedidos, [ERP_EXEMPLO])
    assert "NF" not in pedidos[0]


def test_mais_de_uma_nf_grava_todas():
    atualizados, rel = cruzar([ped(1)], [erp(1, 10), erp(1, 11), erp(1, 10)])
    assert atualizados[0]["NF"] == "10 / 11"
    assert status(rel, "mais_de_uma_nf") == ["1"]


def test_oc_no_erp_sem_nf():
    atualizados, rel = cruzar([ped(1)], [erp(1, 0), erp(1, None), erp(1, "")])
    assert atualizados[0]["NF"] == ""
    assert status(rel, "sem_nf") == ["1"]


def test_oc_so_na_planilha_e_so_no_erp():
    _, rel = cruzar([ped(1), ped(2)], [erp(2, 20), erp(3, 30)])
    assert status(rel, "nao_encontrados") == ["1"]
    assert [o["oc"] for o in rel["so_no_erp"]] == ["3"]
    assert rel["so_no_erp"][0]["nfs"] == ["30"]


def test_oc_casa_mesmo_com_tipo_e_espaco_diferentes():
    pedidos = [ped(" 4101141499 "), ped("4101141499.0"), ped(4101141499.0)]
    atualizados, rel = cruzar(pedidos, [{**ERP_EXEMPLO, "Ordem Compra": "4101141499"}])
    assert [p["NF"] for p in atualizados] == ["15016"] * 3
    assert rel["resumo"]["pedidos_duplicados_na_planilha"] == 1


def test_campo_com_espaco_acento_ou_caixa_diferente():
    registro = {"ordem compra ": 5, "nf": 50, "Total Liq.": "1,00"}
    _, rel = cruzar([ped(5, valor=1)], [registro])
    assert status(rel, "bateram") == ["5"]


def test_pedido_vazio_e_invalido():
    atualizados, rel = cruzar([ped(""), ped(None), ped(0)], [erp(1, 1)])
    assert len(rel["pedido_invalido"]) == 3
    assert all(p["NF"] == "" for p in atualizados)


def test_nf_que_ja_existia_fica_se_o_erp_nao_tem():
    atualizados, _ = cruzar([ped(1, NF="999"), ped(2, NF="888")], [erp(2, 0)])
    assert [p["NF"] for p in atualizados] == ["999", "888"]


def test_nf_trocada_vale_a_do_erp_e_vai_para_o_relatorio():
    atualizados, rel = cruzar([ped(1, NF="999")], [erp(1, 15)])
    assert atualizados[0]["NF"] == "15"
    assert rel["nf_alterada"][0]["nf_anterior"] == "999"


def test_nf_existente_com_outro_nome_nao_duplica():
    atualizados, _ = cruzar([ped(1, **{"NF ": "7"})], [erp(1, 15)])
    assert [k for k in atualizados[0] if k.strip() == "NF"] == ["NF"]


def test_divergencia_de_valor_soma_as_vendas_da_oc():
    _, rel = cruzar([ped(1, valor=3200), ped(2, valor=100)],
                    [erp(1, 10, "1.600,00"), erp(1, 11, "1.600,00"), erp(2, 20, "150,00")])
    assert status(rel, "divergencia_valor") == ["2"]
    assert rel["divergencia_valor"][0]["diferenca_valor"] == "50.00"


def test_mesma_nf_para_varias_ocs():
    _, rel = cruzar([ped(1), ped(2)], [erp(1, 50), erp(2, 50)])
    assert rel["nf_varias_ocs"] == [{"nf": "50", "ocs": ["1", "2"], "na_planilha": ["1", "2"]}]


def test_linha_do_erp_sem_oc_e_contada_e_ignorada():
    _, rel = cruzar([ped(1)], [erp(0, 1), erp(None, 2), erp(1, 3)])
    assert rel["resumo"]["linhas_erp_sem_oc"] == 2
    assert status(rel, "bateram") == ["1"]


@pytest.mark.parametrize("entrada,esperado", [
    (4101141499, "4101141499"), ("4101141499", "4101141499"), (4101141499.0, "4101141499"),
    ("  4101141499.0 ", "4101141499"), (0, None), ("", None), (None, None), (True, None),
    ("abc", None), (1.5, None),
])
def test_normalizar_oc(entrada, esperado):
    assert normalizar_oc(entrada) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    (15016, "15016"), ("15016", "15016"), (15016.0, "15016"), (0, None), ("0", None),
    ("", None), (None, None), ("-", None),
])
def test_normalizar_nf(entrada, esperado):
    assert normalizar_nf(entrada) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("1.740,000000", Decimal("1740")), (1740, Decimal("1740")), (980.5, Decimal("980.5")),
    ("R$ 1.234,56", Decimal("1234.56")), ("", None), (None, None),
])
def test_valor_decimal(entrada, esperado):
    assert valor_decimal(entrada) == esperado


def test_status_cobre_todos_os_casos():
    _, rel = cruzar([ped(1), ped(2), ped(3), ped(4), ped("")],
                    [erp(1, 1), erp(2, 2), erp(2, 3), erp(3, 0)])
    r = rel["resumo"]
    assert (r["bateram_1_nf"], r["mais_de_uma_nf"], r["no_erp_sem_nf"],
            r["nao_encontrados_no_erp"], r["pedido_invalido"]) == (1, 1, 1, 1, 1)
    assert r["percentual_com_nf"] == 40.0
    assert [p["status"] for p in rel["bateram"] + rel["mais_de_uma_nf"] + rel["sem_nf"]
            + rel["nao_encontrados"] + rel["pedido_invalido"]] == [
        BATEU, MAIS_DE_UMA_NF, SEM_NF, NAO_ENCONTRADO, PEDIDO_INVALIDO]


def test_ler_json_aceita_objeto_embrulhado_e_bom(tmp_path):
    arq = tmp_path / "p.json"
    arq.write_bytes(b"\xef\xbb\xbf" + json.dumps({"pedidos": [PEDIDO_EXEMPLO]}).encode())
    assert ler_json(arq) == [PEDIDO_EXEMPLO]


def test_ler_json_recusa_objeto_ambiguo(tmp_path):
    arq = tmp_path / "p.json"
    arq.write_text(json.dumps({"a": [], "b": []}))
    with pytest.raises(ValueError):
        ler_json(arq)


def test_rodar_grava_arquivos_e_preserva_o_original(tmp_path):
    pedidos = tmp_path / "PEDIDOS.json"
    original = json.dumps([PEDIDO_EXEMPLO], ensure_ascii=False, indent=1)
    pedidos.write_text(original, encoding="utf-8")
    (tmp_path / "comparar.json").write_text(json.dumps([ERP_EXEMPLO]), encoding="utf-8")

    assert main(["--pasta", str(tmp_path)]) == 0

    assert pedidos.read_text(encoding="utf-8") == original
    novo = json.loads((tmp_path / "PEDIDOS_ATUALIZADO.json").read_text(encoding="utf-8"))
    assert novo[0]["NF"] == "15016"
    assert "Bateram (1)" in (tmp_path / "RELATORIO_NF.md").read_text(encoding="utf-8")
    rel = json.loads((tmp_path / "RELATORIO_NF.json").read_text(encoding="utf-8"))
    assert rel["resumo"]["bateram_1_nf"] == 1


def test_rodar_nao_sobrescreve_o_proprio_pedidos(tmp_path):
    arq = tmp_path / "PEDIDOS.json"
    arq.write_text("[]")
    with pytest.raises(ValueError):
        rodar(arq, arq, arq)


def test_main_sem_arquivo_da_erro(tmp_path, capsys):
    assert main(["--pasta", str(tmp_path)]) == 1
    assert "não achei" in capsys.readouterr().err


def test_relatorio_markdown_tem_todas_as_secoes():
    _, rel = cruzar([ped(1)], [erp(1, 1)])
    md = relatorio_markdown(rel)
    for secao in ("Resumo", "Mais de uma NF", "sem NF", "não no ERP", "não na planilha",
                  "Divergência de valor", "Mesma NF", "repetido", "NF da planilha trocada",
                  "vazio ou inválido", "Bateram"):
        assert secao in md, secao
