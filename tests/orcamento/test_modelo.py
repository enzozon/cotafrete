"""O modelo da PLANILHA-BASE recusa o erro na hora de digitar (P2 #13).

Sem `showErrorMessage`, a lista suspensa só sugere: o Excel aceita qualquer
texto digitado. O robô continua conferindo tudo: colar por cima passa pela
validação do Excel, mas não pela dele.
"""
import re
import zipfile

import pytest

from scripts import validacoes_modelo as V
from web.dav_ui import MODELO


def _xml() -> str:
    with zipfile.ZipFile(MODELO) as z:
        return z.read("xl/worksheets/sheet1.xml").decode("utf-8")


def _listas() -> dict[str, str]:
    return {re.search(r"<xm:sqref>(.*?)</xm:sqref>", d)[1]: d
            for d in re.findall(r"<x14:dataValidation .*?</x14:dataValidation>", _xml(), re.S)}


def _numeros() -> dict[str, str]:
    return {re.search(r'sqref="(.*?)"', d)[1]: d
            for d in re.findall(r"<dataValidation .*?</dataValidation>", _xml(), re.S)}


@pytest.mark.parametrize("celula", ["B34", "B37", "B38", "M2:M25"])
def test_lista_que_o_robo_recusaria_barra_o_que_esta_fora(celula):
    d = _listas()[celula]
    assert 'showErrorMessage="1"' in d and "errorStyle" not in d and 'error="' in d


@pytest.mark.parametrize("celula", ["B33", "B35", "P2:P25", "Q2:Q25"])
def test_lista_que_vem_do_hse_avisa_mas_deixa_seguir(celula):
    """A cópia em LISTAS envelhece: nome novo no HSE não pode travar o vendedor."""
    d = _listas()[celula]
    assert 'showErrorMessage="1"' in d and 'errorStyle="warning"' in d


def test_as_oito_listas_continuam_apontando_para_a_aba_listas():
    assert len(_listas()) == 8
    assert "LISTAS!$A$2:$A$28" in _listas()["B33"]


@pytest.mark.parametrize("celula, trecho", [
    ("B2:B25", 'type="decimal" operator="greaterThan"'),
    ("C2:F25", 'type="decimal" operator="greaterThanOrEqual"'),
    ("G2:G25", 'errorStyle="warning"'),
    ("L2:L25", 'type="custom"'),
    ("N2:N25", 'type="decimal" operator="between"'),
    ("R2:R25", 'type="textLength" operator="lessThanOrEqual"'),
    ("B26", 'type="textLength" operator="lessThanOrEqual"'),
    ("B32", 'type="whole" operator="greaterThanOrEqual"'),
])
def test_numero_e_tamanho_conferidos_na_digitacao(celula, trecho):
    d = _numeros()[celula]
    assert trecho in d and 'showErrorMessage="1"' in d and 'allowBlank="1"' in d


def test_limites_do_excel_para_a_mensagem():
    for d in [*_listas().values(), *_numeros().values()]:
        assert len(re.search(r'errorTitle="(.*?)"', d)[1]) <= 32
        assert len(re.search(r' error="(.*?)"', d)[1]) <= 255


def test_senha_da_aba_e_partes_do_arquivo_ficam():
    assert "<sheetProtection " in _xml()
    with zipfile.ZipFile(MODELO) as z:
        assert z.namelist()[0] == "[Content_Types].xml" and z.testzip() is None


def test_regravar_nao_muda_nada(tmp_path):
    saida = tmp_path / "m.xlsx"
    V.aplicar(MODELO, saida)
    with zipfile.ZipFile(saida) as z:
        assert z.read("xl/worksheets/sheet1.xml").decode("utf-8") == _xml()
