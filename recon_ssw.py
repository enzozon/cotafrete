"""Recon READ-ONLY do SSW (sistema.ssw.inf.br). Lê, não cota.

    python recon_ssw.py            # só a tela de login, sem credenciais
    python recon_ssw.py --logar    # entra e mapeia a tela de cotação

O SSW é uma plataforma usada por várias transportadoras; cada uma tem seu
domínio. Telas:

    ssw0422  login
    menu01   menu principal
    ssw1608  110 - Cotação de Fretes pelo Cliente

Credenciais no .env: SSW_DOMINIO, SSW_CPF, SSW_USUARIO, SSW_SENHA.
Nunca são impressas nem gravadas nas evidências.

⚠ Sem `--logar` este script não envia NADA: a trava de rede aborta qualquer
POST. Com `--logar` ele faz login (é POST) mas não dispara cotação — o botão
de calcular não é clicado.

Saída em recon_out/ssw/ (pasta já no .gitignore).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

URL_LOGIN = "https://sistema.ssw.inf.br/bin/ssw0422"
URL_MENU = "https://sistema.ssw.inf.br/bin/menu01"
URL_COTACAO = "https://sistema.ssw.inf.br/bin/ssw1608"

SAIDA = Path("recon_out/ssw")

JS_CAMPOS = """() => {
  const rotulo = (e) => {
    if (e.id) {
      const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
      if (l) return l.innerText.trim();
    }
    // O SSW é HTML antigo, em tabela: o rótulo costuma ser a célula anterior.
    const td = e.closest('td');
    const antes = td && td.previousElementSibling;
    if (antes && antes.innerText.trim()) return antes.innerText.trim().slice(0, 40);
    const pai = e.closest('label');
    if (pai) return pai.innerText.trim();
    return '';
  };
  return [...document.querySelectorAll('input, select, textarea')].map(e => ({
    tipo: e.type || e.tagName.toLowerCase(),
    name: e.name || '',
    id: e.id || '',
    rotulo: rotulo(e),
    maxlength: e.maxLength > 0 ? e.maxLength : null,
    valor: (e.value || '').slice(0, 30),
    visivel: !!(e.offsetWidth || e.offsetHeight),
  }));
}"""


def despejar(page, titulo: str) -> None:
    campos = page.evaluate(JS_CAMPOS)
    visiveis = [c for c in campos if c["visivel"]]
    print(f"\n--- {titulo} ({len(visiveis)} visíveis de {len(campos)}) ---")
    for c in visiveis:
        print("  " + json.dumps(c, ensure_ascii=False))
    print("  url:", page.url)


def preencher_login(page) -> None:
    """Preenche domínio/CPF/usuário/senha e envia.

    Os campos do SSW não têm rótulo associado por `for`; o mapeamento sai do
    recon sem login, que roda antes justamente para isso."""
    # Casado por NAME, não por posição. Os maxlength confirmam o mapeamento:
    # f1=3 (domínio), f2=11 (CPF), f3=8 (usuário), f4=8 (senha).
    campos = {
        "f1": os.getenv("SSW_DOMINIO", ""),
        "f2": os.getenv("SSW_CPF", ""),
        "f3": os.getenv("SSW_USUARIO", ""),
        "f4": os.getenv("SSW_SENHA", ""),
    }
    for nome, valor in campos.items():
        if valor:
            page.locator(f'input[name="{nome}"]').first.fill(valor)
            page.wait_for_timeout(200)
    page.keyboard.press("Enter")


def main() -> int:
    from playwright.sync_api import sync_playwright

    logar = "--logar" in sys.argv
    SAIDA.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless="--headed" not in sys.argv)
        page = browser.new_context(
            locale="pt-BR", viewport={"width": 1500, "height": 1000}).new_page()
        page.set_default_timeout(30_000)

        if not logar:
            # sem login, nada de POST — nem por engano
            page.route("**/*", lambda r, q: r.abort()
                       if q.method.upper() != "GET" else r.continue_())

        try:
            page.goto(URL_LOGIN, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            print("titulo:", page.title())
            despejar(page, "1. Login")
            page.screenshot(path=str(SAIDA / "login.png"), full_page=True)
            (SAIDA / "login.html").write_text(page.content(), encoding="utf-8")

            if not logar:
                print("\n(sem --logar: parando aqui, nada foi enviado)")
                return 0

            faltando = [k for k in ("SSW_DOMINIO", "SSW_USUARIO", "SSW_SENHA")
                        if not os.getenv(k)]
            if faltando:
                print(f"\nFaltam no .env: {', '.join(faltando)}")
                return 2

            print("\n2. entrando...")
            preencher_login(page)
            page.wait_for_timeout(4000)
            print("   url apos login:", page.url)
            page.screenshot(path=str(SAIDA / "pos_login.png"), full_page=True)

            # A pergunta do Enzo: dá para ir direto à cotação, pulando o menu?
            print(f"\n3. indo DIRETO para {URL_COTACAO}")
            page.goto(URL_COTACAO, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            print("   url final:", page.url)
            direto = "ssw1608" in page.url and "0422" not in page.url
            print("   atalho funciona?",
                  "SIM" if direto else "NAO - voltou para o login")

            despejar(page, "4. Cotação (ssw1608)")
            page.screenshot(path=str(SAIDA / "cotacao.png"), full_page=True)
            (SAIDA / "cotacao.html").write_text(page.content(), encoding="utf-8")
            print(f"\nevidências em {SAIDA.resolve()}")
            return 0

        except Exception as exc:
            print(f"\nERRO: {type(exc).__name__}: {exc}")
            page.screenshot(path=str(SAIDA / "erro.png"), full_page=True)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
