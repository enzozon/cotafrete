"""Gera planilhas de teste a partir de modelo.xlsx (cópia da PLANILHA-BASE-v3).

Uso direto: python tests/planilhas/gerar.py  → grava todas as variantes nesta pasta.
"""
from pathlib import Path

import openpyxl

MODELO = Path(__file__).with_name("modelo.xlsx")

# Base válida: cliente 18373, ELIZIANE, item 1 = código 13370 com custo 100 (J = 145,00).
VALIDA = {"B2": 1, "C2": 100, "K2": 13370, "B31": 18373, "B33": "ELIZIANE AMORIM ROSA BARROS"}

NOVO = {"A3": "PRODUTO TESTE ROBO", "B3": 1, "C3": 45, "L3": "84716053", "M3": 0,
        "N3": 17, "P3": "INFORMATICA", "Q3": "DELL"}

VARIANTES: dict[str, dict] = {
    "valida": {},
    "sem_cliente": {"B31": None},
    "sem_vendedor": {"B33": None},
    "codigo_e_descricao": {"A2": "QUALQUER DESCRICAO"},
    "novo_sem_ncm": {**NOVO, "L3": None},
    "descricao_duplicada": {"A3": "MOUSE DUPLICADO", "B3": 1, "C3": 10},
    "sem_itens": {"K2": None},
    "valor_zero": {"A3": "SEM CUSTO", "B3": 1, "C3": None},
    "quantidade_invalida": {"A3": "ITEM X", "B3": "dois", "C3": 10},
    "obs_longa": {"B26": "x" * 1025},
    "filial_invalida": {"B37": "7 - NAO EXISTE"},
    "pagamento_invalido": {"B34": "Cheque"},
    "completa": {**NOVO, "B26": "Obs teste", "B30": "CENTRO", "B32": 10, "B34": "Pix",
                 "B35": "30 DIAS", "B36": "OC-1", "B37": "2 - ALIANCA COMERCIO DE TECNOLOGIAS LTDA"},
}


def criar(destino: Path, celulas: dict | None = None, nome: str = "teste.xlsx") -> Path:
    """Copia o modelo aplicando VALIDA + celulas (None apaga a célula)."""
    wb = openpyxl.load_workbook(MODELO)
    ws = wb["ORÇAMENTO"]
    for ref, valor in {**VALIDA, **(celulas or {})}.items():
        ws[ref] = valor
    caminho = Path(destino) / nome
    wb.save(caminho)
    return caminho


if __name__ == "__main__":
    pasta = Path(__file__).parent
    for nome, celulas in VARIANTES.items():
        print(criar(pasta, celulas, f"{nome}.xlsx"))
