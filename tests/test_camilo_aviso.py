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
    lidos, evidencias = CamiloAdapter()._ler_e_fotografar(page, tmp_path)

    assert lidos["aviso"] == FRASE
    assert [Path(x).name for x in evidencias] == ["recusa_do_site.png"]
    assert page.locator("#errormsg").is_visible(), \
        "o popup precisa continuar na tela — e a prova de que a foto o pegou"


def test_sem_recusa_a_foto_continua_sendo_a_do_resultado(page, tmp_path):
    """Cotacao que deu certo nao muda de nome de arquivo nem de comportamento."""
    from carriers.camilo.adapter import CamiloAdapter

    lidos, evidencias = CamiloAdapter()._ler_e_fotografar(page, tmp_path)

    assert lidos["aviso"] == ""
    assert [Path(x).name for x in evidencias] == ["resultado.png"]


# --------------- o popup do SSW tambem diz que deu CERTO
def test_popup_de_sucesso_nao_e_recusa():
    """Cotacoes #27, #28 e #29 de producao (25/08/2026).

    A Camilo devolveu preco 117,91 com protocolo E abriu "Operacao realizada
    com sucesso" na mesma caixa `#errormsg` que usa para recusar. Como eu
    decidia "e recusa" pela PRESENCA do popup, a foto saiu com ele tapando a
    composicao do preco — Frete Valor, Despacho, TDE, Pedagio e a Cubagem
    ficaram escondidos — e ainda foi salva como `recusa_do_site.png`.

    O preco nunca se perdeu (`normalizar_resposta` so olha o aviso quando
    valor e None), mas a evidencia que chega ao vendedor e ao cliente saia
    inutilizada."""
    from carriers.camilo.adapter import e_recusa

    assert e_recusa("Cliente não possui tabela de frete negociada.") is True
    assert e_recusa("Operação realizada com sucesso") is False
    assert e_recusa("OPERAÇÃO REALIZADA COM SUCESSO") is False
    assert e_recusa("") is False
    assert e_recusa(None) is False


def test_com_preco_a_foto_e_a_da_tela_limpa(page, tmp_path):
    """Deu certo: o popup sai da frente antes da foto, e o arquivo volta a
    se chamar resultado.png."""
    from carriers.camilo.adapter import CamiloAdapter

    page.evaluate("preencherPreco()")
    page.evaluate("mostrarSucesso()")
    lidos, evidencias = CamiloAdapter()._ler_e_fotografar(page, tmp_path)

    assert [Path(x).name for x in evidencias] == ["resultado.png"]
    assert lidos["vlr_frete"] == "117,91"
    assert lidos["nro_cotacao"] == "2812827"
    assert lidos["aviso"] == "", "sucesso nao pode virar motivo de recusa"


def test_preco_com_popup_de_recusa_e_recusa_mesmo_assim(page, tmp_path):
    """O bug real, da cotacao #38 (31/08/2026): o SSW calcula um valor no
    campo vlr_frete ANTES de aplicar a recusa por regra de negocio. "Havendo
    preco, popup nenhum transforma em recusa" (o que este teste garantia
    antes) e exatamente a suposicao que mandou 203,32 pro vendedor como se
    fosse uma cotacao fechada numa cidade que a Camilo nem atende.

    O aviso manda, nao o campo de preco: com popup de recusa, a foto e a
    do popup e o preco lido nao pode ser usado."""
    from carriers.camilo.adapter import CamiloAdapter
    from core.models import StatusCotacao

    page.evaluate("preencherPreco()")
    page.evaluate("mostrarAviso()")
    lidos, evidencias = CamiloAdapter()._ler_e_fotografar(page, tmp_path)

    assert [Path(x).name for x in evidencias] == ["recusa_do_site.png"]
    assert lidos["vlr_frete"] == "", \
        "preco calculado atras de um popup de recusa nao pode ser usado"
    assert CamiloAdapter().normalizar_resposta(lidos).status \
        is StatusCotacao.RECUSADO
    assert page.locator("#errormsg").is_visible(), \
        "a foto tem que pegar o popup, nao a tela com o preco limpo"


def test_cotacao_38_cidade_nao_atendida_com_preco_calculado(page, tmp_path):
    """Reproducao direta da cotacao #38: "CIDADE NAO ATENDIDA PARA COLETA -
    CONSULTAR TRANSPORTADORA" com R$ 203,32 ja calculado por tras do popup
    (print anexado pelo Enzo, 31/08/2026).

    Prova o que o vendedor precisa ver: o motivo da recusa, no lugar do
    preco que nao serve pra nada — aquela cidade nao entra na coleta."""
    from carriers.camilo.adapter import CamiloAdapter
    from core.models import StatusCotacao

    page.evaluate("preencherPreco()")
    page.evaluate("mostrarAvisoCidadeNaoAtendida()")
    lidos, evidencias = CamiloAdapter()._ler_e_fotografar(page, tmp_path)
    resultado = CamiloAdapter().normalizar_resposta(lidos)

    assert [Path(x).name for x in evidencias] == ["recusa_do_site.png"], \
        "tem que mostrar a print do erro, nao do resultado"
    assert resultado.status is StatusCotacao.RECUSADO
    assert "CIDADE" in (resultado.motivo_recusa or "").upper()
    assert "NÃO ATENDIDA" in (resultado.motivo_recusa or "").upper()


# ------------------------ recusa ANTES da cubagem (cgc_rem/cgc_dest novos)
def test_destinatario_nao_cadastrado_e_detectado_antes_da_cubagem(page):
    """Reproducao direta do que aconteceu ao preencher CNPJ remet/destin pela
    primeira vez (01/09/2026): o SSW valida o destinatario e avisa NESTE
    ponto, antes de existir Cubagem — sem esta checagem o popup intercepta o
    clique em Cubagem e o adapter estourava TimeoutError."""
    from carriers.camilo.adapter import CamiloAdapter

    page.evaluate("mostrarAvisoDestinatarioNaoCadastrado()")

    aviso = CamiloAdapter()._recusa_antes_da_cubagem(page)

    assert "DESTINATÁRIO" in aviso.upper()
    assert "NÃO CADASTRADO" in aviso.upper()


def test_sem_aviso_libera_seguir_para_a_cubagem(page):
    """Caminho normal: nenhum popup, string vazia, quem chama continua."""
    from carriers.camilo.adapter import CamiloAdapter

    assert CamiloAdapter()._recusa_antes_da_cubagem(page) == ""


def test_aviso_de_sucesso_nao_bloqueia_a_cubagem(page):
    """A mesma caixa do SSW tambem confirma sucesso — isso nao pode virar
    recusa antecipada (o caso das cotacoes #27-29, ja coberto em
    test_popup_de_sucesso_nao_e_recusa, mas agora no momento ANTES da
    cubagem tambem)."""
    from carriers.camilo.adapter import CamiloAdapter

    page.evaluate("mostrarSucesso()")

    assert CamiloAdapter()._recusa_antes_da_cubagem(page) == ""


def test_sem_preco_e_com_recusa_continua_fotografando_o_popup(page, tmp_path):
    """O caso da #20 nao pode ter regredido."""
    from carriers.camilo.adapter import CamiloAdapter

    page.evaluate("mostrarAviso()")
    lidos, evidencias = CamiloAdapter()._ler_e_fotografar(page, tmp_path)

    assert [Path(x).name for x in evidencias] == ["recusa_do_site.png"]
    assert "tabela de frete negociada" in lidos["aviso"]
    assert page.locator("#errormsg").is_visible()


def test_sem_preco_e_com_popup_de_sucesso_nao_inventa_recusa(page, tmp_path):
    """A corrida: o popup aparece antes de o campo de preco encher.

    Sem esta guarda o vendedor leria "A Camilo nao cotou: Operacao realizada
    com sucesso", que nao quer dizer nada."""
    from carriers.camilo.adapter import CamiloAdapter

    page.evaluate("mostrarSucesso()")
    lidos, evidencias = CamiloAdapter()._ler_e_fotografar(page, tmp_path)

    assert lidos["aviso"] == ""
    assert [Path(x).name for x in evidencias] == ["resultado.png"]
