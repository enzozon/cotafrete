"""Cinco DRY-RUNs no formulário da Translovato. Preenche, confere, printa, para.

    python tests/manuais/testar_translovato_dry.py
    python tests/manuais/testar_translovato_dry.py --headed   # vendo o browser

NÃO ENVIA. O botão "Simular cotação" nunca é clicado, e a rota que cria
cotação de verdade (POST /portal-do-cliente/simular-cotacao) fica bloqueada na
camada de rede — as duas travas, porque uma só é uma trava.

Evidências em teste_real/translovato/<timestamp>/preenchido.png, no mesmo
esquema das outras transportadoras.

Por que 5 cargas DIFERENTES: repetir a mesma cinco vezes testaria se o
formulário aceita, não se a CONTA está certa. As cinco foram escolhidas para
cair em regimes diferentes de cubagem — uma volumosa e leve (peso cubado
manda), uma pesada e compacta (peso real manda), e uma com vários volumes.

A conta que este script confere, medida no recon de 18/08/2026:
    cubagem     = qtd x altura x largura x profundidade   (metros, 4 casas)
    peso cubado = cubagem x 300                           (fator do produto)

O fator 300 vem do PRODUTO (SUPR.INFORMATICA), não é constante do site: sem
produto selecionado ele vira 1 e o peso cubado sai 270x menor, sem erro nenhum
na tela. É o motivo de este script conferir em vez de confiar.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

# Estes scripts moram em tests/manuais/, mas importam carriers/, core/ e web/,
# que so existem na RAIZ. `python tests/manuais/testar_x.py` poe tests/manuais
# no sys.path -- a raiz, nao. Sem esta linha, ImportError logo no primeiro
# import, sem chegar a rodar nada.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv

load_dotenv(override=False)

from recon.recon_translovato import (
    CONSULTAS_LIBERADAS, METODOS_DE_ESCRITA, PRODUTO, ROTA_DE_ENVIO,
    URL_COTACAO, URL_LOGIN, entrar,
)

# Ancorado na RAIZ: relativo ao cwd, rodar de outra pasta espalharia
# evidência onde ninguém procura.
SAIDA = Path(__file__).resolve().parents[2] / "teste_real" / "translovato"

FATOR_CUBAGEM = Decimal(300)      # kg/m3 do SUPR.INFORMATICA

# CNPJs fixos, como o Enzo pediu: o que muda de uma rodada para outra é a
# CARGA. Remetente é sempre a Ventura; destinatário é o cliente.
CNPJ_REMETENTE = "05.954.058/0001-98"
CNPJ_DESTINATARIO = "60.042.686/0001-05"

# A ORIGEM é fixa: a carga sai sempre da Ventura, em Vila Velha/ES. Foi o que
# o Enzo definiu como regra, e é também a única origem que já sabemos ser
# atendida. O que varia são os DESTINOS — que é o que varia na vida real.
CEP_ORIGEM = "29105770"

CARGAS = [
    # (apelido, cep_destino, nf, peso, qtd, alt_m, larg_m, prof_m)
    ("1-referencia", "09895003", "568,77",   "1",  "1", "0,3", "0,3", "0,3"),
    ("2-media",      "01310100", "2450,00",  "15", "2", "0,5", "0,4", "0,3"),
    ("3-volumosa",   "30130000", "1200,00",  "5",  "3", "1",   "0,8", "0,6"),
    ("4-compacta",   "90010000", "15000,00", "80", "1", "0,2", "0,2", "0,2"),
    ("5-varios",     "80010000", "8750,50",  "40", "5", "0,6", "0,5", "0,4"),
]

# Frase do alerta que o site abre quando a praça não é atendida. Medido em
# 18/08/2026: vem num sweet-alert que fica POR CIMA da tela e engole todos os
# cliques seguintes — o dry-run travou nele. Praça não atendida não é bug: é
# resposta legítima da transportadora, e o adapter vai precisar tratá-la.
AVISO_FORA_DE_AREA = "não está em nossa regi"


def _dec(texto: str) -> Decimal:
    """'0,3' -> Decimal('0.3'). O site fala em vírgula; o Python, em ponto."""
    return Decimal(texto.replace(".", "").replace(",", "."))


def _br(valor: Decimal, casas: int) -> str:
    """Decimal -> texto no formato do site (vírgula, casas fixas)."""
    quantizado = valor.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    return f"{quantizado:f}".replace(".", ",")


def esperado_da_carga(qtd: str, alt: str, larg: str, prof: str) -> dict[str, str]:
    """O que o site DEVE calcular. Conferir isto é o ponto do script."""
    cubagem = _dec(qtd) * _dec(alt) * _dec(larg) * _dec(prof)
    return {
        "cubagem": _br(cubagem, 4),
        "peso_cubado": _br(cubagem * FATOR_CUBAGEM, 2),
    }


def _digitar(page, seletor: str, valor: str) -> str:
    """Digita tecla a tecla (as máscaras do site rodam no keyup) e devolve o
    que ficou no campo. A leitura de volta é o que prova o preenchimento."""
    campo = page.locator(seletor).first
    campo.click()
    campo.fill("")
    campo.press_sequentially(valor, delay=40)
    campo.blur()
    page.wait_for_timeout(400)
    return campo.input_value()


def _limpar_tela(page) -> str:
    """Fecha alertas e o banner de cookies, e devolve o aviso que apareceu.

    Os dois ficam POR CIMA do formulário e engolem cliques — foi o que travou
    a primeira tentativa dos 5 dry-runs. Mesmo modo de falha do banner de
    cookies da Jadlog: o elemento nasce depois, então não adianta fechar uma
    vez só no começo; tem que fechar antes de cada campo."""
    aviso = ""
    alerta = page.locator(".sweet-alert.visible")
    if alerta.count() and alerta.first.is_visible():
        aviso = alerta.first.inner_text().strip().replace("\n", " ")[:120]
        botao = alerta.first.locator("button.confirm")
        if botao.count():
            botao.first.click()
            page.wait_for_timeout(600)

    for texto in ("Ok, entendi!", "Aceitar todos", "Aceitar"):
        try:
            alvo = page.get_by_role("button", name=texto, exact=False).first
            if alvo.count() and alvo.is_visible(timeout=800):
                alvo.click()
                page.wait_for_timeout(400)
                break
        except Exception:
            continue
    return aviso


def rodar_uma(page, carga, destino: Path) -> dict:
    """Preenche uma carga e devolve o laudo da conferência."""
    apelido, cep_d, nf, peso, qtd, alt, larg, prof = carga
    cep_o = CEP_ORIGEM
    esperado = esperado_da_carga(qtd, alt, larg, prof)
    conferencia: list[tuple[str, str, str]] = []

    def anotar(rotulo: str, quero: str, tenho: str) -> None:
        conferencia.append((rotulo, quero, tenho))
        print(f"     [{'ok ' if tenho.strip() == quero else 'DIVERGE'}] "
              f"{rotulo}: quero {quero!r}, tenho {tenho!r}")

    page.goto(URL_COTACAO, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    _limpar_tela(page)

    # O CNPJ do remetente é o gatilho: é ele que chama get-products e traz a
    # lista de produtos. Preencher o produto antes disto acha lista vazia.
    with page.expect_response(lambda r: "get-cnpj" in r.url, timeout=20_000):
        anotar("CNPJ remetente", CNPJ_REMETENTE,
               _digitar(page, 'input[name="value[sender_cpnj]"]',
                        CNPJ_REMETENTE))
    page.wait_for_timeout(2500)
    anotar("CEP origem", cep_o,
           _digitar(page, 'input[name="value[sender_zipcode]"]', cep_o))
    page.wait_for_timeout(2500)

    aviso = _limpar_tela(page)
    if AVISO_FORA_DE_AREA in aviso:
        print(f"     [praça não atendida na ORIGEM] {aviso!r}")
        destino.mkdir(parents=True, exist_ok=True)
        from carriers.base import print_seguro
        return {"apelido": apelido, "campos": len(conferencia),
                "divergencias": [], "fora_de_area": aviso,
                "evidencias": print_seguro(page, destino / "preenchido.png"),
                "esperado": esperado, "pasta": destino}

    anotar("CNPJ destinatário", CNPJ_DESTINATARIO,
           _digitar(page, 'input[name="value[receiver_cnpj_cpf]"]',
                    CNPJ_DESTINATARIO))
    anotar("CEP destino", cep_d,
           _digitar(page, 'input[name="value[receiver_zipcode]"]', cep_d))
    page.wait_for_timeout(2500)

    aviso = _limpar_tela(page)
    if AVISO_FORA_DE_AREA in aviso:
        print(f"     [praça não atendida no DESTINO] {aviso!r}")
        destino.mkdir(parents=True, exist_ok=True)
        from carriers.base import print_seguro
        return {"apelido": apelido, "campos": len(conferencia),
                "divergencias": [], "fora_de_area": aviso,
                "evidencias": print_seguro(page, destino / "preenchido.png"),
                "esperado": esperado, "pasta": destino}

    escolhido = page.evaluate(
        """(alvo) => {
            const sel = document.querySelector('#product');
            const opt = [...sel.options].find(
                o => o.textContent.trim().toUpperCase() === alvo);
            if (!opt) return null;
            sel.value = opt.value;
            sel.dispatchEvent(new Event('change', {bubbles: true}));
            return opt.textContent.trim();
        }""", PRODUTO)
    anotar("produto", PRODUTO, escolhido or "(nao encontrado)")
    page.wait_for_timeout(1200)

    anotar("valor NF", nf,
           _digitar(page, 'input[name="value[volume_nf]"]', nf))
    anotar("peso total", peso,
           _digitar(page, 'input[name="value[volume_weigth]"]', peso))
    anotar("qtd volumes", qtd,
           _digitar(page, 'input[name="cubing_qnt[]"]', qtd))
    anotar("altura (m)", alt,
           _digitar(page, 'input[name="cubing_height[]"]', alt))
    anotar("largura (m)", larg,
           _digitar(page, 'input[name="cubing_length[]"]', larg))
    anotar("profundidade (m)", prof,
           _digitar(page, 'input[name="cubing_depth[]"]', prof))
    page.wait_for_timeout(1500)

    # O que o SITE calculou, contra o que a NOSSA conta diz que deveria dar.
    anotar("cubagem (m3)", esperado["cubagem"],
           page.locator('input[name="cubing[]"]').first.input_value())
    anotar("peso cubado (kg)", esperado["peso_cubado"],
           page.locator('input[name="cubing_weigth[]"]').first.input_value())

    destino.mkdir(parents=True, exist_ok=True)
    from carriers.base import print_seguro
    evidencias = print_seguro(page, destino / "preenchido.png")

    divergencias = [c for c in conferencia if c[2].strip() != c[1]]
    return {"apelido": apelido, "campos": len(conferencia),
            "divergencias": divergencias, "evidencias": evidencias,
            "esperado": esperado, "pasta": destino}


def main() -> int:
    from playwright.sync_api import sync_playwright

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
            print(f"   [BLOQUEADO - ENVIO REAL] {req.url[:80]}")
            return rota.abort()
        if permitir_escrita["ligado"]:
            return rota.continue_()
        if any(c in req.url for c in CONSULTAS_LIBERADAS):
            return rota.continue_()
        return rota.abort()

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
            print(f"   ok, url: {page.url}\n")

            for i, carga in enumerate(CARGAS, 1):
                marca = datetime.now().strftime("%Y%m%d-%H%M%S")
                print(f"--- {i}/5  {carga[0]} -> teste_real/translovato/{marca}")
                laudos.append(rodar_uma(page, carga, SAIDA / marca))
                print()
        finally:
            browser.close()

    print("=" * 70)
    total_div = 0
    for laudo in laudos:
        div = laudo["divergencias"]
        total_div += len(div)
        if laudo.get("fora_de_area"):
            print(f"{laudo['apelido']:15s} PRAÇA NÃO ATENDIDA      ->  "
                  f"{laudo['pasta']}")
            continue
        print(f"{laudo['apelido']:15s} {laudo['campos'] - len(div)}/"
              f"{laudo['campos']} campos  ->  {laudo['pasta']}")
        for rotulo, quero, tenho in div:
            print(f"      DIVERGE {rotulo}: queria {quero!r}, veio {tenho!r}")
    print(f"\n{len(laudos)} dry-runs, {total_div} divergência(s).")
    print('Nenhuma cotação foi enviada — "Simular cotação" não foi clicado.')
    return 1 if total_div else 0


if __name__ == "__main__":
    raise SystemExit(main())
