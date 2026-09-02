"""Recon READ-ONLY da cotação da Braspress. Lê, não cota.

    python recon/recon_braspress.py [--headed]

A "Área do Cliente" em www.braspress.com/area-do-cliente/minha-conta/ é só a
casca: quem faz login e mostra o formulário é um IFRAME de outro domínio,
https://blue.braspress.com/site/w/cliente/view — e por isso o recon vai DIRETO
nesse domínio (mais rápido, sem o chatbot "Romilda" nem o banner de cookies do
site principal, que não têm nada a ver com a cotação).

Login com BRASPRESS_USUARIO / BRASPRESS_SENHA (usuário = o próprio CNPJ da
Ventura, 08310365000124). Depois de logado, o botão "Cotação" da Minha Conta
manda para /site/w/cotacao/view — medido em 02/09/2026 no HTML pós-login
(botão com onclick="...window.location.href='/site/w/cotacao/view'...").

ACHADOS PRINCIPAIS (medidos, não deduzidos de print):

1. A conta SEMPRE está de um lado da carga. O select "tipoFrete" (1=CIF,
   2=FOB, 3=Consignado) decide qual: CIF trava cnpjRemetenteStr no CNPJ da
   Ventura (com razaoSocialRemetente, cepOrigem e nomeFilialOrigem já
   preenchidos); FOB trava o mesmo do lado do destinatário. O outro lado fica
   livre para digitar. Bate exatamente com o que o Enzo descreveu.

2. Digitar o CNPJ do lado livre com .type() (NUNCA .fill() — fill não
   dispara a busca do site, e um teste com fill() cortou um dígito do CEP:
   "01310-100" virou "01310-10") preenche razão social, CEP e endereço
   inteiros daquele lado. Testado com um CNPJ público (Magazine Luiza,
   47.960.950/0001-21): trouxe "MAGAZINE LUIZA S/A" e o endereço da filial de
   Franca/SP certinho.

3. Popup "Braspress Comunica" (pedido de XML de NF-e por e-mail) aparece
   solto por cima do formulário toda vez que a tela de cotação abre. É só
   marketing — não é o aviso de negócio que a Camilo/SSW têm — mas sem
   fechá-lo ("Fechar") os campos por baixo não recebem clique nem digitação.

4. MÁSCARAS, medidas digitando e lendo de volta (nunca supor):
   - peso, vlrMercadoria: mesmo estilo "dinheiro" da Jadlog/Generoso —
     dígitos digitados viram centavos: type("125") -> "1,25". Fórmula:
     str(int(round(valor * 100))).
   - cubagem[i].comprimento/largura/altura: em METROS, mas com a MESMA
     máscara de 2 casas. Coincidência útil: como 1 m = 100 cm, digitar o
     valor em CENTÍMETROS direto já dá o metro certo — type("120") ->
     "1,20" m = 120 cm. Fórmula: str(int(round(valor_cm))).
   - cubagem[i].volumes: inteiro puro, sem máscara.
   - #volumes (Total de volumes, topo): campo READONLY — soma sozinho as
     linhas de cubagem. NUNCA preencher direto (trava em "element is not
     editable").

5. A tabela de cubagem tem um botão "+" (Ação) para adicionar mais linhas —
   dá para mandar um req.volumes com mais de um Volume, uma linha por item.

NUNCA clica em "Calcular" nem em nenhum outro botão de simular/cotar/enviar —
só descobre a estrutura da tela.

Saída em recon_out/braspress/ (pasta já no .gitignore).
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

URL_LOGIN = "https://blue.braspress.com/site/w/cliente/view"
URL_COTACAO = "https://blue.braspress.com/site/w/cotacao/view"

# CNPJ público (Magazine Luiza), só para provar que a busca por CNPJ do lado
# livre traz razão social + endereço. Nunca um CNPJ sintético — ver a lição
# de "cliente não cadastrado" na Generoso.
CNPJ_TESTE = "47960950000121"

SAIDA = RAIZ / "recon_out" / "braspress"

# Botões que NÃO podem ser clicados neste script.
NUNCA_CLICAR = ("calcular", "cotar", "simular", "solicitar", "salvar",
                "enviar", "confirmar", "gerar", "finalizar")

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
            ? [...e.options].map(o => `${o.value}=${o.text}`).slice(0, 40) : [],
    }));
}"""

JS_BOTOES = """() => [...document.querySelectorAll('button, [role=button], a.btn, a')]
    .filter(e => e.offsetWidth || e.offsetHeight)
    .map(e => (e.innerText || '').trim())
    .filter(t => t && t.length < 60)"""

# Iframes costumam esconder formulário de login/portal de terceiro (ex.:
# provedores de área do cliente white-label). Vale saber se existe algum.
JS_IFRAMES = """() => [...document.querySelectorAll('iframe')]
    .map(f => f.src || '(sem src)')"""


def despejar(page, titulo: str) -> list[dict]:
    campos = [c for c in page.evaluate(JS_CAMPOS) if c["visivel"]]
    print(f"\n--- {titulo} ({len(campos)} campos visiveis) ---")
    for c in campos:
        print("  " + json.dumps(c, ensure_ascii=False))
    print("  botoes:", page.evaluate(JS_BOTOES))
    ifr = page.evaluate(JS_IFRAMES)
    if ifr:
        print("  iframes:", ifr)
    return campos


def main() -> int:
    from playwright.sync_api import sync_playwright

    usuario = os.getenv("BRASPRESS_USUARIO")
    senha = os.getenv("BRASPRESS_SENHA")
    if not usuario or not senha:
        print("Faltam BRASPRESS_USUARIO / BRASPRESS_SENHA no .env")
        return 2

    SAIDA.mkdir(parents=True, exist_ok=True)
    headed = "--headed" in sys.argv

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_context(
            locale="pt-BR", viewport={"width": 1500, "height": 1300}).new_page()
        page.set_default_timeout(45_000)
        try:
            print(f"1. login em {URL_LOGIN}")
            page.goto(URL_LOGIN, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            page.locator('input[name="login"]').first.fill(usuario)
            page.locator('input[name="pass"]').first.fill(senha)
            page.get_by_role("button", name="Acessar").first.click()
            page.wait_for_timeout(4000)
            print(f"   url apos login: {page.url}")
            page.screenshot(path=str(SAIDA / "01_apos_login.png"),
                            full_page=True)
            despejar(page, "1. apos login (Minha Conta)")

            print(f"\n2. abrindo {URL_COTACAO}")
            page.goto(URL_COTACAO, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # Popup "Braspress Comunica" -- so marketing, mas cobre o
            # formulario inteiro e trava clique/digitacao ate ser fechado.
            fechar = page.get_by_role("button", name="Fechar")
            if fechar.count() and fechar.first.is_visible():
                fechar.first.click()
                page.wait_for_timeout(500)
                print("   fechou popup 'Braspress Comunica'")

            campos = despejar(page, "2. formulario de cotacao (CIF, estado inicial)")
            (SAIDA / "02_campos_cif.json").write_text(
                json.dumps(campos, ensure_ascii=False, indent=2), encoding="utf-8")
            (SAIDA / "02_pagina_cif.html").write_text(
                page.content(), encoding="utf-8")
            page.screenshot(path=str(SAIDA / "02_cif.png"), full_page=True)

            # -------------------------------------------- 3. Alterna para FOB
            print("\n3. trocando tipoFrete para FOB")
            page.locator("#tipoFrete").select_option(value="2")
            page.wait_for_timeout(1500)
            campos_fob = despejar(page, "3. formulario (FOB)")
            (SAIDA / "03_campos_fob.json").write_text(
                json.dumps(campos_fob, ensure_ascii=False, indent=2),
                encoding="utf-8")
            page.screenshot(path=str(SAIDA / "03_fob.png"), full_page=True)

            # volta pra CIF (default do site) antes de seguir
            page.locator("#tipoFrete").select_option(value="1")
            page.wait_for_timeout(1000)

            # ------------------------- 4. Digita CNPJ do lado livre (destino)
            print(f"\n4. digitando CNPJ de teste ({CNPJ_TESTE}) no destinatario")
            campo_cnpj = page.locator("#cnpjDestinatario")
            campo_cnpj.click()
            campo_cnpj.type(CNPJ_TESTE, delay=70)
            page.wait_for_timeout(500)
            campo_cnpj.blur()
            page.wait_for_timeout(3000)
            achado = page.evaluate("""() => ({
                razaoSocialDestinatario: document.getElementById(
                    'razaoSocialDestinatario').value,
                cepDestino: document.getElementById('cepDestino').value,
                endereco: document.getElementById('endereco').value,
                nomeFilialDestino: document.getElementById(
                    'nomeFilialDestino').value,
            })""")
            print("   endereco encontrado pelo CNPJ:",
                  json.dumps(achado, ensure_ascii=False))
            page.screenshot(path=str(SAIDA / "04_cnpj_destino.png"),
                            full_page=True)

            # ------------------------------------- 5. Mascaras de carga
            print("\n5. medindo mascaras de peso/valor/cubagem (digitando e "
                  "lendo de volta, sem clicar em Calcular)")

            def _testar(seletor: str, valores: tuple[str, ...]) -> None:
                campo = page.locator(seletor)
                for v in valores:
                    campo.click()
                    campo.fill("")
                    page.wait_for_timeout(120)
                    campo.type(v, delay=60)
                    page.wait_for_timeout(300)
                    campo.blur()
                    page.wait_for_timeout(300)
                    print(f"   {seletor} type({v!r:10}) -> {campo.input_value()!r}")

            _testar("#peso", ("100", "1250"))
            _testar("#vlrMercadoria", ("150000",))
            _testar("#cubagem0comprimento", ("120",))
            _testar("#cubagem0largura", ("80",))
            _testar("#cubagem0altura", ("50",))
            _testar("#cubagem0volumes", ("3",))
            page.wait_for_timeout(500)
            print("   #volumes (total, readonly, auto-somado):",
                  repr(page.locator("#volumes").input_value()))
            print("   #cubagem0total (volumetria, auto-calculada):",
                  repr(page.locator("#cubagem0total").input_value()))

            page.screenshot(path=str(SAIDA / "05_carga_preenchida.png"),
                            full_page=True)
            (SAIDA / "05_pagina_final.html").write_text(
                page.content(), encoding="utf-8")

            print(f"\nevidencias em {SAIDA.resolve()}")
            print(f"(nenhum botao de {NUNCA_CLICAR} foi clicado)")
            return 0

        except Exception as exc:
            print(f"\nERRO: {type(exc).__name__}: {exc}")
            page.screenshot(path=str(SAIDA / "erro.png"), full_page=True)
            (SAIDA / "erro_pagina.html").write_text(
                page.content(), encoding="utf-8")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
