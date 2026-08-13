"""Jadlog — calculadora do PAINEL, com login.

    https://jadlogentregas.com.br/login -> /painel -> /painel/calculadora

Substitui o simulador público (simulador.py), que a Jadlog descontinuou.

⚠ Este é o produto **Jadlog Entregas**: etiqueta pré-paga, pacote a pacote,
para e-commerce. O preço é de varejo, NÃO o frete fracionado contratado. Tem
saldo, créditos e limite de envios na conta.

⚠ A calculadora cota UM pacote. A ficha do Enzo pode ter N volumes iguais, e
a regra combinada é: N cálculos separados, um por volume. Somar os N dá o
total; cada resultado vem com o próprio print.

Credenciais no .env (JADLOG_PAINEL_USUARIO / JADLOG_PAINEL_SENHA). Nunca são
impressas nem gravadas nas evidências.

A ordem dos campos de medida é **Altura, Largura, Comprimento** — diferente do
simulador antigo (Larg., Altura, Comprimento). Os campos não têm name nem id,
então o casamento é pelo rótulo, nunca por posição.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao, print_seguro,
)
from carriers.jadlog import mapping as m
from core.models import CotacaoRequest, StatusCotacao, limpa_doc

URL_LOGIN = "https://jadlogentregas.com.br/login"
URL_CALCULADORA = "https://jadlogentregas.com.br/painel/calculadora"

# Rótulo exato ao lado de cada campo, medido no recon de 13/08/2026.
ROTULO_ALTURA = "Altura (cm)"
ROTULO_LARGURA = "Largura (cm)"
ROTULO_COMPRIMENTO = "Comprimento (cm)"

RE_VALOR = re.compile(r"R\$\s*([\d.]+,\d{2}|\d+,\d{2})")


@dataclass
class Opcao:
    """Uma linha da tabela de resultado."""
    modalidade: str
    prazo: str
    valor: Decimal


def _num_br(txt: str) -> Decimal | None:
    t = txt.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except Exception:
        return None


def ler_opcoes(texto: str) -> list[Opcao]:
    """Tabela de resultado -> lista de opções.

    Formato medido: uma linha por modalidade, com transportadora, modalidade,
    balcão, prazo, valor e o botão Comprar. Ex.:
        jadlog  Express   2-3 dias   R$ 55,12   Comprar
        jadlog  Standard  3-4 dias   R$ 33,56   Comprar
    """
    opcoes: list[Opcao] = []
    for linha in texto.splitlines():
        achado = RE_VALOR.search(linha)
        if not achado:
            continue
        valor = _num_br(achado.group(1))
        if valor is None:
            continue

        # Uma linha de opção tem prazo E botão Comprar. O cabeçalho traz
        # "Valor do Produto: R$ 586,77" — sem isso ele virava a opção mais
        # barata e a cotação devolvia o valor da MERCADORIA como frete.
        prazo_achado = re.search(r"(\d+\s*-\s*\d+\s*dias?|\d+\s*dias?)", linha)
        if not prazo_achado and "comprar" not in linha.lower():
            continue

        antes = linha[:achado.start()]
        prazo = ""
        if p := re.search(r"(\d+\s*-\s*\d+\s*dias?|\d+\s*dias?)", antes):
            prazo = p.group(1).strip()
            antes = antes[:p.start()]
        modalidade = " ".join(antes.replace("jadlog", "").split())
        opcoes.append(Opcao(modalidade=modalidade or "?", prazo=prazo,
                            valor=valor))
    return opcoes


class JadlogPainelAdapter:
    slug = "jadlog_painel"
    nome = "Jadlog Entregas (calculadora do painel)"
    modo: Modo = Modo.SINCRONO
    ativo = True
    fator_cubagem: Decimal = m.FATOR_CUBAGEM
    sla_esperado_min: int | None = None

    def __init__(self, headless: bool = True, timeout_ms: int = 45_000,
                 workdir: str = "teste_real/jadlog") -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.workdir = Path(workdir)

    # ------------------------------------------------ delegações à camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return m.campos_obrigatorios(req)

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        return m.validar(req)

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        """Campos da calculadora — peso de UM volume, não o total.

        A calculadora cota um pacote de cada vez; a soma dos N volumes é feita
        por quem chama, com N chamadas. Mandar o peso total aqui cotaria uma
        caixa pesada com as medidas de uma caixa só."""
        v = req.volumes[0]
        return {
            "cep_origem": limpa_doc(req.origem.cep or ""),
            "cep_destino": limpa_doc(req.destino.cep or ""),
            "valor": f"{req.nota_fiscal.valor_total:.2f}".replace(".", ","),
            "peso": f"{v.peso_kg.normalize():f}".replace(".", ","),
            ROTULO_ALTURA: f"{v.altura_cm.normalize():f}",
            ROTULO_LARGURA: f"{v.largura_cm.normalize():f}",
            ROTULO_COMPRIMENTO: f"{v.comprimento_cm.normalize():f}",
        }

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        """`raw` é o texto da tela de resultado."""
        texto = str(raw or "")
        opcoes = ler_opcoes(texto)
        if not opcoes:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO, raw_response=texto[:800],
                erro="Calculadora não devolveu nenhuma opção com valor.")

        barata = min(opcoes, key=lambda o: o.valor)
        return ResultadoCotacao(
            transportadora=self.slug,
            status=StatusCotacao.COTADO,
            valor_frete=barata.valor,
            prazo_dias=None,          # o painel dá faixa ("2-3 dias"), não número
            raw_response=texto[:800],
        )

    # ------------------------------------------------------------- mecânica
    def _credenciais(self) -> tuple[str, str]:
        usuario = os.getenv("JADLOG_PAINEL_USUARIO")
        senha = os.getenv("JADLOG_PAINEL_SENHA")
        if not usuario or not senha:
            raise RuntimeError(
                "Faltam JADLOG_PAINEL_USUARIO / JADLOG_PAINEL_SENHA no .env")
        return usuario, senha

    def _fechar_cookies(self, page) -> None:
        """O banner de cookies fica POR CIMA do botão Calcular Envio."""
        for texto in ("Aceitar todos os cookies", "Rejeitar Todos"):
            try:
                alvo = page.get_by_text(texto, exact=False).first
                if alvo.count() and alvo.is_visible(timeout=1500):
                    alvo.click()
                    page.wait_for_timeout(600)
                    return
            except Exception:
                continue

    def _entrar(self, page) -> None:
        usuario, senha = self._credenciais()
        page.goto(URL_LOGIN, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        self._fechar_cookies(page)
        page.locator('input[type="email"]').first.fill(usuario)
        page.locator('input[type="password"]').first.fill(senha)
        page.get_by_role("button", name="Entrar").first.click()
        page.wait_for_url(lambda u: "/login" not in u, timeout=self.timeout_ms)
        page.wait_for_timeout(2500)

    def _campo_por_rotulo(self, page, rotulo: str):
        """Os campos não têm name nem id — só o rótulo os distingue.

        Casar por posição seria frágil de um jeito perigoso: a ordem aqui é
        Altura, Largura, Comprimento, ao contrário do simulador antigo. Trocar
        altura com largura numa caixa 80x60x50 muda a cubagem e o preço."""
        rotulos = page.get_by_text(rotulo, exact=False)
        for i in range(min(rotulos.count(), 5)):
            bloco = rotulos.nth(i).locator(
                "xpath=ancestor::*[self::div or self::label][1]")
            campo = bloco.locator("input").first
            if campo.count() and campo.is_visible():
                return campo
        raise RuntimeError(f"campo não encontrado pelo rótulo: {rotulo!r}")

    def _preencher(self, page, campos: dict[str, str]) -> None:
        page.get_by_placeholder("Digite o CEP de Origem").first.fill(
            campos["cep_origem"])
        page.get_by_placeholder("Digite o CEP de Destino").first.fill(
            campos["cep_destino"])

        for rotulo in (ROTULO_ALTURA, ROTULO_LARGURA, ROTULO_COMPRIMENTO):
            self._campo_por_rotulo(page, rotulo).fill(campos[rotulo])

        # valor e peso não têm placeholder; vêm com "0,00" e sufixo R$ / kg
        for sufixo, chave in (("R$", "valor"), ("kg", "peso")):
            self._campo_por_rotulo(page, sufixo).fill(campos[chave])

    # ------------------------------------------------------------------ envio
    def cotar(self, req: CotacaoRequest) -> ResultadoCotacao:
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
            page = browser.new_context(
                locale="pt-BR",
                viewport={"width": 1500, "height": 1200}).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                self._entrar(page)
                page.goto(URL_CALCULADORA, wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
                if "/login" in page.url:
                    raise RuntimeError("sessão não persistiu até a calculadora")
                self._fechar_cookies(page)

                self._preencher(page, campos)
                page.get_by_role("button", name="Calcular Envio").first.click()

                # a tabela de opções só aparece depois do cálculo
                page.wait_for_function(
                    """() => /R\\$\\s*[\\d.,]+/.test(document.body.innerText)
                             && /comprar/i.test(document.body.innerText)""",
                    timeout=self.timeout_ms)
                page.wait_for_timeout(1200)

                texto = page.locator("body").inner_text()
                res = self.normalizar_resposta(texto)
                res.enviado_em = enviado
                res.respondido_em = datetime.now()
                res.evidencias = print_seguro(page, run / "jadlog_resultado.png")
                return res

            except Exception as exc:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.ERRO, enviado_em=enviado,
                    erro=f"{type(exc).__name__}: {exc}",
                    evidencias=print_seguro(page, run / "jadlog_erro.png"))
            finally:
                browser.close()
