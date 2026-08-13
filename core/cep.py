"""CEP -> cidade, UF e código IBGE, pelo ViaCEP.

Camada de IO, separada de core/ficha.py de propósito: a ficha continua pura e
recebe esta função injetada.

Por que existe: escrever cidade à mão na ficha gerou, em 13/08/2026, uma ficha
que dizia "São José dos Campos" com CEP 09895-003, que é São Bernardo do
Campo. A Jadlog cota por CEP e a Della Volpe por cidade — a mesma ficha cotava
duas rotas diferentes, e a comparação entre elas não queria dizer nada.

O ViaCEP é público e sem chave. O cache em disco evita repetir a consulta a
cada rodada de teste e deixa o mesmo CEP dar sempre o mesmo resultado.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

URL = "https://viacep.com.br/ws/{cep}/json/"
TIMEOUT_S = 10.0
CACHE = Path(".cache/cep.json")


class CepInvalido(ValueError):
    """CEP com formato errado ou que o ViaCEP não conhece."""


def _carregar_cache() -> dict[str, list]:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _gravar_cache(cache: dict[str, list]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                     encoding="utf-8")


def buscar(cep: str) -> tuple[str, str, str | None]:
    """(cidade, uf, código IBGE). Levanta CepInvalido se não existir.

    Falhar aqui é melhor que seguir com cidade errada: um CEP inexistente na
    ficha vira frete de outra rota, e ninguém percebe olhando o resultado."""
    digitos = "".join(c for c in cep if c.isdigit())
    if len(digitos) != 8:
        raise CepInvalido(f"CEP precisa ter 8 dígitos, veio {cep!r}")

    cache = _carregar_cache()
    if digitos in cache:
        cidade, uf, ibge = cache[digitos]
        return cidade, uf, ibge

    try:
        resposta = httpx.get(URL.format(cep=digitos), timeout=TIMEOUT_S)
        resposta.raise_for_status()
        dados = resposta.json()
    except httpx.HTTPError as exc:
        raise CepInvalido(f"ViaCEP não respondeu para {cep}: {exc}") from exc

    # o ViaCEP devolve 200 com {"erro": true} para CEP que não existe
    if dados.get("erro"):
        raise CepInvalido(f"CEP não existe: {cep}")

    achado = (dados["localidade"], dados["uf"], dados.get("ibge") or None)
    cache[digitos] = list(achado)
    _gravar_cache(cache)
    return achado
