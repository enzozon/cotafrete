"""Recon READ-ONLY do portal da Translovato. Lê, não cota.

    python recon/recon_translovato.py            # só a tela pública de login
    python recon/recon_translovato.py --logar    # entra e mapeia o formulário
    python recon/recon_translovato.py --logar --headed   # vendo o browser

Telas:
    /fale-conosco/solicitacao-de-cotacao#portal-do-cliente   login
    /portal-do-cliente/minhas-cotacoes                       lista
    /portal-do-cliente/solicitacao-de-cotacao                formulário

Credenciais no .env: TRANSLOVATO_CNPJ, TRANSLOVATO_USUARIO, TRANSLOVATO_SENHA
(o login pede os três — CNPJ, usuário e senha). Nunca são impressas nem
gravadas nas evidências.

TRAVA DE ENVIO — é o ponto do arquivo:
  1. sem --logar, TODO método diferente de GET é abortado;
  2. com --logar, o POST fica liberado SÓ durante o login e é fechado de novo
     assim que ele termina. Depois disso nenhuma requisição de escrita sai,
     nem por clique acidental;
  3. o botão "Simular cotação" nunca é clicado — ele dispara o reCAPTCHA e
     cria uma cotação de verdade na fila da transportadora.

Saída em recon_out/translovato/ (pasta já no .gitignore).
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

BASE = "https://www.translovato.com.br"
URL_LOGIN = f"{BASE}/fale-conosco/solicitacao-de-cotacao#portal-do-cliente"
URL_MINHAS = f"{BASE}/portal-do-cliente/minhas-cotacoes"
URL_COTACAO = f"{BASE}/portal-do-cliente/solicitacao-de-cotacao"

SAIDA = RAIZ / "recon_out" / "translovato"

METODOS_DE_ESCRITA = {"POST", "PUT", "PATCH", "DELETE"}

# Texto do botão que NÃO pode ser clicado neste script.
NUNCA_CLICAR = "Simular cotação"

# A ÚNICA rota que cria cotação de verdade: é o action do #quotationForm.
# Fica bloqueada SEMPRE, inclusive no dry-run — o dry-run preenche e printa,
# não envia. Bloquear a rota exata, e não "todo POST", é o que deixa o resto
# do formulário funcionar sem abrir a porta do envio.
ROTA_DE_ENVIO = "/portal-do-cliente/simular-cotacao"

# Consultas que o formulário faz por POST enquanto é preenchido. Sem elas o
# site simplesmente não responde: get-cnpj é quem traz a razão social E a
# lista de produtos a partir do CNPJ do remetente. Bloquear estas foi o que
# deixou o dropdown de produto vazio nas tentativas de 18/08/2026 — o campo
# não estava quebrado, era o meu próprio porteiro barrando a resposta.
CONSULTAS_LIBERADAS = (
    "/portal-do-cliente/get-cnpj",
    "/portal-do-cliente/get-products",
    "/get-cities",
    "/solicitacao-de-cotacao/validate-cep-attend",
)

# Produto: o Enzo confirmou que TODA cotação da Translovato usa este, seja
# qual for a mercadoria real.
PRODUTO = "SUPR.INFORMATICA"

# Carga do dry-run: os mesmos dados do print que o Enzo mandou (cotação de
# 17/08/2026), justamente para dar para conferir o resultado contra um valor
# já conhecido — R$ 116,36, prazo 3 dias.
#
# ATENÇÃO às unidades: as medidas aqui são em METROS, com vírgula. 0,3 = 30cm.
# Mandar "30" num campo de metros vira uma carga de 30 metros de altura.
DRY_RUN = {
    "sender_cnpj": "05.954.058/0001-98",
    "sender_zipcode": "29105770",
    "receiver_cnpj": "60.042.686/0001-05",
    "receiver_zipcode": "09895003",
    "nf": "568,77",
    "peso": "1",
    "qtd_volumes": "1",
    "altura_m": "0,3",
    "largura_m": "0,3",
    "profundidade_m": "0,3",
}

# O site calcula sozinho a partir das medidas. Se não bater com isto, o
# preenchimento entrou errado em algum campo — e uma cubagem errada é o tipo
# de erro que cota barato e passa despercebido.
ESPERADO = {"cubagem": "0,0270", "peso_cubado": "8,10"}

# Devolve um registro por controle do formulário. As opções dos <select> vêm
# junto de propósito: PRODUTO, ESTADO e CIDADE são listas fechadas, e mandar
# um texto que não está na lista faz o site aceitar calado e cotar errado.
JS_CAMPOS = """() => {
  const rotulo = (e) => {
    if (e.id) {
      const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
      if (l) return l.innerText.trim();
    }
    const pai = e.closest('label');
    if (pai) return pai.innerText.trim().slice(0, 60);
    // o site poe o rotulo flutuante num span dentro do mesmo wrapper
    const w = e.parentElement;
    if (w) {
      const lb = w.querySelector('label, span');
      if (lb && lb !== e && lb.innerText.trim())
        return lb.innerText.trim().slice(0, 60);
    }
    return e.getAttribute('aria-label') || e.placeholder || '';
  };
  return [...document.querySelectorAll('input, select, textarea')].map(e => ({
    tipo: e.type || e.tagName.toLowerCase(),
    name: e.name || '',
    id: e.id || '',
    rotulo: rotulo(e),
    placeholder: e.placeholder || '',
    maxlength: e.maxLength > 0 ? e.maxLength : null,
    obrigatorio: !!e.required,
    bloqueado: !!(e.readOnly || e.disabled),
    classe: (e.className || '').slice(0, 50),
    valor: (e.value || '').slice(0, 40),
    opcoes: e.tagName === 'SELECT'
      ? [...e.options].slice(0, 30).map(o => o.value + '|' + o.text)
      : null,
    visivel: !!(e.offsetWidth || e.offsetHeight),
  }));
}"""

# O botão de simular carrega data-sitekey: precisamos saber QUAL reCAPTCHA é,
# porque v2-invisível e v3 se comportam de formas diferentes em headless.
JS_RECAPTCHA = """() => ({
  elementos: [...document.querySelectorAll('[data-sitekey]')].map(e => ({
    tag: e.tagName,
    sitekey: e.dataset.sitekey || '',
    size: e.dataset.size || '',
    callback: e.dataset.callback || '',
    texto: (e.innerText || '').trim().slice(0, 40),
  })),
  scripts: [...document.querySelectorAll('script[src*="recaptcha"]')]
    .map(s => s.src),
  tem_grecaptcha: typeof grecaptcha !== 'undefined',
})"""


def despejar(page, titulo: str) -> list[dict]:
    campos = page.evaluate(JS_CAMPOS)
    visiveis = [c for c in campos if c["visivel"]]
    print(f"\n--- {titulo} ({len(visiveis)} visíveis de {len(campos)}) ---")
    for c in visiveis:
        print("  " + json.dumps(c, ensure_ascii=False))
    print("  url:", page.url)
    return campos


def entrar(page) -> None:
    """Preenche e envia o login do portal, dentro da janela de POST liberado.

    Seletores medidos no recon SEM login: form #login-portal, campos #cnpj,
    #user (name="username") e input[name="password"]. O <button> não é
    type="submit" comum — a classe "ajax-form" dispara um POST assíncrono
    para /portal-do-cliente/login. Esperar a RESPOSTA desse POST (em vez de
    um sleep às cegas) garante que a janela de escrita só fecha depois que o
    login já saiu — um sleep curto demais fecharia a trava ANTES do POST
    disparar, e o próprio script bloquearia o próprio login."""
    cnpj = os.getenv("TRANSLOVATO_CNPJ", "")
    usuario = os.getenv("TRANSLOVATO_USUARIO", "")
    senha = os.getenv("TRANSLOVATO_SENHA", "")

    page.locator("#login-portal #cnpj").fill(cnpj)
    page.locator("#login-portal #user").fill(usuario)
    page.locator("#login-portal input[name='password']").fill(senha)

    with page.expect_response(
            lambda r: "/portal-do-cliente/login" in r.url, timeout=20_000):
        page.locator("#login-portal button.common-button").click()

    page.wait_for_timeout(1500)


def _digitar(page, seletor: str, valor: str) -> str:
    """Digita tecla a tecla e devolve o que ficou no campo.

    fill() escreve o valor direto no DOM; as máscaras deste site rodam no
    keyup, então fill() num campo mascarado pode deixar o valor cru (sem
    ponto/barra) ou a máscara reformatar por cima depois. Digitar faz a
    máscara do próprio site rodar — e a leitura de volta é o que prova que o
    que ficou é o que a gente queria."""
    campo = page.locator(seletor).first
    campo.click()
    campo.fill("")
    campo.press_sequentially(valor, delay=40)
    campo.blur()
    page.wait_for_timeout(400)
    return campo.input_value()


def preencher_dry_run(page) -> None:
    """Preenche o formulário inteiro e PARA. Não clica em "Simular cotação".

    A ordem importa: o CNPJ do remetente é o gatilho que chama get-cnpj e
    traz a razão social e a lista de produtos. Preencher o produto antes
    disso não funciona — a lista ainda está vazia."""
    conferencia: list[tuple[str, str, str]] = []

    def anotar(rotulo: str, esperado: str, obtido: str) -> None:
        conferencia.append((rotulo, esperado, obtido))
        marca = "ok " if obtido.strip() == esperado else "DIVERGE"
        print(f"   [{marca}] {rotulo}: esperado {esperado!r}, ficou {obtido!r}")

    print("   -- 1. Remetente (o CNPJ destrava o produto) --")
    with page.expect_response(
            lambda r: "get-cnpj" in r.url, timeout=20_000):
        obtido = _digitar(page, 'input[name="value[sender_cpnj]"]',
                          DRY_RUN["sender_cnpj"])
    anotar("CNPJ remetente", DRY_RUN["sender_cnpj"], obtido)
    page.wait_for_timeout(2500)

    razao = page.locator('input[name="value[sender_name]"]').first.input_value()
    print(f"   razão social veio do site: {razao!r}")

    anotar("CEP coleta", DRY_RUN["sender_zipcode"],
           _digitar(page, 'input[name="value[sender_zipcode]"]',
                    DRY_RUN["sender_zipcode"]))
    page.wait_for_timeout(2500)
    for campo in ("sender_state", "sender_city"):
        valor = page.evaluate(
            f"() => {{ const s = document.querySelector("
            f"'select[name=\"value[{campo}]\"]'); return s ? "
            f"(s.options[s.selectedIndex] || {{}}).text || '' : '(sem select)'; }}")
        print(f"   {campo} preenchido pelo site: {valor!r}")

    print("   -- 2. Destinatário --")
    anotar("CNPJ destinatário", DRY_RUN["receiver_cnpj"],
           _digitar(page, 'input[name="value[receiver_cnpj_cpf]"]',
                    DRY_RUN["receiver_cnpj"]))
    anotar("CEP entrega", DRY_RUN["receiver_zipcode"],
           _digitar(page, 'input[name="value[receiver_zipcode]"]',
                    DRY_RUN["receiver_zipcode"]))
    page.wait_for_timeout(2500)
    for campo in ("receiver_state", "receiver_city"):
        valor = page.evaluate(
            f"() => {{ const s = document.querySelector("
            f"'select[name=\"value[{campo}]\"]'); return s ? "
            f"(s.options[s.selectedIndex] || {{}}).text || '' : '(sem select)'; }}")
        print(f"   {campo} preenchido pelo site: {valor!r}")

    print("   -- 3. Produto --")
    opcoes = page.evaluate(
        "() => [...document.querySelectorAll('#product option')]"
        ".map(o => o.textContent.trim()).filter(Boolean)")
    print(f"   opções agora: {opcoes}")
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
    anotar("produto", PRODUTO, escolhido or "(não encontrado)")
    page.wait_for_timeout(1500)

    print("   -- 4. Volume (medidas em METROS) --")
    anotar("valor NF", DRY_RUN["nf"],
           _digitar(page, 'input[name="value[volume_nf]"]', DRY_RUN["nf"]))
    anotar("peso total", DRY_RUN["peso"],
           _digitar(page, 'input[name="value[volume_weigth]"]',
                    DRY_RUN["peso"]))
    anotar("qtd volumes", DRY_RUN["qtd_volumes"],
           _digitar(page, 'input[name="cubing_qnt[]"]',
                    DRY_RUN["qtd_volumes"]))
    anotar("altura (m)", DRY_RUN["altura_m"],
           _digitar(page, 'input[name="cubing_height[]"]',
                    DRY_RUN["altura_m"]))
    anotar("largura (m)", DRY_RUN["largura_m"],
           _digitar(page, 'input[name="cubing_length[]"]',
                    DRY_RUN["largura_m"]))
    anotar("profundidade (m)", DRY_RUN["profundidade_m"],
           _digitar(page, 'input[name="cubing_depth[]"]',
                    DRY_RUN["profundidade_m"]))
    page.wait_for_timeout(1500)

    print("   -- 5. Conferência do cálculo feito pelo site --")
    cubagem = page.locator('input[name="cubing[]"]').first.input_value()
    peso_cubado = page.locator(
        'input[name="cubing_weigth[]"]').first.input_value()
    anotar("cubagem (m³)", ESPERADO["cubagem"], cubagem)
    anotar("peso cubado (kg)", ESPERADO["peso_cubado"], peso_cubado)

    divergencias = [c for c in conferencia if c[2].strip() != c[1]]
    print(f"\n   RESULTADO: {len(conferencia) - len(divergencias)} de "
          f"{len(conferencia)} campos conferem")
    if divergencias:
        print("   DIVERGENTES:")
        for rotulo, esperado, obtido in divergencias:
            print(f"     {rotulo}: esperava {esperado!r}, ficou {obtido!r}")
    print("\n   (o botão \"Simular cotação\" NÃO foi clicado)")


def main() -> int:
    from playwright.sync_api import sync_playwright

    logar = "--logar" in sys.argv
    SAIDA.mkdir(parents=True, exist_ok=True)

    # Fechado por padrão. Só o trecho do login abre, e fecha logo depois.
    permitir_escrita = {"ligado": False}

    def porteiro(rota, req):
        if req.method.upper() not in METODOS_DE_ESCRITA:
            return rota.continue_()
        # A trava que importa: a rota de envio não passa NUNCA, nem com a
        # janela de escrita aberta. É ela que criaria a cotação de verdade.
        if ROTA_DE_ENVIO in req.url:
            print(f"   [BLOQUEADO — ENVIO REAL] {req.url[:90]}")
            return rota.abort()
        if permitir_escrita["ligado"]:
            return rota.continue_()
        if any(consulta in req.url for consulta in CONSULTAS_LIBERADAS):
            print(f"   [consulta liberada] {req.url[:80]}")
            return rota.continue_()
        print(f"   [bloqueado] {req.method} {req.url[:90]}")
        return rota.abort()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless="--headed" not in sys.argv)
        page = browser.new_context(
            locale="pt-BR", viewport={"width": 1500, "height": 1100}).new_page()
        page.set_default_timeout(30_000)
        page.route("**/*", porteiro)

        try:
            print(f"1. abrindo {URL_LOGIN}")
            page.goto(URL_LOGIN, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            print("   titulo:", page.title())
            despejar(page, "1. Tela pública / login")
            page.screenshot(path=str(SAIDA / "login.png"), full_page=True)
            (SAIDA / "login.html").write_text(page.content(), encoding="utf-8")

            if not logar:
                print("\n(sem --logar: parando aqui, nada foi enviado)")
                return 0

            faltando = [k for k in ("TRANSLOVATO_CNPJ", "TRANSLOVATO_USUARIO",
                                    "TRANSLOVATO_SENHA") if not os.getenv(k)]
            if faltando:
                print(f"\nFaltam no .env: {', '.join(faltando)}")
                return 2

            print("\n2. entrando... (POST liberado só aqui)")
            permitir_escrita["ligado"] = True
            entrar(page)
            permitir_escrita["ligado"] = False
            print("   POST fechado de novo. url:", page.url)
            page.screenshot(path=str(SAIDA / "pos_login.png"), full_page=True)

            print(f"\n3. indo DIRETO para {URL_COTACAO}")
            page.goto(URL_COTACAO, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            direto = ("solicitacao-de-cotacao" in page.url
                      and "fale-conosco" not in page.url)
            print("   url final:", page.url)
            print("   atalho funciona?",
                  "SIM" if direto else "NAO - caiu no login")

            campos = despejar(page, "4. Formulário de cotação")
            (SAIDA / "campos.json").write_text(
                json.dumps(campos, ensure_ascii=False, indent=2),
                encoding="utf-8")

            print("\n5. DRY-RUN: preenchendo o formulário (sem enviar)")
            preencher_dry_run(page)
            campos_final = despejar(page, "6. Formulário preenchido")
            (SAIDA / "campos_preenchidos.json").write_text(
                json.dumps(campos_final, ensure_ascii=False, indent=2),
                encoding="utf-8")
            page.screenshot(path=str(SAIDA / "dry_run.png"), full_page=True)

            captcha = page.evaluate(JS_RECAPTCHA)
            print("\n--- reCAPTCHA ---")
            print("  " + json.dumps(captcha, ensure_ascii=False, indent=2))
            (SAIDA / "recaptcha.json").write_text(
                json.dumps(captcha, ensure_ascii=False, indent=2),
                encoding="utf-8")

            page.screenshot(path=str(SAIDA / "cotacao.png"), full_page=True)
            (SAIDA / "cotacao.html").write_text(page.content(), encoding="utf-8")
            print(f"\nevidências em {SAIDA.resolve()}")
            return 0

        except Exception as exc:
            print(f"\nERRO: {type(exc).__name__}: {exc}")
            page.screenshot(path=str(SAIDA / "erro.png"), full_page=True)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
