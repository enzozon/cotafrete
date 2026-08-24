"""Jadlog — camada de TRANSPORTE (HTTP).

Não tem browser. Não tem Playwright. É só um POST autenticado.
Por isso este adapter é bem menor que o da Della Volpe — quando existe API
oficial, o trabalho quase todo é mapeamento, não automação.
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao,
    recusa_por_validacao,
)
from carriers.jadlog import mapping as m
from core.models import CotacaoRequest, StatusCotacao


class TokenAusente(RuntimeError):
    pass


class JadlogAdapter:
    slug = m.SLUG
    nome = m.NOME
    modo: Modo = m.MODO
    fator_cubagem: Decimal = m.FATOR_CUBAGEM
    sla_esperado_min: int | None = m.SLA_ESPERADO_MIN

    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        conta: str | None = None,
        contrato: str | None = None,
        modalidade: str = "package",
        timeout_s: float = 20.0,
    ) -> None:
        self.token = token or os.getenv("JADLOG_TOKEN")
        self.base_url = base_url or os.getenv("JADLOG_URL") or m.URL_FRETE
        self.conta = conta or os.getenv("JADLOG_CONTA")
        self.contrato = contrato or os.getenv("JADLOG_CONTRATO")
        self.modalidade = modalidade
        self.timeout_s = timeout_s

    @property
    def ativo(self) -> bool:
        return bool(self.token)

    # ------------------------------------------------ delegações à camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return m.campos_obrigatorios(req)

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        return m.validar(req, modalidade=self.modalidade)

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        return m.preparar_payload(
            req, modalidade=self.modalidade,
            conta=self.conta, contrato=self.contrato,
            fator=self.fator_cubagem,
        )

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        return m.normalizar_resposta(raw)

    # ------------------------------------------------------------------ envio
    def cotar(self, req: CotacaoRequest) -> ResultadoCotacao:
        if not self.token:
            raise TokenAusente(
                "JADLOG_TOKEN não definido. O token é emitido pela franquia "
                "Jadlog que atende seu CNPJ, mediante contrato. Não há como "
                "cotar sem ele."
            )

        erros = m.bloqueantes(self.validar(req))
        if erros:
            return recusa_por_validacao(self.slug, erros)

        payload = self.preparar_payload(req)
        token = self.token if self.token.lower().startswith("bearer ") \
            else f"Bearer {self.token}"
        enviado = datetime.now()

        try:
            resp = httpx.post(
                self.base_url,
                json=payload,
                headers={"Content-Type": "application/json",
                         "Authorization": token},
                timeout=self.timeout_s,
            )
        except httpx.RequestError as exc:
            return ResultadoCotacao(self.slug, StatusCotacao.ERRO,
                                    erro=f"Falha de rede: {exc}",
                                    enviado_em=enviado)

        if resp.status_code in (401, 403):
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO, enviado_em=enviado,
                erro=f"HTTP {resp.status_code}: token inválido ou expirado.")
        if resp.status_code >= 400:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO, enviado_em=enviado,
                erro=f"HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            dados = resp.json()
        except ValueError:
            return ResultadoCotacao(self.slug, StatusCotacao.ERRO,
                                    raw_response=resp.text[:500],
                                    erro="Resposta não é JSON válido.",
                                    enviado_em=enviado)

        res = self.normalizar_resposta(dados)
        res.enviado_em = enviado
        res.respondido_em = datetime.now()
        return res
