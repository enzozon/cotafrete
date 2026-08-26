"""O recorte do print de evidencia da Della Volpe.

tests/fixtures/dv_dois_formularios.html foi GERADO por
recon/recon_dellavolpe_formularios.py a partir da pagina real, em
26/08/2026. Nao foi digitado a mao: e a mesma disciplina de
tests/test_camilo_aviso.py, onde deduzir seletor de um print foi o bug.

O que a captura mostra: a pagina tem DOIS Contact Form 7 visiveis ao mesmo
tempo — o nosso modal de cotacao (y 725 -> 1970) e o "fale conosco" do rodape
(y 4403 -> 4877). Como o recorte era a UNIAO das caixas de TODOS os campos
visiveis, ele cobria 4150px: o formulario preenchido no topo e milhares de
pixels de pagina vazia embaixo.

Isso nao e so feio. A evidencia da Della Volpe e a unica coisa que o vendedor
tem para conferir o que foi enviado, ja que o preco so volta por e-mail — e
na tela da cotacao o cartao dela ficava tres vezes mais alto que os das
outras quatro, com a maior parte preta.

Roda por file:// — nao sobe servidor e nao toca a rede.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carriers.dellavolpe.adapter import JS_CAIXA_DO_FORMULARIO

FIXTURE = (Path(__file__).parent / "fixtures"
           / "dv_dois_formularios.html").resolve()

# Medidos no site em 26/08/2026 e gravados no cabecalho do fixture.
FORM_DA_COTACAO = (725, 1970)
FORM_DO_RODAPE = (4403, 4877)


@pytest.fixture
def page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        pg = navegador.new_context(
            locale="pt-BR", viewport={"width": 1280, "height": 2600}).new_page()
        pg.set_default_timeout(4_000)
        pg.goto(FIXTURE.as_uri(), wait_until="load")
        yield pg
        navegador.close()


def test_o_fixture_tem_mesmo_os_dois_formularios(page):
    """Se a captura perder o segundo formulario, os testes abaixo passam sem
    provar nada."""
    formularios = page.locator("form")

    assert formularios.count() >= 2


def test_o_recorte_para_no_formulario_da_cotacao(page):
    """O bug, travado.

    Antes: a caixa ia de 725 a 4877 — 4150px, dos quais 2400 de pagina
    vazia."""
    caixa = page.evaluate(JS_CAIXA_DO_FORMULARIO)

    fim = caixa["y"] + caixa["height"]
    assert fim < FORM_DO_RODAPE[0], (
        f"o recorte desceu ate {fim}px e engoliu o formulario do rodape, "
        f"que comeca em {FORM_DO_RODAPE[0]}px")


def test_o_recorte_cobre_todos_os_campos_que_preenchemos(page):
    """O outro sentido: apertar demais corta a evidencia.

    Ja aconteceu duas vezes neste arquivo de adapter — escopar por <form>
    (altura 0) e pelo ancestral com tamanho (ora metade do modal). O print
    tem que conter do primeiro campo visivel do nosso formulario ao ultimo.

    Os limites saem do DOM e nao de numeros fixos: a caixa e a uniao dos
    CAMPOS, que comeca mais abaixo que o <form> que os contem."""
    caixa = page.evaluate(JS_CAIXA_DO_FORMULARIO)
    campos = page.evaluate("""() => {
        const f = document.querySelector('form');
        const v = [...f.querySelectorAll('input, select, textarea')]
            .filter(x => (x.offsetWidth || x.offsetHeight) && x.type !== 'hidden')
            .map(x => x.getBoundingClientRect());
        return {topo: Math.min(...v.map(r => r.y + scrollY)),
                base: Math.max(...v.map(r => r.bottom + scrollY)),
                quantos: v.length};
    }""")

    assert campos["quantos"] >= 15, "o fixture perdeu campos do modal"
    assert caixa["y"] <= campos["topo"]
    assert caixa["y"] + caixa["height"] >= campos["base"]


def test_o_recorte_nao_traz_pagina_vazia_junto(page):
    """Quanto do print e formulario e quanto e fundo.

    O limite sai do DOM e nao de um numero fixo: o CSS do fixture nao e o do
    site, entao px cravado aqui mediria o fixture e nao o defeito. O que
    importa e a sobra — margem do recorte e nada mais.

    Antes: 4723px de recorte para ~1590px de campos, ou seja 3100px de
    pagina preta na evidencia."""
    caixa = page.evaluate(JS_CAIXA_DO_FORMULARIO)
    campos = page.evaluate("""() => {
        const f = document.querySelector('form');
        const v = [...f.querySelectorAll('input, select, textarea')]
            .filter(x => (x.offsetWidth || x.offsetHeight) && x.type !== 'hidden')
            .map(x => x.getBoundingClientRect());
        return Math.max(...v.map(r => r.bottom)) - Math.min(...v.map(r => r.y));
    }""")

    sobra = caixa["height"] - campos
    assert sobra <= 120, (
        f"{sobra:.0f}px de sobra em volta de {campos:.0f}px de campos — "
        f"a margem do recorte e 24px de cada lado")


def test_a_confirmacao_do_envio_continua_dentro_do_recorte(page):
    """"Agradecemos a sua mensagem" fica ABAIXO do botao, na
    .wpcf7-response-output do NOSSO formulario. E a prova de que o envio
    entrou — sem ela o print nao serve para nada.

    O fixture tem duas: a do rodape nao pode ser a que puxa o recorte."""
    page.evaluate("""() => {
        const d = document.querySelector('form .wpcf7-response-output');
        d.textContent = 'Olá Enzo Zon. Agradecemos a sua mensagem.';
        d.style.display = 'block';
    }""")

    caixa = page.evaluate(JS_CAIXA_DO_FORMULARIO)
    alvo = page.evaluate("""() => {
        const r = document.querySelector('form .wpcf7-response-output')
                          .getBoundingClientRect();
        return {y: r.y + scrollY, fim: r.bottom + scrollY};
    }""")

    assert caixa["y"] <= alvo["y"]
    assert caixa["y"] + caixa["height"] >= alvo["fim"]
