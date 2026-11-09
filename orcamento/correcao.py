"""Aplica correções de célula sobre uma cópia da planilha: aprovadas pelo ADM ou automáticas."""
from __future__ import annotations

from pathlib import Path

import openpyxl

from orcamento.agente import filtrar_correcoes
from orcamento.planilha import RODAPE_PADRAO, celula_real, normalizar

# Local de entrega e vendedor: a conferência confere os dois contra o HSE. CNPJ e código de produto
# ficam de fora: um dígito errado vira outro cliente ou outro produto que também passa na conferência.
# As células vêm no endereço do modelo antigo de 24 itens sem o Nº (B30, B33, K2); celula_real acha
# a de verdade quando a planilha tem o Nº na coluna A ou outro número de linhas de item.
CAMPOS_AUTOMATICOS = {"B30": "Local de entrega", "B33": "Vendedor"}
# O que tem de estar ao lado (rótulo do rodapé) ou no topo (cabeçalho da coluna) da célula real.
_ANCORAS = {"B30": "LOCAL DE ENTREGA", "B31": "CLIENTE", "B33": "VENDEDOR", "K": "CODIGO HSE", "O": "DESCRICAO"}


def _destino(ws, celula: str) -> str | None:
    """Célula real, ou None se o rótulo/cabeçalho dela não é o esperado: nunca grava na coluna errada."""
    real = ws[celula_real(ws, celula)]
    rodape = int(celula[1:]) >= RODAPE_PADRAO
    ancora = ws.cell(real.row, real.column - 1) if rodape else ws.cell(1, real.column)
    esperado = _ANCORAS.get(celula if rodape else celula[0])
    return real.coordinate if esperado and normalizar(ancora.value).startswith(esperado) else None


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
               "de": str(ws[real].value or "").strip(), "para": c["valor"].strip()}
              for c in correcoes if (real := _destino(ws, c["celula"]))]
    return [t for t in feitas if t["de"] != t["para"]]


def aplicar(origem: Path, correcoes: list[dict], destino: Path) -> list[str]:
    ok = filtrar_correcoes(correcoes)   # refiltra: o JSON do banco não é de confiança
    wb = openpyxl.load_workbook(origem)  # sem data_only: mantém fórmulas
    ws = wb["ORÇAMENTO"]
    feitas = []
    for c in ok:
        if not (real := _destino(ws, c["celula"])):
            continue
        valor = c["valor"]
        ws[real].value = int(valor) if c["celula"].startswith("K") and valor.isdigit() else valor
        feitas.append(c["celula"])
    wb.save(destino)
    return feitas
