"""Revisão por IA da resposta de cotação do ME — só alertas, nunca valores.

Uma chamada por cotação, pela cadeia de modelos grátis de `core/ia.py`
(Groq e OpenRouter; decisão do usuário em 24/09/2026 — antes era a API da
Anthropic). A IA lê o que o comprador pediu (descrição, texto
do item, Campos Adicionais, observação geral) e o que o usuário preencheu,
e devolve alertas em três níveis: info, atenção, crítico.

O que ela procura é o que o código não consegue: marca pedida × marca
oferecida ("NÃO SERÃO ACEITAS MARCAS SIMILARES"), entrega pedida num lugar
e endereço de outro ("ENTREGAR EM BSB" com End. entrega no ES), NCM que não
combina com o produto, preço fora de escala para o item, unidade/quantidade
estranhas, texto de observação com erro.

Regras que não mudam:
- Nunca altera valor: o resultado é lista de frases. Nada daqui é digitado
  no ME.
- Falhou (sem chave, todos os modelos no limite, JSON estranho) →
  `Revisao.indisponivel` com o motivo, e o fluxo segue. A IA não bloqueia salvar.
- Os cálculos de `regras` (impostos, datas, erros e avisos) vão junto no
  pedido, como FATO: a IA não refaz conta, comenta o que o código não vê.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from core import ia

NIVEIS = ("critico", "atencao", "info")
ROTULO_NIVEL = {"critico": "Crítico", "atencao": "Atenção", "info": "Info"}

SISTEMA = """Você revisa respostas de cotação que uma distribuidora de informática
(Ventura/União, Espírito Santo) vai salvar no portal Mercado Eletrônico para
compradores como a Samarco. Um humano confere e envia depois; seu papel é
apontar problemas antes disso.

Aponte só o que um revisor experiente apontaria:
- marca/modelo oferecido diferente do pedido, quando o comprador pede a marca
  ou diz que não aceita similar;
- local de entrega no texto diferente do "End. entrega" dos Campos Adicionais;
- NCM que não combina com o produto descrito;
- preço unitário fora de escala para o item e a quantidade (ex.: TV por
  R$ 1,00, ou preço que parece ser o total e não o unitário);
- unidade ou quantidade que não batem com o pedido;
- prazo que não atende a data de remessa, quando isso não foi avisado;
- observação do fornecedor confusa, com erro ou que contradiz os campos;
- exigência do texto geral do comprador que a resposta deixa de cumprir.

Não refaça as contas de impostos e datas: elas vêm calculadas e estão certas.
Não repita os erros e avisos que o sistema já deu, a menos que tenha algo a
acrescentar. Não sugira valores novos; descreva o problema. Se não houver
nada a apontar, devolva a lista vazia.

Níveis: "critico" = provável desclassificação ou prejuízo; "atencao" =
conferir antes de enviar; "info" = detalhe. Escreva em português, frases
curtas, citando o número do item (10, 20, ...) no campo `item` quando o alerta
for de um item; `null` quando for da cotação inteira."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "alertas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": ["integer", "null"]},
                    "nivel": {"type": "string", "enum": list(NIVEIS)},
                    "mensagem": {"type": "string"},
                },
                "required": ["item", "nivel", "mensagem"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["alertas"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Alerta:
    item: int | None
    nivel: str
    mensagem: str


@dataclass
class Revisao:
    alertas: list[Alerta] = field(default_factory=list)
    erro: str | None = None     # preenchido = "revisão IA indisponível"
    modelo: str | None = None   # quem respondeu (pode ser o fallback)

    @property
    def indisponivel(self) -> bool:
        return self.erro is not None

    def como_json(self) -> str:
        return json.dumps({"alertas": [a.__dict__ for a in self.alertas],
                           "erro": self.erro, "modelo": self.modelo}, ensure_ascii=False)

    @classmethod
    def de_json(cls, texto: str | None) -> "Revisao | None":
        if not texto:
            return None
        try:
            d = json.loads(texto)
            return cls([Alerta(**a) for a in d.get("alertas", [])], d.get("erro"), d.get("modelo"))
        except (ValueError, TypeError):
            return None


def assinatura(cotacao: dict) -> str:
    """Muda quando muda o que o usuário preencheu: marca a revisão como velha."""
    campos = [cotacao.get("validade_dias")] + [
        [i.get(k) for k in ("numero", "preco", "ncm", "prazo_dias", "marca", "obs", "origem")]
        for i in cotacao.get("itens", [])]
    return hashlib.sha256(json.dumps(campos, default=str).encode()).hexdigest()[:16]


def montar_pedido(cotacao: dict, previa: dict[int, dict[str, str]],
                  erros: list[str], avisos: list[str], obs_geral: str = "") -> str:
    """O texto que vai para a IA. Só dados da cotação — nada de credencial."""
    itens = []
    for i in cotacao["itens"]:
        itens.append({
            "item": i["numero"],
            "pedido_do_comprador": {
                "descricao": i["descricao"], "quantidade": i["quantidade"],
                "unidade": i["unidade"], "texto": i["obs_comprador"],
                "campos_adicionais": i["campos_adicionais"],
            },
            "resposta_do_fornecedor": {
                "preco_unitario": i["preco"] or "(sem preço — o item será RECUSADO no ME, com a observação como justificativa)",
                "ncm": i["ncm"], "prazo_dias": i["prazo_dias"], "marca": i["marca"],
                "observacao": i["obs"], "origem": i["origem"],
            },
            "calculado_pelo_sistema": previa.get(i["numero"], {}),
        })
    dados = {
        "conta": cotacao["conta"].upper(), "cotacao": cotacao["numero"],
        "empresa": cotacao.get("empresa"), "comprador": cotacao.get("comprador"),
        "data_limite": cotacao.get("data_limite"),
        "validade_da_proposta_dias": cotacao.get("validade_dias"),
        "texto_geral_do_comprador": obs_geral,
        "erros_do_sistema": erros, "avisos_do_sistema": avisos,
        "itens": itens,
    }
    return ("Revise esta resposta de cotação. Dados em JSON:\n\n"
            + json.dumps(dados, ensure_ascii=False, indent=1))


def _alertas(dados: Any) -> list[Alerta]:
    """Valida o JSON do modelo. Levantar aqui = próximo modelo da cadeia."""
    brutos = dados["alertas"]
    if not isinstance(brutos, list):
        raise TypeError("'alertas' não é lista")
    alertas = []
    for a in brutos:
        item, nivel = a.get("item"), a.get("nivel")
        mensagem = str(a.get("mensagem") or "").strip()
        if nivel not in NIVEIS or not mensagem:
            continue   # nível inventado ou frase vazia: descarta o alerta, não a resposta
        if isinstance(item, str):
            item = int(item) if item.strip().isdigit() else None
        alertas.append(Alerta(item if isinstance(item, int) else None, nivel, mensagem))
    return sorted(alertas, key=lambda a: (NIVEIS.index(a.nivel), a.item or 0))


def revisar(cotacao: dict, previa: dict[int, dict[str, str]], erros: list[str],
            avisos: list[str], obs_geral: str = "") -> Revisao:
    """Chama a IA. Nunca levanta: qualquer falha vira Revisao(erro=...)."""
    if not ia.configurada():
        return Revisao(erro="falta GROQ_API_KEY ou OPENROUTER_API_KEY no .env")
    try:
        r = ia.completar_json(SISTEMA, montar_pedido(cotacao, previa, erros, avisos, obs_geral),
                              ESQUEMA, funcao="revisão ME", validar=_alertas)
    except ia.IAIndisponivel as exc:
        return Revisao(erro=str(exc)[:500])
    except Exception as exc:   # defeito inesperado: a revisão nunca derruba a tela
        return Revisao(erro=f"{type(exc).__name__}: {exc}"[:300])
    return Revisao(alertas=r.dados, modelo=r.modelo)
