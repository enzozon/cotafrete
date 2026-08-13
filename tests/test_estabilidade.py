"""Não fotografe uma página que ainda está se mexendo.

Medido no simulador da Jadlog em 13/08/2026: depois que o texto do resultado
aparece, o PrimeFaces ainda está animando/repintando o painel. Um print tirado
nessa janela sai com o conteúdo deslocado, ou com o painel em branco — mesmo
sendo print da tela inteira, sem recorte nenhum. O valor "R$ 363,73" some e a
linha do rodapé aparece como "resentado é estimado...".

Isso não dá para pegar medindo tamanho de arquivo nem cor de pixel: a imagem
tem conteúdo de sobra, só que o conteúdo errado.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carriers.base import esperar_estabilidade

FIXTURE_BLOQUEIO = (
    Path(__file__).parent / "fixtures" / "painel_com_bloqueio.html").as_uri()


class PaginaRoteirizada:
    """Devolve uma assinatura diferente a cada evaluate, conforme o roteiro."""

    def __init__(self, roteiro: list[str | None]) -> None:
        self.roteiro = roteiro
        self.leituras = 0
        self.esperas_ms = 0

    def evaluate(self, _js, _arg=None):
        i = min(self.leituras, len(self.roteiro) - 1)
        self.leituras += 1
        return self.roteiro[i]

    def wait_for_timeout(self, ms):
        self.esperas_ms += ms


def test_para_assim_que_duas_leituras_batem():
    """Página parada: não vale gastar segundos esperando à toa."""
    pagina = PaginaRoteirizada(["215|644|1070|182|R$ 161,53"] * 5)

    assert esperar_estabilidade(pagina, "#panel_resultado") is True
    assert pagina.leituras == 2


def test_espera_enquanto_o_painel_ainda_se_mexe():
    """O caso real: geometria mudando durante a animação do PrimeFaces."""
    pagina = PaginaRoteirizada([
        "130|644|1070|182|R$ 161,53",     # deslocado, meio da animação
        "180|644|1070|182|R$ 161,53",
        "215|644|1070|182|R$ 161,53",     # chegou no lugar
        "215|644|1070|182|R$ 161,53",
    ])

    assert esperar_estabilidade(pagina, "#panel_resultado") is True
    assert pagina.leituras == 4
    assert pagina.esperas_ms > 0


def test_texto_mudando_conta_como_instavel():
    """Geometria parada mas texto ainda chegando também estraga o print."""
    pagina = PaginaRoteirizada([
        "215|644|1070|182|",                 # painel no lugar, ainda vazio
        "215|644|1070|182|R$ 16",            # texto entrando
        "215|644|1070|182|R$ 161,53",
        "215|644|1070|182|R$ 161,53",
    ])

    assert esperar_estabilidade(pagina, "#panel_resultado") is True
    assert pagina.leituras == 4


def test_desiste_e_avisa_quando_nunca_estabiliza():
    """Devolve False em vez de travar: melhor um print suspeito, avisado,
    do que a cotação inteira presa num carrossel que nunca para."""
    pagina = PaginaRoteirizada([f"{x}|644|1070|182|R$ 161,53" for x in range(50)])

    assert esperar_estabilidade(pagina, "#panel_resultado", tentativas=6) is False
    assert pagina.leituras == 6


def test_elemento_ausente_nao_conta_como_estavel():
    """Dois `None` seguidos são elemento que não existe, não página parada."""
    pagina = PaginaRoteirizada([None] * 10)

    assert esperar_estabilidade(pagina, "#nao-existe", tentativas=4) is False


# ------------------------------------------------- contra um browser de verdade
@pytest.fixture
def navegador():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def test_overlay_de_bloqueio_impede_o_ok_mesmo_com_painel_pronto(navegador):
    """O caso que produziu o print cinza com o spinner 'Procurar...'.

    Medido na Jadlog: o painel fica com texto e geometria FINAIS aos 200ms,
    mas o .ui-blockui do PrimeFaces só sai aos ~700ms. Olhar só para o painel
    dá 'estável' no meio do bloqueio, e a foto sai da tela bloqueada."""
    page = navegador.new_context().new_page()
    page.goto(FIXTURE_BLOQUEIO)

    assert esperar_estabilidade(page, "#panel_resultado",
                                tentativas=4, intervalo_ms=50) is False


def test_some_o_bloqueio_e_a_pagina_fica_pronta(navegador):
    """Mesma página, overlay removido: aí sim pode fotografar."""
    page = navegador.new_context().new_page()
    page.goto(FIXTURE_BLOQUEIO)
    page.evaluate("() => document.getElementById('bloqueio').remove()")

    assert esperar_estabilidade(page, "#panel_resultado",
                                tentativas=6, intervalo_ms=50) is True
