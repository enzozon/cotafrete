"""Aplica correções de célula sobre uma cópia da planilha: aprovadas pelo ADM ou automáticas."""
from __future__ import annotations

from pathlib import Path

import openpyxl

from orcamento.agente import filtrar_correcoes
from orcamento.planilha import celula_real

# Local de entrega e vendedor: a conferência confere os dois contra o HSE. CNPJ e código de produto
# ficam de fora: um dígito errado vira outro cliente ou outro produto que também passa na conferência.
# As células vêm no endereço do modelo de 24 itens (B30, B33); celula_real acha a de verdade
# quando a planilha tem outro número de linhas de item.
CAMPOS_AUTOMATICOS = {"B30": "Local de entrega", "B33": "Vendedor"}


def automaticas(diag: dict) -> list[dict]:
    """As correções que entram sem aprovação; [] se qualquer uma delas precisar de uma pessoa."""
    brutas = diag.get("correcoes")
    if (diag.get("culpa") != "planilha" or diag.get("confianca") != "alta"
            or diag.get("criados_no_hse") != [] or not isinstance(brutas, list)):
        return []
    ok = filtrar_correcoes(brutas)
    if len(ok) != len(brutas) or any(c["celula"] not in CAMPOS_AUTOMATICOS for c in ok):
        return []
    return ok


def trocas(origem: Path, correcoes: list[dict]) -> list[dict]:
    """O que muda de fato, para contar ao vendedor. Sem o motivo: é texto livre da IA."""
    ws = openpyxl.load_workbook(origem)["ORÇAMENTO"]
    feitas = [{"celula": c["celula"], "campo": CAMPOS_AUTOMATICOS.get(c["celula"], c["celula"]),
               "de": str(ws[celula_real(ws, c["celula"])].value or "").strip(), "para": c["valor"].strip()} for c in correcoes]
    return [t for t in feitas if t["de"] != t["para"]]


def aplicar(origem: Path, correcoes: list[dict], destino: Path) -> list[str]:
    ok = filtrar_correcoes(correcoes)   # refiltra: o JSON do banco não é de confiança
    wb = openpyxl.load_workbook(origem)  # sem data_only: mantém fórmulas
    ws = wb["ORÇAMENTO"]
    for c in ok:
        valor = c["valor"]
        ws[celula_real(ws, c["celula"])].value = int(valor) if c["celula"].startswith("K") and valor.isdigit() else valor
    wb.save(destino)
    return [c["celula"] for c in ok]
