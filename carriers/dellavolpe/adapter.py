"""Della Volpe — camada de BROWSER.

Separada de propósito da camada pura (mapping.py). Tudo que é decisão de negócio
mora lá; aqui só existe o mecânico de localizar campo e digitar.

Seletores por LABEL e PLACEHOLDER, nunca por XPath posicional. É o que faz a
automação sobreviver a mudança de layout do site.

    ADAPTER_BASE_URL=http://localhost:8099 python -m carriers.dellavolpe.adapter
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from carriers.base import CampoSpec, ErroValidacao, Modo, ResultadoCotacao
from carriers.dellavolpe import mapping as m
from carriers.dellavolpe.planilha import gerar_planilha_volumes
from core.models import CotacaoRequest, StatusCotacao

URL_PRODUCAO = "https://dellavolpe.com.br/#cotacao"

SINAIS_CAPTCHA = ("recaptcha", "hcaptcha", "turnstile", "cf-challenge")


class DellavolpeAdapter:
    slug = m.SLUG
    nome = m.NOME
    modo: Modo = m.MODO
    ativo = True
    fator_cubagem: Decimal = m.FATOR_CUBAGEM
    sla_esperado_min: int | None = m.SLA_ESPERADO_MIN

    def __init__(self, base_url: str | None = None, headless: bool = True,
                 timeout_ms: int = 45_000, workdir: str = "runs") -> None:
        self.base_url = base_url or os.getenv("ADAPTER_BASE_URL") or URL_PRODUCAO
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.workdir = Path(workdir)
        self.is_mock = "localhost" in self.base_url or "127.0.0.1" in self.base_url

    # ------------------------------------------------ delegações à camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return m.campos_obrigatorios(req)

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        return m.validar(req)

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        return m.preparar_payload(req)

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        return m.normalizar_resposta(raw)

    # ------------------------------------------------------------------ envio
    def cotar(self, req: CotacaoRequest, *, confirmar_envio: bool = False) -> ResultadoCotacao:
        """confirmar_envio=False faz DRY-RUN: preenche tudo e para antes do submit.

        Contra o site de produção o default é sempre dry-run. Cada envio real cai
        na fila comercial da transportadora — não é lugar de teste."""
        from playwright.sync_api import sync_playwright

        erros = m.bloqueantes(self.validar(req))
        if erros:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO,
                erro="; ".join(f"{e.campo}: {e.mensagem}" for e in erros),
            )

        if confirmar_envio and not self.is_mock:
            self._exigir_confirmacao_explicita()

        payload = self.preparar_payload(req)
        campos = m.campos_do_formulario(payload)
        run = self.workdir / datetime.now().strftime("%Y%m%d-%H%M%S")
        run.mkdir(parents=True, exist_ok=True)

        # anexo gerado a partir da lista de volumes
        anexos_planilha: list[str] = []
        if payload.get("Anexar Planilha") == ["__PLANILHA_VOLUMES__"]:
            anexos_planilha = [str(gerar_planilha_volumes(req, run / "volumes.xlsx"))]
            campos.pop("Anexar Planilha", None)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_context(locale="pt-BR").new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                page.goto(self.base_url, wait_until="networkidle")
                self._abrir_accordion(page)

                if self._tem_captcha(page):
                    page.screenshot(path=str(run / "captcha.png"), full_page=True)
                    return ResultadoCotacao(
                        self.slug, StatusCotacao.INTERVENCAO_NECESSARIA,
                        erro="Proteção anti-bot detectada. Requer ação humana.",
                        evidencias=[str(run / "captcha.png")],
                    )

                # anexos saem ANTES: input[type=file] não aceita fill()
                texto, arquivos = m.separar_anexos(campos)

                self._preencher(page, texto)

                for arq in anexos_planilha:
                    self._anexar(page, "Anexar Planilha", [arq])
                if fispq := arquivos.get("Anexar FISPQ / Licença"):
                    self._anexar(page, "Anexar FISPQ", [fispq])

                page.screenshot(path=str(run / "preenchido.png"), full_page=True)

                if not confirmar_envio:
                    return ResultadoCotacao(
                        self.slug, StatusCotacao.RASCUNHO,
                        raw_response="DRY-RUN: formulário preenchido, nada enviado.",
                        evidencias=[str(run / "preenchido.png")],
                    )

                page.get_by_role("button", name="Pedir orçamento").click()
                page.wait_for_load_state("networkidle")
                page.screenshot(path=str(run / "resposta.png"), full_page=True)

                res = self.normalizar_resposta(page.content())
                res.enviado_em = datetime.now()
                res.evidencias = [str(run / "preenchido.png"), str(run / "resposta.png")]
                return res

            except Exception as exc:
                page.screenshot(path=str(run / "erro.png"), full_page=True)
                return ResultadoCotacao(
                    self.slug, StatusCotacao.ERRO, erro=f"{type(exc).__name__}: {exc}",
                    evidencias=[str(run / "erro.png")],
                )
            finally:
                browser.close()

    # ------------------------------------------------------------- mecânica
    def _exigir_confirmacao_explicita(self) -> None:
        if os.getenv("DV_ENVIO_REAL_AUTORIZADO") != "sim":
            raise RuntimeError(
                "Envio real bloqueado. Cada submissão vira uma cotação na fila "
                "comercial da Della Volpe. Só libere com uma carga que você "
                "realmente precisa cotar: DV_ENVIO_REAL_AUTORIZADO=sim"
            )

    def _abrir_accordion(self, page) -> None:
        for texto in ("Fazer Cotação", "Faça uma Cotação", "Transporte: Carga Lotação"):
            try:
                alvo = page.get_by_text(texto, exact=False).first
                if alvo.is_visible(timeout=1500):
                    alvo.click()
                    page.wait_for_timeout(900)
            except Exception:
                continue

    def _tem_captcha(self, page) -> bool:
        html = page.content().lower()
        return any(s in html for s in SINAIS_CAPTCHA)

    def _localizar(self, page, rotulo: str):
        """Tenta label, depois placeholder, depois name — nessa ordem."""
        for tentativa in (
            lambda: page.get_by_label(rotulo, exact=False).first,
            lambda: page.get_by_placeholder(rotulo, exact=False).first,
            lambda: page.locator(f'[name*="{rotulo[:14]}" i]').first,
        ):
            try:
                loc = tentativa()
                if loc.count() and loc.is_visible(timeout=1200):
                    return loc
            except Exception:
                continue
        raise LookupError(f"campo não encontrado: {rotulo!r}")

    def _preencher(self, page, campos: dict[str, Any]) -> None:
        # UF antes de cidade: o select de cidade só popula depois do XHR
        ordem = sorted(campos, key=lambda k: ("cidade" in k.lower(), k))
        for rotulo in ordem:
            valor = campos[rotulo]
            if not isinstance(valor, str):
                continue
            loc = self._localizar(page, rotulo)
            if loc.evaluate("el => el.tagName") == "SELECT":
                if "cidade" in rotulo.lower():
                    page.wait_for_timeout(1200)  # espera o XHR das cidades
                try:
                    loc.select_option(label=valor)
                except Exception:
                    loc.select_option(value=valor)
                page.wait_for_timeout(500)
            else:
                loc.fill(valor)

    def _anexar(self, page, rotulo: str, arquivos: list[str]) -> None:
        try:
            page.get_by_label(rotulo, exact=False).first.set_input_files(arquivos)
        except Exception:
            page.locator('input[type="file"]').first.set_input_files(arquivos)
