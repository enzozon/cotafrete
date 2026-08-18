"""Recon da calculadora do painel novo da Jadlog. LÊ, não cota.

    python recon/recon_jadlog_painel.py [--headed]

Fluxo: /login -> /painel -> /painel/calculadora

Este script FAZ login (precisa: a calculadora fica atrás dele) e NÃO clica em
nenhum botão de calcular, cotar, solicitar ou salvar. O objetivo é uma coisa
só: descobrir quais campos existem e se a nossa ficha cobre todos.

Credenciais saem do .env (JADLOG_PAINEL_USUARIO / JADLOG_PAINEL_SENHA) e nunca
são impressas nem gravadas nas evidências.

Saída em recon_out/jadlog_painel/ (pasta já no .gitignore).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Este script vive em recon/, mas faz parte do projeto: importa de carriers/ e
# grava a evidencia em recon_out/ na RAIZ. Ancorar no __file__ deixa rodar de
# qualquer pasta -- sem isto, rodar de dentro de recon/ quebra o import e
# espalha print em recon/recon_out/, que ninguem procura.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(override=False)

URL_LOGIN = "https://jadlogentregas.com.br/login"
URL_PAINEL = "https://jadlogentregas.com.br/painel"
URL_CALCULADORA = "https://jadlogentregas.com.br/painel/calculadora"

SAIDA = RAIZ / "recon_out" / "jadlog_painel"

# Botões que NÃO podem ser clicados neste script. Existe para documentar a
# intenção: o recon lê, não dispara nada no sistema da transportadora.
NUNCA_CLICAR = ("calcular", "cotar", "simular", "solicitar", "salvar",
                "enviar", "confirmar", "coletar", "gerar")

JS_CAMPOS = """() => {
    const rotulo = (e) => {
        if (e.id) {
            const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
            if (l) return l.innerText.trim();
        }
        const pai = e.closest('label');
        if (pai) return pai.innerText.trim();
        if (e.getAttribute('aria-label')) return e.getAttribute('aria-label');
        // campo de SPA costuma ter o rótulo num irmão logo acima
        const bloco = e.closest('div');
        if (bloco) {
            const t = bloco.innerText.trim().split('\\n')[0];
            if (t && t.length < 60) return t;
        }
        return '';
    };
    return [...document.querySelectorAll('input, select, textarea')].map(e => ({
        tag: e.tagName.toLowerCase(),
        type: e.type || '',
        name: e.name || '',
        id: e.id || '',
        rotulo: rotulo(e),
        placeholder: e.placeholder || '',
        required: !!e.required,
        visivel: !!(e.offsetWidth || e.offsetHeight),
        valor: (e.value || '').slice(0, 30),
        opcoes: e.tagName === 'SELECT'
            ? [...e.options].map(o => `${o.value}=${o.text}`).slice(0, 30) : [],
    }));
}"""

JS_BOTOES = """() => [...document.querySelectorAll('button, [role=button], a.btn')]
    .filter(e => e.offsetWidth || e.offsetHeight)
    .map(e => (e.innerText || '').trim())
    .filter(t => t && t.length < 40)"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    usuario = os.getenv("JADLOG_PAINEL_USUARIO")
    senha = os.getenv("JADLOG_PAINEL_SENHA")
    if not usuario or not senha:
        print("Faltam JADLOG_PAINEL_USUARIO / JADLOG_PAINEL_SENHA no .env")
        return 2

    SAIDA.mkdir(parents=True, exist_ok=True)
    headed = "--headed" in sys.argv

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_context(
            locale="pt-BR", viewport={"width": 1500, "height": 1000}).new_page()
        page.set_default_timeout(45_000)
        try:
            print(f"1. abrindo {URL_LOGIN}")
            page.goto(URL_LOGIN, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            # banner de cookies atrapalha o clique no botao de entrar
            for texto in ("Aceitar todos os cookies", "Rejeitar Todos"):
                alvo = page.get_by_text(texto, exact=False)
                if alvo.count() and alvo.first.is_visible():
                    alvo.first.click()
                    page.wait_for_timeout(600)
                    break

            page.locator('input[type="email"]').first.fill(usuario)
            page.locator('input[type="password"]').first.fill(senha)
            page.get_by_role("button", name="Entrar").first.click()

            print("2. esperando sair da tela de login")
            page.wait_for_url(lambda u: "/login" not in u, timeout=45_000)
            page.wait_for_timeout(3000)
            print(f"   entrou em: {page.url}")

            print(f"3. abrindo {URL_CALCULADORA}")
            page.goto(URL_CALCULADORA, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            print(f"   url final: {page.url}")

            if "/login" in page.url:
                print("   !! voltou para o login — sessao nao persistiu")
                page.screenshot(path=str(SAIDA / "falha_login.png"), full_page=True)
                return 1

            campos = page.evaluate(JS_CAMPOS)
            visiveis = [c for c in campos if c["visivel"]]
            print(f"\n{len(visiveis)} campos visiveis "
                  f"({len(campos)} no total, incluindo ocultos):\n")
            for c in visiveis:
                print("  " + json.dumps(c, ensure_ascii=False))

            botoes = page.evaluate(JS_BOTOES)
            print(f"\nbotoes na tela: {botoes}")
            print(f"(nenhum foi clicado; lista de proibidos: {NUNCA_CLICAR})")

            (SAIDA / "campos.json").write_text(
                json.dumps(campos, ensure_ascii=False, indent=2), encoding="utf-8")
            (SAIDA / "pagina.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(SAIDA / "calculadora.png"), full_page=True)
            print(f"\nevidencias em {SAIDA.resolve()}")
            return 0

        except Exception as exc:
            print(f"\nERRO: {type(exc).__name__}: {exc}")
            page.screenshot(path=str(SAIDA / "erro.png"), full_page=True)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
