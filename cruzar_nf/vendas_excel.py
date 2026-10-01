"""Lê o Excel de vendas exportado do HSE (Venda (pedido) -> botão Excel).

Formato visto em 01/10/2026 (`planilha_atualizada.xlsx`): uma aba, linhas 1-2
vazias, cabeçalho na linha 3 com a coluna A vazia, uma venda por linha e
linhas vazias no fim. Números e datas já vêm tipados.

Devolve as vendas no mesmo formato de campos do comparar.json antigo
("Tipo", "Código", "Ordem Compra", "NF", "Filial", "Total Líq."...), com a
data em dd/mm/aaaa — assim o `cruzar` lê as duas fontes do mesmo jeito.

Compatível com Python 3.8 (roda no gerenciador do servidor 2012 R2).
"""

from __future__ import annotations

import datetime as _dt
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional

from cruzar_nf.cruzar import _chave_campo, valor_decimal

# Sem essas colunas não dá para cruzar: o Excel veio de outra tela ou mudou
OBRIGATORIAS = ("Código", "Ordem Compra", "NF", "Filial")
LINHAS_PROCURANDO_CABECALHO = 30

# Dinheiro/quantidade: vira número na ENTRADA. O botão Excel do HSE entrega
# texto ("2.351,800000") e o .xlsx re-salvo entrega número; a base acumulada
# mistura os dois, e o cruzamento só não confunde se tudo for número.
NUMERICAS = {_chave_campo(c) for c in (
    "Total Bruto", "Desc/Acres.", "%", "Frete", "Subtotal", "Créditos", "Cashback", "Total Líq.",
    "CMV", "Margem", "IPI", "ST", "Não Entregue", "Peso")}
# Identificadores que são número inteiro. A Ordem Compra NÃO: "046366" perde o zero.
INTEIRAS = {_chave_campo(c) for c in ("Código", "NF", "Ped.Compra", "Ped.Ecomm.", "Pgto")}


class ExcelInvalido(ValueError):
    pass


def _valor(v: Any, coluna: str = "") -> Any:
    if isinstance(v, _dt.datetime):
        v = v.date()
    if isinstance(v, _dt.date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, str):
        v = v.replace("\xa0", " ").strip()
        if not v:
            return None
    chave = _chave_campo(coluna)
    if chave in NUMERICAS and isinstance(v, str):
        numero = valor_decimal(v)
        return float(numero) if numero is not None else v
    if chave in INTEIRAS and isinstance(v, str) and re.fullmatch(r"\d+", v):
        return int(v)
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15 and chave not in NUMERICAS:
        return int(v)          # OC/NF/código que o Excel guardou como 4500785593.0
    return v


class _TabelasHTML(HTMLParser):
    """Lê todas as <table> de um HTML como listas de linhas de texto."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabelas: List[List[List[str]]] = []
        self._linha: Optional[List[str]] = None
        self._celula: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "table":
            self.tabelas.append([])
        elif tag == "tr" and self.tabelas:
            self._linha = []
        elif tag in ("td", "th") and self._linha is not None:
            self._celula = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._celula is not None and self._linha is not None:
            self._linha.append("".join(self._celula).strip())
            self._celula = None
        elif tag == "tr" and self._linha is not None:
            self.tabelas[-1].append(self._linha)
            self._linha = None

    def handle_data(self, dados: str) -> None:
        if self._celula is not None:
            self._celula.append(dados)


def _e_html(caminho: Path) -> bool:
    inicio = caminho.read_bytes()[:512].lstrip(b"\xef\xbb\xbf").lstrip().lower()
    return inicio.startswith(b"<")


def _linhas_html(caminho: Path) -> List[tuple]:
    leitor = _TabelasHTML()
    leitor.feed(caminho.read_bytes().decode("utf-8-sig", errors="replace"))
    chaves = {_chave_campo(c) for c in OBRIGATORIAS}
    for tabela in leitor.tabelas:   # a tabela das vendas é a que tem o cabeçalho certo
        if any(chaves <= {_chave_campo(c) for c in linha} for linha in tabela[:LINHAS_PROCURANDO_CABECALHO]):
            return [tuple(linha) for linha in tabela]
    return []


def _linhas_xlsx(caminho: Path) -> List[tuple]:
    import openpyxl   # aqui dentro: quem só lê o HTML do HSE não precisa do openpyxl

    wb = openpyxl.load_workbook(str(caminho), read_only=True, data_only=True)
    try:
        return list(wb.worksheets[0].iter_rows(values_only=True))
    finally:
        wb.close()


def _achar_cabecalho(linhas: List[tuple]) -> int:
    chaves = {_chave_campo(c) for c in OBRIGATORIAS}
    for i, linha in enumerate(linhas[:LINHAS_PROCURANDO_CABECALHO]):
        nomes = {_chave_campo(c) for c in linha if isinstance(c, str)}
        if chaves <= nomes:
            return i
    raise ExcelInvalido("não achei o cabeçalho (Código, Ordem Compra, NF, Filial) "
                        "nas primeiras linhas: é o Excel da tela Venda (pedido)?")


def ler_excel_vendas(caminho: "str | Path") -> List[Dict[str, Any]]:
    """Vendas do arquivo do HSE: o .xls do botão Excel (que é HTML) ou um .xlsx."""
    caminho = Path(caminho)
    linhas = _linhas_html(caminho) if _e_html(caminho) else _linhas_xlsx(caminho)
    i = _achar_cabecalho(linhas)
    colunas = [(j, str(nome).strip()) for j, nome in enumerate(linhas[i])
               if isinstance(nome, str) and nome.strip()]
    j_codigo = next(j for j, nome in colunas if _chave_campo(nome) == _chave_campo("Código"))
    j_tipo = next((j for j, nome in colunas if _chave_campo(nome) == "TIPO"), None)

    vendas = []
    for linha in linhas[i + 1:]:
        def celula(j):
            return linha[j] if j is not None and j < len(linha) else None
        if celula(j_codigo) in (None, ""):
            continue                       # linha vazia ou de total
        tipo = celula(j_tipo)
        if isinstance(tipo, str) and _chave_campo(tipo) == "TIPO":
            continue                       # cabeçalho repetido
        vendas.append({nome: _valor(celula(j), nome) for j, nome in colunas})
    return vendas


def resumo_excel(vendas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Quantidade e período de emissão, para conferir com a tela do HSE."""
    datas = []
    for v in vendas:
        try:
            datas.append(_dt.datetime.strptime(str(v.get("Emissão")), "%d/%m/%Y").date())
        except ValueError:
            pass
    return {"vendas": len(vendas),
            "emissao_min": min(datas).strftime("%d/%m/%Y") if datas else None,
            "emissao_max": max(datas).strftime("%d/%m/%Y") if datas else None}
