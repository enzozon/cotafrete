"""Mede com que frequencia a Della Volpe pede a caixinha. READ-ONLY.

    python recon/recon_dellavolpe_turnstile.py [quantas]

Abre o formulario publico N vezes, cada uma num contexto LIMPO, e conta em
quantas delas aparece um desafio visivel (Turnstile / reCAPTCHA v2 / hCaptcha).
NAO preenche campo nenhum, NAO envia nada, NAO resolve nada.

Serve para UMA decisao: a Della Volpe volta para AUTOMATICAS ou continua
assistida no envio? Ela saiu de la em 31/08/2026 porque o Cloudflare Turnstile
passou a barrar o envio — sem a caixinha marcada o Contact Form 7 recusa como
spam e nao gera e-mail nenhum (cotacoes #78 a #84). Enquanto estivesse na
lista, toda cotacao gastaria uma vaga de navegador para terminar num cartao
vermelho que ninguem consegue resolver.

Se o desafio aparece SEMPRE, a resposta e nao, e o envio continua com o
vendedor. Se aparece as vezes, da para tentar automatico e cair no cartao
assistido quando ele aparecer. O numero decide; o palpite, nao.

Contexto limpo a cada volta de proposito: cookie de sessao anterior mudaria a
pontuacao e o recon mediria a propria memoria em vez do comportamento do site.

Saida em recon_out/dellavolpe_turnstile/ (pasta no .gitignore).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(override=False)

from carriers.dellavolpe.adapter import (SELETORES_DESAFIO_CAPTCHA,  # noqa: E402
                                         URL_PRODUCAO, DellavolpeAdapter,
                                         argumentos_do_navegador)

SAIDA = RAIZ / "recon_out" / "dellavolpe_turnstile"
QUANTAS_PADRAO = 6

# Entre uma abertura e outra. Seis aberturas em rajada de um IP so parecem
# exatamente o que o Turnstile procura — e ai o recon mede a propria pressa
# em vez do comportamento normal do site.
ESPERA_ENTRE_S = 8


def main() -> int:
    from playwright.sync_api import sync_playwright

    quantas = int(sys.argv[1]) if len(sys.argv) > 1 else QUANTAS_PADRAO
    SAIDA.mkdir(parents=True, exist_ok=True)
    adapter = DellavolpeAdapter()
    voltas: list[dict] = []

    # headless=False, e nao o padrao. O proprio adapter forca janela de verdade
    # no envio real porque o reCAPTCHA v3 do site pontua Chromium headless como
    # robo (ver `cotar`). Medir com headless daria um numero mais pessimista do
    # que a realidade — seria medir uma configuracao que o envio real nunca
    # usa. A janela vai para fora da tela, como la.
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False, args=argumentos_do_navegador(False, False))
        try:
            for i in range(1, quantas + 1):
                contexto = browser.new_context(
                    locale="pt-BR", viewport={"width": 1400, "height": 1200})
                page = contexto.new_page()
                page.set_default_timeout(45_000)
                volta = {"n": i,
                         "quando": datetime.now().isoformat(timespec="seconds")}
                try:
                    page.goto(URL_PRODUCAO, wait_until="domcontentloaded")
                    # state=attached: os <form> deste site tem altura zero,
                    # entao "visible" nunca e satisfeito. Copiado do `cotar`.
                    page.wait_for_selector("form", state="attached",
                                           timeout=45_000)
                    page.wait_for_timeout(2_000)
                    # O formulario mora num acordeao FECHADO. Medir sem abrir
                    # media a pagina inicial, nao o formulario — e um widget
                    # que so existe dentro dele nunca apareceria. A primeira
                    # rodada deste recon errou exatamente assim.
                    adapter._abrir_accordion(page)
                    page.wait_for_timeout(4_000)
                    volta["url"] = page.url
                    volta["desafio"] = adapter._tem_captcha(page)

                    # O HTML cru, alem dos iframes. Turnstile em modo
                    # "managed" nasce como <div class="cf-turnstile"> e so
                    # vira iframe depois; e o campo escondido
                    # cf-turnstile-response e o que o formulario ENVIA. Sem
                    # olhar isso, "nenhum iframe" pode ser lido como "nao tem
                    # protecao" quando na verdade ela esta la, invisivel.
                    html = page.content()
                    volta["marcas_no_html"] = {
                        marca: html.lower().count(marca)
                        for marca in ("cf-turnstile", "turnstile",
                                      "challenges.cloudflare.com",
                                      "g-recaptcha-response", "grecaptcha",
                                      "wpcf7")}
                    (SAIDA / f"volta{i}.html").write_text(html,
                                                          encoding="utf-8")

                    # A MEDIDA QUE DECIDE. A Della Volpe tem script proprio
                    # (`dellaVolpeTurnstileFix`) que so chama turnstile.render
                    # nos `.wpcf7-turnstile` VISIVEIS e com data-sitekey. Ou
                    # seja: o widget existe no HTML de toda pagina, mas so vira
                    # desafio de verdade no formulario que estiver aberto.
                    # Contar iframe nao responde isso; contar isto responde.
                    volta["wpcf7_turnstile"] = page.evaluate(
                        """() => {
                            const es = [...document.querySelectorAll(
                                '.wpcf7-turnstile')];
                            const vis = e => {
                                const r = e.getBoundingClientRect();
                                const s = getComputedStyle(e);
                                return r.width > 0 && r.height > 0
                                    && s.display !== 'none'
                                    && s.visibility !== 'hidden';
                            };
                            return {
                                total: es.length,
                                visiveis: es.filter(vis).length,
                                com_sitekey: es.filter(
                                    e => e.dataset.sitekey).length,
                                visiveis_com_sitekey: es.filter(
                                    e => vis(e) && e.dataset.sitekey).length,
                            };
                        }""")
                    # QUAL seletor casou: se um dia a Della Volpe trocar de
                    # provedor, o recon mostra a troca em vez de so um numero.
                    volta["seletores"] = {
                        sel: page.locator(sel).count()
                        for sel in SELETORES_DESAFIO_CAPTCHA}
                    page.screenshot(path=str(SAIDA / f"volta{i}.png"),
                                    full_page=True)
                except Exception as exc:
                    volta["erro"] = f"{type(exc).__name__}: {exc}"[:200]
                finally:
                    voltas.append(volta)
                    print(f"  volta {i}/{quantas}: "
                          f"desafio={volta.get('desafio')} "
                          f"{volta.get('erro', '')}")
                    contexto.close()
                if i < quantas:
                    time.sleep(ESPERA_ENTRE_S)
        finally:
            browser.close()

    com = sum(1 for v in voltas if v.get("desafio"))
    erros = sum(1 for v in voltas if v.get("erro"))
    (SAIDA / "achados.json").write_text(
        json.dumps({"quantas": quantas, "com_desafio": com, "erros": erros,
                    "voltas": voltas}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    print()
    print(f"RESULTADO: desafio em {com} de {quantas} aberturas "
          f"({erros} erro(s) de carregamento)")
    print(f"saida em {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
