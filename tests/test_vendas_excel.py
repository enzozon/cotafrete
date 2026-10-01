"""Leitura do Excel do HSE e base acumulada de vendas (cruzar_nf/vendas_excel.py, base_vendas.py)."""

from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

import pytest

from cruzar_nf.base_vendas import BaseVendas, chave_venda, data_br
from cruzar_nf.cruzar import cruzar
from cruzar_nf.vendas_excel import ExcelInvalido, ler_excel_vendas, resumo_excel

CABECALHO = [None, "Tipo", "Código", None, "Ped.Compra", "Emissão", "Ordem Compra", "Cliente",
             "CNPJ/CPF", "Total Bruto", "Total Líq.", "Filial", "NF"]


def excel(tmp_path, linhas, nome="vendas.xlsx"):
    """Monta um Excel no formato do HSE: 2 linhas vazias, cabeçalho, vendas, vazias."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None] * len(CABECALHO))
    ws.append([None] * len(CABECALHO))
    ws.append(CABECALHO)
    for l in linhas:
        ws.append(l)
    ws.append([None] * len(CABECALHO))
    caminho = tmp_path / nome
    wb.save(caminho)
    return caminho


def venda(codigo, oc, nf, valor, emissao=dt.datetime(2026, 9, 29), filial="VENTURA MATRIZ"):
    return [None, "VEN", codigo, None, 7000, emissao, oc, "CLIENTE", 33592510000100, valor, valor, filial, nf]


# -- leitura do Excel -----------------------------------------------------------

def test_le_o_excel_no_formato_do_hse(tmp_path):
    vendas = ler_excel_vendas(excel(tmp_path, [venda(4617, 4500785593, 16240, 2351.8),
                                               venda(4611, "046366", 16234, 295)]))
    assert len(vendas) == 2
    assert vendas[0]["Emissão"] == "29/09/2026"
    assert vendas[0]["Ordem Compra"] == 4500785593 and vendas[0]["NF"] == 16240
    assert vendas[1]["Ordem Compra"] == "046366"
    assert "" not in vendas[0]   # coluna sem nome não entra


def test_ignora_linha_vazia_total_e_cabecalho_repetido(tmp_path):
    total = [None, None, None, None, None, None, None, None, None, 9999, 9999, None, None]
    vendas = ler_excel_vendas(excel(tmp_path, [venda(1, 10, 100, 5.0), total, CABECALHO, venda(2, 20, 200, 6.0)]))
    assert [v["Código"] for v in vendas] == [1, 2]


def test_float_inteiro_vira_int(tmp_path):
    vendas = ler_excel_vendas(excel(tmp_path, [venda(1.0, 4500785593.0, 16240.0, 10.5)]))
    assert vendas[0]["Código"] == 1 and vendas[0]["Ordem Compra"] == 4500785593
    assert vendas[0]["Total Líq."] == 10.5


def test_excel_de_outra_tela_da_erro_claro(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.append(["Filial", "Emissão", "Nota", "Valor"])
    wb.save(tmp_path / "notas.xlsx")
    with pytest.raises(ExcelInvalido):
        ler_excel_vendas(tmp_path / "notas.xlsx")


def test_resumo(tmp_path):
    vendas = ler_excel_vendas(excel(tmp_path, [venda(1, 1, 1, 1, dt.datetime(2026, 9, 1)),
                                               venda(2, 2, 2, 2, dt.datetime(2026, 9, 29))]))
    assert resumo_excel(vendas) == {"vendas": 2, "emissao_min": "01/09/2026", "emissao_max": "29/09/2026"}


def test_vendas_do_excel_cruzam_com_os_pedidos(tmp_path):
    vendas = ler_excel_vendas(excel(tmp_path, [venda(1, 4101141499, 15016, 1740)]))
    atualizados, rel = cruzar([{"PEDIDO": 4101141499, "VALOR ": 1740}], vendas)
    assert atualizados[0]["NF"] == "15016"
    assert rel["resumo"]["divergencia_de_valor"] == 0   # valor numérico do Excel não é dividido


HTML_HSE = Path(__file__).parent / "fixtures" / "hse" / "venda_pedido_2026-09-29.xls"


def test_le_o_xls_do_hse_que_e_html():
    # o botão Excel do HSE baixa uma tabela HTML com extensão .xls (01/10/2026)
    vendas = ler_excel_vendas(HTML_HSE)
    assert [v["Código"] for v in vendas] == [4617, 4616]          # a linha de total ficou de fora
    assert vendas[0]["Total Líq."] == 2351.8 and vendas[1]["Total Líq."] == 1091.9
    assert vendas[0]["Ordem Compra"] == "4500785593" and vendas[1]["NF"] == 15726
    assert vendas[1]["Filial"] == "VENTURA MATRIZ" and vendas[0]["Emissão"] == "29/09/2026"


def test_oc_com_zero_a_esquerda_continua_texto(tmp_path):
    html = ('<html><body><table><tr><td></td><td>Tipo</td><td>Código</td><td>Ordem Compra</td><td>Filial</td>'
            '<td>NF</td><td>Total Líq.</td><td>Emissão</td></tr><tr><td></td><td>VEN</td><td>4611</td>'
            '<td>046366</td><td>ALIANCA</td><td>16234</td><td>295,000000</td><td>28/09/2026</td></tr></table></body></html>')
    arq = tmp_path / "x.xls"
    arq.write_text("\ufeff" + html, encoding="utf-8")
    v = ler_excel_vendas(arq)[0]
    assert v["Ordem Compra"] == "046366" and v["Total Líq."] == 295.0 and v["Código"] == 4611


def test_base_misturando_xlsx_e_html_nao_divide_valor(tmp_path):
    # primeira carga do .xlsx (números) + incremental do HTML (texto): o cruzamento
    # não pode tratar o inteiro do .xlsx como "6 casas embutidas"
    xlsx = ler_excel_vendas(excel(tmp_path, [venda(1, 4101000001, 15000, 1740, dt.datetime(2026, 9, 10))]))
    html = ler_excel_vendas(HTML_HSE)
    base = BaseVendas()
    base.mesclar(xlsx, dt.date(2025, 1, 1), dt.date(2026, 9, 28))
    base.mesclar(html, dt.date(2026, 9, 29), dt.date(2026, 9, 29))
    _, rel = cruzar([{"PEDIDO": 4101000001, "VALOR ": 1740}, {"PEDIDO": 4400844711, "VALOR ": 1091.9}], base.lista())
    assert rel["resumo"]["bateram_1_nf"] == 2 and rel["resumo"]["divergencia_de_valor"] == 0


EXCEL_REAL = Path(r"C:\Users\vendas12\.claude\uploads\4fc17f8a-a4ee-4470-a59e-eab1ca64a1d1\a25e9a73-planilha_atualizada.xlsx")


@pytest.mark.skipif(not EXCEL_REAL.is_file(), reason="Excel real só existe na máquina do Enzo")
def test_excel_real_do_hse():
    vendas = ler_excel_vendas(EXCEL_REAL)
    assert len(vendas) == 4055
    assert resumo_excel(vendas)["emissao_min"] == "02/01/2025"
    assert len({chave_venda(v) for v in vendas}) == 4055     # chave empresa+código é única


# -- base acumulada -------------------------------------------------------------

def v(codigo, oc, nf, valor, emissao="15/09/2026", filial="VENTURA MATRIZ"):
    return {"Tipo": "VEN", "Código": codigo, "Emissão": emissao, "Ordem Compra": oc,
            "NF": nf, "Total Líq.": valor, "Filial": filial}


D = dt.date


def test_mescla_novas_alteradas_e_cobertura():
    base = BaseVendas()
    est = base.mesclar([v(1, 10, 100, 5), v(2, 20, None, 6)], D(2026, 9, 1), D(2026, 9, 30))
    assert est == {"recebidas": 2, "novas": 2, "alteradas": 0, "removidas": 0, "total_na_base": 2}
    # a venda 2 ganhou NF; a 1 veio igual
    est = base.mesclar([v(1, 10, 100, 5), v(2, 20, 200, 6)], D(2026, 9, 20), D(2026, 10, 1))
    assert (est["novas"], est["alteradas"]) == (0, 1)
    assert base.cobertura == [(D(2026, 9, 1), D(2026, 10, 1))]
    assert base.ultima_data() == D(2026, 10, 1)


def test_venda_que_sumiu_da_janela_sai_e_fora_da_janela_fica():
    base = BaseVendas()
    base.mesclar([v(1, 10, 100, 5, "05/09/2026"), v(2, 20, 200, 6, "25/09/2026")], D(2026, 9, 1), D(2026, 9, 30))
    est = base.mesclar([v(3, 30, 300, 7, "26/09/2026")], D(2026, 9, 20), D(2026, 9, 30))
    assert est["removidas"] == 1                                  # a 2 (25/09) foi cancelada
    assert sorted(x["Código"] for x in base.lista()) == [1, 3]    # a 1 (05/09) está fora da janela


def test_mesmo_codigo_em_empresas_diferentes_sao_vendas_diferentes():
    base = BaseVendas()
    base.mesclar([v(1, 10, 100, 5, filial="UNIAO"), v(1, 99, 900, 9, filial="ALIANCA")], D(2026, 9, 1), D(2026, 9, 30))
    assert len(base.lista()) == 2


def test_periodos_separados_continuam_separados():
    base = BaseVendas(cobertura=[(D(2025, 1, 1), D(2025, 1, 31))])
    base.mesclar([], D(2025, 3, 1), D(2025, 3, 31))
    assert base.cobertura == [(D(2025, 1, 1), D(2025, 1, 31)), (D(2025, 3, 1), D(2025, 3, 31))]


def test_salvar_e_carregar(tmp_path):
    base = BaseVendas()
    base.mesclar([v(1, 10, 100, 5)], D(2025, 1, 1), D(2026, 9, 29))
    base.salvar(tmp_path / "vendas_hse.json")
    dados = json.loads((tmp_path / "vendas_hse.json").read_text(encoding="utf-8"))
    assert dados["cobertura"] == [["01/01/2025", "29/09/2026"]]
    de_novo = BaseVendas.carregar(tmp_path / "vendas_hse.json")
    assert de_novo.lista() == base.lista() and de_novo.ultima_data() == D(2026, 9, 29)


def test_carregar_arquivo_que_nao_existe_da_base_vazia(tmp_path):
    assert BaseVendas.carregar(tmp_path / "nao.json").lista() == []


def test_data_br():
    assert data_br("29/09/2026") == D(2026, 9, 29)
    assert data_br(dt.datetime(2026, 9, 29, 10)) == D(2026, 9, 29)
    assert data_br("9/29/2026") is None and data_br(None) is None


# -- compatibilidade com o Python do servidor -----------------------------------

@pytest.mark.parametrize("arquivo", sorted(Path(__file__).resolve().parent.parent.joinpath("cruzar_nf").glob("*.py")),
                         ids=lambda p: p.name)
def test_sintaxe_compativel_com_python_38(arquivo):
    """O gerenciador roda num Windows Server 2012 R2: nada de sintaxe nova."""
    ast.parse(arquivo.read_text(encoding="utf-8"), feature_version=(3, 8))
