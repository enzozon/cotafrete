"""Braspress — contra o DOM real do formulário de cotação.

tests/fixtures/braspress_cotacao.html foi capturado por
recon/recon_braspress.py em 02/09/2026 (tela logada, CIF, antes de qualquer
digitação). Roda por file:// — não sobe servidor, não loga, não toca rede.

O que isto trava: se a Braspress renomear um id de campo, este teste falha
ANTES de uma cotação real sair errada — os seletores do adapter são medidos
aqui, não deduzidos.

⚠ A fixture é ESTÁTICA: não reproduz a busca de CNPJ/CEP (que depende do
backend deles). O que dá para provar offline é só que os campos que o
adapter usa continuam existindo com o `id`/`name` esperado.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE = (Path(__file__).parent / "fixtures" / "braspress_cotacao.html").resolve()

CAMPOS_ESPERADOS = (
    "modal", "tipoFrete", "cnpjRemetente", "cnpjDestinatario",
    "cepOrigem", "nomeFilialOrigem", "cepDestino", "nomeFilialDestino",
    "endereco", "volumes", "peso", "vlrMercadoria",
    "cubagem0comprimento", "cubagem0largura", "cubagem0altura",
    "cubagem0volumes", "cubagem0total", "altEmail", "btnCalcular", "btnAdd",
)


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


@pytest.mark.parametrize("campo_id", CAMPOS_ESPERADOS)
def test_campo_existe_com_o_id_esperado(page, campo_id):
    assert page.locator(f"#{campo_id}").count() == 1, (
        f"#{campo_id} sumiu do formulário da Braspress — os seletores do "
        f"adapter precisam ser remedidos.")


def test_tipo_frete_comeca_em_cif():
    """A conta abre com CIF (value="1") por padrão — é o que o adapter
    assume antes de trocar para FOB quando a ficha pede."""
    html = FIXTURE.read_text(encoding="utf-8")
    assert 'id="tipoFrete"' in html


# O auto-preenchimento do CNPJ/razão social/CEP do lado travado (CIF ->
# remetente = Ventura) é feito por JS depois do load, escrevendo em
# `.value` — isso NUNCA aparece em page.content() (HTML serializado), só no
# DOM vivo. Por isso não dá para testar contra esta fixture estática; quem
# prova esse comportamento é o dry-run contra o site real (ver
# teste_real/braspress/, screenshot preenchido.png).
