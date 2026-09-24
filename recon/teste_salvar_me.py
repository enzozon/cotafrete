#!/usr/bin/env python3
"""Teste real de SALVAR (rascunho) no Mercado Eletrônico — autorizado pelo
usuário em 23/09/2026. NUNCA envia.

    python recon/teste_salvar_me.py --conta uniao --cotacao 23052403

Preenche o cabeçalho e SÓ o item 1 com valores marcados "TESTE DO ROBÔ -
NÃO ENVIAR", clica em Salvar e depois relê a página e a lista de pendências
para ver o que o rascunho mudou. Evidência em recon_out/me/<conta>/4x_*.

TRÊS TRAVAS contra envio (a mesma ideia vai para o robô):

  1. clique: só o botão cujo title é "Salvar informações para enviar mais
     tarde"; qualquer outro texto aborta antes de clicar;
  2. form: `HTMLFormElement.prototype.submit` só submete o form RespCota com
     Acao == "9"; qualquer outro vira no-op;
  3. rede: todo POST ao ME (*.me.com.br e *.mercadoe.com) é abortado, exceto
     RespostaCotaItem.asp cujo corpo tenha exatamente um Acao e ele seja "9",
     e a busca de leitura da lista de pendências.

Resultado do teste (23/09/2026, UNIÃO 23052403) em docs/MERCADO_ELETRONICO.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mercado_eletronico.regras import data_entrega  # noqa: E402
from recon.recon_me import (  # noqa: E402
    RE_BUSCA_LEITURA, SAIDA, URL_COTACAO, URL_PENDENCIAS, _despejar, _do_me, _watchdog,
)

TITULO_SALVAR = "Salvar informações para enviar mais tarde"
MARCA = "TESTE DO ROBO - NAO ENVIAR"
ACAO_SALVAR = "9"
CONFIRM_SALVAR = "Você verificou todas as informações digitadas?"

JS_TRAVA_FORM = """
(() => {
  const original = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function () {
    const acao = this.elements && this.elements['Acao'] ? this.elements['Acao'].value : null;
    if (this.name === 'RespCota' && acao === '9') {
      console.warn('[TRAVA] form RespCota Acao=9 liberado (salvar)');
      return original.call(this);
    }
    console.warn('[TRAVA] form.submit BLOQUEADO: ' + this.name + ' Acao=' + acao);
  };
  window.open = () => null;
})();
"""


def post_liberado(url: str, corpo: str) -> bool:
    """Só o POST de salvar passa: RespostaCotaItem.asp com um único Acao=9."""
    if not urlparse(url).path.lower().endswith("/respostacotaitem.asp"):
        return False
    return parse_qs(corpo or "", keep_blank_values=True).get("Acao") == [ACAO_SALVAR]


class TravaRede:
    def __init__(self, destino: Path):
        self.log = (destino / "requisicoes_salvar.jsonl").open("a", encoding="utf-8")
        self.liberados = 0

    def __call__(self, route, request):
        metodo = request.method.upper()
        if _do_me(urlparse(request.url).hostname or "") and metodo != "GET":
            corpo = request.post_data or ""
            ok = post_liberado(request.url, corpo) or bool(RE_BUSCA_LEITURA.match(request.url))
            reg = {"t": time.strftime("%H:%M:%S"), "metodo": metodo, "url": request.url[:200],
                   "liberado": ok, "acao": parse_qs(corpo).get("Acao")}
            self.log.write(json.dumps(reg, ensure_ascii=False) + "\n")
            self.log.flush()
            print(f"  [{'LIBERADO' if ok else 'BLOQUEADO'}] {metodo} {request.url[:90]} Acao={reg['acao']}")
            if not ok:
                return route.abort()
            self.liberados += 1
        return route.continue_()


def _campo(page, nome: str, valor: str) -> None:
    # o ME deixa espaço no fim de alguns names ("atrib_CidadeEstado_1_1_0_0 ")
    loc = page.locator(f"[name='{nome}'], [name='{nome} ']").first
    tag = loc.evaluate("e => e.tagName")
    if tag == "SELECT":
        loc.select_option(valor)
    else:
        # fill direto: digitar tecla a tecla passa pela máscara de dinheiro do
        # ME, que desloca os dígitos ("1,00" virou 1.000,00 no total).
        loc.fill(valor)
    # keyup: o Prazo calcula a data de entrega nele; blur: formata e recalcula
    loc.evaluate("""e => {
        e.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true, key: '0'}));
        e.dispatchEvent(new Event('change', {bubbles:true}));
        e.dispatchEvent(new Event('blur'));
        if (e.onblur) e.onblur();
    }""")


def preencher(page, validade: date) -> None:
    cab = {
        "IcoTerms": "FOB", "atrib_CidadeEstado_1_1_0_0": "Frete FOB",
        "NumFoneCota": "2732991664", "MoedaCot": "BRL",
        "ValidadePropostaAux": validade.strftime("%d/%m/%Y"), "ObsForn": MARCA,
    }
    item = {
        "Preco1": "1,00", "UnidadeResp1": "UN", "TipoImposto1": "1", "IPI1": "0,00", "IPIIncluso1": "I",
        "ICMS1": "12,00", "ICMSIncluso1": "S", "PIS1": "0,00", "PISIncluso1": "I",
        "COFINS1": "0,00", "COFINSIncluso1": "I", "NCM1": "4821.90.00", "Prazo1": "30",
        # o ME não calcula a data sozinho no headless: vai a nossa regra
        "DataEntregaItemAux1": data_entrega(30, date.today()).strftime("%d/%m/%Y"),
        "Fabricante1": "TESTE", "Observacao1": MARCA, "OrigMat1": "992",
        "SubstituicaoTributaria1": "N", "AliquotaSubstituicaoTributaria1": "0,00",
        "ValorSubstituicaoTributaria1": "0,00", "BaseCalculo1": "100,00",
        "BaseCalculoImposto1": "S",
    }
    for nome, valor in {**cab, **item}.items():
        _campo(page, nome, valor)
    # itens não respondidos: o ME já traz BaseCalculo=100,00 e trata isso como
    # item começado ("Base de cálculo preenchida... informe o Preço"). Vazio = ok.
    total = int(page.locator("[name='MaxItem']").first.input_value())
    for n in range(2, total + 1):
        page.locator(f"[name='BaseCalculo{n}']").first.fill("")
    page.locator("#chkItem_1").check()


def clicar_salvar(page) -> None:
    botao = page.locator("#MEComponentManager_MEButton_5")
    titulo = (botao.get_attribute("title") or "") + (botao.get_attribute("data-original-title") or "")
    texto = botao.inner_text().strip()
    if TITULO_SALVAR not in titulo or texto != "Salvar" or "comprador" in titulo.lower():
        raise SystemExit(f"TRAVA: botão não é o Salvar esperado (title={titulo!r}, texto={texto!r})")
    botao.click()


def main() -> None:
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("--conta", required=True, choices=["ventura", "uniao"])
    ap.add_argument("--cotacao", required=True)
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    _watchdog()
    destino = SAIDA / a.conta
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not a.headed)
        ctx = browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1500, "height": 950},
                                  storage_state=str(destino / "estado.json"))
        ctx.add_init_script(JS_TRAVA_FORM)
        trava = TravaRede(destino)
        ctx.route("**/*", trava)
        page = ctx.new_page()
        page.set_default_timeout(60_000)
        salvando = {"sim": False}

        def dialogo(d):
            # o ÚNICO confirm aceito é o do Salvar, e só durante o clique nele
            aceita = d.type in ("alert", "beforeunload") or (
                d.type == "confirm" and salvando["sim"] and d.message.strip() == CONFIRM_SALVAR)
            print(f"  [DIALOG {d.type}] {d.message[:300]} -> {'aceito' if aceita else 'cancelado'}")
            d.accept() if aceita else d.dismiss()

        page.on("dialog", dialogo)
        page.on("pageerror", lambda e: print("  [JS ERRO]", str(e)[:200]))
        page.on("console", lambda m: print("  [CONSOLE]", m.text[:150]) if "TRAVA" in m.text else None)
        try:
            url = URL_COTACAO.format(n=a.cotacao)
            page.goto(url, wait_until="networkidle")
            preencher(page, date.today() + timedelta(days=30))
            _despejar(page, destino, "40_preenchido")
            salvando["sim"] = True
            clicar_salvar(page)
            try:
                page.wait_for_load_state("networkidle", timeout=60_000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            salvando["sim"] = False
            print("  depois de salvar:", page.url, "| POSTs liberados:", trava.liberados)
            _despejar(page, destino, "41_pos_salvar")
            page.goto(url, wait_until="networkidle")
            _despejar(page, destino, "42_relida")
            jsons = []
            page.on("response", lambda r: jsons.append(r) if "transactions/search" in r.url else None)
            page.goto(URL_PENDENCIAS, wait_until="networkidle")
            page.wait_for_timeout(4000)
            _despejar(page, destino, "43_pendencias")
            for r in jsons:
                for c in r.json().get("data", {}).get("result", []):
                    print(f"  lista: {c['processId']} answerStatus={c['answerStatus']!r} status={c['statusName']!r}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
