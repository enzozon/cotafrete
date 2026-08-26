"""Captura os DOIS formularios da pagina da Della Volpe, com a geometria real.

Este script NAO envia o formulario — nao altere isso.

Por que existe: o recorte do print de evidencia e a UNIAO das caixas de todos
os campos visiveis da pagina. Medido em 26/08/2026, a pagina tem dois
Contact Form 7 visiveis ao mesmo tempo:

    o nosso, o modal de cotacao ... y  792 -> 1941   (~1150px)
    o "fale conosco" do rodape .... y 4403 -> 4848

A uniao dos dois cobre 4000px, entao o print sai com o formulario preenchido
no topo e milhares de pixels de pagina vazia embaixo. Na tela do vendedor o
cartao da Della Volpe fica tres vezes mais alto que os das outras.

A saida vira tests/fixtures/dv_dois_formularios.html, que e o que
tests/test_dellavolpe_print.py usa. Gerado e nao digitado de proposito: o bug
do popup da Camilo nasceu de eu deduzir seletor de um PRINT em vez do DOM.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carriers.dellavolpe.adapter import (            # noqa: E402
    DellavolpeAdapter, URL_PRODUCAO, argumentos_do_navegador)

DESTINO = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / \
    "dv_dois_formularios.html"

JS_COLETAR = """() => {
  const visivel = x => (x.offsetWidth || x.offsetHeight) && x.type !== 'hidden';
  const forms = [...document.querySelectorAll('form')].filter(
      f => [...f.querySelectorAll('input, select, textarea')].some(visivel));
  return forms.map(f => {
    const r = f.getBoundingClientRect();
    return {html: f.outerHTML,
            y: Math.round(r.y + window.scrollY),
            h: Math.round(r.height)};
  }).sort((a, b) => a.y - b.y);
}"""

MOLDE = """<!-- GERADO por recon/recon_dellavolpe_formularios.py — nao editar a mao.
     Capturado da pagina real da Della Volpe em {quando}.

     Geometria medida no site:
{mapa}
     A pagina real tem {altura}px de altura. Os espacadores abaixo reproduzem
     a distancia entre os formularios, que e o que faz a uniao das caixas
     estourar. Sem eles o bug nao aparece.
-->
<style>
  body {{ margin: 0; font-family: sans-serif; }}
  .espacador {{ background: #222; }}
  input, select, textarea {{ display: block; width: 700px; height: 36px;
                             margin: 12px 24px; box-sizing: border-box; }}
  input[type=hidden] {{ display: none; }}
  textarea {{ height: 80px; }}
</style>
{corpo}
"""


def limpar(html: str) -> str:
    """Fora script, iframe e atributos de evento: o fixture roda por file://
    e nao pode depender de rede nem executar nada do site."""
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<iframe\b.*?</iframe>", "", html, flags=re.S | re.I)
    html = re.sub(r'\son\w+="[^"]*"', "", html)
    return html


def main() -> int:
    adapter = DellavolpeAdapter()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch(
            headless=False, args=argumentos_do_navegador(False, False))
        page = navegador.new_context(
            locale="pt-BR",
            viewport={"width": 1280, "height": 2600}).new_page()
        page.set_default_timeout(45_000)
        page.goto(URL_PRODUCAO, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        adapter._abrir_accordion(page)
        page.wait_for_timeout(1500)
        formularios = page.evaluate(JS_COLETAR)
        altura = page.evaluate("document.body.scrollHeight")
        navegador.close()

    if len(formularios) < 2:
        print(f"esperava 2+ formularios visiveis, achei {len(formularios)}")
        return 1

    from datetime import datetime
    partes, anterior_fim = [], 0
    mapa = []
    for i, f in enumerate(formularios, 1):
        vao = max(f["y"] - anterior_fim, 0)
        partes.append(f'<div class="espacador" style="height:{vao}px"></div>')
        partes.append(limpar(f["html"]))
        anterior_fim = f["y"] + f["h"]
        mapa.append(f"       formulario {i}: y {f['y']} -> "
                    f"{f['y'] + f['h']}  ({f['h']}px)")

    DESTINO.write_text(
        MOLDE.format(quando=datetime.now().strftime("%d/%m/%Y %H:%M"),
                     mapa="\n".join(mapa), altura=altura,
                     corpo="\n".join(partes)),
        encoding="utf-8")
    print(f"escrito: {DESTINO}  ({DESTINO.stat().st_size} bytes)")
    for linha in mapa:
        print(linha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
