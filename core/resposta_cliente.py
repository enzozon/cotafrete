"""Resposta pronta para o CLIENTE com as opções de frete (sugestão 4, 24/09/2026).

Depois de cotar, o vendedor reescrevia à mão para o cliente os preços que a
tela mostra. Aqui:

1. `opcoes` (código): as transportadoras que deram preço, do banco, da mais
   barata para a mais cara — preço, prazo e validade.
2. `texto_padrao` (código): a resposta sem IA. Aparece SEMPRE.
3. `pedir` (IA, opcional): reescreve no tom da mensagem que o cliente mandou
   (o vendedor cola na tela). A IA só escreve o texto em volta; o validador
   exige que CADA preço apareça exatamente como no banco e recusa qualquer
   número que não esteja nos fatos — texto ruim vai para o próximo modelo.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from typing import Callable

from core import ia

FUNCAO = "resposta ao cliente"

SISTEMA = """Você escreve a mensagem que um vendedor de uma distribuidora manda para
o CLIENTE com as opções de frete de uma carga. Use o tom da mensagem do cliente
quando ela vier (formal ou informal, e-mail ou WhatsApp); sem ela, tom cordial
e direto. Liste TODAS as opções na ordem recebida, cada uma com a
transportadora, o preço escrito EXATAMENTE como veio (ex.: "R$ 1.234,56"), o
prazo e a validade quando houver. Não invente número nenhum: nada de desconto,
total, imposto, data ou prazo que não esteja nos dados. Não assine com nome.
Responda em JSON: {"texto": "..."}"""

ESQUEMA = {
    "type": "object",
    "properties": {"texto": {"type": "string"}},
    "required": ["texto"],
    "additionalProperties": False,
}


def _moeda(v: Decimal) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data(iso: str | None) -> str | None:
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return None


def opcoes(c: dict, nome_de: Callable[[str], str] = lambda s: s) -> list[dict]:
    """[{transportadora, preco, prazo, validade}] das que deram preço, a mais barata primeiro."""
    com_preco = [r for r in c.get("resultados", []) if r.get("valor") is not None]
    return [{"transportadora": nome_de(r["transportadora"]),
             "preco": _moeda(Decimal(r["valor"])),
             "prazo": (f"{r['prazo']} dias" if str(r.get("prazo") or "").strip().isdigit() else None),
             "validade": _data(r.get("validade"))}
            for r in sorted(com_preco, key=lambda r: Decimal(r["valor"]))]


def _rota(c: dict) -> str:
    return (f"{c['cidade_origem']}/{c['uf_origem']} para "
            f"{c['cidade_destino']}/{c['uf_destino']}")


def _carga(c: dict) -> str:
    peso = str(c["peso_kg"]).replace(".", ",")
    vol = int(c["quantidade"])
    return f"{vol} volume{'s' if vol != 1 else ''}, {peso} kg"


def texto_padrao(c: dict, ops: list[dict]) -> str:
    if not ops:
        return ""
    linhas = [f"Olá! Segue a cotação de frete de {_rota(c)} ({_carga(c)}):", ""]
    for o in ops:
        partes = [f"{o['transportadora']}: {o['preco']}"]
        if o["prazo"]:
            partes.append(f"prazo de {o['prazo']}")
        if o["validade"]:
            partes.append(f"válido até {o['validade']}")
        linhas.append("• " + ", ".join(partes))
    linhas += ["", "Fico à disposição para fechar o envio."]
    return "\n".join(linhas)


def _numeros(texto: str) -> set[str]:
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+", texto)}


def _validador(c: dict, ops: list[dict]):
    permitidos = _numeros(texto_padrao(c, ops))

    def validar(dados) -> str:
        texto = str((dados or {}).get("texto") or "").strip()
        if not texto:
            raise ValueError("texto vazio")
        faltando = [o["preco"] for o in ops if o["preco"] not in texto]
        if faltando:
            raise ValueError(f"preço ausente ou alterado: {faltando[:3]}")
        inventados = _numeros(texto) - permitidos
        if inventados:
            raise ValueError(f"números que não estão na cotação: {sorted(inventados)[:5]}")
        return texto
    return validar


def pedir(c: dict, ops: list[dict], mensagem_do_cliente: str = "") -> ia.Resposta:
    """Levanta ia.IAIndisponivel se nenhum modelo der um texto que passe."""
    dados = {"rota": _rota(c), "carga": _carga(c), "opcoes": ops,
             "mensagem_do_cliente": (mensagem_do_cliente or "")[:2000]}
    return ia.completar_json(SISTEMA, json.dumps(dados, ensure_ascii=False, indent=1),
                             ESQUEMA, funcao=FUNCAO, validar=_validador(c, ops),
                             max_tokens=1200)
