"""Provas que o agente de diagnóstico lê: o que o robô guardou do envio e o que o HSE tem."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import openpyxl

from orcamento.hse import _mensagens
from orcamento.planilha import ler_planilha

NAO_VERIFICADO = "nao_verificado"


def pedidos_do_envio(pedidos: list[dict], cliente: str, data: str, codigos: set[str]) -> list[int]:
    """Pedidos do mesmo cliente e dia com ao menos um código de produto em comum."""
    return [p["numero"] for p in pedidos
            if p["cliente"] == cliente and p["data"] == data
            and codigos & {str(i["codigo"]) for i in p["itens"]}]


def _texto(v) -> str | None:
    return None if v is None else str(v)


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


def _arquivos(pasta: Path, sub: str, i: int) -> list[Path]:
    # prefixo "<id>_" exato: 17_* não casa com o id 7
    return sorted(pasta.glob(f"{sub}/{i}_*")) if (pasta / sub).is_dir() else []


def _criados(dav: dict, planilha: dict | None, buscar) -> tuple[list[int] | str, str]:
    m = re.search(r"Cliente:\s*(\d+)", dav.get("relatorio") or "")
    data = (dav.get("iniciado_em") or dav.get("criado_em") or "")[:10]
    if buscar is None:
        return NAO_VERIFICADO, "consulta ao HSE não disponível"
    if not m or not data:
        return NAO_VERIFICADO, "sem código do cliente ou data do envio"
    codigos = {i["codigo"] for i in (planilha or {}).get("itens", []) if i["codigo"]}
    aaaa, mm, dd = data.split("-")
    try:
        pedidos = buscar(m.group(1), f"{dd}/{mm}/{aaaa}", dav.get("numero"))
    except Exception as e:  # HseIndisponivel incluso
        return NAO_VERIFICADO, f"HSE não consultado: {e}"
    return pedidos_do_envio(pedidos, m.group(1), f"{dd}/{mm}/{aaaa}", codigos), ""


def coletar(dav: dict, pasta: Path, buscar_pedidos: Callable[[str, str, int | None], list[dict]] | None) -> dict:
    pasta, i = Path(pasta), dav["id"]
    planilha = _ler_planilha(pasta / "entrada" / f"{i}.xlsx")
    mensagens = []
    for h in _arquivos(pasta, "respostas_hse", i):
        mensagens += [t for _, t in _mensagens(h.read_text(encoding="utf-8", errors="replace"))]
    prints = [p for p in _arquivos(pasta, "prints_hse", i) if p.suffix == ".png"]
    criados, motivo = ([], "")
    if dav["estado"] in ("erro", "incerto"):
        criados, motivo = _criados(dav, planilha, buscar_pedidos)
    conferencia = None
    if dav.get("conferencia_relatorio"):
        conferencia = json.loads(dav["conferencia_relatorio"])
    return {
        "envio": {"id": i, "estado": dav["estado"], "erro": dav.get("erro"),
                  "arquivo": dav.get("arquivo"), "vendedor": dav.get("usuario"),
                  "criado_em": dav.get("criado_em"), "iniciado_em": dav.get("iniciado_em"),
                  "terminado_em": dav.get("terminado_em"), "numero": dav.get("numero")},
        "relatorio": dav.get("relatorio"), "conferencia": conferencia, "planilha": planilha,
        "mensagens_hse": mensagens, "print": str(prints[-1]) if prints else None,
        "criados_no_hse": criados, "motivo_nao_verificado": motivo,
    }
