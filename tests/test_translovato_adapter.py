"""O recorte do print da Translovato — o que o vendedor manda para o cliente.

A tela cheia do portal traz menu, banner de cookies e as condições gerais; o
preço se perde no meio. O adapter recorta, e o que ele recorta é justamente o
que o cliente vai receber.

Enzo pediu em 19/08/2026 que o recorte passasse a incluir o bloco
"Identificação do volume" — produto, valor da NF, peso e a cubagem que o SITE
calculou —, não só a faixa laranja com o valor. Motivo prático: um preço
sozinho não deixa ninguém conferir SOBRE QUAL CARGA ele foi dado, e é
exatamente isso que o cliente pergunta de volta.

Testar offline, contra uma fixture, em vez de contra o portal: o site exige
login, cada simulação cria registro em "Minhas Cotações", e o recorte depende
só de geometria — que a fixture reproduz.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carriers.translovato.adapter import TranslovatoAdapter

FIXTURE = (Path(__file__).parent / "fixtures"
           / "translovato_resultado.html").as_uri()


@pytest.fixture
def navegador():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def _tamanho_png(caminho: Path) -> tuple[int, int]:
    """Largura e altura direto do cabeçalho IHDR, sem depender de Pillow."""
    dados = caminho.read_bytes()
    assert dados[:8] == b"\x89PNG\r\n\x1a\n", "não é um PNG"
    return (int.from_bytes(dados[16:20], "big"),
            int.from_bytes(dados[20:24], "big"))


def _medir(page, seletor: str) -> dict:
    return page.evaluate(
        "s => { const r = document.querySelector(s).getBoundingClientRect();"
        "       return {topo: r.top + window.scrollY,"
        "               base: r.bottom + window.scrollY}; }", seletor)


def test_print_pega_o_volume_junto_com_o_valor(navegador, tmp_path):
    """O recorte tem que ir do topo do bloco do volume até o fim da faixa.

    Antes ele começava na faixa laranja: saía o preço sem produto, sem peso e
    sem cubagem — e a primeira pergunta do cliente ("esse preço é para qual
    carga?") não tinha resposta no print."""
    page = navegador.new_context().new_page()
    page.goto(FIXTURE)

    volume = _medir(page, ".passo")
    faixa = _medir(page, ".faixa")
    altura_dos_dois = faixa["base"] - volume["topo"]

    destino = tmp_path / "resultado.png"
    caminhos = TranslovatoAdapter()._print_resultado(page, destino)

    assert caminhos == [str(destino)]
    _, altura = _tamanho_png(destino)
    # A faixa dos dois lados: cobrir os dois blocos E parar neles. Só o piso
    # não serve de teste — um print da página inteira também "cobre" tudo, e
    # foi assim que a versão antiga passou sem recortar nada.
    assert altura_dos_dois <= altura <= altura_dos_dois + 40, (
        f"o print tem {altura}px; os dois blocos ocupam "
        f"{altura_dos_dois:.0f}px. Menos que isso deixou o volume de fora; "
        f"muito mais que isso é a página inteira de novo.")


def test_print_nao_vira_a_pagina_inteira(navegador, tmp_path):
    """Recortar demais é o outro erro: a tela toda tem 1500px de cabeçalho
    antes do que interessa, e o preço some no meio."""
    page = navegador.new_context().new_page()
    page.goto(FIXTURE)

    destino = tmp_path / "resultado.png"
    TranslovatoAdapter()._print_resultado(page, destino)

    _, altura = _tamanho_png(destino)
    assert altura < 700, f"o print pegou {altura}px — é a página inteira"


def test_sem_a_faixa_de_valor_cai_no_print_da_tela(navegador, tmp_path):
    """Página sem resultado ainda tem que gerar evidência: um erro sem print
    é um erro que ninguém consegue investigar depois."""
    page = navegador.new_context().new_page()
    page.set_content("<h1>Cotação de Frete</h1><p>Preencha os campos</p>")

    destino = tmp_path / "resultado.png"
    caminhos = TranslovatoAdapter()._print_resultado(page, destino)

    assert caminhos and Path(caminhos[0]).exists()
