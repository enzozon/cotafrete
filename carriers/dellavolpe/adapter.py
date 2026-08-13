"""Della Volpe — camada de BROWSER.

Separada de propósito da camada pura (mapping.py). Tudo que é decisão de negócio
mora lá; aqui só existe o mecânico de localizar campo e digitar.

Seletores por LABEL e PLACEHOLDER, nunca por XPath posicional. É o que faz a
automação sobreviver a mudança de layout do site.

    ADAPTER_BASE_URL=http://localhost:8099 python -m carriers.dellavolpe.adapter
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
from carriers.dellavolpe import mapping as m
from carriers.dellavolpe.planilha import gerar_planilha_volumes
from core.models import CotacaoRequest, StatusCotacao

URL_PRODUCAO = "https://dellavolpe.com.br/#cotacao"

# Só DESAFIO conta como bloqueio. O reCAPTCHA v3 do site entrega um badge
# VISÍVEL de 256x60 (div.grecaptcha-badge + iframe api2/anchor?...size=invisible)
# em toda página — é selo, não interrogatório. Medido no site em produção.
SELETORES_DESAFIO_CAPTCHA = (
    'iframe[src*="api2/bframe" i]',                                # v2: imagens
    'iframe[src*="recaptcha" i]:not([src*="size=invisible" i])',   # v2: checkbox
    'iframe[src*="hcaptcha" i]',
    'iframe[src*="turnstile" i]',
    'div[class*="cf-challenge" i]',
)

# Atributos name= reais, medidos por recon_dellavolpe.py contra produção.
# ÚLTIMO recurso do _localizar: só entra quando label, placeholder e texto de
# option não resolvem. Substitui o antigo [name*="{rotulo[:14]}"], que comparava
# texto humano contra atributo de máquina e só acertava por coincidência.
SELETOR_POR_ROTULO = {
    "Nome completo": "nome",
    "E-mail": "email",
    "WhatsApp": "whatsapp",
    "Qual o serviço que você procura?": "servico",
    "CNPJ - Remetente": "cnpj_origem",
    "Selecione o estado de origem": "estado_origem",
    "Selecione a cidade de origem": "cidade_origem",
    "CNPJ - Destinatário": "cnpj_destino",
    "Selecione o estado de destino": "estado_destino",
    "Selecione a cidade de destino": "cidade_destino",
    "Escolha o tipo de veículo": "tipo-veiculo",
    "Peso total": "peso",
    "Quantidade de Volumes": "qtd-volume",
    "Comprimento": "comprimento",
    "Largura": "largura",
    "Altura": "altura",
    "Valor total da nota fiscal": "valor",
    "Tipo de Material que será transportado": "material",
    "CNPJ da empresa que pagará o frete": "cnpj",
}

# Os input[type=file] do site têm name="" e se identificam por data-name.
ANEXO_POR_ROTULO = {
    "Anexar Planilha": "anexo-vol",
    "Anexar FISPQ / Licença": "anexo-fispq",
    "Anexar FISPQ": "anexo-fispq",
}

# Dependências REAIS do formulário: cada um destes precisa vir antes do
# seguinte. A ordenação alfabética que havia aqui punha "Escolha o tipo de
# veículo" (E) antes de "Qual o serviço que você procura?" (Q) — e no site o
# select de veículo fica display:none até FTL ser escolhido.
# Caixa do formulário para o print, em coordenadas da PÁGINA (não da janela).
#
# Os <form> do site são wpcf7-form com altura ZERO: não envolvem visualmente
# nada, quem tem tamanho é o modal em volta. Por isso screenshot do <form>
# falha com "element is not visible" e o print acabava saindo do site inteiro.
# Daí a subida até o primeiro ancestral com altura de verdade.
#
# E o modal ainda ROLA POR DENTRO: o que está fora da área visível dele não
# entra em screenshot nenhum. Por isso o print expande temporariamente os
# containers com overflow antes de medir, e desfaz depois. É mexida só de
# layout — nenhum valor de campo é tocado.
ALTURA_MINIMA_CONTAINER = 200

# O validador do site dispara enquanto o campo ainda está vazio e NÃO reavalia
# sozinho depois que ele é preenchido. Resultado: "O campo é obrigatório" em
# vermelho ao lado de um WhatsApp corretamente preenchido — mensagem velha, num
# print que serve justamente para o Enzo conferir o que foi enviado. Reemitir
# os eventos faz o validador rodar de novo com o valor atual.
# NUNCA disparar em <select>, e nunca 'input'/'change': o select de estado tem
# JS que repopula o de cidade e ZERA a escolha. A primeira versão disto
# reemitia em tudo e apagou as duas cidades já selecionadas — teriam ido 6
# cotações sem cidade nenhuma. Só 'blur', e só em campo de texto.
JS_REVALIDAR = """() => {
    const alvos = 'input[type=text], input[type=email], input[type=tel],'
                + ' input[type=number], textarea';
    document.querySelectorAll(alvos).forEach(e => {
        if (!(e.offsetWidth || e.offsetHeight)) return;
        if (!e.value) return;              // vazio de verdade: erro é legítimo
        e.dispatchEvent(new Event('blur', {bubbles: true}));
    });
}"""

JS_EXPANDIR_ROLAGEM = """() => {
    // O form com MAIS campos visíveis, não o primeiro que tiver algum: o
    // site mantém vários formulários no mesmo DOM e o primeiro com um campo
    // visível era um de 7 campos, o que recortava o print pela metade.
    const visiveis = (f) =>
        [...f.querySelectorAll('input, select, textarea')]
            .filter(x => x.offsetWidth || x.offsetHeight).length;
    const form = [...document.querySelectorAll('form')]
        .filter(f => visiveis(f) > 0)
        .sort((a, b) => visiveis(b) - visiveis(a))[0];
    if (!form) return 0;

    let mexidos = 0;
    for (let n = form; n && n !== document.body; n = n.parentElement) {
        const s = getComputedStyle(n);
        const rola = n.scrollHeight > n.clientHeight + 4;
        if (rola || s.overflowY === 'auto' || s.overflowY === 'scroll'
                 || s.maxHeight !== 'none') {
            n.dataset.dvPrintAntes = JSON.stringify({
                h: n.style.height, mh: n.style.maxHeight,
                oy: n.style.overflowY, o: n.style.overflow,
            });
            n.style.height = 'auto';
            n.style.maxHeight = 'none';
            n.style.overflowY = 'visible';
            n.style.overflow = 'visible';
            mexidos++;
        }
    }
    return mexidos;
}"""

JS_RESTAURAR_ROLAGEM = """() => {
    document.querySelectorAll('[data-dv-print-antes]').forEach(n => {
        const a = JSON.parse(n.dataset.dvPrintAntes);
        n.style.height = a.h; n.style.maxHeight = a.mh;
        n.style.overflowY = a.oy; n.style.overflow = a.o;
        delete n.dataset.dvPrintAntes;
    });
}"""

MARGEM_PRINT_PX = 24
JS_CAIXA_DO_FORMULARIO = """() => {
    // UNIÃO das caixas de TODOS os campos visíveis da página — sem escopar
    // por <form>. Três tentativas anteriores falharam por escopo: o <form>
    // tem altura 0; o ancestral com tamanho é ora metade do modal, ora o site
    // inteiro; e os campos do modal estão espalhados em MAIS DE UM <form>, o
    // que recortava o print na metade. Como só o modal aberto tem campos
    // visíveis, "todo campo visível" é exatamente o formulário que interessa.
    const partes = [...document.querySelectorAll('input, select, textarea')]
        .filter(x => (x.offsetWidth || x.offsetHeight)
                     && x.type !== 'hidden'
                     // banner de cookies não faz parte da cotação
                     && !x.closest('#onetrust-consent-sdk, [id*=onetrust i]'));

    // A confirmação ("Agradecemos a sua mensagem...") fica ABAIXO do botão,
    // fora da área dos campos. Sem incluí-la, o print do envio não mostra
    // justamente a prova de que o envio deu certo.
    partes.push(...[...document.querySelectorAll('.wpcf7-response-output')]
        .filter(e => e.innerText.trim().length > 5));

    if (!partes.length) return null;

    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    for (const e of partes) {
        const r = e.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        x1 = Math.min(x1, r.x); y1 = Math.min(y1, r.y);
        x2 = Math.max(x2, r.right); y2 = Math.max(y2, r.bottom);
    }
    if (!isFinite(x1) || x2 - x1 < 100 || y2 - y1 < 100) return null;

    // O modal é position:fixed — a caixa já é relativa à JANELA e não
    // acompanha a rolagem. Somar scrollY como se fosse coordenada de página
    // empurrava o recorte para baixo: o print começava no meio do WhatsApp e
    // sobrava faixa vazia embaixo, do tamanho exato da rolagem.
    let fixo = false;
    for (let n = partes[0]; n && n !== document.body; n = n.parentElement)
        if (getComputedStyle(n).position === 'fixed') { fixo = true; break; }

    const m = 24;
    const dx = fixo ? 0 : window.scrollX;
    const dy = fixo ? 0 : window.scrollY;
    return {
        fixo,
        x: Math.max(0, x1 - m + dx),
        y: Math.max(0, y1 - m + dy),
        width: (x2 - x1) + 2 * m,
        height: (y2 - y1) + 2 * m,
    };
}"""

ORDEM_DEPENDENCIA = (
    "Qual o serviço que você procura?",
    "Escolha o tipo de veículo",
    "Selecione o estado de origem",
    "Selecione a cidade de origem",
    "Selecione o estado de destino",
    "Selecione a cidade de destino",
)


class DellavolpeAdapter:
    slug = m.SLUG
    nome = m.NOME
    modo: Modo = m.MODO
    ativo = True
    fator_cubagem: Decimal = m.FATOR_CUBAGEM
    sla_esperado_min: int | None = m.SLA_ESPERADO_MIN

    def __init__(self, base_url: str | None = None, headless: bool = True,
                 timeout_ms: int = 45_000, workdir: str = "runs") -> None:
        self.base_url = base_url or os.getenv("ADAPTER_BASE_URL") or URL_PRODUCAO
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.workdir = Path(workdir)
        self.is_mock = "localhost" in self.base_url or "127.0.0.1" in self.base_url

    # ------------------------------------------------ delegações à camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return m.campos_obrigatorios(req)

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        return m.validar(req)

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        return m.preparar_payload(req)

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        return m.normalizar_resposta(raw)

    # ------------------------------------------------------------------ envio
    def cotar(self, req: CotacaoRequest, *, confirmar_envio: bool = False) -> ResultadoCotacao:
        """confirmar_envio=False faz DRY-RUN: preenche tudo e para antes do submit.

        Contra o site de produção o default é sempre dry-run. Cada envio real cai
        na fila comercial da transportadora — não é lugar de teste."""
        from playwright.sync_api import sync_playwright

        erros = m.bloqueantes(self.validar(req))
        if erros:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO,
                erro="; ".join(f"{e.campo}: {e.mensagem}" for e in erros),
            )

        if confirmar_envio and not self.is_mock:
            self._exigir_confirmacao_explicita()
            # O reCAPTCHA v3 do site pontua Chromium headless como robo e o
            # Contact Form 7 barra a submissao como spam — medido em
            # 13/08/2026: cinco envios headless viraram "A submissao
            # mencionou-se como spam" e NENHUM e-mail foi gerado. Com janela
            # de verdade o mesmo envio passa. Nao e preferencia: headless
            # simplesmente nao envia.
            headless_efetivo = False
        else:
            headless_efetivo = self.headless

        payload = self.preparar_payload(req)
        campos = m.campos_do_formulario(payload)
        run = self.workdir / datetime.now().strftime("%Y%m%d-%H%M%S")
        run.mkdir(parents=True, exist_ok=True)

        # anexo gerado a partir da lista de volumes
        anexos_planilha: list[str] = []
        if payload.get("Anexar Planilha") == ["__PLANILHA_VOLUMES__"]:
            anexos_planilha = [str(gerar_planilha_volumes(req, run / "volumes.xlsx"))]
            campos.pop("Anexar Planilha", None)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless_efetivo)
            # Janela ALTA de proposito: o modal de cotacao rola por dentro,
            # e o que fica fora da area visivel dele nao entra em screenshot
            # nenhum. Com 2600px de altura o formulario inteiro cabe sem
            # rolagem interna, e o print sai completo.
            page = browser.new_context(
                locale="pt-BR",
                viewport={"width": 1280, "height": 2600}).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                # networkidle nunca chega nesta pagina: os rastreadores (analytics,
                # chat, pixel) mantem conexao aberta e o goto estourava 45s sem
                # que a pagina tivesse problema nenhum. Espera-se o formulario.
                page.goto(self.base_url, wait_until="domcontentloaded")
                # state=attached: os <form> deste site tem altura zero, entao o
                # padrao (visible) nunca e satisfeito
                page.wait_for_selector("form", state="attached",
                                       timeout=self.timeout_ms)
                page.wait_for_timeout(2000)
                self._abrir_accordion(page)

                if self._tem_captcha(page):
                    page.screenshot(path=str(run / "captcha.png"), full_page=True)
                    return ResultadoCotacao(
                        self.slug, StatusCotacao.INTERVENCAO_NECESSARIA,
                        erro="Proteção anti-bot detectada. Requer ação humana.",
                        evidencias=[str(run / "captcha.png")],
                    )

                # anexos saem ANTES: input[type=file] não aceita fill()
                texto, arquivos = m.separar_anexos(campos)

                self._preencher(page, texto)

                for arq in anexos_planilha:
                    self._anexar(page, "Anexar Planilha", [arq])
                if fispq := arquivos.get("Anexar FISPQ / Licença"):
                    self._anexar(page, "Anexar FISPQ", [fispq])

                # ANTES do submit: é este print que permite conferir o que foi
                # enviado quando o e-mail voltar com preço estranho.
                evid_preenchido = self._print_formulario(
                    page, run / "preenchido.png")

                if not confirmar_envio:
                    return ResultadoCotacao(
                        self.slug, StatusCotacao.RASCUNHO,
                        raw_response="DRY-RUN: formulário preenchido, nada enviado.",
                        evidencias=evid_preenchido,
                    )

                self._enviar(page)

                res = self.normalizar_resposta(page.content())
                res.enviado_em = datetime.now()
                res.evidencias = [
                    *evid_preenchido,
                    # mesmo recorte do formulário: mostra a confirmação do
                    # site, que é a prova de que a cotação entrou
                    *self._print_formulario(page, run / "resposta.png"),
                ]
                return res

            except Exception as exc:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.ERRO, erro=f"{type(exc).__name__}: {exc}",
                    evidencias=print_seguro(page, run / "erro.png"),
                )
            finally:
                browser.close()

    # ------------------------------------------------------------- mecânica
    def _exigir_confirmacao_explicita(self) -> None:
        if os.getenv("DV_ENVIO_REAL_AUTORIZADO") != "sim":
            raise RuntimeError(
                "Envio real bloqueado. Cada submissão vira uma cotação na fila "
                "comercial da Della Volpe. Só libere com uma carga que você "
                "realmente precisa cotar: DV_ENVIO_REAL_AUTORIZADO=sim"
            )

    def _abrir_accordion(self, page) -> None:
        for texto in ("Fazer Cotação", "Faça uma Cotação", "Transporte: Carga Lotação"):
            try:
                alvo = page.get_by_text(texto, exact=False).first
                if alvo.is_visible(timeout=1500):
                    alvo.click()
                    page.wait_for_timeout(900)
            except Exception:
                continue

    def _tem_captcha(self, page) -> bool:
        """Só um DESAFIO VISÍVEL conta como bloqueio.

        O site carrega reCAPTCHA v3 (invisível, por score) em toda página, então
        procurar a string 'recaptcha' no HTML fazia o adapter abortar com
        INTERVENCAO_NECESSARIA em 100% das execuções reais, sem digitar nada."""
        for seletor in SELETORES_DESAFIO_CAPTCHA:
            try:
                if self._primeiro_visivel(page.locator(seletor)) is not None:
                    return True
            except Exception:
                continue
        return False

    def _primeiro_visivel(self, loc):
        """Primeiro elemento VISÍVEL de um locator, ou None.

        Existe porque .first resolve antes de testar visibilidade: a página de
        produção carrega 9 formulários de uma vez com os mesmos name= e
        placeholders, e .first devolvia um campo oculto do formulário errado —
        descartando a estratégia inteira mesmo havendo um campo certo adiante."""
        try:
            total = loc.count()
        except Exception:
            return None
        for i in range(min(total, 40)):
            candidato = loc.nth(i)
            try:
                if candidato.is_visible():
                    return candidato
            except Exception:
                continue
        return None

    def _localizar(self, page, rotulo: str):
        """Label -> placeholder -> texto da 1ª option -> name conhecido.

        Sempre o primeiro campo VISÍVEL de cada estratégia."""
        tentativas = [
            lambda: page.get_by_label(rotulo, exact=False),
            lambda: page.get_by_placeholder(rotulo, exact=False),
            # os <select> do site não têm label nem placeholder: o único texto
            # próprio deles é o da primeira <option>, que é o próprio rótulo
            lambda: page.locator("select").filter(has_text=rotulo),
        ]
        if name := SELETOR_POR_ROTULO.get(rotulo):
            tentativas.append(lambda: page.locator(f'[name="{name}"]'))

        for tentativa in tentativas:
            try:
                alvo = self._primeiro_visivel(tentativa())
            except Exception:
                continue
            if alvo is not None:
                return alvo
        raise LookupError(f"campo não encontrado: {rotulo!r}")

    @staticmethod
    def _ordenar(campos: dict[str, Any]) -> list[str]:
        """Campos com dependência primeiro, na ordem declarada; o resto depois."""
        prioridade = {r: i for i, r in enumerate(ORDEM_DEPENDENCIA)}
        return sorted(campos, key=lambda k: (prioridade.get(k, len(prioridade)), k))

    def _esperar_opcoes(self, page, loc) -> None:
        """Espera o XHR popular o select, em vez de apostar num tempo fixo.

        wait_for_timeout(1200) era palpite: numa rede mais lenta que o palpite o
        select ainda está vazio e a cidade fica em branco, em silêncio."""
        page.wait_for_function(
            "el => el.options.length > 1",
            arg=loc.element_handle(),
            timeout=self.timeout_ms,
        )

    def _preencher(self, page, campos: dict[str, Any]) -> None:
        for rotulo in self._ordenar(campos):
            valor = campos[rotulo]
            if not isinstance(valor, str):
                continue
            loc = self._localizar(page, rotulo)
            if loc.evaluate("el => el.tagName") == "SELECT":
                if "cidade" in rotulo.lower():
                    self._esperar_opcoes(page, loc)
                try:
                    # UF vai como sigla ("ES") mas a option exibe "Espírito
                    # Santo": casa por value, não por label.
                    loc.select_option(label=valor)
                except Exception:
                    loc.select_option(value=valor)
            else:
                loc.fill(valor)

    def _enviar(self, page) -> None:
        """Clica em "Pedir orçamento" e ESPERA a confirmação aparecer.

        O botão é `input.wpcf7-submit[value="Pedir orçamento"]` e existe uma
        cópia em CADA formulário do site — os outros ficam ocultos no mesmo
        DOM. `get_by_role(...).click()` pegava o primeiro da lista, que podia
        ser um oculto: o clique "funcionava", o Playwright não reclamava, e
        nada era enviado. Foi assim que 5 cotações saíram sem gerar e-mail.

        Depois do clique, esperar `networkidle` também não bastava: o CF7
        responde por AJAX e só então escreve o texto na div de resposta. Sem
        esperar por ESSE texto, o HTML era lido antes da confirmação existir.
        """
        botao = page.locator(
            'input.wpcf7-submit[type="submit"]:visible').first
        if not botao.count():
            botao = page.get_by_role("button", name="Pedir orçamento").first
        botao.scroll_into_view_if_needed(timeout=10_000)
        botao.click(timeout=15_000)

        # a div de resposta existe desde o começo, vazia; o que muda é o texto
        try:
            page.wait_for_function(
                """() => [...document.querySelectorAll('.wpcf7-response-output')]
                       .some(e => e.innerText.trim().length > 5)""",
                timeout=self.timeout_ms)
        except Exception:
            pass          # normalizar_resposta decide; aqui não se inventa nada
        page.wait_for_timeout(1200)      # deixa o texto pintar antes do print

    def _print_formulario(self, page, destino: Path) -> list[str]:
        """Print do FORMULÁRIO, não do site inteiro.

        É a única evidência que o Enzo tem para conferir o que foi enviado,
        já que o preço só volta por e-mail. Com full_page=True o formulário
        saía como uma tira no topo de uma imagem de 5000px, seguida de banner
        e rodapé — ilegível justamente na parte que importa.

        Se o formulário não for localizável, cai para o print da página: com
        o envio já feito, evidência ruim é melhor que nenhuma.
        """
        try:
            page.evaluate(JS_REVALIDAR)
            page.wait_for_timeout(600)
            page.evaluate(JS_EXPANDIR_ROLAGEM)
            page.wait_for_timeout(500)          # deixa o layout reassentar
            try:
                caixa = page.evaluate(JS_CAIXA_DO_FORMULARIO)
                if caixa:
                    fixo = caixa.pop("fixo", False)
                    # Elemento fixo: coordenada de JANELA, print de janela.
                    # Elemento normal: coordenada de PÁGINA, e full_page deixa
                    # o recorte passar da altura da janela sem cortar o fim.
                    page.screenshot(path=str(destino), full_page=not fixo,
                                    clip=caixa, timeout=15_000)
                    return [str(destino)]
            finally:
                # devolve o layout ao normal ANTES do submit, aconteça o que
                # acontecer: o print não pode alterar o que o site recebe
                page.evaluate(JS_RESTAURAR_ROLAGEM)
        except Exception:
            pass
        return print_seguro(page, destino)

    def _form_visivel(self, page):
        """O <form> que está de fato aberto no accordion, ou None.

        Sem escopo, o anexo pode ir parar num formulário oculto de outro
        serviço — todos convivem no mesmo DOM."""
        forms = page.locator("form")
        try:
            total = forms.count()
        except Exception:
            return None
        for i in range(min(total, 20)):
            form = forms.nth(i)
            try:
                if form.locator("input:visible, select:visible").count():
                    return form
            except Exception:
                continue
        return None

    def _anexar(self, page, rotulo: str, arquivos: list[str]) -> None:
        """Cada anexo no SEU input.

        O fallback antigo mandava os dois para input[type=file].first, então a
        FISPQ caía no slot da planilha de volumes — exatamente o cenário que
        separar_anexos() foi escrito para proteger. Os inputs são d-none, então
        aqui NÃO se filtra por visibilidade: set_input_files funciona em campo
        oculto, e é assim que o site trata anexo."""
        try:
            por_label = page.get_by_label(rotulo, exact=False)
            if por_label.count():
                por_label.first.set_input_files(arquivos)
                return
        except Exception:
            pass

        if data_name := ANEXO_POR_ROTULO.get(rotulo):
            seletor = f'input[type="file"][data-name="{data_name}"]'
            for escopo in (self._form_visivel(page), page):
                if escopo is None:
                    continue
                try:
                    loc = escopo.locator(seletor)
                    if loc.count():
                        loc.first.set_input_files(arquivos)
                        return
                except Exception:
                    continue

        raise LookupError(f"campo de anexo não encontrado: {rotulo!r}")
