"""Translovato — portal do cliente, com login. Preenche, simula e lê o preço.

    https://www.translovato.com.br/portal-do-cliente/solicitacao-de-cotacao

Credenciais no .env: TRANSLOVATO_CNPJ, TRANSLOVATO_USUARIO, TRANSLOVATO_SENHA
(o login pede os três). Nunca são impressas nem gravadas nas evidências.

Síncrono: o preço aparece na própria página, numa faixa laranja, em segundos.

⚠ O botão "Simular cotação" CRIA uma cotação em "Minhas Cotações" no portal
deles. Não é fila de vendedor como a Della Volpe — é auto-serviço —, mas cada
chamada deixa registro, então não serve para teste de repetição às cegas.

Duas coisas que este adapter faz e que parecem excesso, mas não são (as duas
foram medidas contra o site real em 18/08/2026):

1. CONFERE a cubagem e o peso cubado que o site calculou contra a nossa
   conta, antes de simular. Se o produto não tiver entrado, o peso cubado sai
   300x menor e o preço volta barato, sem nenhum erro na tela. Sem esta
   conferência a cotação errada passaria por boa.
2. Fecha alerta e banner de cookies ANTES DE CADA ETAPA. Os dois nascem
   depois do carregamento e ficam por cima do formulário, engolindo cliques —
   o mesmo modo de falha que travou o login da Jadlog.
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao, print_seguro,
)
from carriers.translovato import mapping as m
from core.models import CotacaoRequest, StatusCotacao, limpa_doc

# Só esta rota cria cotação. Fica nomeada para o porteiro de rede dos scripts
# de recon poder bloqueá-la sem depender de adivinhar a URL.
ROTA_DE_ENVIO = "/portal-do-cliente/simular-cotacao"

# Consultas que o formulário faz por POST enquanto é preenchido. get-cnpj traz
# a razão social, e get-products traz a lista de produtos — sem ela o fator de
# cubagem fica errado.
CONSULTAS = (
    "/portal-do-cliente/get-cnpj",
    "/portal-do-cliente/get-products",
    "/get-cities",
    "/solicitacao-de-cotacao/validate-cep-attend",
)

# Consulta pública de cobertura. É a MESMA que o formulário deles dispara ao
# sair do campo de CEP — achada no js do site (main.min.js, validateCepAttend)
# em 19/08/2026. Responde `true`/`false` em ~1s, sem login.
#
# Duas exigências, as duas medidas em 19/08/2026 e as duas silenciosas:
#
# 1. CSRF do CodeIgniter — o token vem no cookie `csrf_cookie_name` ao abrir a
#    página pública e volta no campo `csrf_test_name`. Sem ele, HTTP 500.
# 2. O cabeçalho X-Requested-With: XMLHttpRequest é OBRIGATÓRIO. Sem ele a
#    rota nem existe: devolve HTTP 200 com a página "Página não encontrada",
#    que passa por resposta válida em qualquer checagem de status.
URL_CEP_ATENDIDO = f"{m.BASE}/solicitacao-de-cotacao/validate-cep-attend"
URL_PAGINA_PUBLICA = f"{m.BASE}/fale-conosco/solicitacao-de-cotacao"
COOKIE_CSRF = "csrf_cookie_name"
CAMPO_CSRF = "csrf_test_name"
# Generoso perto do medido (0,2s a 0,5s em 19/08/2026) e curto de propósito:
# são DUAS consultas, origem e destino, e o pior caso delas entra na frente da
# cotação. Um teto alto aqui transformaria a otimização em atraso.
TIMEOUT_CEP_S = 5.0

TIMEOUT_RESULTADO_MS = 60_000
ESPERA_AJAX_MS = 2500      # get-cnpj/get-cities/validate-cep respondem nisso


class ForaDeArea(Exception):
    """Praça fora da malha. Não é falha do robô — é resposta da transportadora,
    e vira RECUSADO, não ERRO, para o vendedor entender o que aconteceu."""


class SemTabela(Exception):
    """A Translovato não tem tabela de preço para o CNPJ do remetente.

    Também é resposta da transportadora, não falha nossa: vira RECUSADO."""


class TranslovatoAdapter:
    slug = m.SLUG
    nome = m.NOME
    modo: Modo = m.MODO
    ativo = True
    fator_cubagem: Decimal = m.FATOR_CUBAGEM
    sla_esperado_min: int | None = m.SLA_ESPERADO_MIN

    def __init__(self, headless: bool = True, timeout_ms: int = 45_000,
                 workdir: str = "teste_real/translovato") -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.workdir = Path(workdir)

    # ------------------------------------------------ delegações à camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return m.campos_obrigatorios(req)

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        return m.validar(req)

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        return m.preparar_payload(req)

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        return m.normalizar_resposta(raw)

    # ------------------------------------------------------------- mecânica
    def _credenciais(self) -> tuple[str, str, str]:
        cnpj = os.getenv("TRANSLOVATO_CNPJ")
        usuario = os.getenv("TRANSLOVATO_USUARIO")
        senha = os.getenv("TRANSLOVATO_SENHA")
        if not cnpj or not usuario or not senha:
            raise RuntimeError(
                "Faltam TRANSLOVATO_CNPJ / TRANSLOVATO_USUARIO / "
                "TRANSLOVATO_SENHA no .env")
        return cnpj, usuario, senha

    def _limpar_tela(self, page) -> str:
        """Fecha alerta e banner de cookies; devolve o aviso que apareceu.

        Os dois ficam POR CIMA do formulário e engolem cliques. Nascem depois
        do carregamento, então não adianta fechar uma vez no começo."""
        aviso = ""
        alerta = page.locator(".sweet-alert.visible")
        try:
            if alerta.count() and alerta.first.is_visible():
                aviso = alerta.first.inner_text().strip().replace("\n", " ")
                botao = alerta.first.locator("button.confirm")
                if botao.count():
                    botao.first.click()
                    page.wait_for_timeout(600)
        except Exception:
            pass

        for texto in ("Ok, entendi!", "Aceitar todos", "Aceitar"):
            try:
                alvo = page.get_by_role("button", name=texto,
                                        exact=False).first
                if alvo.count() and alvo.is_visible(timeout=800):
                    alvo.click()
                    page.wait_for_timeout(400)
                    break
            except Exception:
                continue
        return aviso

    def _entrar(self, page) -> None:
        cnpj, usuario, senha = self._credenciais()
        page.goto(m.URL_LOGIN, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        self._limpar_tela(page)

        page.locator("#login-portal #cnpj").fill(cnpj)
        page.locator("#login-portal #user").fill(usuario)
        page.locator("#login-portal input[name='password']").fill(senha)

        # O botão é ajax-form: o POST é assíncrono. Esperar a RESPOSTA em vez
        # de dormir um tempo fixo evita seguir com a sessão ainda não criada.
        with page.expect_response(
                lambda r: "/portal-do-cliente/login" in r.url, timeout=20_000):
            page.locator("#login-portal button.common-button").click()
        page.wait_for_timeout(1500)

    def _digitar(self, page, seletor: str, valor: str) -> str:
        """Digita tecla a tecla e devolve o que ficou no campo.

        As máscaras deste site rodam no keyup: `fill()` num campo mascarado
        deixa o valor cru ou é reformatado por cima depois. A leitura de volta
        é o que prova que ficou o que a gente queria."""
        campo = page.locator(seletor).first
        campo.click()
        campo.fill("")
        campo.press_sequentially(valor, delay=40)
        campo.blur()
        page.wait_for_timeout(400)
        return campo.input_value()

    def _preencher(self, page, campos: dict[str, str]) -> None:
        """Preenche na ordem que o site exige.

        O CNPJ do remetente vem PRIMEIRO de propósito: é ele que dispara
        get-products e traz a lista de produtos. Escolher o produto antes
        disso acha a lista vazia — e sem produto o fator de cubagem é 1."""
        with page.expect_response(lambda r: "get-cnpj" in r.url,
                                  timeout=20_000):
            self._digitar(page, 'input[name="value[sender_cpnj]"]',
                          campos["value[sender_cpnj]"])
        page.wait_for_timeout(ESPERA_AJAX_MS)

        self._digitar(page, 'input[name="value[sender_zipcode]"]',
                      campos["value[sender_zipcode]"])
        page.wait_for_timeout(ESPERA_AJAX_MS)
        aviso = self._limpar_tela(page)
        if m.AVISO_FORA_DE_AREA in aviso:
            raise ForaDeArea(aviso)

        self._digitar(page, 'input[name="value[receiver_cnpj_cpf]"]',
                      campos["value[receiver_cnpj_cpf]"])
        self._digitar(page, 'input[name="value[receiver_zipcode]"]',
                      campos["value[receiver_zipcode]"])
        page.wait_for_timeout(ESPERA_AJAX_MS)
        aviso = self._limpar_tela(page)
        if m.AVISO_FORA_DE_AREA in aviso:
            raise ForaDeArea(aviso)

        # O <select> real fica display:none atrás de um widget selectBox, e
        # select_option exige visibilidade. Setar o value e disparar 'change'
        # é o que o próprio widget escuta.
        escolhido = page.evaluate(
            """(alvo) => {
                const sel = document.querySelector('#product');
                if (!sel) return null;
                const opt = [...sel.options].find(
                    o => o.textContent.trim().toUpperCase() === alvo);
                if (!opt) return null;
                sel.value = opt.value;
                sel.dispatchEvent(new Event('change', {bubbles: true}));
                return opt.textContent.trim();
            }""", campos["value[volume_product]"])
        if not escolhido:
            # Sem tabela para este remetente. Não é falha do robô: é resposta
            # da transportadora, e vira RECUSADO com frase que o vendedor
            # entende — não um RuntimeError técnico no cartão.
            raise SemTabela(
                m.recusa_sem_tabela(campos["value[sender_cpnj]"]))
        page.wait_for_timeout(1200)

        for name in ("value[volume_nf]", "value[volume_weigth]",
                     "cubing_qnt[]", "cubing_height[]", "cubing_length[]",
                     "cubing_depth[]"):
            self._digitar(page, f'input[name="{name}"]', campos[name])
        page.wait_for_timeout(1500)

    def _conferir_cubagem(self, page, esperado: dict[str, str]) -> None:
        """A trava contra o erro silencioso. Ver o docstring do módulo."""
        cubagem = page.locator('input[name="cubing[]"]').first.input_value()
        peso = page.locator('input[name="cubing_weigth[]"]').first.input_value()

        if cubagem.strip() != esperado["cubagem"]:
            raise RuntimeError(
                f"a cubagem que o site calculou ({cubagem!r}) não bate com a "
                f"nossa conta ({esperado['cubagem']!r}) — alguma medida entrou "
                "errada. Não vou cotar com isso.")
        if peso.strip() != esperado["peso_cubado"]:
            raise RuntimeError(
                f"o peso cubado do site ({peso!r}) não bate com o esperado "
                f"({esperado['peso_cubado']!r}). Normalmente é o produto que "
                "não entrou — sem ele o fator vira 1 e o frete sai barato "
                "demais.")

    def _print_resultado(self, page, destino: Path) -> list[str]:
        """Recorta o que vai para o cliente: a carga E o preço.

        Vai do topo do bloco "Identificação do volume" até o fim da faixa
        laranja. Só o preço não basta — a primeira pergunta que o cliente faz
        de volta é "esse valor é para qual carga?", e produto, peso e cubagem
        (calculados pelo SITE, não por nós) respondem isso no mesmo print.

        A tela cheia não serve: traz menu, banner de cookies e as condições
        gerais, e o preço se perde no meio.

        Rola a página antes de medir. Sem isso o recorte só funcionava por
        sorte, quando a faixa já estava visível — com ela abaixo da dobra as
        coordenadas caíam fora da janela, o screenshot falhava e caía calado
        no print da página inteira."""
        try:
            caixa = page.evaluate(r"""() => {
                const folga = 12;
                const acha = (re) => [...document.querySelectorAll('*')].find(
                    el => el.children.length === 0
                          && re.test(el.textContent || ''));
                // Sobe até o ancestral que JÁ CONTÉM o que interessa. O
                // closest('div') direto pegava só a caixinha do rótulo.
                const sobe = (el, re, limite) => {
                    for (let i = 0; i < limite && el && el.parentElement; i++) {
                        el = el.parentElement;
                        if (re.test(el.innerText || '')) return el;
                    }
                    return null;
                };
                const recorte = (topo, base, esq, dir) => {
                    const x = Math.max(0, esq - folga);
                    const y = Math.max(0, topo - folga);
                    return {x, y,
                        width: Math.min(dir - esq + folga * 2,
                                        window.innerWidth - x),
                        height: Math.min(base - topo + folga * 2,
                                         window.innerHeight - y)};
                };

                const rotuloFaixa = acha(/Consulta de Valor/i);
                if (!rotuloFaixa) return null;
                const faixa = sobe(rotuloFaixa, /R\$\s*[\d.,]+/, 6);
                if (!faixa) return null;

                const rotuloVol = acha(/Identifica[çc][ãa]o do volume/i);
                const volume = rotuloVol
                    ? sobe(rotuloVol, /PESO CUBADO/i, 8) : null;

                if (volume) {
                    window.scrollTo({top: window.scrollY
                        + volume.getBoundingClientRect().top - folga,
                        behavior: 'instant'});
                    const v = volume.getBoundingClientRect();
                    const f = faixa.getBoundingClientRect();
                    // Os dois juntos podem não caber na janela (tela pequena,
                    // muitas linhas de cubagem). Aí é melhor o print antigo,
                    // que sempre coube, do que um recorte cortado ao meio.
                    if (v.top >= -1 && f.bottom > v.top
                            && f.bottom <= window.innerHeight + 1)
                        return recorte(Math.min(v.top, f.top),
                                       Math.max(v.bottom, f.bottom),
                                       Math.min(v.left, f.left),
                                       Math.max(v.right, f.right));
                }

                faixa.scrollIntoView({block: 'center', behavior: 'instant'});
                const f = faixa.getBoundingClientRect();
                return recorte(f.top, f.bottom, f.left, f.right);
            }""")
            if caixa and caixa["height"] > 40 and caixa["width"] > 100:
                page.screenshot(path=str(destino), clip=caixa, timeout=10_000)
                return [str(destino)]
        except Exception:
            pass
        return print_seguro(page, destino)

    # ------------------------------------------------------- cobertura (rápido)
    def _cep_atendido(self, cep: str) -> bool | None:
        """A Translovato atende esta praça? `None` = não deu para saber.

        Os três estados são de propósito. `False` só sai quando ELES
        responderam que não; qualquer outra coisa — rede fora, HTTP diferente
        de 200, corpo inesperado, endpoint mudado de nome — vira `None`, e
        quem chama segue cotando do jeito normal.

        Recusar por dúvida seria o pior erro possível aqui: o robô diria "não
        atende" sobre uma praça que a Translovato atende, e o vendedor
        perderia o frete achando que o sistema conferiu. Perder 40 segundos é
        muito melhor que isso.

        Medido em 19/08/2026: ES, SP, MG, RS, PR e Salvador/BA respondem
        `true`; Rio Branco/AC, Macapá/AP e Fortaleza/CE respondem `false`."""
        import httpx

        try:
            with httpx.Client(timeout=TIMEOUT_CEP_S, follow_redirects=True,
                              headers={"X-Requested-With": "XMLHttpRequest",
                                       "Referer": URL_PAGINA_PUBLICA}) as c:
                c.get(URL_PAGINA_PUBLICA)
                token = c.cookies.get(COOKIE_CSRF)
                if not token:
                    return None
                resp = c.post(URL_CEP_ATENDIDO,
                              data={"cep": limpa_doc(cep or ""),
                                    CAMPO_CSRF: token})
        except Exception:
            return None

        if resp.status_code != 200:
            return None
        corpo = resp.text.strip().lower()
        if corpo == "true":
            return True
        if corpo == "false":
            return False
        return None

    # ------------------------------------------------------------------ envio
    def cotar(self, req: CotacaoRequest) -> ResultadoCotacao:
        from playwright.sync_api import sync_playwright

        erros = m.bloqueantes(self.validar(req))
        if erros:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO,
                erro="; ".join(f"{e.campo}: {e.mensagem}" for e in erros))

        # Pergunta a cobertura ANTES de abrir o navegador. O caminho completo
        # (login, formulário, preenchimento) leva ~40s para chegar na MESMA
        # resposta, e quem espera é o vendedor na frente do cliente.
        #
        # `is False` de propósito: só recusa quando ELES disseram não. `None`
        # é dúvida, e dúvida segue para a cotação de verdade.
        for lado, local in (("origem", req.origem), ("destino", req.destino)):
            if self._cep_atendido(local.cep or "") is False:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.RECUSADO,
                    motivo_recusa=m.recusa_cep_nao_atendido(local.cep or "",
                                                            lado))

        campos = self.preparar_payload(req)
        esperado = m.cubagem_esperada(req)
        run = self.workdir / datetime.now().strftime("%Y%m%d-%H%M%S")
        run.mkdir(parents=True, exist_ok=True)
        enviado = datetime.now()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_context(
                locale="pt-BR",
                viewport={"width": 1500, "height": 1100}).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                self._entrar(page)
                page.goto(m.URL_COTACAO, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                if "solicitacao-de-cotacao" not in page.url:
                    raise RuntimeError("sessão não persistiu até o formulário")
                self._limpar_tela(page)

                self._preencher(page, campos)
                self._conferir_cubagem(page, esperado)
                print_seguro(page, run / "preenchido.png")

                botao = page.get_by_role("button",
                                         name="Simular cotação").first
                botao.scroll_into_view_if_needed()
                self._limpar_tela(page)
                botao.click()

                page.wait_for_function(
                    """() => /Consulta de Valor/i.test(document.body.innerText)
                             && /R\\$\\s*[\\d.,]+/.test(document.body.innerText)""",
                    timeout=TIMEOUT_RESULTADO_MS)
                page.wait_for_timeout(1500)

                res = self.normalizar_resposta(
                    page.locator("body").inner_text())
                res.enviado_em = enviado
                res.respondido_em = datetime.now()
                res.evidencias = self._print_resultado(
                    page, run / "resultado.png")
                return res

            except ForaDeArea as fora:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.RECUSADO, enviado_em=enviado,
                    motivo_recusa="A Translovato não atende este CEP.",
                    raw_response=str(fora)[:400],
                    evidencias=print_seguro(page, run / "fora_de_area.png"))
            except SemTabela as sem:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.RECUSADO, enviado_em=enviado,
                    motivo_recusa=str(sem),
                    evidencias=print_seguro(page, run / "sem_tabela.png"))
            except Exception as exc:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.ERRO, enviado_em=enviado,
                    erro=f"{type(exc).__name__}: {exc}",
                    evidencias=print_seguro(page, run / "erro.png"))
            finally:
                browser.close()
