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


# ------------------------------------------- praça fora da malha, sem esperar
# O endpoint público deles responde em ~1s. O caminho completo (login,
# formulário, preenchimento) leva ~40s para chegar na MESMA resposta — e quem
# espera os 40s é o vendedor, na frente do cliente.
#
# Medido em 19/08/2026 contra o site real: Vila Velha/ES, São Bernardo/SP,
# São Paulo/SP, BH/MG, Porto Alegre/RS, Curitiba/PR e Salvador/BA respondem
# `true`; Rio Branco/AC, Macapá/AP e Fortaleza/CE respondem `false`.
import pytest as _pytest

from core.models import StatusCotacao


def _carga():
    from decimal import Decimal
    from core.models import (
        CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
        Solicitante, Volume,
    )
    return CotacaoRequest(
        solicitante=Solicitante(nome="Enzo", email="e@ex.com",
                                whatsapp="27999887766"),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf="ES", cidade="Vila Velha", cep="29105770"),
        destino=Local(uf="AC", cidade="Rio Branco", cep="69900000"),
        remetente=Parte(cnpj="05.954.058/0001-98"),
        destinatario=Parte(cnpj="60.042.686/0001-05"),
        pagador_frete=Parte(cnpj="05.954.058/0001-98"),
        volumes=[Volume(qtd=1, comprimento_cm=Decimal(30),
                        largura_cm=Decimal(30), altura_cm=Decimal(30),
                        peso_kg=Decimal(1))],
        mercadoria=Mercadoria(tipo_material="LUVA DE BOMBEIRO"),
        nota_fiscal=NotaFiscal(valor_total=Decimal("568.77")))


@_pytest.fixture
def sem_navegador(monkeypatch):
    """Faz o teste explodir se o código chegar a abrir o Chromium."""
    import playwright.sync_api

    def nao_devia(*a, **k):
        raise AssertionError("abriu o navegador — devia ter recusado antes")

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", nao_devia)


def test_cep_fora_da_malha_recusa_na_hora_sem_abrir_navegador(monkeypatch,
                                                              sem_navegador):
    adapter = TranslovatoAdapter()
    # Como no site: Vila Velha/ES é atendida, Rio Branco/AC não. Um stub que
    # recusa os dois passaria mesmo se o código só olhasse a origem.
    monkeypatch.setattr(adapter, "_cep_atendido",
                        lambda cep: "69900" not in cep)

    res = adapter.cotar(_carga())

    assert res.status is StatusCotacao.RECUSADO
    assert "69900-000" in (res.motivo_recusa or ""), "faltou dizer QUAL CEP"
    assert "destino" in (res.motivo_recusa or "").lower()


def test_na_duvida_cota_do_jeito_normal(monkeypatch):
    """Rede fora, resposta estranha, endpoint mudado: `None` significa "não
    deu para saber", e aí o certo é cotar.

    Recusar por dúvida mataria em silêncio uma cotação legítima — o robô
    diria "não atende" sobre uma praça que a Translovato atende. Perder os
    40 segundos é muito melhor que perder o frete."""
    adapter = TranslovatoAdapter()
    monkeypatch.setattr(adapter, "_cep_atendido", lambda cep: None)

    import playwright.sync_api

    def chegou_no_navegador(*a, **k):
        raise RuntimeError("SEGUIU-PARA-O-NAVEGADOR")

    monkeypatch.setattr(playwright.sync_api, "sync_playwright",
                        chegou_no_navegador)

    with _pytest.raises(RuntimeError, match="SEGUIU-PARA-O-NAVEGADOR"):
        adapter.cotar(_carga())


def test_cep_atendido_segue_para_a_cotacao(monkeypatch):
    adapter = TranslovatoAdapter()
    monkeypatch.setattr(adapter, "_cep_atendido", lambda cep: True)

    import playwright.sync_api

    def chegou_no_navegador(*a, **k):
        raise RuntimeError("SEGUIU-PARA-O-NAVEGADOR")

    monkeypatch.setattr(playwright.sync_api, "sync_playwright",
                        chegou_no_navegador)

    with _pytest.raises(RuntimeError, match="SEGUIU-PARA-O-NAVEGADOR"):
        adapter.cotar(_carga())
