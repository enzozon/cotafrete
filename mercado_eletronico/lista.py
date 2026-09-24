"""Lista de pendências do Mercado Eletrônico — camada PURA, sem navegador.

A tela "Oportunidades a Responder" do ME é montada com o JSON de
`POST api.web.mercadoe.com/supplier/transactions/v1/transactions/search`.
O robô captura esse JSON (é leitura; a trava deixa passar) e `ler_busca`
o transforma em `CotacaoPendente`.

Status (recon de 23/09/2026): o ME conhece Não Respondida, Parcialmente
Respondida, Totalmente Respondida e Recusada. Rascunho salvo continua "Não
Respondida" — "Salva no ME" é estado nosso, não do ME.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# O Brasil não tem horário de verão desde 2019: offset fixo, sem tzdata.
BRASILIA = timezone(timedelta(hours=-3), "America/Sao_Paulo")
TIPO_COTACAO = 7
URL_RESPOSTA = "https://www.me.com.br/RespostaCotaItem.asp?Cotacao={n}&SuperCleanPage="
STATUS_ENVIADA = frozenset({"Parcialmente Respondida", "Totalmente Respondida"})
STATUS_RECUSADA = "Recusada"


class RespostaInesperada(ValueError):
    """O JSON do ME mudou de formato — melhor parar do que listar errado."""


@dataclass(frozen=True)
class CotacaoPendente:
    numero: int
    empresa: str
    comprador: str
    codigo: str
    data_limite: datetime  # com fuso de Brasília
    status_resposta: str
    status_processo: str

    @property
    def link(self) -> str:
        return URL_RESPOSTA.format(n=self.numero)

    @property
    def enviada(self) -> bool:
        return self.status_resposta in STATUS_ENVIADA

    @property
    def recusada(self) -> bool:
        return self.status_resposta == STATUS_RECUSADA


def _data_utc(texto: str) -> datetime:
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(BRASILIA)
    except (AttributeError, ValueError) as exc:
        raise RespostaInesperada(f"dueDate ilegível: {texto!r}") from exc


def _cotacao(r: dict) -> CotacaoPendente:
    numero = r.get("processId")
    if not isinstance(numero, int):
        raise RespostaInesperada(f"processId ilegível: {numero!r}")
    return CotacaoPendente(
        numero=numero,
        empresa=(r.get("company") or r.get("workflow") or "").strip(),
        comprador=(r.get("customerName") or "").strip(),
        codigo=(r.get("clientCode") or r.get("summary") or "").strip(),
        data_limite=_data_utc(r.get("dueDate")),
        status_resposta=(r.get("answerStatus") or "").strip(),
        status_processo=(r.get("statusName") or "").strip(),
    )


def ler_busca(resposta: dict) -> list[CotacaoPendente]:
    """JSON da busca → cotações, da data limite mais próxima à mais distante."""
    dados = (resposta or {}).get("data") or {}
    registros = dados.get("result") or []
    cotacoes = [_cotacao(r) for r in registros if r.get("processType") == TIPO_COTACAO]
    return sorted(cotacoes, key=lambda c: c.data_limite)
