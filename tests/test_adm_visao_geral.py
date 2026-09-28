""""Visão geral" no menu do painel leva ao ALTO da página.

O alvo é `#topo`, o cabeçalho — e o cabeçalho é `position:sticky`. Com a
página rolada, ele está grudado no alto da tela, o navegador acha que o
alvo já está à vista e não rola nada. Nas outras telas (Contas, E-mails
Della Volpe) funcionava, porque o link abre outra página; no painel o
clique não fazia nada (24/09/2026).

Conferido num navegador de verdade: é rolagem, não dá para ver no HTML.
"""

from __future__ import annotations

import importlib
import socket
import threading
import time

import pytest

from core.banco import Banco
from tests.test_dellavolpe_ingestor import CARGA

SENHA = "senha-do-painel-de-teste"


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    import uvicorn

    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    import web.app as modulo
    importlib.reload(modulo)
    banco = Banco(tmp_path / "cotafrete.db")
    monkeypatch.setattr(modulo, "banco", banco)
    monkeypatch.setattr(modulo.adm, "banco", banco)
    # Cotação bastante para a página ter o que rolar.
    for _ in range(40):
        banco.salvar_cotacao("enzo", CARGA)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    # lifespan="off": o lifespan do app liga a varredura do ME e o leitor da
    # caixa do suporte com as senhas do .env — ME de verdade e e-mail de
    # verdade num teste, e threads que sobram atropelando os testes seguintes.
    srv = uvicorn.Server(uvicorn.Config(modulo.app, host="127.0.0.1",
                                        port=porta, log_level="error",
                                        lifespan="off"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{porta}", modulo.adm.token_de(SENHA)
    srv.should_exit = True


def _pagina(p, base, token):
    nav = p.chromium.launch()
    pg = nav.new_page(viewport={"width": 1440, "height": 700})
    pg.context.add_cookies([{"name": "cotafrete_adm", "value": token,
                             "url": base}])
    return nav, pg


def _esperar_o_alto(pg) -> int:
    # A rolagem é suave (scroll-behavior:smooth): espera ela terminar.
    for _ in range(40):
        if pg.evaluate("window.scrollY") == 0:
            break
        pg.wait_for_timeout(50)
    return pg.evaluate("window.scrollY")


def test_visao_geral_no_painel_volta_ao_alto(servidor):
    from playwright.sync_api import sync_playwright
    base, token = servidor
    with sync_playwright() as p:
        nav, pg = _pagina(p, base, token)
        pg.goto(f"{base}/adm")
        pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        pg.wait_for_timeout(300)
        assert pg.evaluate("window.scrollY") > 300, "a página não rolou"

        pg.click('.lateral a[data-secao="topo"]')

        assert _esperar_o_alto(pg) == 0
        # E o menu marca a visão geral, não o último item visto no caminho.
        pg.wait_for_timeout(300)
        assert pg.eval_on_selector_all(
            ".lateral a.atual", "as => as.map(a => a.dataset.secao)"
        ) == ["topo"]
        nav.close()


def test_as_outras_secoes_continuam_rolando_ate_elas(servidor):
    """A correção não pode engolir os outros itens do menu."""
    from playwright.sync_api import sync_playwright
    base, token = servidor
    with sync_playwright() as p:
        nav, pg = _pagina(p, base, token)
        pg.goto(f"{base}/adm")

        pg.click('.lateral a[data-secao="historico"]')
        pg.wait_for_timeout(1200)

        assert pg.evaluate("window.scrollY") > 300
        assert pg.url.endswith("#historico")
        nav.close()


def test_de_outra_tela_visao_geral_abre_o_painel_no_alto(servidor):
    from playwright.sync_api import sync_playwright
    base, token = servidor
    with sync_playwright() as p:
        nav, pg = _pagina(p, base, token)
        pg.goto(f"{base}/adm/dellavolpe")

        pg.click('.lateral a[data-secao="topo"]')
        pg.wait_for_url(f"{base}/adm#topo")

        assert _esperar_o_alto(pg) == 0
        nav.close()
