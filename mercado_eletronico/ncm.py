"""Sugerir NCM pela IA para os itens do ME que ficaram sem.

Pedido do usuário (24/09/2026), passo 2 da IA no site. Quem vem antes da IA
(web/me_ui._gravar_lidos): o que o vendedor digitou, o NCM que o COMPRADOR
escreveu nos Campos Adicionais ("NCM: 8507.60.00" — os itens com código de
material trazem) e a memória do material. A IA fica para o que sobra: os
itens genéricos ("POSTO DUPLO", "TV65", "Divisórias"), que chegam com "NCM:"
vazio.

A IA sugere, o vendedor confere: cada sugestão vem com a descrição da
posição na tabela e uma confiança, e a tela diz "sugerido pela IA". Um NCM
palpite só vira memória do material depois de conferido (me_ui).

Conferido em código, não na confiança da IA: 8 dígitos, capítulo que existe
(01–97, sem o 77, que a TIPI não usa), item que foi pedido. O resto some.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core import ia
from mercado_eletronico import regras as rg

CONFIANCAS = ("alta", "media", "baixa")
ROTULO_CONFIANCA = {"alta": "alta", "media": "média", "baixa": "baixa"}
POR_CHAMADA = 25       # uma cotação de 18 itens vai numa chamada só
MAX_TEXTO_ITEM = 600   # o texto do comprador às vezes é um memorial inteiro

SISTEMA = """Você é um classificador fiscal brasileiro. Para cada item de uma cotação
de compra (empresa de mineração comprando de uma distribuidora), sugira o NCM
(Nomenclatura Comum do Mercosul, 8 dígitos, tabela TIPI vigente) mais provável
para o produto DESCRITO.

Use a descrição, o texto do comprador (medidas, material, modelo, marca) e a
marca oferecida. Regras:
- Um NCM por item, 8 dígitos, formato "9403.30.00".
- descricao_ncm: o texto da posição/subposição, curto, em português
  ("Móveis de madeira para escritórios").
- confianca: "alta" quando a descrição não deixa dúvida; "media" quando há
  mais de uma posição possível e você escolheu a mais comum; "baixa" quando a
  descrição é vaga demais (diga o que falta em `motivo`).
- motivo: uma frase curta — por que essa posição, ou o que o vendedor deve
  confirmar (ex.: "se o tampo for de metal, vai para 9403.10.00").
- Não invente item: responda só os números de item recebidos."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "sugestoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "integer"},
                    "ncm": {"type": "string"},
                    "descricao_ncm": {"type": "string"},
                    "confianca": {"type": "string", "enum": list(CONFIANCAS)},
                    "motivo": {"type": "string"},
                },
                "required": ["item", "ncm", "descricao_ncm", "confianca", "motivo"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sugestoes"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Sugestao:
    ncm: str             # "9403.30.00"
    descricao: str
    confianca: str       # alta / media / baixa
    motivo: str

    def nota(self) -> str:
        """O que a tela mostra embaixo do campo (e o que fica no banco)."""
        return (f"{self.descricao} — confiança {ROTULO_CONFIANCA[self.confianca]}"
                + (f". {self.motivo}" if self.motivo else ""))[:400]


def capitulo_existe(ncm8: str) -> bool:
    cap = int(ncm8[:2])
    return 1 <= cap <= 97 and cap != 77


def limpar(dados: Any, pedidos: set[int]) -> dict[int, Sugestao]:
    """Resposta da IA → sugestões que passam na conferência. Puro."""
    saida: dict[int, Sugestao] = {}
    for s in dados.get("sugestoes") or []:
        try:
            item = int(s.get("item"))
        except (TypeError, ValueError):
            continue
        d = rg.normalizar_ncm(str(s.get("ncm") or ""))
        confianca = str(s.get("confianca") or "").lower().replace("é", "e")
        if item not in pedidos or item in saida or len(d) != 8 or not capitulo_existe(d):
            continue
        saida[item] = Sugestao(
            ncm=rg.formatar_ncm(d),
            descricao=" ".join(str(s.get("descricao_ncm") or "").split())[:160],
            confianca=confianca if confianca in CONFIANCAS else "baixa",
            motivo=" ".join(str(s.get("motivo") or "").split())[:200])
    return saida


def _pedido(itens: list[dict]) -> str:
    linhas = []
    for i in itens:
        linhas.append({
            "item": i["numero"], "descricao": i.get("descricao") or "",
            "texto_do_comprador": " ".join((i.get("obs_comprador") or "").split())[:MAX_TEXTO_ITEM],
            "quantidade": f"{i.get('quantidade') or ''} {i.get('unidade') or ''}".strip(),
            "marca_oferecida": i.get("marca") or "",
        })
    return "Sugira o NCM destes itens:\n\n" + json.dumps(linhas, ensure_ascii=False, indent=1)


def sugerir(itens: list[dict]) -> tuple[dict[int, Sugestao], str]:
    """Itens (dicts de me_item) → {número: Sugestao}, e o modelo que
    respondeu. Levanta ia.IAIndisponivel se nenhum modelo responder."""
    sugestoes: dict[int, Sugestao] = {}
    modelos = []
    for ini in range(0, len(itens), POR_CHAMADA):
        lote = itens[ini:ini + POR_CHAMADA]
        pedidos = {i["numero"] for i in lote}
        r = ia.completar_json(SISTEMA, _pedido(lote), ESQUEMA, funcao="sugerir NCM",
                              validar=lambda d, p=pedidos: _exige_alguma(limpar(d, p)),
                              max_tokens=3000)
        sugestoes |= r.dados
        modelos.append(r.modelo)
    return sugestoes, ", ".join(dict.fromkeys(modelos))


def _exige_alguma(s: dict[int, Sugestao]) -> dict[int, Sugestao]:
    """Resposta sem nenhuma sugestão aproveitável = próximo modelo."""
    if not s:
        raise ValueError("nenhuma sugestão de NCM válida")
    return s
