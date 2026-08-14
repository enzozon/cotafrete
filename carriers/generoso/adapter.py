"""Transporte Generoso — formulário de cotação em ETAPAS.

    https://cliente.generoso.com.br/cotacao

⚠ A URL divulgada (generoso.com.br/cotacao) é 404; a página de erro é que
aponta para a área do cliente.

Cinco etapas, cada uma só libera a seguinte:
    1. Solicitante   e-mail, CNPJ, nome, WhatsApp
    2. Tipo pagador  select; com FOB o CNPJ do destinatário fica travado
    3. Origem        CNPJ do remetente preenche o endereço inteiro
    4. Destino       CNPJ travado; o endereço precisa ser destravado pelo CEP
    5. Carga         valor da NF, medidas, peso, quantidade

Assíncrono como a Della Volpe: a tela final só confirma o recebimento
("Recebemos seu pedido de cotação"), o preço vem por e-mail depois.

TRÊS REGRAS MEDIDAS NO SITE em 13/08/2026 — sem elas a cotação sai errada e
sem nenhum aviso na tela:

1. Na ORIGEM, não digitar o CEP. O CNPJ do remetente traz CEP, cidade,
   bairro, rua, número e complemento do cadastro da empresa. Digitar o CEP
   por cima troca tudo pelo endereço genérico daquele CEP — para o CNPJ
   60.042.686/0001-05 o cadastro é Santo André/Vila Metalúrgica e o CEP
   resolve para São Bernardo do Campo/Planalto. Cidade diferente, frete
   diferente.

2. No DESTINO é o oposto. O CNPJ vem travado e traz só o CEP; cidade,
   estado, bairro e rua ficam vazios. Redisparar o CEP preenche — e aqui
   pode, porque não há endereço bom para perder.

3. O campo de peso tem máscara de 2 casas, da direita para a esquerda:
   "1" vira 0.01 e "100" vira 1.00. Sempre 2 casas.

E a busca do site só acorda com digitação: `fill()` instantâneo não dispara.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from datetime import datetime

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao, Severidade, print_seguro,
)
from core.models import CotacaoRequest, StatusCotacao

URL = "https://cliente.generoso.com.br/cotacao"

TIPO_PAGADOR_DESTINATARIO = "Destinatario (FOB)"
TIPO_PAGADOR_REMETENTE = "Remetente (CIF)"

BOTAO_PROXIMO = "Próximo"
BOTAO_CONFIRMAR = "Confirmar e ver resultado"

# Tipo de embalagem é OBRIGATÓRIO e não é um <input> — são cards clicáveis
# (Caixa, Fardo, Rolo, Engradado, Outro), então não apareceu no levantamento
# de campos do recon. Sem escolher um, a etapa da Carga não avança e o site
# responde "O tipo de embalagem é obrigatório".
EMBALAGENS = ("Caixa", "Fardo", "Rolo", "Engradado", "Outro")
EMBALAGEM_PADRAO = "Caixa"

# Frases da tela final, medidas no site.
FRASES_CONFIRMACAO = (
    "recebemos seu pedido de cota",
    "entraremos em contato",
)

# Digitação humana: a busca de CNPJ/CEP do site não dispara com fill().
DELAY_DIGITACAO_MS = 60
ESPERA_BUSCA_MS = 4_500


def ler_resultado(texto: str) -> bool:
    """True se a tela confirma o recebimento da cotação."""
    t = (texto or "").lower()
    return any(f in t for f in FRASES_CONFIRMACAO)


def _inteiro(v: Decimal) -> str:
    """Medida em cm, sem casa decimal — o campo não tem máscara."""
    return str(int(v))


def _duas_casas(v: Decimal) -> str:
    """Peso e dinheiro: 2 casas com vírgula, pela máscara do campo."""
    return f"{v:.2f}".replace(".", ",")


class GenerosoAdapter:
    slug = "generoso"
    nome = "Transporte Generoso"
    modo: Modo = Modo.ASSINCRONO_LENTO      # preço volta por e-mail
    ativo = True
    fator_cubagem: Decimal = Decimal(300)   # ⚠ presumido; não confirmado ainda
    sla_esperado_min: int | None = None

    def __init__(self, headless: bool = True, timeout_ms: int = 45_000,
                 workdir: str = "teste_real/generoso",
                 tipo_pagador: str = TIPO_PAGADOR_DESTINATARIO,
                 embalagem: str = EMBALAGEM_PADRAO) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.workdir = Path(workdir)
        self.tipo_pagador = tipo_pagador
        if embalagem not in EMBALAGENS:
            raise ValueError(
                f"embalagem {embalagem!r} não existe no site. "
                f"Use uma de: {', '.join(EMBALAGENS)}")
        self.embalagem = embalagem

    # ------------------------------------------------------- camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return [
            CampoSpec("E-mail", True, "email"),
            CampoSpec("CNPJ do solicitante", True, "text"),
            CampoSpec("Nome", True, "text"),
            CampoSpec("WhatsApp", True, "tel"),
            CampoSpec("CNPJ do remetente", True, "text"),
            CampoSpec("Valor total da nota fiscal", True, "text"),
            CampoSpec("Altura", True, "text"),
            CampoSpec("Largura", True, "text"),
            CampoSpec("Comprimento", True, "text"),
            CampoSpec("Peso unitário", True, "text"),
            CampoSpec("Quantidade", True, "text"),
        ]

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        erros: list[ErroValidacao] = []
        if not req.solicitante.whatsapp:
            erros.append(ErroValidacao("whatsapp", "O site exige WhatsApp."))
        v = req.volumes[0]
        if v.peso_kg <= 0:
            erros.append(ErroValidacao("peso_kg",
                                       "Peso precisa ser maior que zero."))
        for rotulo, medida in (("comprimento", v.comprimento_cm),
                               ("largura", v.largura_cm),
                               ("altura", v.altura_cm)):
            if medida != medida.to_integral_value():
                erros.append(ErroValidacao(
                    rotulo,
                    f"O campo aceita centímetros inteiros; veio {medida}.",
                    Severidade.AVISO))
        return erros

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        """Ficha -> campos do formulário. Endereços NÃO entram: vêm do CNPJ."""
        v = req.volumes[0]
        return {
            # etapa 1
            "email": req.solicitante.email,
            "cnpj_solicitante": req.pagador_frete.cnpj_formatado,
            "nome": req.solicitante.nome,
            "whatsapp": req.solicitante.whatsapp_formatado,
            # etapa 2
            "tipo_pagador": self.tipo_pagador,
            # etapa 3 — o endereço inteiro sai deste CNPJ
            "cnpj_remetente": req.remetente.cnpj_formatado,
            # etapa 5
            "valor_nf": _duas_casas(req.nota_fiscal.valor_total),
            "altura": _inteiro(v.altura_cm),
            "largura": _inteiro(v.largura_cm),
            "comprimento": _inteiro(v.comprimento_cm),
            "peso": _duas_casas(v.peso_kg),      # unitário; o site soma
            "quantidade": str(v.qtd),
            "embalagem": self.embalagem,
            # O QUE é a carga. O formulário não tem seletor de tipo de
            # mercadoria (o site manda 1 fixo), e sem isto o "LUVA DE
            # BOMBEIRO" da ficha não chegava ao Generoso de jeito nenhum —
            # o vendedor receberia uma cotação sem saber o que transportar.
            "observacao": req.mercadoria.tipo_material,
        }

    # --------------------------------------------------------- mecânica
    @staticmethod
    def _campo(page, seletor: str):
        """Último campo VISÍVEL que casa. As etapas concluídas viram resumo,
        mas os inputs delas continuam no DOM — pegar o primeiro escreveria na
        etapa errada."""
        loc = page.locator(f"{seletor}:visible")
        total = loc.count()
        if not total:
            raise RuntimeError(f"campo não encontrado: {seletor}")
        return loc.nth(total - 1)

    def _digitar(self, page, seletor: str, valor: str) -> None:
        """Digita de verdade, tecla a tecla.

        `fill()` troca o valor de uma vez e não acorda a busca de CNPJ/CEP do
        site — medido no recon: com fill o endereço nunca chega."""
        campo = self._campo(page, seletor)
        campo.fill("")
        page.wait_for_timeout(150)
        campo.type(valor, delay=DELAY_DIGITACAO_MS)
        page.wait_for_timeout(200)

    def _conferir(self, page, esperado: dict[str, str]) -> list[str]:
        """Lê de volta o que foi digitado. Devolve a lista de divergências.

        Campo com máscara devolve outra coisa: foi assim que o peso da Jadlog
        virou 0,01 e a medida da Della Volpe virou 3,0. A comparação ignora
        formatação (ponto, vírgula, R$) mas não o número."""
        so_digitos = lambda s: "".join(c for c in s if c.isdigit())
        problemas = []
        for seletor, valor in esperado.items():
            obtido = self._campo(page, seletor).input_value()
            if so_digitos(obtido) != so_digitos(valor):
                problemas.append(f"{seletor}: digitei {valor!r}, campo tem {obtido!r}")
        return problemas

    @staticmethod
    def _chegou_na_carga(page) -> bool:
        """A etapa da Carga é a única com o campo de valor da nota. Serve de
        prova de que o 'Próximo' anterior funcionou de verdade — clicar sem
        conferir foi o que fez 5 cotações da Della Volpe não saírem."""
        return page.locator(
            'input[name="totalMerchandiseValue"]:visible').count() > 0

    @staticmethod
    def _chegou_no_resumo(page) -> bool:
        """O botão de confirmar só existe na tela de conferência."""
        return page.get_by_role(
            "button", name=BOTAO_CONFIRMAR).count() > 0

    @staticmethod
    def _erros_da_tela(page) -> str:
        """As mensagens em vermelho do próprio site.

        Repetir o que o site diz é melhor que inventar diagnóstico: foi assim
        que apareceu "O tipo de embalagem é obrigatório", um campo que nem é
        <input> e por isso não estava no levantamento do recon."""
        achados = page.evaluate("""() => [...document.querySelectorAll('p, span, div')]
            .filter(e => {
                const c = getComputedStyle(e).color;
                return /obrigat|inv[aá]lid|erro/i.test(e.innerText || '')
                       && e.innerText.length < 120
                       && e.children.length === 0;
            })
            .map(e => e.innerText.trim())""")
        return "; ".join(dict.fromkeys(achados)) or "(nenhuma mensagem visível)"

    def _escolher_embalagem(self, page, run: Path) -> None:
        """Clica no card do tipo de embalagem.

        O rótulo é só texto dentro do card; quem recebe o clique é o
        contêiner. Tenta do texto para fora até algo reagir, e guarda o HTML
        da região se nada funcionar — adivinhar seletor em silêncio foi o que
        custou quatro tentativas no print da Della Volpe."""
        rotulo = page.get_by_text(self.embalagem, exact=True).last
        tentativas = (
            rotulo.locator(
                "xpath=ancestor::*[self::button or self::label"
                " or @role='button'][1]"),
            rotulo.locator("xpath=parent::*"),
            rotulo.locator("xpath=ancestor::div[2]"),
            rotulo,
        )
        for alvo in tentativas:
            try:
                if not alvo.count():
                    continue
                alvo.first.click(timeout=5_000)
                page.wait_for_timeout(700)
                if "obrigat" not in self._erros_da_tela(page).lower():
                    return
            except Exception:
                continue

        (run / "embalagem.html").write_text(
            page.evaluate("""() => {
                const t = [...document.querySelectorAll('*')].find(
                    e => /Tipo de embalagem/i.test(e.textContent || '')
                         && e.children.length < 8);
                return t ? t.outerHTML : document.body.innerHTML.slice(0, 4000);
            }"""), encoding="utf-8")

    def _avancar(self, page) -> None:
        page.get_by_role("button", name=BOTAO_PROXIMO).last.click()
        page.wait_for_timeout(2_500)

    def _esperar_endereco(self, page) -> dict[str, str]:
        """Espera cidade e rua chegarem, e devolve o endereço que o site achou.

        Sem essa espera o "Próximo" é clicado com o endereço em branco e a
        etapa nem avança — ou pior, avança com endereço incompleto."""
        for _ in range(12):
            achado = {
                campo: self._campo(page, f'input[name="{campo}"]').input_value()
                for campo in ("cep", "city", "state", "neighborhood", "address")
            }
            if achado["city"] and achado["address"]:
                return achado
            page.wait_for_timeout(700)
        return achado

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        texto = str(raw or "")
        if not ler_resultado(texto):
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO, raw_response=texto[:800],
                erro="Confirmação de recebimento não apareceu na tela.")
        return ResultadoCotacao(
            transportadora=self.slug,
            status=StatusCotacao.AGUARDANDO_RETORNO,
            valor_frete=None,        # correto: o preço vem por e-mail
            raw_response=texto[:800],
        )

    # ------------------------------------------------------------- envio
    def cotar(self, req: CotacaoRequest, *,
              confirmar_envio: bool = False) -> ResultadoCotacao:
        """confirmar_envio=False faz DRY-RUN: preenche as 5 etapas, printa
        cada uma e PARA antes de "Confirmar e ver resultado".

        Cada envio real vira uma cotação na fila de um vendedor do Generoso,
        igual à Della Volpe — por isso o default é dry-run."""
        from playwright.sync_api import sync_playwright

        erros = [e for e in self.validar(req)
                 if e.severidade is Severidade.ERRO]
        if erros:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO,
                erro="; ".join(f"{e.campo}: {e.mensagem}" for e in erros))

        c = self.preparar_payload(req)
        run = self.workdir / datetime.now().strftime("%Y%m%d-%H%M%S")
        run.mkdir(parents=True, exist_ok=True)
        enviado = datetime.now()
        evidencias: list[str] = []
        avisos: list[str] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_context(
                locale="pt-BR",
                viewport={"width": 1400, "height": 1400}).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                page.goto(URL, wait_until="domcontentloaded")
                page.wait_for_selector('input[name="email"]')
                page.wait_for_timeout(1_500)

                # ------------------------------------------- 1. Solicitante
                for seletor, valor in (
                        ('input[name="email"]', c["email"]),
                        ('input[name="document"]', c["cnpj_solicitante"]),
                        ('input[name="name"]', c["nome"]),
                        ('input[name="whatsapp"]', c["whatsapp"])):
                    self._digitar(page, seletor, valor)
                avisos += self._conferir(page, {
                    'input[name="document"]': c["cnpj_solicitante"],
                    'input[name="whatsapp"]': c["whatsapp"]})
                evidencias += print_seguro(page, run / "etapa1_solicitante.png")
                self._avancar(page)

                # ------------------------------------------ 2. Tipo pagador
                page.locator("select:visible").last.select_option(
                    label=c["tipo_pagador"])
                page.wait_for_timeout(1_200)
                evidencias += print_seguro(page, run / "etapa2_pagador.png")
                self._avancar(page)

                # ----------------------------------------------- 3. Origem
                # O CNPJ preenche o endereço inteiro. NÃO tocar no CEP: medido
                # que digitá-lo troca o endereço da empresa pelo genérico do
                # CEP, em outra cidade.
                seletor_cnpj = 'input[name="document"]:not([disabled])'
                self._digitar(page, seletor_cnpj, c["cnpj_remetente"])
                self._campo(page, seletor_cnpj).blur()
                page.wait_for_timeout(ESPERA_BUSCA_MS)
                origem = self._esperar_endereco(page)
                if not origem["city"]:
                    raise RuntimeError(
                        f"o CNPJ {c['cnpj_remetente']} não trouxe endereço de "
                        f"origem; sem isso a cotação sairia de lugar nenhum")
                evidencias += print_seguro(page, run / "etapa3_origem.png")
                self._avancar(page)

                # ---------------------------------------------- 4. Destino
                # Aqui o CNPJ vem travado e traz só o CEP. Redisparar o CEP é
                # o que preenche cidade, bairro e rua.
                cep_destino = self._campo(page,
                                          'input[name="cep"]').input_value()
                self._digitar(page, 'input[name="cep"]', cep_destino)
                self._campo(page, 'input[name="cep"]').blur()
                page.wait_for_timeout(ESPERA_BUSCA_MS)
                destino = self._esperar_endereco(page)
                if not destino["city"]:
                    raise RuntimeError(
                        f"o CEP {cep_destino} não trouxe cidade de destino")

                evidencias += print_seguro(page, run / "etapa4_destino.png")
                self._avancar(page)

                # "Número" costuma ficar vazio (o CEP não traz numeração) e
                # ainda assim a etapa avança — foi o que o Enzo fez à mão.
                # Só se NÃO avançar é que marcamos "Sem número", clicando no
                # RÓTULO: o input real é escondido por CSS e não reage nem a
                # check(force=True).
                if not self._chegou_na_carga(page):
                    page.get_by_text("Sem número", exact=False).last.click()
                    page.wait_for_timeout(800)
                    evidencias += print_seguro(
                        page, run / "etapa4_sem_numero.png")
                    self._avancar(page)

                # ------------------------------------------------ 5. Carga
                for seletor, valor in (
                        ('input[name="totalMerchandiseValue"]', c["valor_nf"]),
                        ('input[name="cubageValues.0.height"]', c["altura"]),
                        ('input[name="cubageValues.0.width"]', c["largura"]),
                        ('input[name="cubageValues.0.length"]',
                         c["comprimento"]),
                        ('input[name="cubageValues.0.weight"]', c["peso"]),
                        ('input[name="cubageValues.0.quantity"]',
                         c["quantidade"])):
                    self._digitar(page, seletor, valor)
                page.wait_for_timeout(1_200)

                # conferência que importa: peso e medidas passam por máscara
                avisos += self._conferir(page, {
                    'input[name="cubageValues.0.weight"]': c["peso"],
                    'input[name="cubageValues.0.height"]': c["altura"],
                    'input[name="cubageValues.0.width"]': c["largura"],
                    'input[name="cubageValues.0.length"]': c["comprimento"],
                    'input[name="totalMerchandiseValue"]': c["valor_nf"]})
                self._escolher_embalagem(page, run)
                self._digitar(page, 'input[name="observation"]',
                              c["observacao"])

                evidencias += print_seguro(page, run / "etapa5_carga.png")
                self._avancar(page)

                # -------------------------------------------- 6. Conferência
                # Conferir que a etapa REALMENTE passou. Sem isto o dry-run
                # dava "rascunho" com a Carga ainda na tela reclamando de
                # campo obrigatório — e o print chamado "resumo" não era
                # resumo nenhum.
                if not self._chegou_no_resumo(page):
                    raise RuntimeError(
                        "a etapa da Carga não avançou. O site diz: "
                        + self._erros_da_tela(page))

                evidencias += print_seguro(page, run / "resumo.png")

                if not confirmar_envio:
                    return ResultadoCotacao(
                        self.slug, StatusCotacao.RASCUNHO, enviado_em=enviado,
                        raw_response="DRY-RUN: 5 etapas preenchidas, "
                                     "nada enviado.",
                        erro="; ".join(avisos) if avisos else None,
                        evidencias=evidencias)

                page.get_by_role("button", name=BOTAO_CONFIRMAR).last.click()
                page.wait_for_timeout(6_000)
                evidencias += print_seguro(page, run / "resultado.png")

                res = self.normalizar_resposta(
                    page.locator("body").inner_text())
                res.enviado_em = enviado
                res.respondido_em = datetime.now()
                res.evidencias = evidencias
                return res

            except Exception as exc:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.ERRO, enviado_em=enviado,
                    erro=f"{type(exc).__name__}: {exc}",
                    evidencias=evidencias
                    + print_seguro(page, run / "erro.png"))
            finally:
                browser.close()
