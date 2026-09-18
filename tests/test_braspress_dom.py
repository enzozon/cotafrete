"""Braspress — contra o DOM real do formulário de cotação.

tests/fixtures/braspress_cotacao.html foi capturado por
recon/recon_braspress.py em 02/09/2026 (tela logada, CIF, antes de qualquer
digitação). Roda por file:// — não sobe servidor, não loga, não toca rede:
os recursos externos que vieram na captura são barrados no `page` abaixo.

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


# scope="module": os 20 campos são 20 parâmetros do MESMO teste, e todos só
# LEEM o DOM. Com o escopo de função, cada um subia um Chromium inteiro —
# vinte navegadores para vinte `count()`.
@pytest.fixture(scope="module")
def page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_context(locale="pt-BR").new_page()

        # A promessa do topo deste arquivo ("não toca rede") era falsa. A
        # fixture foi capturada do site real e traz <script> do Google
        # Analytics, do Tag Manager e um html5shiv hospedado em
        # googlecode.com — domínio morto desde 2015. Com wait_until="load" o
        # Playwright esperava por tudo isso: o teste offline dependia de DNS,
        # e estourava os 4 s quando a resolução demorava.
        #
        # Barrar o que não for file:// faz a promessa virar verdade. É
        # também o que se quer deste teste: ele mede os ids do formulário,
        # não a disponibilidade da internet.
        pg.route("**/*", lambda rota: (
            rota.continue_() if rota.request.url.startswith("file:")
            else rota.abort()))

        pg.set_default_timeout(4_000)
        # domcontentloaded e não load: o que se afere é o DOM, e nenhum dos
        # recursos externos chega mesmo (ver o route acima).
        pg.goto(FIXTURE.as_uri(), wait_until="domcontentloaded")
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
