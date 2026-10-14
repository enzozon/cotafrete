"""Recon READ-ONLY da cotação da Favorita, LOGADO. Lê, não cota.

    python recon/recon_favorita.py [--ate-destino] [--ate-carga]

O Enzo disse que o site é "praticamente igual à Generoso". Este script existe
para MEDIR isso em vez de acreditar: login, cartão do solicitante, menu
"Alterar empresa", etapas e nomes dos campos. Cada etapa só é preenchida com
--ate-*; sem flag, só despeja a primeira tela.

⚠ NUNCA clica no botão final de confirmar. A trava é não procurar por ele.

Saída em recon_out/favorita/ (pasta já no .gitignore).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402

from carriers.base import argumentos_de_navegador_real  # noqa: E402

load_dotenv(RAIZ / ".env")

BASE = "https://cliente.favorita.com.br"
SAIDA = RAIZ / "recon_out" / "favorita"

# Mesma carga dos testes da Generoso: CIF, Ventura na origem.
CNPJ_DESTINATARIO = "60.042.686/0001-05"

JS_CAMPOS = """() => [...document.querySelectorAll('input, select, textarea')]
    .filter(e => e.offsetWidth || e.offsetHeight)
    .map(e => ({
        tipo: e.type || e.tagName.toLowerCase(), name: e.name || '',
        id: e.id || '', placeholder: e.placeholder || '',
        valor: (e.value || '').slice(0, 40), desabilitado: !!e.disabled,
        opcoes: e.tagName === 'SELECT'
            ? [...e.options].map(o => o.text.trim()) : undefined,
    }))"""

JS_BOTOES = """() => [...document.querySelectorAll('button, [role=button]')]
    .filter(e => e.offsetWidth || e.offsetHeight)
    .map(e => (e.innerText || '').trim().replace(/\\s+/g, ' '))
    .filter(t => t && t.length < 50)"""


def despejar(page, titulo: str) -> None:
    print(f"\n--- {titulo} | {page.url}")
    for c in page.evaluate(JS_CAMPOS):
        print("  " + json.dumps(c, ensure_ascii=False))
    print("  botoes:", page.evaluate(JS_BOTOES))


def guardar(page, nome: str) -> None:
    page.screenshot(path=str(SAIDA / f"{nome}.png"), full_page=True)
    (SAIDA / f"{nome}.html").write_text(page.content(), encoding="utf-8")


def digitar(page, seletor: str, valor: str) -> None:
    loc = page.locator(f"{seletor}:visible")
    campo = loc.nth(loc.count() - 1)
    campo.fill("")
    campo.type(valor, delay=60)
    campo.blur()


def main() -> int:
    from playwright.sync_api import sync_playwright

    SAIDA.mkdir(parents=True, exist_ok=True)
    usuario, senha = os.getenv("FAVORITA_USUARIO"), os.getenv("FAVORITA_SENHA")
    if not (usuario and senha):
        print("faltam FAVORITA_USUARIO/FAVORITA_SENHA no .env")
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False,
                                    args=argumentos_de_navegador_real())
        page = browser.new_context(
            locale="pt-BR", viewport={"width": 1400, "height": 1400}).new_page()
        page.set_default_timeout(30_000)

        page.goto(BASE + "/cotacao", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        despejar(page, "0. /cotacao sem login")
        guardar(page, "0_publico")

        page.goto(BASE + "/login", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        despejar(page, "1. /login")
        guardar(page, "1_login")
        page.locator('input[name="email"]').first.fill(usuario)
        page.locator('input[name="password"]').first.fill(senha)
        page.wait_for_timeout(1500)
        page.get_by_role("button", name="Entrar").click()
        page.wait_for_timeout(8000)
        print("\napos login:", page.url)
        guardar(page, "2_pos_login")

        page.goto(BASE + "/cotacao", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        despejar(page, "3. /cotacao logado")
        guardar(page, "3_cotacao")

        gatilho = page.locator('button[data-slot="dropdown-menu-trigger"]')
        print("\ngatilhos de menu:", gatilho.count())
        if gatilho.count():
            gatilho.first.click()
            page.wait_for_timeout(1000)
            itens = page.locator('[data-slot="dropdown-menu-item"]')
            for i in range(itens.count()):
                print(f"  item {i}: {itens.nth(i).inner_text()!r} "
                      f"habilitado={itens.nth(i).is_enabled()}")
            page.keyboard.press("Escape")

        if "--ate-destino" in sys.argv or "--ate-carga" in sys.argv:
            page.locator("select:visible").last.select_option(
                label="Remetente (CIF)")
            page.wait_for_timeout(1500)
            page.get_by_role("button", name="Próximo").last.click()
            page.wait_for_timeout(3000)
            despejar(page, "4. Origem (CIF)")
            guardar(page, "4_origem")
            page.get_by_role("button", name="Próximo").last.click()
            page.wait_for_timeout(3000)
            despejar(page, "5. Destino antes")
            digitar(page, 'input[name="document"]:not([disabled])',
                    CNPJ_DESTINATARIO)
            page.wait_for_timeout(5000)
            despejar(page, "5. Destino apos CNPJ")
            guardar(page, "5_destino")

        if "--ate-carga" in sys.argv:
            page.get_by_role("button", name="Próximo").last.click()
            page.wait_for_timeout(3000)
            despejar(page, "6. Carga")
            guardar(page, "6_carga")
            peso = page.locator('input[name="cubageValues.0.weight"]:visible')
            if peso.count():
                for t in ("1", "100", "1250"):
                    peso.first.fill("")
                    peso.first.type(t, delay=60)
                    page.wait_for_timeout(400)
                    print(f"  peso type({t!r}) -> {peso.first.input_value()!r}")

        print(f"\nevidencias em {SAIDA}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
