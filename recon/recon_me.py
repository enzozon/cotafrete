#!/usr/bin/env python3
"""Recon do Mercado Eletrônico (ME). SÓ LEITURA — nunca salva, nunca envia.

    python recon/recon_me.py login        --conta ventura
    python recon/recon_me.py pendencias   --conta ventura
    python recon/recon_me.py cotacao 23039029 --conta ventura
    python recon/recon_me.py url "https://www.me.com.br/..." --conta ventura

Grava tudo em recon_out/me/<conta>/ (fora do Git: tem token de sessão e dado
de comprador): print da página inteira, HTML/texto de cada frame, campos de
formulário, botões e o registro de toda requisição de escrita.

TRAVAS (redundantes de propósito, não remova nenhuma):

  1. o único clique do script é o "Entrar" do login. Nenhum botão da cotação
     é clicado — nem Salvar, nem Confirmar, nem a paginação dos itens (que
     também faz POST do formulário);
  2. depois do login, um route ABORTA todo POST/PUT/PATCH/DELETE para
     *.me.com.br e toda URL (qualquer método) com cara de envio/gravação.
     Cada bloqueio vai para requisicoes.jsonl;
  3. `form.submit`, `window.open` e `__doPostBack` viram no-op via
     add_init_script, antes de qualquer script do ME rodar.

A credencial vem de ME_<CONTA>_LOGIN / ME_<CONTA>_SENHA (.env) e nunca é impressa.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RAIZ / ".env", override=False)

SAIDA = RAIZ / "recon_out" / "me"
URL_BASE = "https://www.me.com.br"
URL_PENDENCIAS = URL_BASE + "/supplier/inbox/pendencies/4?CreateDateStart=2026-06-25"
URL_COTACAO = URL_BASE + "/RespostaCotaItem.asp?Cotacao={n}&SuperCleanPage="
LIMITE_SEGUNDOS = 240  # watchdog: navegador travado não segura o terminal

METODOS_ESCRITA = {"POST", "PUT", "PATCH", "DELETE"}
RE_URL_PROIBIDA = re.compile(
    r"envi|submit|finaliz|respond|confirm|grava|salva|save|send|delete|exclu|recus",
    re.IGNORECASE,
)
RE_LOGIN = re.compile(r"/Login\.mvc/", re.IGNORECASE)
# A listagem mora em outro domínio do ME e busca por POST. É leitura: a
# única escrita liberada depois do login, e só nesse caminho exato.
HOSTS_ME = ("me.com.br", "mercadoe.com")
RE_BUSCA_LEITURA = re.compile(
    r"^https://api\.web\.mercadoe\.com/supplier/transactions/v1/transactions/search$"
)


def _do_me(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in HOSTS_ME)

JS_TRAVA = """
(() => {
  window.open = () => null;
  HTMLFormElement.prototype.submit = function () {
    console.warn('[TRAVA] form.submit bloqueado: ' + (this.action || ''));
  };
  Object.defineProperty(window, '__doPostBack', {
    configurable: false, get: () => () => console.warn('[TRAVA] __doPostBack bloqueado'),
    set: () => {},
  });
})();
"""

JS_CAMPOS = """
() => {
  const rotulo = (el) => {
    if (el.id) {
      const lb = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lb && lb.innerText.trim()) return lb.innerText.trim();
    }
    const td = el.closest('td');
    if (td && td.previousElementSibling) return td.previousElementSibling.innerText.trim().slice(0, 80);
    return el.getAttribute('aria-label') || el.getAttribute('title') || '';
  };
  return [...document.querySelectorAll('input, select, textarea')].map(el => ({
    tag: el.tagName.toLowerCase(), type: (el.type || '').toLowerCase(),
    name: el.name || '', id: el.id || '', label: rotulo(el),
    value: el.type === 'password' ? '***' : (el.value || '').slice(0, 200),
    checked: el.checked === true, disabled: el.disabled === true, readonly: el.readOnly === true,
    visivel: !!(el.offsetParent || el.getClientRects().length),
    fundo: getComputedStyle(el).backgroundColor,
    options: el.tagName === 'SELECT'
      ? [...el.options].map(o => ({v: o.value, t: o.text.trim(), s: o.selected})) : [],
  }));
}
"""

JS_BOTOES = """
() => [...document.querySelectorAll(
    'button, input[type=button], input[type=submit], input[type=image], a[onclick], a[href^="javascript"]'
  )].map(el => ({
    tag: el.tagName.toLowerCase(), id: el.id || '', name: el.name || '',
    texto: (el.innerText || el.value || '').trim().slice(0, 80),
    title: el.getAttribute('title') || '',
    onclick: (el.getAttribute('onclick') || '').slice(0, 300),
    href: (el.getAttribute('href') || '').slice(0, 300),
    visivel: !!(el.offsetParent || el.getClientRects().length),
  }))
"""

JS_FORMS = """
() => [...document.forms].map(f => ({
  name: f.name || '', id: f.id || '', action: f.getAttribute('action') || '',
  method: (f.method || '').toUpperCase(), campos: f.elements.length,
}))
"""


def _credenciais(conta: str) -> tuple[str, str]:
    login = os.environ.get(f"ME_{conta.upper()}_LOGIN", "")
    senha = os.environ.get(f"ME_{conta.upper()}_SENHA", "")
    if not login or not senha:
        sys.exit(f"Faltam ME_{conta.upper()}_LOGIN / ME_{conta.upper()}_SENHA no .env.")
    return login, senha


class Trava:
    """Route que registra e aborta escrita. `logado` fecha a janela do login."""

    def __init__(self, destino: Path):
        self.logado = False
        self.bloqueios: list[dict[str, Any]] = []
        self._log = (destino / "requisicoes.jsonl").open("a", encoding="utf-8")

    def motivo(self, metodo: str, url: str) -> str | None:
        u = urlparse(url)
        host = u.hostname or ""
        if not _do_me(host):
            return None
        login = RE_LOGIN.search(url) and not self.logado
        if metodo in METODOS_ESCRITA and not (login or RE_BUSCA_LEITURA.match(url)):
            return "escrita no ME"
        if RE_URL_PROIBIDA.search(u.path + "?" + (u.query or "")):
            return "url com cara de envio/gravação"
        return None

    def __call__(self, route, request) -> None:
        url, metodo = request.url, request.method.upper()
        motivo = self.motivo(metodo, url)
        if motivo or (metodo != "GET" and _do_me(urlparse(url).hostname or "")):
            reg = {"t": time.strftime("%H:%M:%S"), "metodo": metodo, "url": url[:300],
                   "tipo": request.resource_type}
            if motivo:
                reg["bloqueado"] = motivo
                reg["corpo"] = (request.post_data or "")[:800] if metodo in METODOS_ESCRITA else ""
                self.bloqueios.append(reg)
                print(f"  [BLOQUEADO] {metodo} {url[:110]} ({motivo})")
            self._log.write(json.dumps(reg, ensure_ascii=False) + "\n")
            self._log.flush()
        if motivo:
            route.abort()
        else:
            route.continue_()


def _despejar(page, destino: Path, prefixo: str) -> None:
    page.screenshot(path=str(destino / f"{prefixo}.png"), full_page=True)
    for i, frame in enumerate(page.frames):
        if frame.url in ("about:blank", ""):
            continue
        try:
            dados = {"url": frame.url, "forms": frame.evaluate(JS_FORMS),
                     "botoes": frame.evaluate(JS_BOTOES), "campos": frame.evaluate(JS_CAMPOS)}
            texto = frame.evaluate("() => document.body ? document.body.innerText : ''")
            html = frame.content()
        except Exception as exc:
            print(f"  frame {i} ilegível: {exc}")
            continue
        (destino / f"{prefixo}_frame{i}.html").write_text(html, encoding="utf-8")
        (destino / f"{prefixo}_frame{i}.txt").write_text(texto, encoding="utf-8")
        (destino / f"{prefixo}_frame{i}.json").write_text(
            json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  frame {i}: {frame.url[:90]} — {len(dados['campos'])} campos, "
              f"{len(dados['botoes'])} botões, {len(dados['forms'])} forms")


def _watchdog() -> None:
    def matar():
        time.sleep(LIMITE_SEGUNDOS)
        print(f"  [WATCHDOG] passou de {LIMITE_SEGUNDOS}s — encerrando", flush=True)
        os._exit(3)
    threading.Thread(target=matar, daemon=True).start()


def _rodar(conta: str, headed: bool, acao) -> None:
    from playwright.sync_api import sync_playwright

    destino = SAIDA / conta
    destino.mkdir(parents=True, exist_ok=True)
    estado = destino / "estado.json"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        ctx = browser.new_context(
            locale="pt-BR", timezone_id="America/Sao_Paulo",
            viewport={"width": 1500, "height": 950},
            storage_state=str(estado) if estado.exists() else None,
        )
        ctx.add_init_script(JS_TRAVA)
        trava = Trava(destino)
        trava.logado = estado.exists()
        ctx.route("**/*", trava)
        page = ctx.new_page()
        page.set_default_timeout(60_000)
        page.on("dialog", lambda d: (print(f"  [DIALOG] {d.type}: {d.message[:200]}"), d.dismiss()))
        page.on("console", lambda m: print("  [CONSOLE]", m.text[:150]) if "TRAVA" in m.text else None)
        try:
            acao(page, ctx, trava, destino, estado)
        finally:
            browser.close()


def cmd_login(conta: str, headed: bool) -> None:
    login, senha = _credenciais(conta)

    def acao(page, ctx, trava, destino, estado):
        trava.logado = False
        page.goto(URL_PENDENCIAS, wait_until="domcontentloaded")
        page.fill("#LoginName", login)
        page.fill("#RAWSenha", senha)
        page.click("#SubmitAuth")  # o ÚNICO clique do script
        page.wait_for_load_state("networkidle")
        trava.logado = True
        print("  depois do login:", page.url)
        _despejar(page, destino, "01_pos_login")
        if "login" in page.url.lower():
            print("  ainda na tela de login — ver 01_pos_login.png")
        else:
            ctx.storage_state(path=str(estado))
            print("  sessão salva em", estado.relative_to(RAIZ))

    _rodar(conta, headed, acao)


def cmd_pagina(conta: str, url: str, prefixo: str, headed: bool, espera: float) -> None:
    def acao(page, ctx, trava, destino, estado):
        jsons = []

        def guardar(resp):
            if "json" in resp.headers.get("content-type", ""):
                try:
                    jsons.append({"url": resp.url, "status": resp.status, "json": resp.json()})
                except Exception:
                    pass

        page.on("response", guardar)
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass
        page.wait_for_timeout(int(espera * 1000))
        print("  url final:", page.url)
        if "login" in page.url.lower():
            print("  sessão expirou — rode `login` de novo")
        _despejar(page, destino, prefixo)
        (destino / f"{prefixo}_xhr.json").write_text(
            json.dumps(jsons, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {len(jsons)} respostas JSON; {len(trava.bloqueios)} bloqueios")

    _rodar(conta, headed, acao)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["login", "pendencias", "cotacao", "url"])
    ap.add_argument("alvo", nargs="?")
    ap.add_argument("--conta", default="ventura", choices=["ventura", "uniao"])
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--espera", type=float, default=4)
    ap.add_argument("--prefixo")
    a = ap.parse_args()
    _watchdog()
    if a.acao == "login":
        cmd_login(a.conta, a.headed)
    elif a.acao == "pendencias":
        cmd_pagina(a.conta, a.alvo or URL_PENDENCIAS, a.prefixo or "10_pendencias", a.headed, a.espera)
    elif a.acao == "cotacao":
        n = a.alvo or "23039029"
        cmd_pagina(a.conta, URL_COTACAO.format(n=n), a.prefixo or f"20_cotacao_{n}", a.headed, a.espera)
    else:
        nome = re.sub(r"\W+", "_", urlparse(a.alvo).path)[:40]
        cmd_pagina(a.conta, a.alvo, a.prefixo or f"30{nome}", a.headed, a.espera)


if __name__ == "__main__":
    main()
