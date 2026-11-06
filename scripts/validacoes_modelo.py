"""Regrava as validações da PLANILHA-BASE pelo XML (P2 #13).

    python -m scripts.validacoes_modelo [entrada.xlsx] [saida.xlsx]

Pelo XML porque o openpyxl apagaria as listas x14. Mexe só nas validações da aba
ORÇAMENTO e o resto do arquivo vai igual. Regra: "stop" no que o robô recusaria
de qualquer jeito; "warning" no que vem do HSE, porque a cópia em LISTAS envelhece
e um nome novo não pode travar o vendedor.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

MODELO = Path(__file__).resolve().parent.parent / "orcamento" / "modelo" / "PLANILHA-BASE-v3.xlsx"
ABA = "xl/worksheets/sheet1.xml"

# célula: (avisar em vez de barrar, título, mensagem)
LISTAS = {
    "B33": (True, "Vendedor", "Este nome não está na lista. O robô confere no HSE: use o nome exato."),
    "B34": (False, "Forma de pagamento", "Escolha uma das formas de pagamento da lista."),
    "B35": (True, "Parcelamento", "Este parcelamento não está na lista. Confira antes de seguir."),
    "B37": (False, "Filial", "Escolha a filial 1, 2 ou 3 na lista."),
    "B38": (False, "Frete", "Escolha CIF ou FOB na lista."),
    "M2:M25": (False, "Origem", "Escolha a origem na lista (0 a 8)."),
    "P2:P25": (True, "Grupo", "Este grupo não está na lista. O produto novo precisa de um grupo do HSE."),
    "Q2:Q25": (True, "Marca", "Esta marca não está na lista. O produto novo precisa de uma marca do HSE."),
}

_NCM = 'LEN(SUBSTITUTE(SUBSTITUTE(L2,".",""),"-",""))=8'
# (célula, tipo, operador, fórmula 1, fórmula 2, avisar, título, mensagem)
NUMEROS = [
    ("B2:B25", "decimal", "greaterThan", "0", None, False, "Quantidade", "A quantidade precisa ser um número maior que zero."),
    ("C2:F25", "decimal", "greaterThanOrEqual", "0", None, False, "Valor", "Digite só o número, sem letras, zero ou maior."),
    ("G2:G25", "decimal", "greaterThanOrEqual", "0", None, True, "Margem", "Margem negativa ou que não é número. Confira antes de seguir."),
    ("L2:L25", "custom", None, _NCM, None, False, "NCM", "O NCM precisa ter 8 dígitos."),
    ("N2:N25", "decimal", "between", "0", "100", False, "ICMS", "O ICMS precisa ser um número de 0 a 100."),
    ("R2:R25", "textLength", "lessThanOrEqual", "512", None, False, "Descrição no DAV", "A descrição no DAV aceita até 512 caracteres."),
    # 1024 do HSE menos a linha "FRETE CIF, PRAZO DE ENTREGA 30 DIAS" que o robô acrescenta.
    ("B26", "textLength", "lessThanOrEqual", "980", None, False, "Observações", "As observações aceitam até 980 caracteres."),
    ("B32", "whole", "greaterThanOrEqual", "0", None, False, "Prazo de entrega", "O prazo é um número inteiro de dias."),
]


def _alerta(avisar: bool, titulo: str, mensagem: str) -> str:
    estilo = 'errorStyle="warning" ' if avisar else ""
    return f'{estilo}allowBlank="1" showErrorMessage="1" errorTitle={quoteattr(titulo)} error={quoteattr(mensagem)}'


def _lista(m: re.Match) -> str:
    uid, miolo = m[1], m[2]
    celula = re.search(r"<xm:sqref>(.*?)</xm:sqref>", miolo)[1]
    return f'<x14:dataValidation type="list" {_alerta(*LISTAS[celula])} xr:uid="{uid}">{miolo}</x14:dataValidation>'


def _numero(n: int, regra: tuple) -> str:
    celula, tipo, operador, f1, f2, avisar, titulo, mensagem = regra
    op = f'operator="{operador}" ' if operador else ""
    formulas = f"<formula1>{escape(f1)}</formula1>" + (f"<formula2>{f2}</formula2>" if f2 else "")
    return (f'<dataValidation type="{tipo}" {op}{_alerta(avisar, titulo, mensagem)} sqref="{celula}" '
            f'xr:uid="{{00000000-0002-0000-0000-0000{n:02X}000000}}">{formulas}</dataValidation>')


def regravar(xml: str) -> str:
    xml = re.sub(r'<x14:dataValidation [^>]*?xr:uid="([^"]+)">(.*?)</x14:dataValidation>', _lista, xml, flags=re.S)
    bloco = (f'<dataValidations count="{len(NUMEROS)}">'
             + "".join(_numero(n, r) for n, r in enumerate(NUMEROS, 16)) + "</dataValidations>")
    xml, trocas = re.subn(r"<dataValidations .*?</dataValidations>", lambda _: bloco, xml, flags=re.S)
    if trocas != 1:
        raise ValueError("modelo sem o bloco de validações")
    return xml


def aplicar(entrada: Path, saida: Path) -> None:
    with zipfile.ZipFile(entrada) as z:
        partes = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for info, dados in partes:
            if info.filename == ABA:
                dados = regravar(dados.decode("utf-8")).encode("utf-8")
            z.writestr(info, dados, compress_type=zipfile.ZIP_DEFLATED)


if __name__ == "__main__":
    entrada = Path(sys.argv[1]) if len(sys.argv) > 1 else MODELO
    saida = Path(sys.argv[2]) if len(sys.argv) > 2 else entrada
    temp = saida.with_suffix(".tmp.xlsx")
    aplicar(entrada, temp)
    temp.replace(saida)
    print(f"Validações gravadas em {saida}")
