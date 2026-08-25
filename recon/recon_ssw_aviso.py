"""Captura o popup de recusa do SSW — o que a cotacao #20 mostrou e nos nao lemos.

    python recon/recon_ssw_aviso.py

Reproduz a carga da cotacao #20 de producao (25/08/2026, Arthur Carvalho), que
a Camilo RECUSA por falta de tabela negociada para o CNPJ pagador. Como a
resposta e uma recusa, nada e criado do lado da transportadora.

Nao reimplementa o fluxo: usa o proprio CamiloAdapter e troca so o
`_ler_e_fotografar`, para despejar o popup no instante em que ele esta na
tela — antes de o codigo de producao decidir o que fazer com ele.

Saida em recon_out/ssw_aviso/ (pasta no .gitignore).
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv

load_dotenv(override=False)

from carriers.camilo.adapter import CamiloAdapter          # noqa: E402
from core.models import (CotacaoRequest, Local, Mercadoria,  # noqa: E402
                         NotaFiscal, Parte, Servico, Solicitante, TipoFrete,
                         Volume)

SAIDA = RAIZ / "recon_out" / "ssw_aviso"

# Candidatos a conteiner do aviso. Os tres primeiros sao os que estavam no
# adapter (deduzidos de um PRINT, nao do DOM) — a lista existe para mostrar
# preto no branco quais casam e quais nao.
CANDIDATOS = ("#errormsg", "#errorpanel", "#alerta", "div[role='dialog']",
              ".ui-dialog-content")


def carga_da_20() -> CotacaoRequest:
    """10 volumes de 30x30x30 cm, 1 kg cada. CIF: quem paga e o remetente."""
    return CotacaoRequest(
        solicitante=Solicitante(nome="recon", email="recon@ex.com",
                                whatsapp="27999887766"),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf="SP", cidade="São Bernardo do Campo", cep="09895003"),
        destino=Local(uf="ES", cidade="Vila Velha", cep="29105770"),
        remetente=Parte(cnpj="60042686000105"),      # HERCULES — o que e recusado
        destinatario=Parte(cnpj="05954058000198"),
        tipo_frete=TipoFrete.CIF,
        volumes=[Volume(qtd=10, comprimento_cm=Decimal(30),
                        largura_cm=Decimal(30), altura_cm=Decimal(30),
                        peso_kg=Decimal(1))],
        mercadoria=Mercadoria(tipo_material="luva"),
        nota_fiscal=NotaFiscal(valor_total=Decimal("568.77")),
    )


def despejar_aviso(page) -> dict:
    """Tudo o que da para saber sobre o popup enquanto ele esta na tela."""
    achados = {}
    for sel in CANDIDATOS:
        try:
            loc = page.locator(sel).first
            n = loc.count()
            achados[sel] = {
                "existe": bool(n),
                "visivel": bool(n) and loc.is_visible(timeout=800),
                "texto": (loc.inner_text() if n else "")[:400],
            }
        except Exception as e:
            achados[sel] = {"erro": f"{type(e).__name__}: {e}"}

    for nome, js in (
        ("errormsg_outerHTML",
         "() => (document.getElementById('errormsg')||{}).outerHTML || ''"),
        ("ancestrais_do_OK", """() => {
            const links = [...document.querySelectorAll('a')]
                .filter(a => /\bOK\b/i.test(a.textContent || ''));
            if (!links.length) return '';
            let e = links[0], cadeia = [];
            while (e && cadeia.length < 6) {
                cadeia.push(e.tagName + (e.id ? '#' + e.id : '')
                            + (e.className ? '.' + e.className : ''));
                e = e.parentElement;
            }
            return cadeia.join('  <  ');
        }"""),
    ):
        try:
            achados[nome] = page.evaluate(js)
        except Exception as e:
            achados[nome] = f"{type(e).__name__}: {e}"
    return achados


def main() -> int:
    SAIDA.mkdir(parents=True, exist_ok=True)
    adapter = CamiloAdapter()
    # Engancha em `_ler_e_fotografar`, que e o instante logo depois do clique
    # em simular e ANTES de qualquer decisao sobre fechar o popup.
    original = CamiloAdapter._ler_e_fotografar
    capturado: dict = {}

    def espiao(self, page, run):
        try:
            page.screenshot(path=str(SAIDA / "com_popup.png"), timeout=10_000)
        except Exception as e:
            capturado["print_falhou"] = str(e)
        capturado.update(despejar_aviso(page))
        try:
            (SAIDA / "pagina_com_popup.html").write_text(
                page.content(), encoding="utf-8")
        except Exception as e:
            capturado["html_falhou"] = str(e)
        return original(self, page, run)

    CamiloAdapter._ler_e_fotografar = espiao
    try:
        res = adapter.cotar(carga_da_20(), confirmar_envio=True)
    finally:
        CamiloAdapter._ler_e_fotografar = original

    (SAIDA / "achados.json").write_text(
        json.dumps(capturado, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f'status  : {res.status.value}')
    print(f'erro    : {res.erro}')
    print(f'recusa  : {res.motivo_recusa}')
    print()
    for sel in CANDIDATOS:
        d = capturado.get(sel, {})
        print(f'  {sel:24} existe={d.get("existe")!s:5} '
              f'visivel={d.get("visivel")!s:5} texto={d.get("texto","")[:60]!r}')
    print()
    print('cadeia do link OK:', capturado.get("ancestrais_do_OK", "")[:200])
    print()
    print('outerHTML do #errormsg:')
    print(capturado.get("errormsg_outerHTML", "")[:900])
    print()
    print(f'saida em {SAIDA}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
