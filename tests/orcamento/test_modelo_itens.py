"""Modelo com N linhas de item (orcamento/modelo_itens.py) e o leitor achando o rodapé deslocado."""
import io
import re
import zipfile

import openpyxl
import pytest

from orcamento.correcao import aplicar
from orcamento.modelo_itens import MODELO, gerar_modelo
from orcamento.planilha import ler_planilha


def _aba(dados: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(dados)).read("xl/worksheets/sheet1.xml").decode("utf-8")


def _preencher(tmp_path, n: int):
    """Item no primeiro e no último lugar + rodapé, pelo deslocamento a partir de OBSERVAÇÕES."""
    wb = openpyxl.load_workbook(io.BytesIO(gerar_modelo(n)))
    ws = wb["ORÇAMENTO"]
    r = n + 2
    for linha in {2, n + 1}:
        ws[f"A{linha}"], ws[f"C{linha}"], ws[f"K{linha}"] = f"PRODUTO {linha}", 100, str(linha)
    ws[f"B{r}"], ws[f"B{r + 5}"], ws[f"B{r + 6}"], ws[f"B{r + 7}"] = "OBS", "18373", 10, "FULANO"
    ws[f"B{r + 11}"], ws[f"B{r + 12}"] = 2, "CIF"
    p = tmp_path / f"m{n}.xlsx"
    wb.save(p)
    return p


@pytest.mark.parametrize("n", [1, 24, 50, 1000])
def test_modelo_com_n_itens(tmp_path, n):
    xml = _aba(gerar_modelo(n))
    ws = openpyxl.load_workbook(io.BytesIO(gerar_modelo(n)))["ORÇAMENTO"]
    assert ws[f"A{n + 2}"].value == "OBSERVAÇÕES:" and ws[f"A{n + 14}"].value == "Frete"
    assert ws[f"I{n + 2}"].value == f"=SUM(I2:I{n + 1})"
    assert ws[f"J{n + 1}"].value == f"=SUM(I{n + 1}/B{n + 1})" and ws[f"B{n + 1}"].value == 1
    assert ws[f"G{n + 1}"].value == 45 and ws[f"S{n + 1}"].value == "=ROW()-1" and ws["S1"].value == "Nº"
    for col in "MPQ":   # listas x14 cobrem todas as linhas de item
        assert f"<xm:sqref>{col}2:{col}{n + 1}</xm:sqref>" in xml
    assert f"<xm:sqref>B{n + 9}</xm:sqref>" in xml and f'sqref="B2:B{n + 1}"' in xml
    original = re.search(r"<sheetProtection [^>]*/>", _aba(MODELO.read_bytes()))[0]
    assert original in xml and ws.protection.sheet

    orc = ler_planilha(_preencher(tmp_path, n))
    assert [i.linha for i in orc.itens] == sorted({2, n + 1})
    assert (orc.observacoes, orc.cliente, orc.prazo_dias, orc.vendedor, orc.filial, orc.frete) == \
        ("OBS", "18373", 10, "FULANO", 2, "CIF")


def test_numero_do_item_travado():
    wb = openpyxl.load_workbook(io.BytesIO(gerar_modelo(3)))
    ws = wb["ORÇAMENTO"]
    assert ws["S4"].protection.locked and not ws["A4"].protection.locked


@pytest.mark.parametrize("n", [0, 1001])
def test_fora_da_faixa(n):
    with pytest.raises(ValueError):
        gerar_modelo(n)


def test_erro_aponta_a_celula_real(tmp_path):
    p = _preencher(tmp_path, 50)
    wb = openpyxl.load_workbook(p)
    wb["ORÇAMENTO"]["B57"] = None
    wb.save(p)
    from orcamento.planilha import ErroPlanilha
    with pytest.raises(ErroPlanilha, match=r"Cliente \(B57\)"):
        ler_planilha(p)


def test_correcao_da_ia_vai_para_a_celula_real(tmp_path):
    """A IA fala em B33 (modelo de 24 itens); com 50 itens o vendedor está na B59, e a B33 é um item."""
    dest = tmp_path / "out.xlsx"
    aplicar(_preencher(tmp_path, 50), [{"celula": "B33", "valor": "CICLANO", "motivo": ""}], dest)
    ws = openpyxl.load_workbook(dest)["ORÇAMENTO"]
    assert ws["B59"].value == "CICLANO" and ws["B33"].value == 1
