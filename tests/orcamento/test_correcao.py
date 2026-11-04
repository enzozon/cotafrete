import openpyxl

from orcamento.correcao import aplicar
from tests.orcamento.planilhas.gerar import criar


def test_aplicar_so_celulas_permitidas(tmp_path):
    origem = criar(tmp_path)
    dest = tmp_path / "out.xlsx"
    mudou = aplicar(origem, [{"celula": "J2", "valor": "1", "motivo": ""},
                             {"celula": "K2", "valor": "999", "motivo": ""},
                             {"celula": "B30", "valor": "CENTRO", "motivo": ""}], dest)
    assert sorted(mudou) == ["B30", "K2"]
    ws = openpyxl.load_workbook(dest)["ORÇAMENTO"]
    assert ws["K2"].value == 999 and ws["B30"].value == "CENTRO"


def test_aplicar_nao_toca_formula(tmp_path):
    origem = criar(tmp_path)
    dest = tmp_path / "out.xlsx"
    aplicar(origem, [{"celula": "K2", "valor": "5", "motivo": ""}], dest)
    j2 = openpyxl.load_workbook(dest)["ORÇAMENTO"]["J2"].value
    assert isinstance(j2, str) and j2.startswith("=")
