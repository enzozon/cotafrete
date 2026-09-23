#!/usr/bin/env python3
"""Recon do Mercado Eletrônico (ME). SÓ LEITURA — nunca salva, nunca envia.

    python recon/recon_me.py login        --conta ventura
    python recon/recon_me.py pendencias   --conta ventura
    python recon/recon_me.py cotacao 23039029 --conta ventura

Grava tudo em recon_out/me/<conta>/ (fora do Git: tem token de sessão e dado
de comprador): print da página inteira, HTML de cada frame, campos de
formulário, botões e o registro de toda requisição de escrita.

TRAVAS (redundantes de propósito, não remova nenhuma):

  1. o único clique do script é o "Entrar" do login. Nenhum botão da cotação
     é clicado — nem Salvar, nem Enviar, nem aba;
  2. depois do login, um page.route ABORTA todo POST/PUT/PATCH/DELETE para
     *.me.com.br e toda URL (qualquer método) com cara de envio. Cada bloqueio
     vai para requisicoes.jsonl, então dá para ver o que a página tentou
     fazer sozinha;
  3. `window.open`, `form.submit` e `__doPostBack` viram no-op via
     add_init_script, antes de qualquer script do ME rodar.

A credencial vem de ME_<CONTA>_LOGIN / ME_<CONTA>_SENHA e nunca é impressa.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "recon_out" / "me"

URL_BASE = "https://www.me.com.br"
URL_PENDENCIAS = URL_BASE + "/supplier/inbox/pendencies/4?CreateDateStart=2026-06-25"
URL_COTACAO = URL_BASE + "/RespostaCotaItem.asp?Cotacao={n}&SuperCleanPage="

METODOS_ESCRITA = {"POST", "PUT", "PATCH", "DELETE"}
# URL com cara de envio/gravação: bloqueada mesmo em GET.
RE_URL_PROIBIDA = re.compile(
    r"envi|submit|finaliz|respond|confirm|grava|salva|save|send|delete|exclu",
    re.IGNORECASE,
)
# Só o POST do próprio login passa (e só antes de a sessão existir).
RE_LOGIN = re.compile(r"/Login\.mvc/", re.IGNORECASE)
# A listagem nova vive em outro domínio do ME e busca por POST. É leitura:
# a única escrita liberada depois do login, e só nesse caminho exato.
HOSTS_ME = ("me.com.br", "mercadoe.com")
RE_BUSCA_LEITURA = re.compile(r"^https://api\.web\.mercadoe\.com/supplier/transactions/v1/transactions/search$")

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
    const pai = el.closest('label');
    if (pai && pai.innerText.trim()) return pai.innerText.trim();
    const td = el.closest('td');
    if (td && td.previousElementSibling) return td.previousElementSibling.innerText.trim().slice(0, 80);
    return el.getAttribute('aria-label') || el.getAttribute('title') || '';
  };
  return [...document.querySelectorAll('input, select, textarea')].map(el => ({
    tag: el.tagName.toLowerCase(),
    type: (el.type || '').toLowerCase(),
    name: el.name || '',
    id: el.id || '',
    label: rotulo(el),
    value: el.type === 'password' ? '***' : (el.value || '').slice(0, 200),
    checked: el.checked === true,
    disabled: el.disabled === true,
    readonly: el.readOnly === true,
    visivel: !!(el.offsetParent || el.getClientRects().length),
    style_bg: getComputedStyle(el).backgroundColor,
    onchange: (el.getAttribute('onchange') || el.getAttribute('onblur') || '').slice(0, 200),
    options: el.tagName === 'SELECT'
      ? [...el.options].map(o => ({v: o.value, t: o.text.trim(), s: o.selected})).slice(0, 80)
      : [],
  }));
}
"""

JS_BOTOES = """
() => [...document.querySelectorAll(
    'button, input[type=button], input[type=submit], input[type=image], a[onclick], a[href^="javascript"], [role=button]'
  )].map(el => ({
    tag: el.tagName.toLowerCase(),
    id: el.id || '', name: el.name || '',
    texto: (el.innerText || el.value || el.title || el.alt || '').trim().slice(0, 80),
    onclick: (el.getAttribute('onclick') || '').slice(0, 300),
    href: (el.getAttribute('href') || '').slice(0, 300),
    form_action: el.form ? (el.form.getAttribute('action') || '') : '',
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
        sys.exit(f"Faltam ME_{conta.upper()}_LOGIN / ME_{conta.upper()}_SENHA no ambiente.")
    return login, senha


class Trava:
    """page.route que registra e aborta escrita. `logado` fecha a janela do login."""

    def __init__(self, destino: Path):
        self.logado = False
        self.bloqueios: list[dict[str, Any]] = []
        self._log = (destino / "requisicoes.jsonl").open("a", encoding="utf-8")

    def __call__(self, route, request) -> None:
        url, metodo = request.url, request.method.upper()
        host = urlparse(url).hostname or ""
        do_me = any(host == h or host.endswith("." + h) for h in HOSTS_ME)
        motivo = None
        if do_me and metodo in METODOS_ESCRITA:
            login = RE_LOGIN.search(url) and not self.logado
            if not (login or RE_BUSCA_LEITURA.match(url)):
                motivo = "escrita no ME"
        if do_me and RE_URL_PROIBIDA.search(urlparse(url).path + "?" + (urlparse(url).query or "")):
            motivo = "url com cara de envio/gravação"
        registro = {"t": time.strftime("%H:%M:%S"), "metodo": metodo, "url": url[:300],
                    "tipo": request.resource_type}
        if RE_BUSCA_LEITURA.match(url):
            registro["corpo"] = (request.post_data or "")[:2000]
        if motivo:
            registro["bloqueado"] = motivo
            if metodo in METODOS_ESCRITA:
                registro["corpo"] = (request.post_data or "")[:500]
            self.bloqueios.append(registro)
            print(f"  [BLOQUEADO] {metodo} {url[:120]} ({motivo})")
        if do_me and (metodo != "GET" or motivo):
            self._log.write(json.dumps(registro, ensure_ascii=False) + "\n")
            self._log.flush()
        if motivo:
            route.abort()
        else:
            route.continue_()


def _despejar(page, destino: Path, prefixo: str) -> None:
    """Print, HTML, campos, botões e forms de todos os frames."""
    destino.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(destino / f"{prefixo}.png"), full_page=True, timeout=30_000)
    except Exception as exc:  # página gigante: fica o print da primeira tela
        print(f"  print da página inteira falhou ({exc.__class__.__name__}); só a tela visível")
        page.screenshot(path=str(destino / f"{prefixo}.png"), timeout=30_000)
    resumo = []
    for i, frame in enumerate(page.frames):
        print(f"  frame {i}: {frame.url[:100]}", flush=True)
        if frame.is_detached() or not frame.url.startswith(URL_BASE):
            continue  # chat, analytics, about:blank — já travou o despejo
        try:
            html = frame.content()
            campos = frame.evaluate(JS_CAMPOS)
            botoes = frame.evaluate(JS_BOTOES)
            forms = frame.evaluate(JS_FORMS)
            texto = frame.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception as exc:  # frame que sumiu no meio
            print(f"  frame {i} ilegível: {exc}")
            continue
        (destino / f"{prefixo}_frame{i}.html").write_text(html, encoding="utf-8")
        (destino / f"{prefixo}_frame{i}.txt").write_text(texto, encoding="utf-8")
        (destino / f"{prefixo}_frame{i}.json").write_text(
            json.dumps({"url": frame.url, "forms": forms, "botoes": botoes, "campos": campos},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"  frame {i} despejado", flush=True)
        resumo.append(f"frame {i}: {frame.url[:90]} — {len(campos)} campos, "
                      f"{len(botoes)} botões, {len(forms)} forms")
    print("\n".join("  " + r for r in resumo))


def _abrir(conta: str, headed: bool):
    from playwright.sync_api import sync_playwright

    destino = SAIDA / conta
    destino.mkdir(parents=True, exist_ok=True)
    estado = destino / "estado.json"
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=not headed, channel="chromium")
    ctx = browser.new_context(
        locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width": 1500, "height": 950},
        storage_state=str(estado) if estado.exists() else None,
    )
    ctx.add_init_script(JS_TRAVA)
    trava = Trava(destino)
    trava.logado = estado.exists()
    ctx.route("**/*", trava)
    page = ctx.new_page()
    page.set_default_timeout(60_000)
    page.on("dialog", lambda d: (print(f"  [DIALOG] {d.type}: {d.message[:200]}"), d.dismiss()))
    return pw, browser, ctx, page, trava, destino, estado


def cmd_login(conta: str, headed: bool) -> None:
    login, senha = _credenciais(conta)
    pw, browser, ctx, page, trava, destino, estado = _abrir(conta, headed)
    try:
        page.goto(URL_PENDENCIAS, wait_until="domcontentloaded")
        page.fill("#LoginName", login)
        page.fill("#RAWSenha", senha)
        page.click("#SubmitAuth")  # o ÚNICO clique do script
        page.wait_for_load_state("networkidle")
        time.sleep(3)
        trava.logado = True
        print("  depois do login:", page.url)
        _despejar(page, destino, "01_pos_login")
        if "Login" in page.url:
            print("  ainda na tela de login — ver 01_pos_login.png")
        else:
            ctx.storage_state(path=str(estado))
            print("  sessão salva em", estado.relative_to(RAIZ))
    finally:
        browser.close()
        pw.stop()


def cmd_pagina(conta: str, url: str, prefixo: str, headed: bool, espera: float) -> None:
    pw, browser, ctx, page, trava, destino, estado = _abrir(conta, headed)
    respostas = []

    def guardar(resp):
        if resp.request.resource_type not in ("xhr", "fetch"):
            return
        ct = resp.headers.get("content-type", "")
        item = {"url": resp.url, "status": resp.status, "metodo": resp.request.method, "tipo": ct}
        if "json" in ct:
            try:
                item["json"] = resp.json()
            except Exception:
                pass
        respostas.append(item)

    page.on("response", guardar)
    try:
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass
        time.sleep(espera)
        print("  url final:", page.url)
        _despejar(page, destino, prefixo)
        print("  gravando xhr", flush=True)
        (destino / f"{prefixo}_xhr.json").write_text(
            json.dumps(respostas, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {len(respostas)} respostas JSON; {len(trava.bloqueios)} bloqueios")
    finally:
        browser.close()
        pw.stop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["login", "pendencias", "cotacao", "url"])
    ap.add_argument("alvo", nargs="?")
    ap.add_argument("--conta", default="ventura", choices=["ventura", "uniao"])
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--espera", type=float, default=4)
    a = ap.parse_args()
    if a.acao == "login":
        cmd_login(a.conta, a.headed)
    elif a.acao == "pendencias":
        cmd_pagina(a.conta, a.alvo or URL_PENDENCIAS, "10_pendencias", a.headed, a.espera)
    elif a.acao == "cotacao":
        cmd_pagina(a.conta, URL_COTACAO.format(n=a.alvo or "23039029"),
                   f"20_cotacao_{a.alvo or '23039029'}", a.headed, a.espera)
    else:
        nome = re.sub(r"\W+", "_", urlparse(a.alvo).path)[:40]
        cmd_pagina(a.conta, a.alvo, f"30{nome}", a.headed, a.espera)


if __name__ == "__main__":
    main()
