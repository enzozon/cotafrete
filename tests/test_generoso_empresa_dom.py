"""A troca de empresa no portal da Generoso, contra o DOM real.

tests/fixtures/generoso_empresas.html foi GERADO por
recon/recon_generoso_empresa.py a partir de cliente.generoso.com.br em
25/08/2026. O menu e um dropdown do Radix: nao existe no DOM ate o clique
no gatilho, e o `id` do gatilho e gerado por render.

O detalhe que mais importa aqui: o menu tem QUATRO itens, e o quarto e
"Adicionar empresa". Escolher por posicao abriria o cadastro de uma empresa
nova no portal do cliente.

Roda por file:// — nao sobe servidor e nao toca a rede.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carriers.generoso.adapter import GenerosoAdapter
from carriers.generoso.mapping import EMPRESAS, empresa_de

FIXTURE = (Path(__file__).parent / "fixtures" / "generoso_empresas.html").resolve()

VENTURA = empresa_de("08.310.365/0001-24")
ALIANCA = empresa_de("05.954.058/0001-98")
UNIAO = empresa_de("20.837.281/0001-49")


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


@pytest.mark.parametrize("empresa", [VENTURA, ALIANCA],
                         ids=lambda e: e.nome)
def test_escolhe_a_empresa_pelo_cnpj(page, empresa):
    GenerosoAdapter()._escolher_empresa(page, empresa)

    escolhido = page.evaluate("() => window.__escolhido || ''")
    assert empresa.cnpj in escolhido


def test_empresa_ja_selecionada_nao_e_clicada(page):
    """Na captura de 25/08/2026 a conta estava na Uniao, e o Radix marca o
    item ativo como desabilitado.

    Isso e SUCESSO, nao falha — e o caso mais comum, porque a conta abre na
    empresa que cotou por ultimo. Insistir no clique custava um TimeoutError
    de 4s em toda cotacao que ja estivesse na empresa certa."""
    GenerosoAdapter()._escolher_empresa(page, UNIAO)

    # Só o que a fixture modela: nenhum item foi clicado. O fechamento pelo
    # Escape é do Radix de verdade, e não está reproduzido aqui.
    assert page.evaluate("() => window.__escolhido || ''") == ""


def test_nunca_clica_em_adicionar_empresa(page):
    """O quarto item cadastra empresa nova no portal do cliente. Nenhuma
    escolha pode chegar nele — nem quando o CNPJ procurado nao esta no menu."""
    for empresa in EMPRESAS:
        page.goto(FIXTURE.as_uri(), wait_until="load")
        try:
            GenerosoAdapter()._escolher_empresa(page, empresa)
        except RuntimeError:
            pass
        assert "Adicionar" not in page.evaluate("() => window.__escolhido || ''")


def test_empresa_fora_do_menu_falha_alto(page):
    """Se o CNPJ nao estiver no menu, seguir em silencio cotaria com a
    empresa errada — e cotacao sai com CNPJ no papel. Melhor parar."""
    from carriers.generoso.mapping import Empresa

    with pytest.raises(RuntimeError, match="99.999.999"):
        GenerosoAdapter()._escolher_empresa(
            page, Empresa("99.999.999/0001-99", "Inexistente"))

    assert page.evaluate("() => window.__escolhido || ''") == ""


def test_sem_alvo_nao_mexe_no_menu(page):
    """empresa=None e o caso de quem nao tem empresa do grupo na ponta
    travada: deixa como esta, sem nem abrir o menu."""
    GenerosoAdapter()._escolher_empresa(page, None)

    assert page.evaluate("() => window.__escolhido || ''") == ""
    assert page.locator('[data-slot="dropdown-menu-item"]').count() == 0
