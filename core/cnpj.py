"""CNPJ -> razão social, pela BrasilAPI.

Mesmo padrão do core/cep.py: camada de IO, pública e sem chave, com cache em
disco. Existe porque a mensagem de WhatsApp precisa dizer o NOME da empresa,
não só o número — quem lê do outro lado precisa saber quem é o remetente e
quem é o destinatário.

Falhar aqui NÃO pode derrubar a cotação: sem o nome a mensagem ainda serve,
com o CNPJ sozinho. Por isso `buscar` devolve None em vez de levantar.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
TIMEOUT_S = 12.0
CACHE = Path(".cache/cnpj.json")


def _digitos(valor: str) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _carregar() -> dict[str, str]:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _gravar(cache: dict[str, str]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                     encoding="utf-8")


def buscar(cnpj: str) -> str | None:
    """Razão social, ou None se não achar.

    Prefere o nome fantasia quando existe: é como a empresa é conhecida por
    quem atende o telefone da transportadora. Cai para a razão social."""
    d = _digitos(cnpj)
    if len(d) != 14:
        return None

    cache = _carregar()
    if d in cache:
        return cache[d] or None

    try:
        r = httpx.get(URL.format(cnpj=d), timeout=TIMEOUT_S)
        r.raise_for_status()
        dados = r.json()
    except Exception:
        return None      # sem nome a mensagem ainda serve; não derrubar

    nome = ((dados.get("nome_fantasia") or "").strip()
            or (dados.get("razao_social") or "").strip())
    cache[d] = nome
    _gravar(cache)
    return nome or None


def formatar(cnpj: str) -> str:
    """00.000.000/0000-00 a partir de qualquer entrada."""
    d = _digitos(cnpj)
    if len(d) != 14:
        return str(cnpj or "")
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
