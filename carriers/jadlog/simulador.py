"""Jadlog — simulador PÚBLICO, via browser. Não precisa de token.

Caminho alternativo ao adapter.py (API REST /embarcador, que exige token de
contrato). O simulador devolve preço na hora, de graça, e serve para comparar
enquanto o contrato não sai.

    https://www.jadlog.com.br/siteInstitucional/simulacao.jad

⚠ A URL divulgada (/jadlog/simulacao) é um wrapper: o POST nela devolve
ViewExpiredException porque a view JSF está registrada na canônica acima.

⚠ Preço de tabela/balcão, NÃO o preço contratado. E o simulador não devolve
prazo — só valor.

Diferença crítica em relação ao adapter.py: aqui NÃO se manda peso cubado.
O simulador recebe as dimensões e faz a cubagem por conta própria; mandar o
peso já cubado junto das medidas contaria cubagem duas vezes e inflaria o
frete. A regra max(real, cubado) vale para a API REST, que não recebe medidas.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from carriers.base import CampoSpec, ErroValidacao, Modo, ResultadoCotacao
from carriers.jadlog import mapping as m
from core.models import CotacaoRequest, StatusCotacao, limpa_doc

URL_SIMULADOR = "https://www.jadlog.com.br/siteInstitucional/simulacao.jad"

FRETE_A_PAGAR_SIM = "S"
FRETE_A_PAGAR_NAO = "N"

RE_VALOR = re.compile(r"R\$\s*([\d.]+,\d{2}|[\d,]+\.\d{2}|\d+[.,]\d{2})")


def _num_br_para_decimal(txt: str) -> Decimal | None:
    """'1.234,56' e '118.09' viram Decimal. O site mistura os dois formatos."""
    t = txt.strip()
    if "," in t and "." in t:                 # 1.234,56 -> milhar + decimal BR
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:                            # 118,09
        t = t.replace(",", ".")
    try:
        return Decimal(t)
    except Exception:
        return None


class JadlogSimuladorAdapter:
    slug = "jadlog_simulador"
    nome = "Jadlog (simulador público)"
    modo: Modo = Modo.SINCRONO
    ativo = True
    fator_cubagem: Decimal = m.FATOR_CUBAGEM
    sla_esperado_min: int | None = None

    def __init__(self, base_url: str | None = None, headless: bool = True,
                 timeout_ms: int = 45_000, workdir: str = "runs",
                 modalidade: str = "expresso") -> None:
        self.base_url = base_url or URL_SIMULADOR
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.workdir = Path(workdir)
        self.modalidade = modalidade

    # ------------------------------------------------ delegações à camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return m.campos_obrigatorios(req)

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        return m.validar(req, modalidade=self.modalidade)

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        """Campos do FORMULÁRIO do simulador — peso REAL, não cubado."""
        mv = req.maior_volume
        return {
            "origem": limpa_doc(req.origem.cep or ""),
            "destino": limpa_doc(req.destino.cep or ""),
            "peso": f"{req.peso_total_kg.normalize():f}",
            "valor_mercadoria": f"{req.nota_fiscal.valor_total:.2f}".replace(".", ","),
            "valor_coleta": "0,00",
            "valLargura": f"{mv.largura_cm.normalize():f}",
            "valAltura": f"{mv.altura_cm.normalize():f}",
            "valComprimento": f"{mv.comprimento_cm.normalize():f}",
        }

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        """`raw` é o texto do painel de resultado."""
        texto = str(raw or "")
        achado = RE_VALOR.search(texto)
        valor = _num_br_para_decimal(achado.group(1)) if achado else None
        if valor is None:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO, raw_response=texto[:500],
                erro="Simulador não devolveu valor reconhecível.")
        return ResultadoCotacao(
            transportadora=self.slug,
            status=StatusCotacao.COTADO,
            valor_frete=valor,
            prazo_dias=None,          # o simulador não informa prazo
            raw_response=texto[:500],
        )

    # ------------------------------------------------------------- mecânica
    def _preencher_conferindo(self, page, form, campos: dict[str, str],
                              tentativas: int = 3) -> None:
        """Preenche e CONFERE, porque o JSF apaga campo em partial update.

        O campo tem máscara (29065560 -> '29065-560'), então a conferência
        compara só os dígitos. Sem isso um CEP some em silêncio e a simulação
        volta com erro genérico — ou pior, com valor de outra rota."""
        so_digitos = lambda s: "".join(c for c in s if c.isdigit())
        for _ in range(tentativas):
            faltando = []
            for nome, valor in campos.items():
                campo = form.locator(f'[name="{nome}"]').first
                if so_digitos(campo.input_value()) != so_digitos(valor):
                    campo.fill(valor)
                    faltando.append(nome)
            if not faltando:
                return
            page.wait_for_timeout(500)
        pendentes = [n for n, v in campos.items()
                     if so_digitos(form.locator(f'[name="{n}"]').first.input_value())
                     != so_digitos(v)]
        if pendentes:
            raise RuntimeError(f"campos não fixaram no formulário: {pendentes}")

    # ------------------------------------------------------------------ envio
    def cotar(self, req: CotacaoRequest, *,
              frete_a_pagar: bool = False) -> ResultadoCotacao:
        from playwright.sync_api import sync_playwright

        erros = m.bloqueantes(self.validar(req))
        if erros:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO,
                erro="; ".join(f"{e.campo}: {e.mensagem}" for e in erros))

        campos = self.preparar_payload(req)
        run = self.workdir / datetime.now().strftime("%Y%m%d-%H%M%S")
        run.mkdir(parents=True, exist_ok=True)
        enviado = datetime.now()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            # viewport largo: em 1280 o painel de resultado renderiza cortado
            page = browser.new_context(
                locale="pt-BR", viewport={"width": 1500, "height": 1000}).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                page.goto(self.base_url, wait_until="domcontentloaded")
                page.wait_for_selector("#form_precifica")
                form = page.locator("#form_precifica")

                # Selects e radio ANTES do texto: cada um dispara um partial
                # update do JSF que re-renderiza o form e limpa campos já
                # digitados (o CEP de origem era o que mais sofria).
                form.locator('[name="modalidade"]').first.select_option(
                    str(m.MODALIDADES[self.modalidade]))
                form.locator('[name="entrega"]').first.select_option(
                    m.TP_ENTREGA_DOMICILIO)
                form.locator(
                    f'[name="selectFrete"][value='
                    f'"{FRETE_A_PAGAR_SIM if frete_a_pagar else FRETE_A_PAGAR_NAO}"]'
                ).first.check()
                page.wait_for_timeout(400)

                self._preencher_conferindo(page, form, campos)
                page.locator('input[value="Simular"]').first.click()

                # O painel só ganha valor depois do POST JSF — e o JSF SUBSTITUI
                # o elemento no partial update. Por isso a espera re-consulta o
                # DOM a cada poll: um element_handle capturado antes do clique
                # aponta para um nó desanexado, que nunca muda.
                page.wait_for_function(
                    "() => { const el = document.getElementById('panel_resultado');"
                    " return el && /R\\$\\s*[\\d.,]+/.test(el.innerText); }",
                    timeout=self.timeout_ms)

                painel = page.locator("#panel_resultado")
                texto = painel.inner_text()

                # o painel acabou de ser trocado pelo JSF: sem rolar até ele e
                # dar um respiro, o print sai cinza, antes da pintura
                painel.scroll_into_view_if_needed()
                page.wait_for_timeout(700)
                painel.screenshot(path=str(run / "jadlog_resultado.png"))
                page.screenshot(path=str(run / "jadlog_tela.png"), full_page=True)

                res = self.normalizar_resposta(texto)
                res.enviado_em = enviado
                res.respondido_em = datetime.now()
                res.evidencias = [str(run / "jadlog_resultado.png"),
                                  str(run / "jadlog_tela.png")]
                return res

            except Exception as exc:
                page.screenshot(path=str(run / "jadlog_erro.png"), full_page=True)
                return ResultadoCotacao(
                    self.slug, StatusCotacao.ERRO, enviado_em=enviado,
                    erro=f"{type(exc).__name__}: {exc}",
                    evidencias=[str(run / "jadlog_erro.png")])
            finally:
                browser.close()
