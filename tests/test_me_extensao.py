"""Abrir a cotação no ME já na conta certa (29/09/2026).

O servidor faz um login novo (aqui, um falso) e a extensão do CotaFrete põe
SÓ a sessão no Chrome do vendedor e abre a cotação. A ponta a ponta carrega a
extensão a partir do ZIP que o próprio CotaFrete gera, num Chromium de
verdade, com o ME respondido localmente.
"""

from __future__ import annotations

import io
import json
import socket
import threading
import time
import zipfile

import pytest

from core import sessao as sessao_cf
from core.banco import Banco
from mercado_eletronico import sessao_me
from tests.test_me_tela import cliente, robo  # noqa: F401  (fixtures)
from web import app as app_web
from web import me_extensao, me_ui

FALSOS = [{"name": "ASP.NET_SessionId", "value": "sessao-teste", "path": "/", "expires": -1},
          {"name": "ME", "value": "me-teste", "path": "/", "expires": 1900000000}]


def test_id_da_extensao_sai_da_chave_do_manifesto():
    assert sessao_me.id_da_extensao() == sessao_me.EXTENSAO_ID


def test_abre_pelo_link_da_lista_de_oportunidades():
    assert sessao_me.url_da_cotacao(23083602) == \
        "https://www.me.com.br/FornShowCotacao.asp?Cot=23083602&SuperCleanPage=true"


@pytest.fixture
def cotacao(cliente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(me_extensao, "SESSAO_ME", lambda conta: chamadas.append(conta) or FALSOS)
    cid = me_ui.banco.me_criar("edp_alianca", 23083602, status="pendente", empresa="EDP - Outsourcing")
    return cid, chamadas


def test_sessao_so_para_quem_esta_logado(cliente, cotacao):
    cid, chamadas = cotacao
    cliente.cookies.clear()
    r = cliente.post(f"/me/{cid}/sessao-me")
    assert r.status_code == 401 and chamadas == []


def test_sessao_da_conta_da_cotacao_sem_cache_e_no_historico(cliente, cotacao):
    cid, chamadas = cotacao
    r = cliente.post(f"/me/{cid}/sessao-me")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json() == {"url": sessao_me.url_da_cotacao(23083602), "cookies": FALSOS}
    assert chamadas == ["edp_alianca"]                       # a conta DA cotação
    h = me_ui.banco.me_historico(cid)[-1]
    assert (h["evento"], h["detalhe"], h["usuario"]) == (
        "aberta no ME na conta certa", "EDP e WEG · ALIANÇA", "enzo")
    assert cliente.post("/me/99999/sessao-me").status_code == 404


def test_me_fora_do_ar_vira_mensagem_e_historico(cliente, cotacao, monkeypatch):
    cid, _ = cotacao
    def quebra(conta):
        raise TimeoutError("ME lento")
    monkeypatch.setattr(me_extensao, "SESSAO_ME", quebra)
    r = cliente.post(f"/me/{cid}/sessao-me")
    assert r.status_code == 502 and "EDP e WEG · ALIANÇA" in r.json()["erro"]
    assert me_ui.banco.me_historico(cid)[-1]["evento"] == "abrir no ME falhou"


def test_pacote_da_extensao_com_o_endereco_de_quem_baixou(cliente):
    r = cliente.get("/me-extensao/cotafrete-me.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    m = json.loads(z.read("cotafrete-me/manifest.json"))
    assert m["externally_connectable"]["matches"] == ["http://testserver/*"]
    assert m["host_permissions"] == ["https://www.me.com.br/*", "http://testserver/*"]
    assert m["key"] == sessao_me.CHAVE_PUBLICA and m["permissions"] == ["cookies", "tabs"]
    assert "chrome.cookies.set" in z.read("cotafrete-me/background.js").decode()
    cliente.cookies.clear()
    assert cliente.get("/me-extensao/cotafrete-me.zip", follow_redirects=False).status_code == 303
    assert cliente.get("/me-extensao", follow_redirects=False).status_code == 303


def test_pagina_de_instalacao_e_botao_da_cotacao(cliente, cotacao):
    cid, _ = cotacao
    assert "Carregar sem compactação" in cliente.get("/me-extensao").text
    html = cliente.get(f"/me/{cid}").text
    assert 'id="abrir-me"' in html and f'data-cid="{cid}"' in html
    assert "FornShowCotacao.asp?Cot=23083602" in html and sessao_me.EXTENSAO_ID in html
    assert "/me-extensao" in html                         # sem extensão: como instalar


# ------------------------------------------------------ ponta a ponta
@pytest.fixture
def servidor(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    import uvicorn
    banco = Banco(tmp_path / "t.db")
    monkeypatch.setattr(app_web, "banco", banco)
    monkeypatch.setattr(me_ui, "banco", banco)
    monkeypatch.setattr(me_extensao, "SESSAO_ME", lambda conta: FALSOS)
    cid = banco.me_criar("edp_alianca", 23083602, status="pendente", empresa="EDP - Outsourcing")
    banco.criar_conta("enzo")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app_web.app, host="127.0.0.1", port=porta,
                                        log_level="error", lifespan="off"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{porta}", cid, sessao_cf.assinar("enzo", banco.segredo_sessao())
    srv.should_exit = True


def test_clicar_abre_o_me_ja_com_a_sessao_da_conta_certa(servidor, tmp_path):
    from playwright.sync_api import sync_playwright
    import urllib.request
    base, cid, cookie = servidor
    pedido = urllib.request.Request(f"{base}/me-extensao/cotafrete-me.zip",
                                    headers={"Cookie": f"{app_web.COOKIE}={cookie}"})
    zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(pedido).read())).extractall(tmp_path / "ext")
    ext = tmp_path / "ext" / "cotafrete-me"

    with sync_playwright() as p:
        # O ME de verdade fica inalcançável: a aba que a extensão abre escapa do
        # ctx.route, então o nome nem resolve e o teste não sai da máquina.
        ctx = p.chromium.launch_persistent_context(
            str(tmp_path / "perfil"), channel="chromium", headless=True,
            args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}",
                  "--host-resolver-rules=MAP www.me.com.br ~NOTFOUND"])
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        assert sw.url.split("/")[2] == sessao_me.EXTENSAO_ID       # identidade fixa
        # O vendedor estava logado em OUTRA conta.
        ctx.add_cookies([{"name": "ME", "value": "da-conta-errada", "url": "https://www.me.com.br/",
                          "httpOnly": True, "secure": True},
                         {"name": app_web.COOKIE, "value": cookie, "url": base}])
        pg = ctx.new_page()
        pg.goto(f"{base}/me/{cid}")
        with ctx.expect_page(timeout=20_000) as nova:
            pg.click("#abrir-me")
        nova.value.wait_for_load_state()
        # A aba é da extensão: o endereço que ela abriu vem do próprio Chrome.
        abas = sw.evaluate("async () => (await chrome.tabs.query({})).map(t => t.url || t.pendingUrl)")
        assert sessao_me.url_da_cotacao(23083602) in abas
        me = {c["name"]: c for c in ctx.cookies("https://www.me.com.br")}
        assert me["ME"]["value"] == "me-teste" and me["ME"]["httpOnly"]
        assert me["ASP.NET_SessionId"]["value"] == "sessao-teste"
        assert "Aberto no ME numa nova aba" in pg.inner_text("#me-abrindo")
        ctx.close()
