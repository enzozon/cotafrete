"""Validação isolada: nunca lê .env, banco ou evidências de produção.

Execute com --tests, --capture ou --serve (prévia sintética na porta 8012).
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import sys
from contextlib import nullcontext
from uuid import uuid4
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def carregar(pasta):
    from core.banco import Banco
    inicializar = Banco.__init__

    def isolado(self, caminho=None):
        inicializar(self, caminho if caminho is not None else pasta / "inicio.db")

    with patch("dotenv.load_dotenv", return_value=False), \
         patch("core.evidencias.limpar_antigas", return_value=0), \
         patch.object(Banco, "__init__", isolado):
        modulo = importlib.import_module("web.app")
    return modulo


def preparar(modulo, pasta):
    from core.banco import Banco
    from decimal import Decimal
    from fastapi.testclient import TestClient
    from web import adm

    banco = Banco(pasta / "demonstracao.db")
    modulo.banco = adm.banco = banco
    os.environ["COTAFRETE_ADM_SENHA"] = "senha-sintetica-local"
    carga = dict(cep_origem="01001-000", cep_destino="20040-020",
                 cidade_origem="São Paulo", uf_origem="SP",
                 cidade_destino="Rio de Janeiro", uf_destino="RJ",
                 peso_kg="24", quantidade=2, comprimento_cm=40,
                 largura_cm=30, altura_cm=25, valor_nf="1800",
                 material="Caixas de demonstração", tipo_frete="cif",
                 cnpj_remetente="00.000.000/0000-00",
                 cnpj_destinatario="00.000.000/0000-00",
                 cnpj_pagador="00.000.000/0000-00",
                 nome_remetente="Remetente fictício", nome_destinatario="Destino fictício",
                 nome_pagador="Remetente fictício", email="demo@example.invalid",
                 nome_solicitante="Equipe Demo", whatsapp_solicitante="00000000000")
    for i in range(8):
        cid = banco.salvar_cotacao("Equipe Demo", carga)
        for n, slug in enumerate(modulo.AUTOMATICAS):
            banco.salvar_resultado(cid, slug, status="cotado" if n != 2 else "erro",
                                  valor=Decimal(120 + 15*n + i) if n != 2 else None,
                                  prazo="3" if n != 2 else None,
                                  erro="Falha sintética para revisão" if n == 2 else None)
    cliente = TestClient(modulo.app)
    cliente.cookies.set(modulo.COOKIE, "Equipe Demo")
    cliente.cookies.set(adm.COOKIE_ADM, adm.token_de("senha-sintetica-local"))
    return cliente


PAGINAS = {
    "login": "/login", "login-adm": "/adm/entrar", "formulario": "/",
    "dashboard": "/adm", "resultados-ficha": "/cotacao/1",
    "historico": "/historico", "ajuda": "/documentacao",
    "email": "/email/1/dellavolpe", "della-volpe": "/dellavolpe/1",
    "detalhe-adm": "/adm/cotacao/1", "whatsapp-avulso": "/whatsapp-avulso",
}


def resposta(cliente, caminho):
    from urllib.parse import urlsplit
    from starlette.responses import Response
    path = urlsplit(caminho).path
    if path == "/whatsapp-avulso":
        import re
        html = (ROOT / "web/cotacao_whatsapp.html").read_text(encoding="utf-8")
        # A página legada traz exemplos antigos: nunca entram nas capturas.
        html = re.sub(r'(<input\b[^>]*\bvalue=")[^"]*', r'\1', html)
        return Response(html, media_type="text/html")
    if path in PAGINAS.values() or path.startswith(("/marca/", "/logos/", "/ajuda/")):
        return cliente.get(caminho)
    return Response("Prévia: operação desabilitada", status_code=403)


def corpo(r):
    return r.content if hasattr(r, "content") else r.body


def capturar(cliente):
    from playwright.sync_api import sync_playwright
    saida = Path(__file__).parent
    relatorio = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for largura in (1440, 390):
            for tema in ("claro", "escuro"):
                context = browser.new_context(viewport={"width": largura, "height": 1000},
                                              color_scheme="dark" if tema == "escuro" else "light")
                context.add_init_script(f"localStorage.setItem('tema', '{tema}')")
                page = context.new_page()
                erros = []
                page.on("pageerror", lambda erro: erros.append(str(erro)))
                page.on("console", lambda msg: erros.append(msg.text) if msg.type == "error" else None)

                def atender(route):
                    from urllib.parse import urlsplit
                    url = urlsplit(route.request.url)
                    if url.hostname != "cotafrete.test" or route.request.method != "GET":
                        route.abort()
                        return
                    r = resposta(cliente, url.path + ("?" + url.query if url.query else ""))
                    route.fulfill(status=r.status_code, content_type=r.headers.get("content-type", "text/plain"), body=corpo(r))

                page.route("**/*", atender)
                for nome, url in PAGINAS.items():
                    erros.clear()
                    page.goto("http://cotafrete.test" + url)
                    page.wait_for_timeout(4500 if nome.startswith("login") else 700)
                    overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    page.screenshot(path=str(saida / f"{nome}-{largura}-{tema}.png"), full_page=True)
                    assert not overflow, f"Overflow: {nome}, {largura}, {tema}"
                    assert not erros, f"Console: {nome}: {erros}"
                    relatorio.append(dict(tela=nome, largura=largura, tema=tema, overflow=False, erros=[]))
                # O hero deve parar e respeitar movimento reduzido.
                page.emulate_media(reduced_motion="reduce")
                page.goto("http://cotafrete.test/login")
                assert page.locator(".trajeto").evaluate("e => getComputedStyle(e).animationName") == "none"
                page.keyboard.press("Tab")
                assert page.evaluate("document.activeElement !== document.body")
                context.close()
        browser.close()
    (saida / "validacao-visual.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(relatorio)} capturas; sem overflow ou erros de console.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args, pytest_args = parser.parse_known_args()
    # mkdir padrão evita as ACLs restritas de TemporaryDirectory no Windows.
    # Tudo permanece descartável e dentro deste worktree.
    pasta = Path(__file__).parent / ".runtime" / uuid4().hex
    pasta.mkdir(parents=True)
    with nullcontext():
        modulo = carregar(pasta)
        if args.tests:
            import pytest
            raise SystemExit(pytest.main((pytest_args or ["tests", "-q"]) + ["--maxfail=1", "--ignore=tests/manuais", "--basetemp=" + str(pasta / "pytest")]))
        cliente = preparar(modulo, pasta)
        if args.smoke:
            for nome, url in PAGINAS.items():
                r = resposta(cliente, url)
                assert r.status_code == 200, (nome, r.status_code)
                assert b'lang="pt-BR"' in corpo(r), nome
            print(f"{len(PAGINAS)} telas renderizadas com dados sintéticos; HTTP 200 e pt-BR.")
        if args.capture:
            capturar(cliente)
        if args.serve:
            from http.server import BaseHTTPRequestHandler, HTTPServer

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    r = resposta(cliente, self.path)
                    self.send_response(r.status_code)
                    self.send_header("Content-Type", r.headers.get("content-type", "text/plain"))
                    self.end_headers()
                    self.wfile.write(corpo(r))

            print("Prévia sintética: http://127.0.0.1:8012/login | /adm | /whatsapp-avulso", flush=True)
            HTTPServer(("127.0.0.1", 8012), Handler).serve_forever()


if __name__ == "__main__":
    main()
