"""Mede a busca de CNPJ do portal da Generoso. READ-ONLY: nao cota.

    python recon/recon_generoso_cnpj.py

Faz login, chega na etapa "Dados da origem" e digita um CNPJ, capturando
TODAS as chamadas de rede. Roda duas vezes: com um CNPJ que a Generoso
conhece e com um que ela nao conhece. NAO avanca da etapa da origem e NAO
envia cotacao nenhuma.

Existe por causa da cotacao #56 (28/08/2026): o CNPJ 41.747.639/0001-12 (um
fornecedor) nao trouxe endereco nenhum, o adapter levantou RuntimeError e a
retentativa repetiu TRES vezes uma resposta que o site ja tinha dado. Para
virar RECUSADO em vez de ERRO e preciso saber distinguir "a Generoso nao tem
esse CNPJ" de "o AJAX nao voltou a tempo" — e a tela nao diz nada nos dois
casos ("(nenhuma mensagem visivel)").

Saida em recon_out/generoso_cnpj/ (pasta no .gitignore).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(override=False)

from carriers.generoso.adapter import (                       # noqa: E402
    BOTAO_PROXIMO, ESPERA_BUSCA_MS, SELETOR_CNPJ_LIVRE,
    TIPO_PAGADOR_DESTINATARIO, URL, GenerosoAdapter)

SAIDA = RAIZ / "recon_out" / "generoso_cnpj"

CNPJ_CONHECIDO = "20.837.281/0001-49"      # a Uniao, cliente da Generoso
CNPJ_DESCONHECIDO = "41.747.639/0001-12"   # o fornecedor da #56

CAMPOS_ENDERECO = ("cep", "city", "state", "neighborhood", "address")


def _sondar(adapter, p, cnpj: str) -> dict:
    """Digita um CNPJ na etapa da origem e devolve o que o site fez."""
    trafego: list[dict] = []
    browser = p.chromium.launch(**adapter.opcoes_do_navegador())
    page = browser.new_context(
        locale="pt-BR", viewport={"width": 1400, "height": 1400}).new_page()
    page.set_default_timeout(45_000)

    def anotar(resposta):
        # so o que o proprio portal chama; o resto e analytics e imagem
        if "generoso" not in resposta.url or resposta.request.resource_type in (
                "image", "font", "stylesheet", "script", "document"):
            return
        registro = {"url": resposta.url[:160], "metodo": resposta.request.method,
                    "status": resposta.status}
        try:
            registro["corpo"] = resposta.text()[:700]
        except Exception as exc:
            registro["corpo"] = f"<ilegivel: {type(exc).__name__}>"
        trafego.append(registro)

    try:
        adapter._entrar(page)
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("select")
        page.wait_for_timeout(3_000)

        # etapa 1: tipo pagador. FOB de proposito — e o modo da #56, e o
        # unico em que a ORIGEM e digitada (no CIF ela vem travada na
        # conta e quem se digita e o destino). Ver pontas_a_digitar.
        page.locator("select:visible").last.select_option(
            label=TIPO_PAGADOR_DESTINATARIO)
        page.wait_for_timeout(1_500)
        page.get_by_role("button", name=BOTAO_PROXIMO).last.click()
        page.wait_for_timeout(2_500)

        # etapa 2: origem — o unico ponto que interessa
        page.on("response", anotar)
        adapter._digitar(page, SELETOR_CNPJ_LIVRE, cnpj)
        adapter._campo(page, SELETOR_CNPJ_LIVRE).blur()
        page.wait_for_timeout(ESPERA_BUSCA_MS + 4_000)   # folga sobre o adapter

        endereco = {c: adapter._campo(page, f'input[name="{c}"]').input_value()
                    for c in CAMPOS_ENDERECO}
        texto = " ".join(page.locator("body").inner_text().split())

        page.screenshot(path=str(SAIDA / f"origem_{cnpj[:2]}.png"))
        return {"cnpj": cnpj, "endereco": endereco, "trafego": trafego,
                "tela": texto[:900]}
    finally:
        browser.close()


def main() -> int:
    from playwright.sync_api import sync_playwright

    SAIDA.mkdir(parents=True, exist_ok=True)
    adapter = GenerosoAdapter()
    achados = {}

    with sync_playwright() as p:
        for rotulo, cnpj in (("conhecido", CNPJ_CONHECIDO),
                             ("desconhecido", CNPJ_DESCONHECIDO)):
            print(f"\n=== {rotulo}: {cnpj}")
            achados[rotulo] = _sondar(adapter, p, cnpj)
            r = achados[rotulo]
            print(f"  endereco: {r['endereco']}")
            for c in r["trafego"]:
                print(f"  {c['metodo']:>5} {c['status']}  {c['url']}")
                print(f"        {c['corpo'][:300]}")

    (SAIDA / "achados.json").write_text(
        json.dumps(achados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaida em {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
