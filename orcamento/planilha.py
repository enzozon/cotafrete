"""Lê e valida a PLANILHA-BASE-v3 (aba ORÇAMENTO) sem acessar o HSE."""
import re
import unicodedata
import warnings
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter

LINHA_INI = 2
RODAPE_PADRAO = 26  # "OBSERVAÇÕES:" no modelo de 24 itens
MAX_OBS = 1024
MAX_DESCRICAO = 512  # maxLength do #dsObsItem_<cdItem> no HSE (visto em 29/10/2026)
FRETES = ("CIF", "FOB")
FILIAIS = {1, 2, 3}
ICMS_PADRAO = Decimal("17")
CENTAVO = Decimal("0.01")

# A planilha usa listas suspensas x14; só lemos, então o aviso do openpyxl é ruído.
warnings.filterwarnings("ignore", message="Data Validation extension")

# Textos da aba LISTAS (e códigos do HSE) → código de rfFormaPg
FORMAS_PG = {
    "BOLETO": "BO", "CARTAO CREDITO": "CC", "CARTAO DE CREDITO": "CC",
    "CARTAO DEBITO": "CD", "CARTAO DE DEBITO": "CD", "CREDIARIO": "CA",
    "CREDIARIO (CARNE)": "CA", "DEPOSITO": "DE", "DINHEIRO": "DI", "PIX": "PX",
    **{c: c for c in ("BO", "CC", "CD", "CA", "DE", "DI", "PX")},
}


@dataclass(frozen=True)
class Item:
    numero: int            # Item 1 = linha 2
    linha: int
    produto: str
    quantidade: Decimal
    custo: Decimal
    valor_unit: Decimal    # coluna J, 2 casas
    codigo: str | None
    ncm: str | None
    origem: int
    icms: Decimal
    descricao_cadastro: str
    grupo: str | None
    marca: str | None
    descricao: str = ""  # coluna R: vai para a descrição do item no DAV


@dataclass(frozen=True)
class Orcamento:
    arquivo: Path
    itens: tuple[Item, ...]
    observacoes: str
    local_entrega: str | None
    cliente: str
    prazo_dias: int | None
    vendedor: str
    forma_pg: str | None
    parcelamento: str | None
    ordem_compra: str | None
    filial: int
    avisos: tuple[str, ...]
    frete: str | None = None  # B38 (no modelo de 24 itens): CIF ou FOB


class ErroPlanilha(Exception):
    def __init__(self, erros: list[str]):
        super().__init__("; ".join(erros))
        self.erros = erros


def normalizar(txt) -> str:
    if txt is None:
        return ""
    s = unicodedata.normalize("NFKD", str(txt))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.upper().split())


def _texto(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def _num(v) -> Decimal | None:
    """Número da célula; None se vazia; ValueError se não for número."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, bool):
        raise ValueError(v)
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in s or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):  # "1.500" em texto = mil e quinhentos
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(v) from None


def _aba(wb):
    for ws in wb.worksheets:
        if normalizar(ws.title) == "ORCAMENTO":
            return ws
    raise ErroPlanilha(["aba ORÇAMENTO não encontrada"])


def linha_frete(frete: str, prazo: int) -> str:
    return f"FRETE {frete}, PRAZO DE ENTREGA {prazo} {'DIA' if prazo == 1 else 'DIAS'}"


def _com_frete(obs: str, frete: str | None, prazo: int | None) -> str:
    if not frete or not prazo:
        return obs
    return "\n".join(filter(None, (obs, linha_frete(frete, prazo))))


def observacoes_hse(orc: Orcamento) -> str:
    """Texto do #txObservacao: observações (B26 no modelo de 24 itens) e, numa linha abaixo, o frete."""
    return _com_frete(orc.observacoes, orc.frete, orc.prazo_dias)


def _ler_item(ws, linha: int, erros: list[str], avisos: list[str], desloc: int = 0) -> Item | None:
    # chaves no layout antigo (A = PRODUTO); desloc = colunas antes do PRODUTO (o Nº)
    cel = {c: ws.cell(linha, i + desloc).value for i, c in enumerate("ABCDEFGHIJKLMNOPQR", 1)}
    produto, codigo = _texto(cel["A"]), _texto(cel["K"])
    if not produto and not codigo:
        return None
    n = linha - 1
    pre = f"Item {n}:"
    qtd_errada = len(erros)

    def num(col: str, nome: str) -> Decimal | None:
        try:
            return _num(cel[col])
        except ValueError:
            erros.append(f"{pre} {nome} inválido(a) ({cel[col]!r})")
            return None

    qtd = num("B", "quantidade")
    if len(erros) == qtd_errada and (qtd is None or qtd <= 0):
        erros.append(f"{pre} quantidade deve ser maior que zero")
    custo, d, e, f, g = (num(c, nome) for c, nome in
                         (("C", "CUSTO"), ("D", "FRETE PARA VIR"), ("E", "FRETE DELLA"),
                          ("F", "MADEIRA"), ("G", "MARGEM")))
    j = num("J", "VALOR DE VENDA UNITARIO")
    # a caixa do HSE tem uma linha só: quebra de linha (Alt+Enter) vira um espaço
    descricao = re.sub(r"\s*[\r\n]+\s*", " ", _texto(cel["R"]) or "")
    if len(descricao) > MAX_DESCRICAO:
        erros.append(f"{pre} DESCRIÇÃO NO DAV com {len(descricao)} caracteres (máximo {MAX_DESCRICAO})")
    if len(erros) > qtd_errada:
        return None

    custo = custo or Decimal(0)
    if j is None:  # arquivo salvo sem cache de fórmulas: mesma conta da planilha
        h = custo * qtd + (d or 0) + (e or 0) + (f or 0)
        i = h * (g or 0) / 100 + h
        j = i / qtd
        avisos.append(f"{pre} valor recalculado (planilha sem cache de fórmulas)")
    valor = j.quantize(CENTAVO, ROUND_HALF_UP)
    if valor <= 0:
        erros.append(f"{pre} valor unitário (coluna {_coluna('J', desloc)}) deve ser maior que zero")

    if codigo:  # com CÓDIGO HSE as colunas L–Q são ignoradas
        return Item(numero=n, linha=linha, produto=produto or "", quantidade=qtd, custo=custo,
                    valor_unit=valor, codigo=codigo, ncm=None, origem=0, icms=ICMS_PADRAO,
                    descricao_cadastro=produto or "", grupo=None, marca=None, descricao=descricao)

    ncm = _texto(cel["L"])
    if ncm:
        ncm = re.sub(r"\D", "", ncm)
        if len(ncm) != 8:
            erros.append(f"{pre} NCM deve ter 8 dígitos ({cel['L']!r})")
    origem = num("M", "ORIGEM")
    if origem is not None and (origem != origem.to_integral() or not 0 <= origem <= 8):
        erros.append(f"{pre} ORIGEM deve ser de 0 a 8 ({cel['M']!r})")
    icms = num("N", "ICMS")
    if icms is not None and 0 < icms < 1:  # célula formatada como %
        icms *= 100

    return Item(
        numero=n, linha=linha, produto=produto or "", quantidade=qtd, custo=custo,
        valor_unit=valor, codigo=codigo, ncm=ncm or None,
        origem=int(origem or 0), icms=icms if icms is not None else ICMS_PADRAO,
        descricao_cadastro=_texto(cel["O"]) or produto or "",
        grupo=_texto(cel["P"]), marca=_texto(cel["Q"]), descricao=descricao,
    )


def _descricoes_conflitantes(itens: list[Item], erros: list[str]) -> None:
    """Produto novo com a mesma descrição de outro, mas dados diferentes: o robô cadastraria um só."""
    vistos: dict[str, Item] = {}
    for it in itens:
        if it.codigo:
            continue
        primeiro = vistos.setdefault(normalizar(it.descricao_cadastro), it)
        if primeiro is it:
            continue
        # NCM, grupo e marca em branco a IA preenche: só conflita se os dois vierem preenchidos
        diferentes = [nome for nome, a, b in (("NCM", primeiro.ncm, it.ncm), ("grupo", primeiro.grupo, it.grupo),
                                              ("marca", primeiro.marca, it.marca)) if a and b and a != b]
        diferentes += [nome for nome, a, b in (("custo", primeiro.custo, it.custo), ("origem", primeiro.origem, it.origem),
                                               ("ICMS", primeiro.icms, it.icms)) if a != b]
        if diferentes:
            erros.append(f"Item {it.numero}: descrição deve ser diferente da do item {primeiro.numero} "
                         f"(mesma descrição com {', '.join(diferentes)} diferentes)")


def _codigos_conflitantes(itens: list[Item], erros: list[str]) -> None:
    """Mesmo CÓDIGO HSE com valor diferente: o HSE junta as linhas e recusa o preço (envio #149)."""
    vistos: dict[str, Item] = {}
    for it in itens:
        if not it.codigo:
            continue
        primeiro = vistos.setdefault(it.codigo, it)
        if primeiro is not it and primeiro.valor_unit != it.valor_unit:
            erros.append(f"Item {it.numero}: mesmo CÓDIGO HSE do item {primeiro.numero} com outro valor "
                         "deve ficar numa linha só, com a quantidade somada (o HSE junta as linhas)")


def _filial(v, celula: str, erros: list[str]) -> int:
    s = _texto(v)
    if not s:
        return 1
    m = re.match(r"\s*(\d+)", s)
    if not m or int(m.group(1)) not in FILIAIS:
        erros.append(f"Filial ({celula}) inválida ({s!r}); use 1, 2 ou 3")
        return 1
    return int(m.group(1))


def colunas_antes(ws) -> int:
    """Colunas antes do PRODUTO na linha 1: 1 no modelo com o Nº na coluna A, 0 nos antigos."""
    for c in range(1, 6):
        if normalizar(ws.cell(1, c).value) == "PRODUTO":
            return c - 1
    return 0


def _coluna(letra: str, desloc: int) -> str:
    return get_column_letter(column_index_from_string(letra) + desloc)


def linha_rodape(ws, desloc: int | None = None) -> int:
    """Linha de "OBSERVAÇÕES:" na coluna dos rótulos (a do PRODUTO): os itens vão até a linha antes
    dela e o rodapé anda junto."""
    col = 1 + (colunas_antes(ws) if desloc is None else desloc)
    for linha in range(LINHA_INI, ws.max_row + 1):
        if normalizar(ws.cell(linha, col).value).startswith("OBSERVACOES"):
            return linha
    return RODAPE_PADRAO


def traduzir(celula: str, desloc: int, rodape: int) -> str:
    """Endereço no modelo antigo de 24 itens, sem o Nº (B30, K2...) → endereço numa planilha com
    `desloc` colunas antes do PRODUTO e "OBSERVAÇÕES:" na linha `rodape`."""
    col, linha = re.fullmatch(r"([A-Z]+)(\d+)", celula).groups()
    linha = int(linha)
    if linha >= RODAPE_PADRAO:
        linha += rodape - RODAPE_PADRAO
    return f"{_coluna(col, desloc)}{linha}"


def celula_real(ws, celula: str) -> str:
    desloc = colunas_antes(ws)
    return traduzir(celula, desloc, linha_rodape(ws, desloc))


def layout(path: Path) -> tuple[int, int]:
    """(colunas antes do PRODUTO, linha de "OBSERVAÇÕES:") lendo só o necessário do arquivo."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = _aba(wb)
        cab = next(ws.iter_rows(min_row=1, max_row=1, max_col=5, values_only=True), ())
        desloc = next((i for i, v in enumerate(cab) if normalizar(v) == "PRODUTO"), 0)
        for n, (v,) in enumerate(ws.iter_rows(min_row=LINHA_INI, min_col=1 + desloc, max_col=1 + desloc,
                                              values_only=True), LINHA_INI):
            if normalizar(v).startswith("OBSERVACOES"):
                return desloc, n
        return desloc, RODAPE_PADRAO
    finally:
        wb.close()


def ler_planilha(path: Path) -> Orcamento:
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:  # arquivo corrompido / não é xlsx
        raise ErroPlanilha([f"não foi possível abrir a planilha: {e}"]) from e
    ws = _aba(wb)
    erros: list[str] = []
    avisos: list[str] = []

    desloc = colunas_antes(ws)
    r = linha_rodape(ws, desloc)
    rotulo, valor = _coluna("A", desloc), _coluna("B", desloc)
    b = {campo: f"{valor}{r + d}" for campo, d in (("obs", 0), ("local", 4), ("cliente", 5), ("prazo", 6),
                                              ("vendedor", 7), ("forma", 8), ("parcelamento", 9),
                                              ("oc", 10), ("filial", 11), ("frete", 12))}
    itens = [it for linha in range(LINHA_INI, r)
             if (it := _ler_item(ws, linha, erros, avisos, desloc))]
    if not itens and not erros:
        erros.append(f"nenhum item preenchido (linhas {LINHA_INI} a {r - 1}, "
                     f"coluna {rotulo} ou {_coluna('K', desloc)})")
    _descricoes_conflitantes(itens, erros)
    _codigos_conflitantes(itens, erros)

    obs = _texto(ws[b["obs"]].value) or ""
    cliente = _texto(ws[b["cliente"]].value)
    if not cliente:
        erros.append(f"Cliente ({b['cliente']}) é obrigatório")
    vendedor = _texto(ws[b["vendedor"]].value)
    if not vendedor:
        erros.append(f"VENDEDOR ({b['vendedor']}) é obrigatório")

    prazo = None
    try:
        p = _num(ws[b["prazo"]].value)
        if p is not None:
            if p < 0 or p != p.to_integral():
                raise ValueError(p)
            prazo = int(p)
    except ValueError:
        erros.append(f"Prazo de entrega ({b['prazo']}) inválido ({ws[b['prazo']].value!r})")

    forma = _texto(ws[b["forma"]].value)
    if forma:
        codigo = FORMAS_PG.get(normalizar(forma))
        if not codigo:
            erros.append(f"Forma de pagamento ({b['forma']}) desconhecida ({forma!r})")
        forma = codigo

    # Só o modelo com a linha "Frete" (A38 no de 24 itens) tem o FRETE na coluna B; no anterior ela é a linha "ITEM 1".
    a_frete = f"{rotulo}{r + 12}"
    frete = (normalizar(ws[b["frete"]].value) or None) if normalizar(ws[a_frete].value) == "FRETE" else None
    if frete and frete not in FRETES:
        erros.append(f"FRETE ({b['frete']}) deve ser CIF ou FOB ({ws[b['frete']].value!r})")
    elif frete and not prazo:
        erros.append(f"Prazo de entrega ({b['prazo']}) é obrigatório quando o FRETE ({b['frete']}) está marcado")
    texto = _com_frete(obs, frete if frete in FRETES else None, prazo)
    if len(texto) > MAX_OBS:
        com = " + linha do FRETE" if texto != obs else ""
        erros.append(f"OBSERVAÇÕES{com} com {len(texto)} caracteres (máximo {MAX_OBS})")

    filial = _filial(ws[b["filial"]].value, b["filial"], erros)
    if erros:
        raise ErroPlanilha(erros)
    return Orcamento(
        arquivo=Path(path), itens=tuple(itens), observacoes=obs,
        local_entrega=_texto(ws[b["local"]].value), cliente=cliente, prazo_dias=prazo,
        vendedor=vendedor, forma_pg=forma, parcelamento=_texto(ws[b["parcelamento"]].value),
        ordem_compra=_texto(ws[b["oc"]].value), filial=filial, avisos=tuple(avisos), frete=frete,
    )
