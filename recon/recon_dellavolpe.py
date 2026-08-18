#!/usr/bin/env python3
"""Recon do formulário real da Della Volpe. SÓ LEITURA.

    python recon/recon_dellavolpe.py            # headless
    python recon/recon_dellavolpe.py --headed   # ver a página

Abre a página, expande o accordion da cotação e despeja em recon_out/campos.json
todo campo de formulário que encontrar: tag, type, name, id, rótulo associado,
placeholder, required e as opções de cada <select>. Depois compara esses rótulos
com os que carriers/dellavolpe/mapping.py usa como chave de payload, que é o que
o adapter procura na página.

ESTE SCRIPT NUNCA ENVIA O FORMULÁRIO. Cada submit real vira uma cotação na fila
de um vendedor. Duas travas, de propósito redundantes:

  1. não existe nenhuma chamada de submit/click em botão aqui — o único clique é
     o que expande o accordion, sem o qual os campos nem existem no DOM;
  2. um page.route aborta toda requisição POST/PUT/PATCH para o domínio, então
     mesmo um clique acidental não chega na transportadora.

Não remova nenhuma das duas.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Este script vive em recon/, mas faz parte do projeto: importa de carriers/ e
# grava a evidencia em recon_out/ na RAIZ. Ancorar no __file__ deixa rodar de
# qualquer pasta -- sem isto, rodar de dentro de recon/ quebra o import e
# espalha print em recon/recon_out/, que ninguem procura.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from carriers.dellavolpe import mapping as m
from carriers.dellavolpe.adapter import URL_PRODUCAO, DellavolpeAdapter

SAIDA = RAIZ / "recon_out"
METODOS_BLOQUEADOS = {"POST", "PUT", "PATCH", "DELETE"}

# Roda no browser: devolve um registro por controle de formulário do documento.
# Procura o rótulo em quatro lugares porque o site mistura <label for>, wrapper
# <label>, aria-label e placeholder — e o adapter depende de achar algum deles.
JS_CAMPOS = """
() => {
  const rotulo = (el) => {
    if (el.id) {
      const lb = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lb && lb.innerText.trim()) return lb.innerText.trim();
    }
    const pai = el.closest('label');
    if (pai && pai.innerText.trim()) return pai.innerText.trim();
    const aria = el.getAttribute('aria-label');
    if (aria && aria.trim()) return aria.trim();
    const lbl = el.getAttribute('aria-labelledby');
    if (lbl) {
      const alvo = document.getElementById(lbl);
      if (alvo && alvo.innerText.trim()) return alvo.innerText.trim();
    }
    return '';
  };
  return [...document.querySelectorAll('input, select, textarea')]
    .filter(el => el.type !== 'hidden')
    .map(el => ({
      tag: el.tagName.toLowerCase(),
      type: (el.type || '').toLowerCase(),
      name: el.name || '',
      id: el.id || '',
      label: rotulo(el),
      placeholder: el.getAttribute('placeholder') || '',
      required: el.required === true,
      visivel: !!(el.offsetParent || el.getClientRects().length),
      options: el.tagName === 'SELECT'
        ? [...el.options].map(o => o.text.trim()).filter(Boolean).slice(0, 40)
        : [],
    }));
}
"""


def _bloquear_escrita(route, request) -> None:
    """Trava de rede: nada que não seja leitura sai daqui."""
    if request.method.upper() in METODOS_BLOQUEADOS:
        print(f"  [BLOQUEADO] {request.method} {request.url}")
        route.abort()
    else:
        route.continue_()


def coletar(headed: bool, url: str) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    SAIDA.mkdir(parents=True, exist_ok=True)
    campos: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_context(locale="pt-BR").new_page()
        page.set_default_timeout(45_000)
        page.route("**/*", _bloquear_escrita)
        try:
            page.goto(url, wait_until="networkidle")

            # sem expandir o accordion os campos não existem no DOM
            DellavolpeAdapter()._abrir_accordion(page)
            page.wait_for_timeout(1200)

            for frame in page.frames:
                try:
                    achados = frame.evaluate(JS_CAMPOS)
                except Exception as exc:
                    print(f"  frame {frame.url[:60]!r} ilegível: {exc}")
                    continue
                for c in achados:
                    c["frame"] = "main" if frame is page.main_frame else frame.url
                campos.extend(achados)

            (SAIDA / "pagina.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(SAIDA / "pagina.png"), full_page=True)

            html = page.content().lower()
            for sinal in ("recaptcha", "hcaptcha", "turnstile", "cf-challenge"):
                if sinal in html:
                    print(f"  ⚠ proteção anti-bot detectada: {sinal}")
        finally:
            browser.close()

    (SAIDA / "campos.json").write_text(
        json.dumps(campos, ensure_ascii=False, indent=2), encoding="utf-8")
    return campos


# ------------------------------------------------------------------ comparação
def _normalizar(s: str) -> str:
    """Compara rótulos ignorando caixa, asterisco de obrigatório e espaço extra."""
    return " ".join(s.replace("*", " ").split()).strip().lower()


def _candidatos(rotulo: str, campos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Campos que get_by_label/get_by_placeholder(rotulo, exact=False) casaria.

    exact=False casa por SUBSTRING: o rótulo do mapping precisa estar contido no
    texto da página, não ser igual a ele. Por isso 'Peso total' acha
    'Peso total (1 ~ 34.000kg)*' — e por isso um rótulo curto demais pode achar
    campos que não são o dele."""
    alvo = _normalizar(rotulo)
    return [c for c in campos
            if any(alvo in _normalizar(c[k]) for k in ("label", "placeholder") if c[k])]


def comparar(campos: list[dict[str, Any]]) -> int:
    """Confere os rótulos do mapping contra o que existe na página.

    Devolve quantos rótulos NÃO resolvem para exatamente um campo — tanto os
    que não acham nada quanto os ambíguos, porque o adapter usa .first e
    escolheria em silêncio."""
    esperados = [c.nome for c in m.campos_obrigatorios(_carga_referencia())]

    print("\n── rótulos do mapping vs. página real ───────")
    problemas = 0
    casados: set[str] = set()
    for rotulo in esperados:
        cands = _candidatos(rotulo, campos)
        if len(cands) == 1:
            marca = "✓"
            nota = f"name={cands[0]['name'] or '—'!r}"
        elif not cands:
            marca, nota, problemas = "✗", "NÃO ENCONTRADO na página", problemas + 1
        else:
            marca = "⚠"
            nota = ("AMBÍGUO, .first escolhe: "
                    + ", ".join(repr(c["name"] or c["id"]) for c in cands))
            problemas += 1
        casados.update(c["id"] or c["name"] for c in cands)
        print(f"  {marca} {rotulo:<45} {nota}")

    orfaos = [c for c in campos
              if c["visivel"] and (c["id"] or c["name"]) not in casados]
    if orfaos:
        print("\n── campos visíveis que o mapping não preenche ───")
        for c in orfaos:
            print(f"  · {c['tag']}[{c['type']}] name={c['name']!r} "
                  f"label={c['label']!r} required={c['required']}")

    return problemas


def _carga_referencia():
    """Carga FTL com medidas distintas e produto químico: força campos_obrigatorios
    a devolver TODOS os rótulos possíveis, inclusive os condicionais."""
    from decimal import Decimal

    from core.models import (
        CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
        Solicitante, Volume,
    )
    return CotacaoRequest(
        solicitante=Solicitante(nome="Recon", email="recon@exemplo.com.br",
                                whatsapp="27999887766"),
        servico=Servico.LOTACAO_FTL,
        veiculo_desejado="Truck (até 12.500 kg)",
        origem=Local(uf="ES", cidade="Vitória"),
        destino=Local(uf="SP", cidade="São Paulo"),
        remetente=Parte(cnpj="11.222.333/0001-81"),
        destinatario=Parte(cnpj="45.723.174/0001-10"),
        pagador_frete=Parte(cnpj="61.139.432/0001-72"),
        volumes=[
            Volume(qtd=1, comprimento_cm=Decimal(100), largura_cm=Decimal(50),
                   altura_cm=Decimal(40), peso_kg=Decimal(10)),
            Volume(qtd=1, comprimento_cm=Decimal(80), largura_cm=Decimal(40),
                   altura_cm=Decimal(30), peso_kg=Decimal(8)),
        ],
        mercadoria=Mercadoria(tipo_material="Solvente", is_perigoso=True,
                              fispq_path="fispq.pdf"),
        nota_fiscal=NotaFiscal(valor_total=Decimal(25_000)),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Recon read-only do form da Della Volpe")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--url", default=URL_PRODUCAO)
    args = ap.parse_args()

    print(f"── recon (SÓ LEITURA) ───────────────────────\n  {args.url}")
    campos = coletar(args.headed, args.url)
    print(f"  {len(campos)} campo(s) em recon_out/campos.json")

    divergentes = comparar(campos)
    print("\n" + ("✔ todos os rótulos do mapping existem na página"
                  if not divergentes
                  else f"✗ {divergentes} rótulo(s) divergente(s) — ajustar mapping"))
    return 1 if divergentes else 0


if __name__ == "__main__":
    sys.exit(main())
