"""A linha da cotação se completa NO NAVEGADOR ao escolher a origem.

É JavaScript (fetch da prévia a cada mudança), não dá para ver no HTML:
um navegador de verdade abre a cotação real da EDP (fixture), escolhe a
origem, digita preço, NCM e prazo, e confere que a linha mostra impostos,
entrega e total — e que o contador de itens prontos anda.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest

from core import sessao
from core.banco import Banco

FIX = Path(__file__).parent / "fixtures" / "me_real"
PRINTS = Path(__file__).resolve().parent.parent / "runs" / "testes"


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    import uvicorn

    import web.app as app_web
    from web import me_ui

    banco = Banco(tmp_path / "t.db")
    monkeypatch.setattr(app_web, "banco", banco)
    monkeypatch.setattr(me_ui, "banco", banco)
    monkeypatch.setattr(me_ui, "LEITOR", lambda conta, n: [
        (FIX / "edp_23050183.html").read_text(encoding="utf-8")])
    cid = banco.me_criar("nestle_ventura", 23050183, status="pendente",
                         empresa="EDP - Outsourcing")
    me_ui.carregar_itens(cid)
    banco.criar_conta("enzo")

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app_web.app, host="127.0.0.1", port=porta,
                                        log_level="error", lifespan="off"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    yield (f"http://127.0.0.1:{porta}", cid,
           sessao.assinar("enzo", banco.segredo_sessao()), app_web.COOKIE)
    srv.should_exit = True


def test_escolher_a_origem_completa_a_linha(servidor):
    from playwright.sync_api import expect, sync_playwright
    base, cid, cookie, nome = servidor
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pg = nav.new_page(viewport={"width": 1440, "height": 1000})
        pg.context.add_cookies([{"name": nome, "value": cookie, "url": base}])
        pg.goto(f"{base}/me/{cid}")

        # O quadro da cotação: frete CIF pelo aviso da EDP, e os avisos dela.
        expect(pg.locator(".me-frete")).to_have_text("Frete CIF")
        expect(pg.locator(".me-avisos")).to_contain_text("Condição de Pagamento padrão EDP")
        expect(pg.locator("#me-prontos")).to_have_text("0")
        linha = pg.locator("#linha-1")
        expect(linha).to_contain_text("Escolha a origem")

        pg.select_option("select[name=origem_1]", "2")
        expect(linha).to_contain_text("ICMS 4,00% (sim)")          # GO, origem 2
        expect(linha).to_contain_text("PIS 0,65% (sim)")           # VENTURA

        pg.fill("input[name=preco_1]", "12,50")
        pg.fill("input[name=ncm_1]", "85365090")
        pg.fill("input[name=prazo_1]", "10")
        pg.fill("input[name=marca_1]", "WEG")
        expect(linha).to_contain_text("total R$ 62,50")            # 5 × 12,50
        expect(linha).to_contain_text("dias corridos")
        expect(pg.locator("#me-prontos")).to_have_text("1")

        # A linha de baixo continua esperando a origem dela.
        expect(pg.locator("#linha-2")).to_contain_text("Escolha a origem")
        PRINTS.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(PRINTS / "me_linha_completa.png"), full_page=True)
        nav.close()
