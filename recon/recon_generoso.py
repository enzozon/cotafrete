"""Recon READ-ONLY da cotação do Generoso. Lê, não cota.

    python recon/recon_generoso.py [--headed]

Formulário em ETAPAS: Solicitante -> Tipo pagador -> Origem -> Destino ->
Carga -> Confirmar. Cada etapa só libera a seguinte depois de preenchida, e
por isso o recon anda passo a passo, preenchendo com dados de teste e
conferindo o que o site devolve — em especial o autopreenchimento de endereço
por CNPJ, que segundo o Enzo funciona na origem e falha no destino.

⚠ NUNCA clica em "Confirmar e ver resultado". A trava de rede aborta o POST
final por segurança, do mesmo jeito que recon_dellavolpe.py.

Saída em recon_out/generoso/ (pasta já no .gitignore).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Este script vive em recon/, mas faz parte do projeto: importa de carriers/ e
# grava a evidencia em recon_out/ na RAIZ. Ancorar no __file__ deixa rodar de
# qualquer pasta -- sem isto, rodar de dentro de recon/ quebra o import e
# espalha print em recon/recon_out/, que ninguem procura.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

URL = "https://cliente.generoso.com.br/cotacao"

# Dados de teste, os mesmos dos prints que o Enzo mandou.
SOLICITANTE = {
    "email": "vendas2@venturainformatica.com.br",
    "cnpj": "08.310.365/0001-24",
    "nome": "Enzo Zon",
    "whatsapp": "(27) 3339-1891",
}
CNPJ_REMETENTE = "60.042.686/0001-05"
CNPJ_DESTINATARIO = "08.310.365/0001-24"
CEP_ORIGEM = "09895-510"
CEP_DESTINO = "29105-770"

SAIDA = RAIZ / "recon_out" / "generoso"

# Texto do botão que NÃO pode ser clicado neste script.
NUNCA_CLICAR = "Confirmar e ver resultado"

JS_CAMPOS = """() => {
    const rotulo = (e) => {
        if (e.id) {
            const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
            if (l) return l.innerText.trim();
        }
        const pai = e.closest('label');
        if (pai) return pai.innerText.trim();
        if (e.getAttribute('aria-label')) return e.getAttribute('aria-label');
        const bloco = e.closest('div');
        if (bloco) {
            const t = bloco.innerText.trim().split('\\n')[0];
            if (t && t.length < 60) return t;
        }
        return '';
    };
    return [...document.querySelectorAll('input, select, textarea')]
        .filter(e => e.offsetWidth || e.offsetHeight)
        .map(e => ({
            tipo: e.type || e.tagName.toLowerCase(),
            name: e.name || '',
            id: e.id || '',
            rotulo: rotulo(e),
            placeholder: e.placeholder || '',
            valor: (e.value || '').slice(0, 40),
            desabilitado: !!e.disabled,
            somenteLeitura: !!e.readOnly,
        }));
}"""

JS_BOTOES = """() => [...document.querySelectorAll('button, [role=button]')]
    .filter(e => e.offsetWidth || e.offsetHeight)
    .map(e => (e.innerText || '').trim().replace(/\\s+/g, ' '))
    .filter(t => t && t.length < 40)"""


def despejar(page, titulo: str) -> list[dict]:
    campos = page.evaluate(JS_CAMPOS)
    print(f"\n--- {titulo} ({len(campos)} campos visiveis) ---")
    for c in campos:
        print("  " + json.dumps(c, ensure_ascii=False))
    print("  botoes:", page.evaluate(JS_BOTOES))
    return campos


def conferir(page, esperado: dict[str, str]) -> None:
    """Lê de volta o que foi digitado. Campo com máscara devolve outra coisa
    — foi assim que o peso da Jadlog virou 0,01 e a medida da Della Volpe
    virou 3,0. Comparar só os dígitos ignora a formatação, não o valor."""
    so_digitos = lambda s: "".join(c for c in s if c.isdigit())
    for nome, valor in esperado.items():
        obtido = page.locator(f'input[name="{nome}"]').first.input_value()
        igual = (obtido == valor) or (so_digitos(obtido) == so_digitos(valor)
                                      and so_digitos(valor))
        marca = "ok " if igual else "DIVERGE"
        print(f"  {marca} {nome:<12} digitei {valor!r:38} campo tem {obtido!r}")


def avancar(page, rotulo: str) -> None:
    """Clica em Próximo. NUNCA em 'Confirmar e ver resultado'."""
    botao = page.get_by_role("button", name="Próximo").first
    if not botao.count():
        print(f"  [{rotulo}] sem botao Proximo visivel")
        return
    botao.click()
    page.wait_for_timeout(2500)
    print(f"  [{rotulo}] avancou")


def main() -> int:
    from playwright.sync_api import sync_playwright

    SAIDA.mkdir(parents=True, exist_ok=True)
    headed = "--headed" in sys.argv

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_context(
            locale="pt-BR", viewport={"width": 1400, "height": 1200}).new_page()
        page.set_default_timeout(30_000)

        # O site BUSCA CNPJ e CEP por requisicao propria, entao bloquear todo
        # POST impediria justamente o que precisamos observar. Bloqueio so o
        # ruido de terceiros; a trava do envio e nao clicar no botao final.
        def bloquear(route, request):
            terceiro = not request.url.startswith("https://cliente.generoso.com.br")
            if terceiro and request.method.upper() != "GET":
                route.abort()
            else:
                route.continue_()

        page.route("**/*", bloquear)

        page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(4000)
        print(f"titulo: {page.title()}")
        print(f"url: {page.url}")

        despejar(page, "1. Solicitante")

        # ---------------------------------------------------- 1. Solicitante
        for nome, valor in (("email", SOLICITANTE["email"]),
                            ("document", SOLICITANTE["cnpj"]),
                            ("name", SOLICITANTE["nome"]),
                            ("whatsapp", SOLICITANTE["whatsapp"])):
            page.locator(f'input[name="{nome}"]').first.fill(valor)
            page.wait_for_timeout(300)
        conferir(page, {"email": SOLICITANTE["email"],
                        "document": SOLICITANTE["cnpj"],
                        "name": SOLICITANTE["nome"],
                        "whatsapp": SOLICITANTE["whatsapp"]})
        page.screenshot(path=str(SAIDA / "etapa1.png"), full_page=True)
        avancar(page, "1 -> 2")

        despejar(page, "2. Tipo pagador")

        # ---------------------------------------------------- 2. Tipo pagador
        # O select não tem name nem id; é o único da etapa.
        page.locator("select").first.select_option(label="Destinatario (FOB)")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(SAIDA / "etapa2.png"), full_page=True)
        avancar(page, "2 -> 3")

        # ------------------------------------------------------ 3. Origem
        despejar(page, "3. Dados da origem")
        campo_cnpj_origem = page.locator('input[name="document"]:not([disabled])').first
        campo_cnpj_origem.fill(CNPJ_REMETENTE)
        page.wait_for_timeout(3500)      # o site busca o CNPJ
        campo_cnpj_origem.blur()
        page.wait_for_timeout(3500)
        despejar(page, "3. Origem APOS CNPJ + blur")

        # NAO digitar o CEP: medido acima, isso SOBRESCREVE o endereco que o
        # CNPJ trouxe, com dados de outra cidade.
        page.screenshot(path=str(SAIDA / "etapa3.png"), full_page=True)
        avancar(page, "3 -> 4")

        # ------------------------------------------------------ 4. Destino
        despejar(page, "4. Destino ANTES do CNPJ")
        # O CNPJ do destinatario ja vem preenchido e DESABILITADO (e o pagador
        # FOB). Ele traz o CEP mas nao o resto do endereco — cidade, estado,
        # bairro e rua ficam vazios. Aqui, ao contrario da origem, redisparar
        # o CEP e o certo: nao ha endereco bom para sobrescrever.
        campo_cep = page.locator('input[name="cep"]').last
        cep_atual = campo_cep.input_value()
        print(f"\n  CEP que veio do CNPJ: {cep_atual!r} — redisparando a busca")
        campo_cep.fill("")
        page.wait_for_timeout(400)
        campo_cep.type(cep_atual or CEP_DESTINO, delay=60)
        campo_cep.blur()
        page.wait_for_timeout(4500)
        despejar(page, "4. Destino APOS redisparar o CEP")
        page.screenshot(path=str(SAIDA / "etapa4.png"), full_page=True)
        avancar(page, "4 -> 5")

        # ------------------------------------------------------ 5. Carga
        despejar(page, "5. Carga")
        page.screenshot(path=str(SAIDA / "etapa5.png"), full_page=True)

        # A MASCARA DO PESO: segundo o Enzo, para 1 kg digita-se "100".
        # Medir antes de acreditar — foi assim que a Jadlog cotou 0,01 kg.
        campos_peso = page.locator(
            'input[name*="weight" i], input[name*="peso" i]')
        print(f"\n  campos de peso encontrados: {campos_peso.count()}")
        if campos_peso.count():
            alvo = campos_peso.first
            for tentativa in ("1", "100", "1,00", "1.00", "050", "1200"):
                alvo.fill("")
                page.wait_for_timeout(200)
                alvo.type(tentativa, delay=60)
                page.wait_for_timeout(500)
                print(f"    type({tentativa!r:7}) -> {alvo.input_value()!r}")

        (SAIDA / "pagina.html").write_text(page.content(), encoding="utf-8")
        print(f"\nevidencias em {SAIDA.resolve()}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
