"""Provas que o agente de diagnóstico lê: o que o robô guardou do envio e o que o HSE tem."""
from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

import openpyxl

from orcamento.hse import _mensagens
from orcamento.planilha import _texto, ler_planilha

NAO_VERIFICADO = "nao_verificado"
MARGEM = 25  # pedidos para cada lado do número de referência
ANTES = 5  # pedidos antes do último DAV conhecido anterior ao envio
MAX_PAGINAS = 60  # teto de pedidos lidos no HSE por diagnóstico

_RASCUNHO = re.compile(r"\brascunho\s+(\d{5})\b", re.I)
_CONTINUAM = "Produtos cadastrados no HSE (continuam lá):"
_CADASTROU = re.compile(r"CADASTROU produto novo (\d+ - [^|\n]*?)\s*(?:\||$)", re.M)
_CODIGO_DO_ROBO = re.compile(r"(?:usou produto existente|CADASTROU produto novo) (\d+) - ")


def _decimal(v) -> Decimal | None:
    s = str(v).strip()
    if "," in s:  # pt-BR do HSE: "8.300,940000"
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _mesmo_valor(hse, planilha) -> bool:
    a, b = _decimal(hse), _decimal(planilha)
    return a is None or b is None or a == b  # ilegível não descarta: melhor sobrar pedido que sumir


def pedidos_do_envio(pedidos: list[dict], cliente: str, data: str, codigos: set[str],
                     ignorar: set[int] = frozenset(), valores: dict | None = None) -> list[int]:
    """Pedidos do mesmo cliente e dia, fora de `ignorar`, com todos os itens entre os produtos do envio
    (e, com `valores` código → valor unitário, ao mesmo preço)."""
    valores = valores or {}

    def do_envio(i: dict) -> bool:
        c = str(i["codigo"])
        return c in codigos and (c not in valores or _mesmo_valor(i["valor"], valores[c]))

    return [p["numero"] for p in pedidos
            if p["numero"] not in ignorar and p["cliente"] == cliente and p["data"] == data
            and p["itens"] and all(do_envio(i) for i in p["itens"])]


def _ler_planilha(arquivo: Path) -> dict | None:
    if not arquivo.exists():
        return None
    try:
        o = ler_planilha(arquivo)
        return {"cliente": o.cliente, "vendedor": o.vendedor, "local": o.local_entrega,
                "itens": [{"n": i.numero, "codigo": i.codigo, "descricao": i.descricao_cadastro,
                           "qtd": str(i.quantidade), "valor": str(i.valor_unit),
                           "ncm": i.ncm, "grupo": i.grupo, "marca": i.marca} for i in o.itens]}
    except Exception:  # ErroPlanilha ou qualquer outro: recusadas também precisam mostrar os itens
        pass
    try:
        ws = openpyxl.load_workbook(arquivo, data_only=True)["ORÇAMENTO"]
        itens = [{"n": r - 1, "codigo": _texto(ws[f"K{r}"].value),
                  "descricao": _texto(ws[f"O{r}"].value) or _texto(ws[f"A{r}"].value),
                  "qtd": _texto(ws[f"B{r}"].value), "valor": _texto(ws[f"J{r}"].value),
                  "ncm": _texto(ws[f"L{r}"].value), "grupo": _texto(ws[f"P{r}"].value),
                  "marca": _texto(ws[f"Q{r}"].value)}
                 for r in range(2, 26) if ws[f"A{r}"].value or ws[f"K{r}"].value]
        return {"cliente": _texto(ws["B31"].value), "vendedor": _texto(ws["B33"].value),
                "local": _texto(ws["B30"].value), "itens": itens}
    except Exception:
        return None


def faixa_de_busca(numeros: list[tuple[str, int]], quando: str, margem: int = MARGEM,
                   teto: int | None = MAX_PAGINAS) -> range:
    """Números de pedido entre o último DAV (com número) antes de `quando` e o primeiro depois.

    `numeros` = (hora ISO, número) de todos os DAVs com número. Só um lado conhecido: ±2×margem
    em volta dele. Faixa maior que `teto`: os `teto` números mais perto do (lado de antes + 1)."""
    antes = max((n for h, n in numeros if h <= quando), default=None)
    depois = min((n for h, n in numeros if h >= quando), default=None)
    if antes is None and depois is None:
        return range(0)
    if antes is not None and depois is not None:
        faixa = range(min(antes, depois) - ANTES, max(antes, depois) + margem + 1)
    else:
        n = depois if antes is None else antes
        faixa = range(n - 2 * margem, n + 2 * margem + 1)
    if teto is None or len(faixa) <= teto:
        return faixa
    centro = depois if antes is None else antes + 1
    inicio = min(max(faixa.start, centro - teto // 2), faixa.stop - teto)
    return range(inicio, inicio + teto)


class Achados(list):
    """Pedidos lidos no HSE; `aviso` diz quando a busca não cobriu a faixa toda."""
    aviso = ""


def buscador_hse(hse, numeros: list[tuple[str, int]]) -> Callable[[str, str, int | None, str | None], list[dict]]:
    def buscar(cliente: str, data: str, perto_de: int | None, quando: str | None) -> list[dict]:
        achados = Achados()
        if perto_de is not None:
            faixa = range(perto_de - MARGEM, perto_de + MARGEM + 1)
        else:
            quando = quando or datetime.strptime(data, "%d/%m/%Y").replace(hour=12).isoformat()
            faixa, inteira = faixa_de_busca(numeros, quando), faixa_de_busca(numeros, quando, teto=None)
            if not inteira:
                achados.aviso = "sem referência de número"
            elif len(faixa) < len(inteira):
                achados.aviso = (f"faixa cortada: li {faixa.start}..{faixa.stop - 1} de "
                                 f"{inteira.start}..{inteira.stop - 1}")
        achados += [p for p in map(hse.ler_pedido, faixa) if p and p["cliente"] == cliente and p["data"] == data]
        return achados
    return buscar


def _arquivos(pasta: Path, sub: str, i: int) -> list[Path]:
    # prefixo "<id>_" exato: 17_* não casa com o id 7
    return sorted(pasta.glob(f"{sub}/{i}_*")) if (pasta / sub).is_dir() else []


def _criados(dav: dict, planilha: dict | None, buscar, ignorar: set[int]) -> tuple[list[int] | str, str]:
    relatorio = dav.get("relatorio") or ""
    m = re.search(r"Cliente:\s*(\d+)", relatorio)
    quando = dav.get("iniciado_em") or dav.get("criado_em") or ""
    data = quando[:10]
    if buscar is None:
        return NAO_VERIFICADO, "consulta ao HSE não disponível"
    if not m or not data:
        return NAO_VERIFICADO, "sem código do cliente ou data do envio"
    itens = (planilha or {}).get("itens", [])
    # produtos achados pela descrição ou cadastrados pelo robô não têm código K na planilha
    codigos = {i["codigo"] for i in itens if i["codigo"]} | set(_CODIGO_DO_ROBO.findall(relatorio))
    valores = {i["codigo"]: i["valor"] for i in itens if i["codigo"] and i["valor"]}
    try:
        dia = datetime.strptime(data, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return NAO_VERIFICADO, f"data do envio ilegível: {data!r}"
    numero = str(dav.get("numero") or "")
    try:
        pedidos = buscar(m.group(1), dia, int(numero) if numero.isdigit() else None, quando)
    except Exception as e:  # HseIndisponivel incluso
        return NAO_VERIFICADO, f"HSE não consultado: {e}"
    if pedidos and not codigos:
        return NAO_VERIFICADO, "sem códigos de produto do envio para comparar com os pedidos do cliente"
    achados = pedidos_do_envio(pedidos, m.group(1), dia, codigos, ignorar, valores)
    aviso = getattr(pedidos, "aviso", "")
    if aviso and not achados:  # não leu tudo: "nada criado" seria um palpite
        return NAO_VERIFICADO, aviso
    return achados, aviso


def _produtos_criados(texto: str) -> list[str]:
    candidatos = [p.strip() for linha in texto.splitlines() if _CONTINUAM in linha
                  for p in linha.split(_CONTINUAM, 1)[1].split(";")]
    candidatos += [p.strip() for p in _CADASTROU.findall(texto)]
    saida: dict[str, str] = {}
    for p in candidatos:
        if p:
            saida.setdefault(p.split(" - ", 1)[0], p)
    return list(saida.values())


def _cnpj_valido(d: str) -> bool:
    if len(set(d)) == 1:
        return False

    def dv(base: str) -> str:
        r = sum(int(a) * b for a, b in zip(base, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(base):])) % 11
        return "0" if r < 2 else str(11 - r)
    return dv(d[:12]) == d[12] and dv(d[:13]) == d[13]


def _cliente_b31(planilha: dict | None) -> dict | None:
    if not planilha or planilha.get("cliente") is None:
        return None
    valor = str(planilha["cliente"])
    d = re.sub(r"\D", "", valor)
    return {"valor": valor, "cnpj_valido": _cnpj_valido(d) if len(d) == 14 else None}


def _envio_anterior(anterior: dict | None) -> dict | None:
    if not anterior:
        return None
    linhas = [ln.strip() for ln in (anterior.get("relatorio") or "").splitlines()
              if "cadastrado no item" in ln or "CADASTROU produto novo" in ln]
    return {"id": anterior["id"], "estado": anterior["estado"], "erro": anterior.get("erro"), "linhas": linhas}


def coletar(dav: dict, pasta: Path, buscar_pedidos: Callable[[str, str, int | None, str | None], list[dict]] | None,
            ignorar: set[int] = frozenset(), anterior: dict | None = None) -> dict:
    """`ignorar`: números de outros DAVs; `anterior`: o envio que este corrige (linha do banco)."""
    pasta, i = Path(pasta), dav["id"]
    planilha = _ler_planilha(pasta / "entrada" / f"{i}.xlsx")
    mensagens = []
    for h in _arquivos(pasta, "respostas_hse", i):
        mensagens += [t for _, t in _mensagens(h.read_text(encoding="utf-8", errors="replace"))]
    prints = [p for p in _arquivos(pasta, "prints_hse", i) if p.suffix == ".png"]
    criados, motivo = ([], "")
    if dav["estado"] in ("erro", "incerto"):
        criados, motivo = _criados(dav, planilha, buscar_pedidos, ignorar)
    texto = "\n".join(t for t in (dav.get("relatorio"), dav.get("erro")) if t)
    rascunhos = list(dict.fromkeys(int(n) for n in _RASCUNHO.findall(texto)))
    if isinstance(criados, list):
        criados += [n for n in rascunhos if n not in criados]
    try:
        conferencia = json.loads(dav["conferencia_relatorio"]) if dav.get("conferencia_relatorio") else None
    except ValueError:
        conferencia = None
    return {
        "envio": {"id": i, "estado": dav["estado"], "erro": dav.get("erro"),
                  "arquivo": dav.get("arquivo"), "vendedor": dav.get("usuario"),
                  "criado_em": dav.get("criado_em"), "iniciado_em": dav.get("iniciado_em"),
                  "terminado_em": dav.get("terminado_em"), "numero": dav.get("numero")},
        "relatorio": dav.get("relatorio"), "conferencia": conferencia, "planilha": planilha,
        "mensagens_hse": mensagens, "print": str(prints[-1]) if prints else None,
        "criados_no_hse": criados, "motivo_nao_verificado": motivo,
        "rascunhos": rascunhos, "produtos_criados": _produtos_criados(texto),
        "cliente_b31": _cliente_b31(planilha), "envio_anterior": _envio_anterior(anterior),
    }
