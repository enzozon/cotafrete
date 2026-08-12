"""Contrato que toda transportadora implementa."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from core.models import CotacaoRequest, StatusCotacao


class Modo(str, Enum):
    SINCRONO = "sincrono"                    # API devolve preço na resposta HTTP
    ASSINCRONO_RAPIDO = "assincrono_rapido"  # form -> e-mail automático em minutos
    ASSINCRONO_LENTO = "assincrono_lento"    # form -> vendedor humano, horas/dias


class Severidade(str, Enum):
    ERRO = "erro"
    AVISO = "aviso"


@dataclass
class ErroValidacao:
    campo: str
    mensagem: str
    severidade: Severidade = Severidade.ERRO


@dataclass
class ResultadoCotacao:
    transportadora: str
    status: StatusCotacao
    protocolo: str | None = None
    valor_frete: Decimal | None = None   # None é resposta VÁLIDA, não falha
    prazo_dias: int | None = None
    moeda: str = "BRL"
    raw_response: Any = None
    evidencias: list[str] = field(default_factory=list)
    erro: str | None = None
    enviado_em: datetime | None = None
    respondido_em: datetime | None = None


@dataclass
class CampoSpec:
    nome: str
    obrigatorio: bool
    tipo: str
    condicao: str | None = None


@runtime_checkable
class CarrierAdapter(Protocol):
    slug: str
    nome: str
    modo: Modo
    ativo: bool
    fator_cubagem: Decimal
    sla_esperado_min: int | None

    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]: ...

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]: ...

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        """Função PURA: modelo central -> campos da transportadora.
        É aqui que mora o risco de mapeamento, e é isso que os testes cobrem."""
        ...

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao: ...
