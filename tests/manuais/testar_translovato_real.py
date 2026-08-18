"""Cinco cotações REAIS na Translovato. ENVIA de verdade.

    python tests/manuais/testar_translovato_real.py --enviar
    python tests/manuais/testar_translovato_real.py --enviar --headed

⚠ Cada envio clica em "Simular cotação" e cria um registro em
"Minhas Cotações" no portal da Translovato. Sem `--enviar` o script não faz
nada — a trava é explícita para não enviar por engano ao rodar o arquivo
errado.

Reusa o preenchimento de testar_translovato_dry.py, que já foi conferido campo
a campo (65/65 em 18/08/2026). Aqui só entra o que o dry-run não faz: clicar,
esperar o resultado e ler valor/prazo/validade.

Evidências em teste_real/translovato/<timestamp>/:
    preenchido.png  a tela antes de enviar
    resultado.png   a faixa com o valor, para o funcionário e o cliente
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Estes scripts moram em tests/manuais/, mas importam carriers/, core/ e web/,
# que so existem na RAIZ. `python tests/manuais/testar_x.py` poe tests/manuais
# no sys.path -- a raiz, nao.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv(override=False)

from carriers.base import print_seguro
from recon.recon_translovato import (
    CONSULTAS_LIBERADAS, METODOS_DE_ESCRITA, ROTA_DE_ENVIO, URL_LOGIN, entrar,
)
from tests.manuais.testar_translovato_dry import (
    CARGAS, SAIDA, _limpar_tela, rodar_uma,
)

# Espaçamento entre envios. Cinco POSTs em um minuto é o jeito mais rápido de
# ser tratado como robô — e aí o teste mede a nossa pressa, não o site.
PAUSA_S = 30

# A faixa de resultado do print do Enzo: "Consulta de Valor de Cotação",
# com PRAZO DE ENTREGA, VALIDADE DA COTAÇÃO e VALOR.
RE_VALOR = re.compile(r"R\$\s*([\d.]+,\d{2})")
RE_PRAZO = re.compile(r"(\d+)\s*dias?", re.I)
RE_VALIDADE = re.compile(r"(\d{2}/\d{2}/\d{4})")


def ler_resultado(page) -> dict[str, str]:
    """Lê a faixa de resultado. Devolve o que achou, sem inventar.

    Um campo que não aparecer volta vazio de propósito: preencher com um
    palpite aqui viraria preço errado no histórico do Enzo."""
    texto = page.locator("body").inner_text()
    # Só o trecho da faixa, para o "R$" do valor da NF não virar o frete.
    corte = texto.find("Consulta de Valor")
    faixa = texto[corte:corte + 400] if corte >= 0 else texto

    valor = RE_VALOR.search(faixa)
    prazo = RE_PRAZO.search(faixa)
    validade = RE_VALIDADE.search(faixa)
    return {
        "valor": valor.group(1) if valor else "",
        "prazo": f"{prazo.group(1)} dias" if prazo else "",
        "validade": validade.group(1) if validade else "",
        "achou_faixa": "sim" if corte >= 0 else "nao",
    }


def enviar_e_ler(page, destino: Path) -> dict[str, str]:
    """Clica em "Simular cotação" e espera o valor aparecer."""
    botao = page.get_by_role("button", name="Simular cotação").first
    botao.scroll_into_view_if_needed()
    _limpar_tela(page)          # alerta/cookie por cima engole o clique
    botao.click()

    try:
        # O resultado é síncrono: a faixa aparece na própria página.
        page.wait_for_function(
            """() => /Consulta de Valor/i.test(document.body.innerText)
                     && /R\\$\\s*[\\d.,]+/.test(document.body.innerText)""",
            timeout=60_000)
        page.wait_for_timeout(1500)
    except Exception as exc:
        print(f"     resultado não apareceu: {type(exc).__name__}")
        aviso = _limpar_tela(page)
        if aviso:
            print(f"     o site avisou: {aviso!r}")
        print_seguro(page, destino / "resultado.png")
        return {"valor": "", "prazo": "", "validade": "",
                "achou_faixa": "nao", "erro": aviso or str(exc)[:120]}

    lido = ler_resultado(page)
    print_seguro(page, destino / "resultado.png")
    return lido


def main() -> int:
    from playwright.sync_api import sync_playwright

    enviar = "--enviar" in sys.argv
    if not enviar:
        print("Sem --enviar: este script não faz nada.")
        print("Para ENVIAR de verdade (cria cotação no portal):")
        print("  python tests/manuais/testar_translovato_real.py --enviar")
        return 2

    faltando = [k for k in ("TRANSLOVATO_CNPJ", "TRANSLOVATO_USUARIO",
                            "TRANSLOVATO_SENHA") if not os.getenv(k)]
    if faltando:
        print(f"Faltam no .env: {', '.join(faltando)}")
        return 2

    permitir_escrita = {"ligado": False}

    def porteiro(rota, req):
        if req.method.upper() not in METODOS_DE_ESCRITA:
            return rota.continue_()
        if ROTA_DE_ENVIO in req.url:
            # Aqui é o único lugar do projeto onde esta rota passa, e só
            # porque o Enzo pediu envio real explicitamente em 18/08/2026.
            print(f"   [ENVIO REAL] {req.url[:70]}")
            return rota.continue_()
        if permitir_escrita["ligado"]:
            return rota.continue_()
        if any(c in req.url for c in CONSULTAS_LIBERADAS):
            return rota.continue_()
        return rota.abort()

    print("=" * 70)
    print("ENVIO REAL — cada rodada cria uma cotação em Minhas Cotações")
    print("=" * 70)

    laudos = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless="--headed" not in sys.argv)
        page = browser.new_context(
            locale="pt-BR", viewport={"width": 1500, "height": 1100}).new_page()
        page.set_default_timeout(30_000)
        page.route("**/*", porteiro)

        try:
            print("entrando no portal...")
            page.goto(URL_LOGIN, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            permitir_escrita["ligado"] = True
            entrar(page)
            permitir_escrita["ligado"] = False
            print("   ok\n")

            for i, carga in enumerate(CARGAS, 1):
                marca = datetime.now().strftime("%Y%m%d-%H%M%S")
                destino = SAIDA / marca
                print(f"--- {i}/5  {carga[0]} -> teste_real/translovato/{marca}")

                laudo = rodar_uma(page, carga, destino)
                if laudo.get("fora_de_area"):
                    laudos.append({**laudo, "resultado": {}})
                    print()
                    continue
                if laudo["divergencias"]:
                    print("     preenchimento divergiu — NÃO vou enviar esta")
                    laudos.append({**laudo, "resultado": {}})
                    print()
                    continue

                resultado = enviar_e_ler(page, destino)
                print(f"     VALOR R$ {resultado['valor'] or '?'}   "
                      f"prazo {resultado['prazo'] or '?'}   "
                      f"validade {resultado['validade'] or '?'}")
                laudos.append({**laudo, "resultado": resultado})

                if i < len(CARGAS):
                    print(f"     aguardando {PAUSA_S}s antes da próxima...")
                    time.sleep(PAUSA_S)
                print()
        finally:
            browser.close()

    print("=" * 70)
    print(f"{'carga':15s} {'valor':>12s} {'prazo':>9s} {'validade':>12s}   pasta")
    sem_valor = 0
    for laudo in laudos:
        r = laudo.get("resultado") or {}
        if laudo.get("fora_de_area"):
            print(f"{laudo['apelido']:15s} {'PRAÇA NÃO ATENDIDA':>36s}   "
                  f"{laudo['pasta'].name}")
            continue
        if not r.get("valor"):
            sem_valor += 1
        rotulo_valor = ("R$ " + r["valor"]) if r.get("valor") else "—"
        print(f"{laudo['apelido']:15s} {rotulo_valor:>12s} "
              f"{r.get('prazo') or '—':>9s} {r.get('validade') or '—':>12s}   "
              f"{laudo['pasta'].name}")
    print(f"\n{len(laudos)} rodadas, {sem_valor} sem valor lido.")
    return 1 if sem_valor else 0


if __name__ == "__main__":
    raise SystemExit(main())
