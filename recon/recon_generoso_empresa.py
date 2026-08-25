"""Mede o menu "Alterar empresa" do portal da Generoso. READ-ONLY: nao cota.

    python recon/recon_generoso_empresa.py

Faz login, abre a tela de cotacao, clica em "Alterar empresa" e despeja o
menu inteiro. NAO preenche nada e NAO avanca etapa nenhuma — o objetivo e
so descobrir como o menu e escrito.

Existe porque em 25/08/2026 a leitura do popup da Camilo foi deduzida de um
PRINT e os tres seletores estavam errados. Nunca mais.

Saida em recon_out/generoso_empresa/ (pasta no .gitignore).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(override=False)

from carriers.generoso.adapter import URL, GenerosoAdapter   # noqa: E402

SAIDA = RAIZ / "recon_out" / "generoso_empresa"

# Candidatos ao gatilho. O `id` do Radix e gerado por render
# (radix-_R_6j9qnpfiv9fl97b_), entao esta fora de questao.
GATILHOS = ('button[data-slot="dropdown-menu-trigger"]',
            'button:has-text("Alterar empresa")',
            'text="Alterar empresa"')

# Candidatos aos itens, depois de aberto.
ITENS = ('[data-slot="dropdown-menu-item"]', '[role="menuitem"]',
         '[data-radix-menu-content] [role="menuitem"]')

JS_MENU = """() => {
  // Radix monta o menu num portal no fim do <body>. Pega qualquer coisa
  // aberta e devolve o HTML inteiro, para ler com calma depois.
  const abertos = [...document.querySelectorAll(
      '[data-state="open"][role="menu"], [data-radix-popper-content-wrapper]')];
  return abertos.map(e => e.outerHTML);
}"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    SAIDA.mkdir(parents=True, exist_ok=True)
    adapter = GenerosoAdapter()
    achados: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=adapter.headless)
        page = browser.new_context(
            locale="pt-BR", viewport={"width": 1400, "height": 1400}).new_page()
        page.set_default_timeout(adapter.timeout_ms)
        try:
            adapter._entrar(page)
            page.goto(URL, wait_until="domcontentloaded")
            page.wait_for_selector("select")
            page.wait_for_timeout(3_000)
            page.screenshot(path=str(SAIDA / "1_antes.png"))

            achados["gatilhos"] = {}
            gatilho = None
            for sel in GATILHOS:
                try:
                    loc = page.locator(sel).first
                    n = loc.count()
                    achados["gatilhos"][sel] = {
                        "existe": bool(n),
                        "visivel": bool(n) and loc.is_visible(timeout=1_000),
                        "texto": (loc.inner_text() if n else "")[:60],
                    }
                    if achados["gatilhos"][sel]["visivel"] and gatilho is None:
                        gatilho = sel
                except Exception as e:
                    achados["gatilhos"][sel] = {"erro": f"{type(e).__name__}: {e}"}

            if gatilho is None:
                achados["parou"] = "nenhum gatilho visivel"
            else:
                achados["gatilho_usado"] = gatilho
                page.locator(gatilho).first.click()
                page.wait_for_timeout(1_500)
                page.screenshot(path=str(SAIDA / "2_menu_aberto.png"))

                achados["itens"] = {}
                for sel in ITENS:
                    try:
                        loc = page.locator(sel)
                        achados["itens"][sel] = {
                            "quantos": loc.count(),
                            "textos": [t.strip() for t in loc.all_inner_texts()],
                        }
                    except Exception as e:
                        achados["itens"][sel] = {"erro": f"{type(e).__name__}: {e}"}

                pedacos = page.evaluate(JS_MENU) or []
                (SAIDA / "menu.html").write_text(
                    "\n".join(pedacos) or "(nada aberto)", encoding="utf-8")
        finally:
            (SAIDA / "achados.json").write_text(
                json.dumps(achados, ensure_ascii=False, indent=2),
                encoding="utf-8")
            browser.close()

    print(json.dumps(achados, ensure_ascii=False, indent=2)[:2600])
    print(f"\nsaida em {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
