"""Aplica as correções de célula aprovadas pelo ADM sobre uma cópia da planilha."""
from __future__ import annotations

from pathlib import Path

import openpyxl

from orcamento.agente import filtrar_correcoes


def aplicar(origem: Path, correcoes: list[dict], destino: Path) -> list[str]:
    ok = filtrar_correcoes(correcoes)   # refiltra: o JSON do banco não é de confiança
    wb = openpyxl.load_workbook(origem)  # sem data_only: mantém fórmulas
    ws = wb["ORÇAMENTO"]
    for c in ok:
        valor = c["valor"]
        ws[c["celula"]].value = int(valor) if c["celula"].startswith("K") and valor.isdigit() else valor
    wb.save(destino)
    return [c["celula"] for c in ok]
