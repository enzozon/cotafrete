"""Modelo com N linhas de item e Nº na coluna A (orcamento/modelo_itens.py); leitor nos dois layouts."""
import io
import re
import zipfile

import openpyxl
import pytest

from orcamento.correcao import aplicar, trocas
from orcamento.diagnostico import _origem
from orcamento.modelo_itens import MODELO, gerar_modelo
from orcamento.planilha import ErroPlanilha, celula_real, layout, ler_planilha
from tests.orcamento.planilhas.gerar import criar


def _aba(dados: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(dados)).read("xl/worksheets/sheet1.xml").decode("utf-8")


def _preencher(tmp_path, n: int):
    """Item no primeiro e no último lugar + rodapé (rótulos na B, valores na C)."""
    wb = openpyxl.load_workbook(io.BytesIO(gerar_modelo(n)))
    ws = wb["ORÇAMENTO"]
    r = n + 2
    for linha in {2, n + 1}:
        ws[f"B{linha}"], ws[f"D{linha}"], ws[f"L{linha}"] = f"PRODUTO {linha}", 100, str(linha)
    ws[f"C{r}"], ws[f"C{r + 5}"], ws[f"C{r + 6}"], ws[f"C{r + 7}"] = "OBS", "18373", 10, "FULANO"
    ws[f"C{r + 11}"], ws[f"C{r + 12}"] = 2, "CIF"
    p = tmp_path / f"m{n}.xlsx"
    wb.save(p)
    return p


@pytest.mark.parametrize("n", [1, 24, 50, 1000])
def test_modelo_com_n_itens(tmp_path, n):
    xml = _aba(gerar_modelo(n))
    ws = openpyxl.load_workbook(io.BytesIO(gerar_modelo(n)))["ORÇAMENTO"]
    assert ws["A1"].value == "Nº" and ws["B1"].value == "PRODUTO"
    assert ws[f"B{n + 2}"].value == "OBSERVAÇÕES:" and ws[f"B{n + 14}"].value == "Frete"
    assert ws[f"J{n + 2}"].value == f"=SUM(J2:J{n + 1})"
    assert ws[f"K{n + 1}"].value == f"=SUM(J{n + 1}/C{n + 1})" and ws[f"C{n + 1}"].value == 1
    assert ws[f"H{n + 1}"].value == 45 and ws[f"A{n + 1}"].value == "=ROW()-1"
    assert f"<f>ROW()-1</f><v>{n}</v></c>" in xml
    for col in "NQR":   # listas x14 cobrem todas as linhas de item
        assert f"<xm:sqref>{col}2:{col}{n + 1}</xm:sqref>" in xml
    assert f"<xm:sqref>C{n + 9}</xm:sqref>" in xml and f'sqref="C2:C{n + 1}"' in xml
    original = re.search(r"<sheetProtection [^>]*/>", _aba(MODELO.read_bytes()))[0]
    assert original in xml and ws.protection.sheet

    p = _preencher(tmp_path, n)
    orc = ler_planilha(p)
    assert [i.linha for i in orc.itens] == sorted({2, n + 1})
    assert orc.itens[0].produto == "PRODUTO 2" and orc.itens[0].codigo == "2"
    assert (orc.observacoes, orc.cliente, orc.prazo_dias, orc.vendedor, orc.filial, orc.frete) == \
        ("OBS", "18373", 10, "FULANO", 2, "CIF")
    assert layout(p) == (1, n + 2)


def test_numero_do_item_travado_e_produto_livre():
    ws = openpyxl.load_workbook(io.BytesIO(gerar_modelo(3)))["ORÇAMENTO"]
    assert ws["A4"].protection.locked and not ws["B4"].protection.locked


@pytest.mark.parametrize("n", [0, 1001])
def test_fora_da_faixa(n):
    with pytest.raises(ValueError):
        gerar_modelo(n)


def test_erro_aponta_a_celula_real(tmp_path):
    p = _preencher(tmp_path, 50)
    wb = openpyxl.load_workbook(p)
    wb["ORÇAMENTO"]["C57"] = None
    wb["ORÇAMENTO"]["D51"] = None   # sem custo: valor zero
    wb.save(p)
    with pytest.raises(ErroPlanilha) as e:
        ler_planilha(p)
    assert "Cliente (C57) é obrigatório" in e.value.erros
    assert "Item 50: valor unitário (coluna K) deve ser maior que zero" in e.value.erros


def test_layout_antigo_sem_numero_continua(tmp_path):
    p = criar(tmp_path)   # cópia do modelo antigo: PRODUTO na A
    orc = ler_planilha(p)
    assert orc.itens[0].codigo == "13370" and orc.cliente == "18373"
    ws = openpyxl.load_workbook(p)["ORÇAMENTO"]
    assert (celula_real(ws, "B33"), celula_real(ws, "K2")) == ("B33", "K2")
    assert layout(p) == (0, 26)


def test_layout_com_numero_na_coluna_s(tmp_path):
    """O modelo do PR #147 tinha o Nº na coluna S: o robô lê só de A a R e ignora."""
    wb = openpyxl.load_workbook(criar(tmp_path))
    ws = wb["ORÇAMENTO"]
    ws["S1"] = "Nº"
    for r in range(2, 26):
        ws[f"S{r}"] = r - 1
    p = tmp_path / "s.xlsx"
    wb.save(p)
    orc = ler_planilha(p)
    assert len(orc.itens) == 1 and orc.itens[0].codigo == "13370"


def test_correcao_da_ia_vai_para_a_celula_real(tmp_path):
    """A IA fala em B33/K2 (modelo antigo); com o Nº e 50 itens o vendedor está na C59 e o código na L2."""
    origem, dest = _preencher(tmp_path, 50), tmp_path / "out.xlsx"
    correcoes = [{"celula": "B33", "valor": "CICLANO", "motivo": ""}, {"celula": "K2", "valor": "777", "motivo": ""}]
    assert [t["celula"] for t in trocas(origem, correcoes)] == ["B33", "K2"]
    assert aplicar(origem, correcoes, dest) == ["B33", "K2"]
    ws = openpyxl.load_workbook(dest)["ORÇAMENTO"]
    assert ws["C59"].value == "CICLANO" and ws["L2"].value == 777
    assert ws["B33"].value is None and ws["K2"].value == "=SUM(J2/C2)"


def test_correcao_nunca_grava_onde_o_rotulo_nao_bate(tmp_path):
    origem, dest = _preencher(tmp_path, 3), tmp_path / "out.xlsx"
    wb = openpyxl.load_workbook(origem)
    wb["ORÇAMENTO"]["B12"] = "OUTRA COISA"   # rótulo de VENDEDOR (B33 do modelo antigo) trocado
    wb.save(origem)
    assert aplicar(origem, [{"celula": "B33", "valor": "CICLANO", "motivo": ""}], dest) == []
    assert openpyxl.load_workbook(dest)["ORÇAMENTO"]["C12"].value == "FULANO"


def test_diagnostico_indica_a_celula_da_planilha():
    real = {"K3": "L3", "B31": "C57"}.get
    d = _origem(["Item 2: código 49025 não encontrado no HSE", "Cliente 1 não encontrado no HSE",
                 "VENDEDOR (C59) é obrigatório"], False, lambda c: real(c, c))
    assert d["campos"] == ["L3", "C57", "C59"]
