#!/usr/bin/env python3
"""Copia das cotações pendentes do ME para teste offline. NUNCA envia.

    python recon/copia_cotacoes_me.py                 # as duas contas
    python recon/copia_cotacoes_me.py --conta uniao

As cotações fecham e somem; sem cópia não há como testar o robô e a tela
depois. Para cada cotação de "Oportunidades a Responder" grava, por página
de itens: HTML inteiro, texto, campos (JSON) e print. Grava também o JSON
da listagem.

    recon_out/me/copias/<conta>/            cópia crua (fora do Git)
    tests/fixtures/me_real/                 cópia para teste (token removido)

Página 2 em diante só abre por POST do formulário (GET dá erro no ME). É o
único POST liberado aqui, e só com o corpo `Acao=11..19` (troca de página;
o ME grava o rascunho da página atual, o que o usuário autorizou em
23/09/2026). Salvar (9), ENVIAR (1), recusar (2), desconto (5) e todo o
resto continuam abortados pela trava do recon_me.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("recon_me", RAIZ / "recon" / "recon_me.py")
rm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rm)

FIXTURES = RAIZ / "tests" / "fixtures" / "me_real"
RE_FORM_COTACAO = re.compile(r"^https://www\.me\.com\.br/RespostaCotaItem\.asp\?Cotacao=\d+&FID=$", re.I)
ACOES_PAGINA = {str(n) for n in range(11, 20)}
RE_TOKEN = re.compile(r'(name="RequestVerificationToken"[^>]*value=")[^"]*(")', re.I)


def acao_do_post(corpo: str | None) -> list[str]:
    return parse_qs(corpo or "", keep_blank_values=True).get("Acao", [])


class TravaPaginacao(rm.Trava):
    """A trava do recon + uma exceção: POST de troca de página da cotação."""

    def __call__(self, route, request) -> None:
        if (request.method.upper() == "POST" and RE_FORM_COTACAO.match(request.url)
                and acao_do_post(request.post_data) and set(acao_do_post(request.post_data)) <= ACOES_PAGINA):
            print(f"  [PAGINA] POST liberado Acao={acao_do_post(request.post_data)}")
            self._log.write(json.dumps({"metodo": "POST", "url": request.url,
                                        "liberado": "troca de página",
                                        "acao": acao_do_post(request.post_data)}) + "\n")
            self._log.flush()
            route.continue_()
            return
        super().__call__(route, request)


def sanitizar(html: str) -> str:
    return RE_TOKEN.sub(r"\1TOKEN\2", html)


def _gravar_pagina(page, cru: Path, numero: int, pagina: int) -> None:
    nome = f"{numero}_p{pagina}"
    try:
        page.screenshot(path=str(cru / f"{nome}.png"), full_page=True, timeout=60_000)
    except Exception:
        page.screenshot(path=str(cru / f"{nome}.png"), timeout=30_000)
    html = page.main_frame.content()
    (cru / f"{nome}.html").write_text(html, encoding="utf-8")
    (cru / f"{nome}.txt").write_text(page.evaluate("() => document.body.innerText"), encoding="utf-8")
    campos = page.evaluate(rm.JS_CAMPOS)
    (cru / f"{nome}_campos.json").write_text(json.dumps(campos, ensure_ascii=False, indent=1), encoding="utf-8")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / f"{nome}.html").write_text(sanitizar(html), encoding="utf-8")
    try:  # print leve para o Git: JPEG
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        Image.open(cru / f"{nome}.png").convert("RGB").save(FIXTURES / f"{nome}.jpg", quality=60)
    except ImportError:
        pass
    itens = page.evaluate("() => [...document.querySelectorAll('[id^=spanItem_]')].map(e => e.innerText.trim())")
    print(f"  {nome}: {len(itens)} itens {itens}")


def _paginas(page) -> list[int]:
    return page.evaluate(r"""() => [...new Set([...document.querySelectorAll('a[href*="Envia(1"]')]
        .map(a => (a.getAttribute('href').match(/Envia\((1\d)\)/) || [])[1])
        .filter(Boolean).map(n => Number(n) - 10))].sort()""")


def copiar(conta: str) -> None:
    destino = rm.SAIDA / conta
    destino.mkdir(parents=True, exist_ok=True)
    estado = destino / "estado.json"
    if not estado.exists():
        rm.cmd_login(conta, headed=False)
    cru = rm.SAIDA / "copias" / conta
    cru.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1500, "height": 950},
                                  storage_state=str(estado))
        ctx.add_init_script(rm.JS_TRAVA)
        trava = TravaPaginacao(destino)
        trava.logado = True
        ctx.route("**/*", trava)
        page = ctx.new_page()
        page.set_default_timeout(60_000)
        page.on("dialog", lambda d: (print(f"  [DIALOG] {d.message[:150]}"), d.dismiss()))

        with page.expect_response(lambda r: r.url.endswith("/transactions/search"), timeout=60_000) as resp:
            page.goto(rm.URL_PENDENCIAS, wait_until="domcontentloaded")
        if "login" in page.url.lower():
            sys.exit(f"sessão de {conta} expirou: rode recon_me.py login --conta {conta}")
        lista = resp.value.json()
        (cru / "lista.json").write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")
        FIXTURES.mkdir(parents=True, exist_ok=True)
        (FIXTURES / f"lista_{conta}.json").write_text(json.dumps(lista, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")
        numeros = [r["processId"] for r in lista["data"]["result"]]
        print(f"{conta}: {numeros}")

        for n in numeros:
            page.goto(rm.URL_COTACAO.format(n=n), wait_until="domcontentloaded")
            page.wait_for_load_state("load")
            page.wait_for_timeout(2500)
            _gravar_pagina(page, cru, n, 1)
            for p in [p for p in _paginas(page) if p > 1]:
                # Mesmo caminho do link "2" do ME, sem passar pelo Envia
                # (as validações dele não mudam nada numa troca de página).
                # requestSubmit porque o recon desliga form.submit.
                with page.expect_navigation(timeout=60_000):
                    page.evaluate("""(p) => { const f = document.RespCota;
                        f.Acao.value = String(p + 10); f.CurrentPage.value = String(p);
                        f.requestSubmit(); }""", p)
                page.wait_for_timeout(2500)
                _gravar_pagina(page, cru, n, p)
        browser.close()
    print(f"  bloqueios: {len(trava.bloqueios)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conta", choices=["ventura", "uniao"])
    a = ap.parse_args()
    for conta in [a.conta] if a.conta else ["ventura", "uniao"]:
        copiar(conta)


if __name__ == "__main__":
    main()
