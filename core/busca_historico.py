"""Busca em português no histórico (sugestão 5, 24/09/2026).

"cotações para Anchieta acima de 100 kg em agosto" → filtros de uma lista
FECHADA. A IA nunca escreve SQL: ela só preenche os campos de `FILTROS`, o
validador joga fora o que não for do tipo certo, e `aplicar` filtra em Python
as cotações que o banco já devolveu. Os filtros entendidos vão para a URL e
aparecem na tela — a pessoa confere e tira o que estiver errado.

Sem IA (sem chave ou fora do ar), a frase vira busca por trecho na cidade de
origem, de destino e no material.
"""

from __future__ import annotations

import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

from core import ia

FUNCAO = "busca no histórico"

# nome → rótulo da tela. A ordem é a dos chips.
FILTROS = {
    "origem": "origem", "destino": "destino", "material": "material",
    "peso_min": "peso a partir de", "peso_max": "peso até",
    "desde": "de", "ate": "até", "transportadora": "com preço da",
    "status": "situação",
}
PESO_MAXIMO = Decimal(1_000_000)   # kg; nenhuma carga real passa disso
STATUS = {"com_preco": "com preço", "sem_preco": "sem preço nenhum"}

SISTEMA = """Você transforma a frase de busca de um vendedor em filtros para a lista
de cotações de frete dele. Preencha SÓ o que a frase pede; o resto fica null.
- origem / destino: nome da cidade ou sigla da UF, como escrito na frase.
- material: tipo de material citado (ex.: "eletrônicos").
- peso_min / peso_max: números em kg ("acima de 100 kg" → peso_min 100).
- desde / ate: datas AAAA-MM-DD do período ("em agosto" → primeiro e último dia
  de agosto do ano de hoje, ou do ano anterior se agosto ainda não chegou).
- transportadora: um dos códigos da lista recebida, quando a frase citar uma.
- status: "com_preco" ou "sem_preco" quando a frase falar de ter ou não preço.
Responda em JSON com todas as chaves."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "origem": {"type": ["string", "null"]},
        "destino": {"type": ["string", "null"]},
        "material": {"type": ["string", "null"]},
        "peso_min": {"type": ["number", "null"]},
        "peso_max": {"type": ["number", "null"]},
        "desde": {"type": ["string", "null"]},
        "ate": {"type": ["string", "null"]},
        "transportadora": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
    },
    "required": list(FILTROS),
    "additionalProperties": False,
}


def _plano(t) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t or ""))
                   if not unicodedata.combining(c)).casefold().strip()


def _decimal(v) -> Decimal | None:
    try:
        d = Decimal(str(v).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    # Teto: "peso_min=1e30" na URL quebrava o quantize de `limpar` (erro 500).
    return d if d.is_finite() and 0 <= d <= PESO_MAXIMO else None


def _data(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def limpar(bruto: dict, slugs: Iterable[str]) -> dict[str, str]:
    """Só as chaves de FILTROS, cada uma do tipo certo, como texto (para a
    URL). O que não passa some — vale para a IA e para a URL editada à mão."""
    slugs = set(slugs)
    saida: dict[str, str] = {}
    for k in ("origem", "destino", "material"):
        v = " ".join(str(bruto.get(k) or "").split())[:60]
        if v:
            saida[k] = v
    for k in ("peso_min", "peso_max"):
        if bruto.get(k) not in (None, "") and (d := _decimal(bruto[k])) is not None:
            saida[k] = str(d.quantize(Decimal(1)) if d == d.to_integral() else d)
    for k in ("desde", "ate"):
        if (d := _data(bruto.get(k))) is not None:
            saida[k] = d.isoformat()
    if (t := str(bruto.get("transportadora") or "").strip().lower()) in slugs:
        saida["transportadora"] = t
    if (s := str(bruto.get("status") or "")) in STATUS:
        saida["status"] = s
    return saida


def _local(cidade, uf, procura: str) -> bool:
    """Duas letras é UF, e só UF: "SP" não pode achar "Jaspe"."""
    p = _plano(procura)
    if len(p) == 2:
        return p == _plano(uf)
    return p in _plano(cidade)


def aplicar(cotacoes: list[dict], f: dict[str, str]) -> list[dict]:
    """Filtra em Python. `f` já passou por `limpar`."""
    def passa(c: dict) -> bool:
        if "origem" in f and not _local(c["cidade_origem"], c["uf_origem"], f["origem"]):
            return False
        if "destino" in f and not _local(c["cidade_destino"], c["uf_destino"], f["destino"]):
            return False
        if "material" in f and _plano(f["material"]) not in _plano(c.get("material")):
            return False
        peso = _decimal(c.get("peso_kg"))
        if "peso_min" in f and (peso is None or peso < Decimal(f["peso_min"])):
            return False
        if "peso_max" in f and (peso is None or peso > Decimal(f["peso_max"])):
            return False
        dia = _data(c.get("criado_em"))
        if "desde" in f and (dia is None or dia < date.fromisoformat(f["desde"])):
            return False
        if "ate" in f and (dia is None or dia > date.fromisoformat(f["ate"])):
            return False
        if "transportadora" in f and f["transportadora"] not in c.get("com_preco", []):
            return False
        if f.get("status") == "com_preco" and c.get("melhor_preco") is None:
            return False
        if f.get("status") == "sem_preco" and c.get("melhor_preco") is not None:
            return False
        return True
    return [c for c in cotacoes if passa(c)]


def por_trecho(cotacoes: list[dict], frase: str) -> list[dict]:
    """Sem IA: a frase inteira como trecho de cidade ou material."""
    p = _plano(frase)
    return [c for c in cotacoes
            if any(p in _plano(c.get(k)) for k in ("cidade_origem", "cidade_destino", "material"))]


def descrever(f: dict[str, str], nome_de=lambda s: s) -> list[str]:
    def valor(k: str, v: str) -> str:
        if k in ("desde", "ate"):
            return date.fromisoformat(v).strftime("%d/%m/%Y")
        if k.startswith("peso"):
            return f"{v} kg"
        if k == "transportadora":
            return nome_de(v)
        if k == "status":
            return STATUS[v]
        return v
    return [f"{FILTROS[k]}: {valor(k, f[k])}" for k in FILTROS if k in f]


def interpretar(frase: str, hoje: date, slugs: dict[str, str]) -> dict[str, str]:
    """Frase → filtros limpos. `slugs` = {código: nome}. Levanta
    ia.IAIndisponivel se nenhum modelo responder no formato."""
    pedido = (f"Hoje: {hoje.isoformat()}\nTransportadoras (código: nome): "
              + ", ".join(f"{s}: {n}" for s, n in slugs.items())
              + f"\nFrase: {frase[:300]}")
    r = ia.completar_json(SISTEMA, pedido, ESQUEMA, funcao=FUNCAO,
                          validar=lambda d: limpar(d, slugs), max_tokens=400)
    return r.dados
