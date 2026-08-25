"""A leitura do popup de recusa do SSW, contra o DOM real.

tests/fixtures/ssw_aviso.html foi GERADO a partir de recon/recon_ssw_aviso.py,
que reproduziu a cotacao #20 de producao (25/08/2026, Arthur Carvalho) e
fotografou a tela no instante da recusa. Nao foi digitado a mao de proposito:
o bug que estes testes travam nasceu justamente de eu deduzir os seletores de
um PRINT em vez do DOM.

O que aconteceu na #20: o site recusou com "Cliente nao possui tabela de frete
negociada", o adapter FECHOU o popup (o seletor do botao OK casava) mas nao
conseguiu LER (os seletores do conteiner nao existiam nesta tela). O vendedor
recebeu "A tela nao devolveu valor de frete" — cara de defeito nosso — e o
print salvo saiu ja sem o aviso, porque a foto era tirada depois de fechar.

Roda por file:// — nao sobe servidor e nao toca a rede.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carriers.camilo.adapter import SELETORES_AVISO, _texto_do_aviso

FIXTURE = (Path(__file__).parent / "fixtures" / "ssw_aviso.html").resolve()

FRASE = "Cliente não possui tabela de frete negociada.Cotação não permitida."


@pytest.fixture
def page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_context(locale="pt-BR").new_page()
        pg.set_default_timeout(4_000)
        pg.goto(FIXTURE.as_uri(), wait_until="load")
        yield pg
        browser.close()


def test_le_a_frase_do_site_quando_o_popup_aparece(page):
    """O caso da #20. Sem isto o motivo da recusa morre na tela."""
    page.evaluate("mostrarAviso()")

    assert _texto_do_aviso(page) == FRASE


def test_nao_traz_o_enfeite_do_popup(page):
    """O SSW pendura titulo, botao de fechar e ate um "undefined" solto
    dentro da mesma caixa. Nada disso ajuda o vendedor."""
    page.evaluate("mostrarAviso()")
    texto = _texto_do_aviso(page)

    for lixo in ("Aviso", "7. OK", "undefined", "×"):
        assert lixo not in texto


def test_sem_popup_nao_inventa_aviso(page):
    """`#errormsg` EXISTE na pagina desde o inicio, escondido por
    visibility:hidden. Ler sem checar visibilidade transformaria toda
    cotacao bem-sucedida numa recusa."""
    assert _texto_do_aviso(page) == ""


def test_depois_de_fechado_volta_a_ser_silencio(page):
    """Fechar no "7. OK" esconde a caixa; o conteudo continua no DOM."""
    page.evaluate("mostrarAviso()")
    page.evaluate("showmsgonclick()")

    assert _texto_do_aviso(page) == ""


def test_os_seletores_deduzidos_de_print_nao_existem_nesta_tela(page):
    """A causa raiz, travada como teste.

    `#alerta`, `div[role=dialog]` e `.ui-dialog-content` foram deduzidos de
    uma imagem. Nenhum dos tres existe no SSW. Se alguem os reintroduzir
    achando que sao um fallback inofensivo, que ao menos veja aqui que sao
    apenas custo de timeout."""
    page.evaluate("mostrarAviso()")

    for inexistente in ("#alerta", "div[role='dialog']", ".ui-dialog-content"):
        assert page.locator(inexistente).count() == 0
        assert inexistente not in SELETORES_AVISO


# ------------------- a foto tem que pegar o popup, nao a tela ja limpa
def test_recusa_e_fotografada_antes_de_fechar(page, tmp_path):
    """O outro metade do bug da #20.

    Ate aqui a sequencia era: fechar o aviso -> fotografar. Sobrava uma tela
    vazia, sem preco e sem motivo — exatamente a imagem que o Enzo recebeu e
    que nao explicava nada. Quando ha recusa nao existe preco atras do popup
    para desobstruir, entao a foto certa e COM ele na frente."""
    from carriers.camilo.adapter import CamiloAdapter

    page.evaluate("mostrarAviso()")
    aviso, evidencias = CamiloAdapter()._ler_e_fotografar(page, tmp_path)

    assert aviso == FRASE
    assert [Path(x).name for x in evidencias] == ["recusa_do_site.png"]
    assert page.locator("#errormsg").is_visible(), \
        "o popup precisa continuar na tela — e a prova de que a foto o pegou"


def test_sem_recusa_a_foto_continua_sendo_a_do_resultado(page, tmp_path):
    """Cotacao que deu certo nao muda de nome de arquivo nem de comportamento."""
    from carriers.camilo.adapter import CamiloAdapter

    aviso, evidencias = CamiloAdapter()._ler_e_fotografar(page, tmp_path)

    assert aviso == ""
    assert [Path(x).name for x in evidencias] == ["resultado.png"]
