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

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao, esperar_estabilidade,
    print_seguro,
    recusa_por_validacao,
)
from carriers.jadlog import mapping as m
from core.models import CotacaoRequest, StatusCotacao, limpa_doc

URL_SIMULADOR = "https://www.jadlog.com.br/siteInstitucional/simulacao.jad"

FRETE_A_PAGAR_SIM = "S"
FRETE_A_PAGAR_NAO = "N"

RE_VALOR = re.compile(r"R\$\s*([\d.]+,\d{2}|[\d,]+\.\d{2}|\d+[.,]\d{2})")

# "CEP nao atendido" (sem acento, como o site escreve), "CEP não atendido",
# "Localidade não atendida". Resposta comercial legítima — a Jadlog não roda
# aquela rota nessa modalidade. Nunca vira R$.
RE_SEM_COBERTURA = re.compile(r"n[ãa]o\s+atendid", re.IGNORECASE)


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


def _linha_da_recusa(texto: str) -> str:
    """A linha que explica a recusa, sem o disclaimer de rodapé junto."""
    for linha in texto.splitlines():
        if RE_SEM_COBERTURA.search(linha):
            return linha.strip()
    return texto.strip()[:120]


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
        if valor is not None:
            return ResultadoCotacao(
                transportadora=self.slug,
                status=StatusCotacao.COTADO,
                valor_frete=valor,
                prazo_dias=None,      # o simulador não informa prazo
                raw_response=texto[:500],
            )

        # Sem valor: separar "a Jadlog disse não" de "algo quebrou". Os dois
        # chegavam aqui como ERRO, e o operador ia caçar bug numa rota que a
        # transportadora simplesmente não atende.
        if RE_SEM_COBERTURA.search(texto):
            return ResultadoCotacao(
                transportadora=self.slug,
                status=StatusCotacao.RECUSADO,
                motivo_recusa=_linha_da_recusa(texto),
                raw_response=texto[:500],
            )

        return ResultadoCotacao(
            self.slug, StatusCotacao.ERRO, raw_response=texto[:500],
            erro="Simulador não devolveu valor reconhecível.")

    # ------------------------------------------------------------- mecânica
    @staticmethod
    def _texto_painel(page) -> str:
        """Texto do painel de resultado, '' se ainda não existe/está oculto."""
        painel = page.locator("#panel_resultado")
        return painel.inner_text().strip() if painel.count() else ""

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
            return recusa_por_validacao(self.slug, erros)

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
                antes = self._texto_painel(page)
                page.locator('input[value="Simular"]').first.click()

                # Espera o painel MUDAR, não o "R$" aparecer. "CEP nao atendido"
                # é resposta válida e nunca vira R$: esperar por valor gastava os
                # 45s de timeout e devolvia TimeoutError, escondendo o motivo.
                # O JSF SUBSTITUI o elemento no partial update, então a espera
                # re-consulta o DOM a cada poll — um element_handle capturado
                # antes do clique aponta para um nó desanexado, que nunca muda.
                page.wait_for_function(
                    "antes => { const el = document.getElementById('panel_resultado');"
                    " if (!el) return false;"
                    " const t = el.innerText.trim();"
                    " return t.length > 0 && t !== antes; }",
                    arg=antes, timeout=self.timeout_ms)

                painel = page.locator("#panel_resultado")
                painel.scroll_into_view_if_needed()

                # O JSF acabou de trocar o painel e o PrimeFaces ainda anima a
                # entrada dele. Fotografar aqui sai com o valor deslocado ou o
                # painel em branco. Ler o texto também tem que ser DEPOIS: no
                # meio da animação ele vem incompleto.
                estavel = esperar_estabilidade(page, "#panel_resultado")
                texto = painel.inner_text()

                res = self.normalizar_resposta(texto)
                if not estavel:
                    res.erro = ("Painel não parou de mudar antes do print — "
                                "confira a evidência antes de usar este valor.")
                res.enviado_em = enviado
                res.respondido_em = datetime.now()
                # Print da TELA INTEIRA, não recorte do painel. Recortar por
                # coordenada saía cortado de forma intermitente (o "R$" do valor
                # sumia): a página se mexe entre medir a caixa e capturar, e a
                # deriva medida variou de 17 a 85px entre rodadas. A tela cheia
                # não tem coordenada para errar, e ainda mostra o formulário
                # preenchido junto — dá para conferir a rota que gerou o preço.
                res.evidencias = print_seguro(page, run / "jadlog_tela.png")
                return res

            except Exception as exc:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.ERRO, enviado_em=enviado,
                    erro=f"{type(exc).__name__}: {exc}",
                    evidencias=print_seguro(page, run / "jadlog_erro.png"))
            finally:
                browser.close()
