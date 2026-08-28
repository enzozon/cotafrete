"""Como o navegador da Generoso precisa se apresentar para o site abrir.

Em 28/08/2026, entre a cotação #55 (08:42, cotou R$ 686,91) e a #57 (10:25),
o portal da Generoso passou a responder com o **checkpoint de segurança da
Vercel**: uma tela branca escrita "Falha ao verificar seu navegador — Código
21", com o rodapé "Ponto de verificação de segurança da Vercel | gru1::…".
A página de login nunca chegava a existir, e o adapter morria esperando
`input[name="email"]` por 45s.

Matriz medida naquele dia, contra a página de login real:

    headless (o que rodava)          webdriver=true   HeadlessChrome  BLOQUEADO 21
    headed fora da tela              webdriver=true   Chrome          BLOQUEADO 21
    headless + flag                  webdriver=false  HeadlessChrome  BLOQUEADO 29
    headed fora da tela + flag       webdriver=false  Chrome          PASSOU 4,9s
    Chrome de verdade + flag         webdriver=false  Chrome          PASSOU 5,0s

As duas marcas precisam sair JUNTAS — consertar uma só troca o código do erro.
Por isso o teste olha as duas no navegador de verdade, e não a lista de
argumentos: argumento certo com efeito nenhum passaria despercebido, que é
exatamente como este bug chegou à produção.

Nada aqui vai à rede. Sobe o navegador com a configuração real e pergunta a
ele quem ele diz que é.
"""

from __future__ import annotations

import pytest

from carriers.dellavolpe.adapter import argumentos_do_navegador
from carriers.generoso.adapter import GenerosoAdapter


@pytest.fixture
def playwright():
    mod = pytest.importorskip("playwright.sync_api")
    with mod.sync_playwright() as p:
        yield p


def _identidade(p, **launch) -> dict:
    """Quem o navegador diz que é, numa página em branco."""
    browser = p.chromium.launch(**launch)
    try:
        page = browser.new_context(locale="pt-BR").new_page()
        page.goto("about:blank")
        return {"webdriver": page.evaluate("() => navigator.webdriver"),
                "ua": page.evaluate("() => navigator.userAgent")}
    finally:
        browser.close()


# ------------------------------------------------------------------ o bug #57
def test_o_navegador_da_generoso_nao_se_anuncia_como_robo(playwright):
    """As duas marcas que o checkpoint da Vercel lê, nas condições reais."""
    quem = _identidade(playwright, **GenerosoAdapter().opcoes_do_navegador())

    assert quem["webdriver"] is False, (
        "navigator.webdriver=true é a marca de automação — foi o que sobrou "
        "denunciando quando só a janela foi consertada (Código 29)")
    assert "Headless" not in quem["ua"], (
        f"o User-Agent entrega o robô sozinho: {quem['ua']}")


def test_a_janela_fica_fora_de_qualquer_monitor(playwright):
    """Janela de verdade, sim; na frente do vendedor, não.

    É o mesmo -3000 da Della Volpe: maior que qualquer monitor comum."""
    args = GenerosoAdapter().opcoes_do_navegador()["args"]

    assert any("--window-position=-3000,-3000" in a for a in args)


# ------------------------------- as duas headed ao mesmo tempo (pedido do Enzo)
def test_generoso_e_dellavolpe_sobem_juntas_sem_atrapalhar(playwright):
    """Duas janelas headed ao mesmo tempo — o caso real de produção.

    Passaram a ser DUAS transportadoras com janela de verdade, e o semáforo
    tem exatamente 2 vagas de navegador: elas vão cair juntas. Cada Chromium
    tem seu próprio perfil temporário, então não deveriam disputar nada — mas
    "não deveriam" não é medição.

    A Della Volpe entra só com a configuração de navegador dela. Rodar o
    `cotar()` dela aqui mandaria uma cotação de verdade para a mesa de um
    vendedor."""
    gen = GenerosoAdapter().opcoes_do_navegador()
    dv = {"headless": False,
          "args": argumentos_do_navegador(headless=False, mostrar_janela=False)}

    g = playwright.chromium.launch(**gen)
    d = playwright.chromium.launch(**dv)
    try:
        pg = g.new_context(locale="pt-BR").new_page()
        pd = d.new_context(locale="pt-BR").new_page()
        pg.goto("about:blank")
        pd.goto("about:blank")

        # As duas vivas e respondendo, com a janela uma da outra aberta.
        assert pg.evaluate("() => 1 + 1") == 2
        assert pd.evaluate("() => 1 + 1") == 2
        assert pg.evaluate("() => navigator.webdriver") is False
        assert "Headless" not in pd.evaluate("() => navigator.userAgent")
    finally:
        g.close()
        d.close()
