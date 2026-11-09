"""PLANILHA-BASE-v3 com N linhas de item, editando o XML do modelo.

openpyxl apagaria as listas suspensas x14 (vendedor, grupo, marca...), então o arquivo é montado
direto no XML: as linhas de item são repetidas, o rodapé desce (ou sobe) junto e as referências
(mesclagens, validações, TOTAL, comentários) acompanham. A proteção da aba fica como está.
A coluna A do modelo é o Nº do item (=ROW()-1, travada); o resto vem copiado da linha modelo.
"""
import io
import re
import zipfile
from pathlib import Path

MODELO = Path(__file__).resolve().parent / "modelo" / "PLANILHA-BASE-v3.xlsx"
PADRAO, MAXIMO = 24, 1000
_ULTIMA = PADRAO + 1          # última linha de item no modelo (25)
_ABA = "xl/worksheets/sheet1.xml"   # ORÇAMENTO
_REF = re.compile(r"(\$?[A-Z]{1,3}\$?)(\d+)(?::(\$?[A-Z]{1,3}\$?)(\d+))?")


def _refs(texto: str, n: int) -> str:
    """Ajusta referências A1 ao novo tamanho: o fim de um intervalo de itens (…25) vira N+1 e o rodapé anda."""
    d = n - PADRAO

    def linha(r: int, fim: bool) -> int:
        return r + d if r > _ULTIMA else (n + 1 if fim and r == _ULTIMA else r)

    def troca(m):
        a = f"{m[1]}{linha(int(m[2]), not m[3])}"
        return a if not m[3] else f"{a}:{m[3]}{linha(int(m[4]), True)}"
    return _REF.sub(troca, texto)


def _renumerar(row: str, r: int) -> str:
    row = re.sub(r'^<row r="\d+"', f'<row r="{r}"', row)
    return re.sub(r'(<c r="[A-Z]+)\d+"', rf'\g<1>{r}"', row)


def _formulas(linha2: str) -> dict[str, str]:
    """Fórmulas compartilhadas da linha 2 (coluna → texto com {r} no lugar da linha)."""
    return {m[1]: re.sub(r"\b([A-Z]+)2\b", r"\1{r}", m[2])
            for m in re.finditer(r'<c r="([A-Z]+)2"[^>]*><f t="shared"[^>]*>([^<]+)</f>', linha2)}


def _item(modelo: str, r: int, formulas: dict[str, str]) -> str:
    row = _renumerar(modelo, r)
    for col, f in formulas.items():   # fórmula própria da linha (o modelo usa fórmula compartilhada)
        row = re.sub(rf'<c r="{col}{r}" s="(\d+)">.*?</c>',
                     lambda m: f'<c r="{col}{r}" s="{m[1]}"><f>{f.format(r=r)}</f><v>0</v></c>', row)
    return re.sub(r"(<f>ROW\(\)-1</f><v>)\d+", rf"\g<1>{r - 1}", row)   # Nº do item


def _aba(xml: str, n: int) -> str:
    ini, fim = xml.index("<sheetData>") + len("<sheetData>"), xml.index("</sheetData>")
    linhas = {int(m[1]): m[0] for m in re.finditer(r'<row r="(\d+)"[^>]*?(?:/>|>.*?</row>)', xml[ini:fim])}
    formulas = _formulas(linhas[2])
    # linha do meio do modelo para as novas; a última linha de item é sempre a 25 (borda de fechamento)
    itens = [_item(linhas[_ULTIMA if r == n + 1 else min(r, PADRAO)], r, formulas) for r in range(2, n + 2)]
    rodape = [re.sub(r"<f>([^<]*)</f>", lambda m: f"<f>{_refs(m[1], n)}</f>", _renumerar(x, r + n - PADRAO))
              for r, x in sorted(linhas.items()) if r > _ULTIMA]
    cabeca, cauda = xml[:ini], xml[fim:]
    cabeca = re.sub(r'<dimension ref="([^"]+)"', lambda m: f'<dimension ref="{_refs(m[1], n)}"', cabeca)
    cauda = re.sub(r'((?:ref|sqref)=")([^"]+)"', lambda m: f'{m[1]}{_refs(m[2], n)}"', cauda)
    cauda = re.sub(r"<xm:sqref>([^<]+)</xm:sqref>", lambda m: f"<xm:sqref>{_refs(m[1], n)}</xm:sqref>", cauda)
    return cabeca + linhas[1] + "".join(itens) + "".join(rodape) + cauda


def _vml(vml: str, n: int) -> str:
    """Comentários do rodapé: linha (0-based) e âncora descem junto."""
    d = n - PADRAO
    vml = re.sub(r"<x:Row>(\d+)</x:Row>", lambda m: f"<x:Row>{int(m[1]) + d if int(m[1]) >= _ULTIMA else m[1]}</x:Row>", vml)

    def ancora(m):
        v = [int(x) for x in m[1].split(",")]
        for i in (2, 6):
            if v[i] >= _ULTIMA:
                v[i] += d
        return "<x:Anchor>\n    " + ", ".join(map(str, v)) + "</x:Anchor>"
    return re.sub(r"<x:Anchor>\s*([\d,\s]+?)\s*</x:Anchor>", ancora, vml)


def gerar_modelo(n: int = PADRAO) -> bytes:
    if not 1 <= n <= MAXIMO:
        raise ValueError(f"itens deve ser de 1 a {MAXIMO}")
    saida = io.BytesIO()
    with zipfile.ZipFile(MODELO) as zin, zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            nome = info.filename
            if nome == "xl/calcChain.xml":   # o Excel refaz; com linhas novas ela ficaria errada
                continue
            dados = zin.read(nome)
            if nome == _ABA:
                dados = _aba(dados.decode("utf-8"), n).encode("utf-8")
            elif nome == "xl/comments1.xml":
                dados = re.sub(rb'ref="([^"]+)"', lambda m: b'ref="%s"' % _refs(m[1].decode(), n).encode(), dados)
            elif nome.endswith(".vml"):
                dados = _vml(dados.decode("utf-8"), n).encode("utf-8")
            elif nome in ("[Content_Types].xml", "xl/_rels/workbook.xml.rels"):
                dados = re.sub(rb"<(?:Override|Relationship) [^>]*calcChain[^>]*/>", b"", dados)
            zout.writestr(info, dados)
    return saida.getvalue()
