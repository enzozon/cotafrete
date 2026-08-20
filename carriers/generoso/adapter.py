"""Transporte Generoso — formulário de cotação em ETAPAS.

    https://cliente.generoso.com.br/cotacao

⚠ A URL divulgada (generoso.com.br/cotacao) é 404; a página de erro é que
aponta para a área do cliente.

COTA LOGADO. Refeito em 20/08/2026, e o de antes não existe mais.

Deslogado o formulário tem cinco etapas e a tela final só diz "Recebemos seu
pedido de cotação" — o preço viria por e-mail, horas depois. Logado, a etapa
do solicitante some (é a conta) e o preço aparece na própria tela.

QUATRO ETAPAS, logado:
    1. Tipo pagador  select: Remetente (CIF) / Destinatario (FOB) / Terceiro
    2. Origem        JÁ VEM PRONTA E TRAVADA no CNPJ da conta
    3. Destino       CNPJ em branco; digitá-lo traz o endereço inteiro
    4. Carga         valor da NF, medidas, peso, quantidade, embalagem

REGRAS MEDIDAS NO SITE — sem elas a cotação sai errada e sem aviso na tela:

1. O tipo de pagador decide QUEM é a Ventura. Logado, o solicitante é a
   conta: com CIF ela é a remetente (frete saindo), com FOB é a
   destinatária (frete vindo). Escolher FOB para um frete de saída trava o
   destino no CNPJ da própria conta, e o site recusa com "CEP de coleta não
   pode ser o mesmo de destino" — mensagem que NÃO aparece na tela, só no
   aria-invalid do campo. O Cotafrete cota frete saindo daqui: CIF.

2. Não digitar CEP em lugar nenhum. Cada ponta é preenchida pelo CNPJ, e
   redigitar o CEP por cima estraga o endereço: no destino, redigitar
   "09.220-570" fez a máscara comer o zero à esquerda e o resumo saiu com
   "92.205-70". CEP errado é cotação para o lugar errado, calada.

3. Na ORIGEM não há nada a preencher: CNPJ, cidade e estado vêm travados.
   Se o remetente da ficha não for o CNPJ da conta, a cotação sairia de
   outra praça sem ninguém perceber — por isso aqui ela é recusada.

4. O campo de peso tem máscara de 2 casas, da direita para a esquerda:
   "1" vira 0.01 e "100" vira 1.00. Sempre 2 casas.

E a busca do site só acorda com digitação: `fill()` instantâneo não dispara.
"""

from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from datetime import datetime

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao, Severidade, print_seguro,
)
from core.models import CotacaoRequest, StatusCotacao, limpa_doc

URL = "https://cliente.generoso.com.br/cotacao"
URL_LOGIN = "https://cliente.generoso.com.br/login"
ESPERA_LOGIN_MS = 30_000

# O CNPJ que da para digitar. Na origem o site trava o da conta
# (input desabilitado); no destino ele vem vazio e editavel.
SELETOR_CNPJ_LIVRE = 'input[name="document"]:not([disabled])'

# As três opções do select, escritas como o site escreve.
#
# LOGADO, quem é o solicitante é a conta — a Ventura. Então:
#   CIF       a Ventura é a REMETENTE  -> frete saindo daqui (o caso do Cotafrete)
#   FOB       a Ventura é a DESTINATÁRIA -> frete vindo para cá
#   Terceiro  paga um CNPJ que não é nenhuma das duas pontas
#
# Escolher FOB para um frete de saída faz o site travar o destino no CNPJ da
# conta e recusar com "CEP de coleta não pode ser o mesmo de destino" — sem
# nenhuma mensagem visível na tela. Medido em 20/08/2026.
TIPO_PAGADOR_DESTINATARIO = "Destinatario (FOB)"
TIPO_PAGADOR_REMETENTE = "Remetente (CIF)"
TIPO_PAGADOR_TERCEIRO = "Terceiro"

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


# A tela de resultado, LOGADO. Medida no envio real de 20/08/2026:
#
#     Cotação: 2651152
#     Frete                 R$ 421,94
#     Previsão de entrega   25/08/26
#     Cotado em             20/08/26
#     Cotação válida até    30/08/26
#
# Rótulo numa linha, valor na seguinte — daí o \s* entre eles. O R$ vem com
# espaço NÃO separável, por isso o texto é normalizado antes de casar.
RE_PROTOCOLO = re.compile(r"cota[çc][ãa]o:\s*(\d+)", re.IGNORECASE)
RE_FRETE = re.compile(r"\bfrete\s*R\$\s*([\d.]*\d,\d{2})", re.IGNORECASE)
RE_PREVISAO = re.compile(r"previs[ãa]o de entrega\D*?(\d{2}/\d{2}/\d{2})",
                         re.IGNORECASE)
RE_COTADO_EM = re.compile(r"cotado em\D*?(\d{2}/\d{2}/\d{2})", re.IGNORECASE)


def _dinheiro(bruto: str) -> Decimal | None:
    """'1.421,94' -> Decimal('1421.94').

    Ponto é milhar e vírgula é decimal. Lido do jeito errado, 1.421,94 vira
    1,42 — cem vezes menos, e o número vai calado para a mesa do cliente."""
    try:
        return Decimal(bruto.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def _dias_entre(cotado: str, previsto: str) -> int | None:
    """A tela dá datas (dd/mm/aa); o resto do sistema compara prazo em dias."""
    try:
        inicio = datetime.strptime(cotado, "%d/%m/%y")
        fim = datetime.strptime(previsto, "%d/%m/%y")
    except ValueError:
        return None
    dias = (fim - inicio).days
    return dias if dias >= 0 else None


def ler_resultado(texto: str) -> bool:
    """True se a tela confirma o recebimento da cotação."""
    t = (texto or "").lower()
    return any(f in t for f in FRASES_CONFIRMACAO)


def recusa_remetente_diferente(cnpj_ficha: str, cnpj_conta: str) -> str:
    """Frase para o vendedor quando a ficha pede uma origem que o site não
    aceita. Dizer só "recusado" faria ele repetir a cotação igual."""
    return (
        f"A Generoso cota logada na conta da Ventura, e essa conta é o CNPJ "
        f"{cnpj_conta}. O site trava a origem nele e não deixa trocar. Esta "
        f"cotação pede remetente {cnpj_ficha}, então o frete sairia de outro "
        f"endereço sem ninguém perceber. Refaça com {cnpj_conta} como "
        f"remetente, ou fale com a Generoso pelo WhatsApp.")


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
                 tipo_pagador: str = TIPO_PAGADOR_REMETENTE,
                 embalagem: str = EMBALAGEM_PADRAO,
                 usuario: str | None = None,
                 senha: str | None = None) -> None:
        # Do .env por padrão, como as outras. Passar por parâmetro existe
        # para o teste, não para o dia a dia.
        self.usuario = usuario if usuario is not None else os.getenv(
            "GENEROSO_USUARIO")
        self.senha = senha if senha is not None else os.getenv(
            "GENEROSO_SENHA")
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
            # etapa 4 — e o do destino sai deste. Logado, o campo vem VAZIO:
            # o site não deduz mais o destinatário do tipo de pagador.
            "cnpj_destinatario": req.destinatario.cnpj_formatado,
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

    def _entrar(self, page) -> None:
        """Login. Sem ele o site não mostra preço, só confirma o recebimento.

        Espera a URL virar /dashboard em vez de um sleep fixo: credencial
        errada deixa a página parada em /login, e seguir dali preencheria o
        formulário público inteiro para no fim descobrir que não estava
        logado — 45s jogados fora e um resultado sem preço, que ninguém
        saberia explicar."""
        page.goto(URL_LOGIN, wait_until="domcontentloaded")
        page.wait_for_selector('input[name="email"]')
        page.wait_for_timeout(1_200)
        page.fill('input[name="email"]', self.usuario)
        page.fill('input[name="password"]', self.senha)
        page.get_by_role("button", name="Entrar").click()
        try:
            page.wait_for_url("**/dashboard", timeout=ESPERA_LOGIN_MS)
        except Exception:
            raise RuntimeError(
                "o login na Generoso não passou (a tela não saiu de /login). "
                "Confira GENEROSO_USUARIO e GENEROSO_SENHA no .env")

    @staticmethod
    def _cnpj_travado_da_origem(page) -> str:
        """O CNPJ que o site fixou na origem. Logado, ele é o da conta e não
        dá para trocar — então é ele que decide de onde o frete sai."""
        campo = page.locator('input[name="document"]:visible')
        return campo.last.input_value() if campo.count() else ""

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
        """Três telas possíveis, nesta ordem de preferência.

        1. LOGADO deu certo: tem preço, protocolo e as duas datas.
        2. A sessão caiu no meio: o site volta ao formulário público, que só
           confirma o recebimento. Não é preço, mas também não é falha — a
           cotação foi enviada e a resposta vem por e-mail.
        3. Qualquer outra coisa é erro, e o texto vai junto para dar o que
           investigar."""
        #   e o espaco NAO separavel que o site usa depois do R$.
        # Escrito como escape de proposito: o caractere de verdade e
        # invisivel no editor, e regex que nao casa por causa de um
        # espaco que ninguem ve e das piores coisas de depurar.
        texto = str(raw or "").replace(" ", " ")

        frete = RE_FRETE.search(texto)
        if frete:
            protocolo = RE_PROTOCOLO.search(texto)
            previsao = RE_PREVISAO.search(texto)
            cotado = RE_COTADO_EM.search(texto)
            return ResultadoCotacao(
                transportadora=self.slug,
                status=StatusCotacao.COTADO,
                protocolo=protocolo.group(1) if protocolo else None,
                valor_frete=_dinheiro(frete.group(1)),
                prazo_dias=(_dias_entre(cotado.group(1), previsao.group(1))
                            if cotado and previsao else None),
                raw_response=texto[:800],
            )

        if ler_resultado(texto):
            return ResultadoCotacao(
                transportadora=self.slug,
                status=StatusCotacao.AGUARDANDO_RETORNO,
                valor_frete=None,    # correto: sem login o preço vem por e-mail
                raw_response=texto[:800],
            )

        return ResultadoCotacao(
            self.slug, StatusCotacao.ERRO, raw_response=texto[:800],
            erro="A tela de resultado não trouxe preço nem confirmação de "
                 "recebimento.")

    # ------------------------------------------------------------- envio
    def cotar(self, req: CotacaoRequest, *,
              confirmar_envio: bool = False) -> ResultadoCotacao:
        """confirmar_envio=False faz DRY-RUN: loga, preenche as 4 etapas,
        printa cada uma e PARA antes de "Confirmar e ver resultado".

        Cada envio real vira uma cotação na conta da Ventura no portal deles.
        O default continua sendo dry-run: um clique a mais aqui tem custo do
        lado de fora."""
        erros = [e for e in self.validar(req)
                 if e.severidade is Severidade.ERRO]
        if erros:
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO,
                erro="; ".join(f"{e.campo}: {e.mensagem}" for e in erros))

        # Antes de qualquer navegador: sem login a Generoso não devolve preço,
        # e descobrir isso depois custaria 45s de uma vaga de navegador que as
        # outras transportadoras estão esperando.
        if not (self.usuario and self.senha):
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO,
                erro="Faltam GENEROSO_USUARIO e GENEROSO_SENHA no .env. "
                     "Sem login, a Generoso não mostra o preço na tela.")

        from playwright.sync_api import sync_playwright

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
                self._entrar(page)
                page.goto(URL, wait_until="domcontentloaded")
                page.wait_for_selector("select")
                page.wait_for_timeout(3_000)

                # -------------------------------------------- 1. Tipo pagador
                page.locator("select:visible").last.select_option(
                    label=c["tipo_pagador"])
                page.wait_for_timeout(1_500)
                evidencias += print_seguro(page, run / "etapa1_pagador.png")
                self._avancar(page)

                # ------------------------------------------------- 2. Origem
                # Nada a preencher: o site já travou tudo no CNPJ da conta. O
                # que há a fazer é CONFERIR que é o remetente certo — se não
                # for, o frete sairia de outra praça e ninguém veria.
                conta = self._cnpj_travado_da_origem(page)
                if conta and limpa_doc(conta) != limpa_doc(c["cnpj_remetente"]):
                    return ResultadoCotacao(
                        self.slug, StatusCotacao.RECUSADO,
                        motivo_recusa=recusa_remetente_diferente(
                            c["cnpj_remetente"], conta),
                        enviado_em=enviado, evidencias=evidencias)

                origem = self._esperar_endereco(page)
                if not origem["city"]:
                    raise RuntimeError(
                        "a conta não trouxe o endereço de origem; sem isso a "
                        "cotação sairia de lugar nenhum")
                evidencias += print_seguro(page, run / "etapa2_origem.png")
                self._avancar(page)

                # ------------------------------------------------ 3. Destino
                # Logado, este campo vem VAZIO e é dele que sai o endereço
                # inteiro. Não tocar no CEP: redigitá-lo comeu o zero à
                # esquerda de 09.220-570 e o resumo saiu "92.205-70".
                self._digitar(page, SELETOR_CNPJ_LIVRE, c["cnpj_destinatario"])
                self._campo(page, SELETOR_CNPJ_LIVRE).blur()
                page.wait_for_timeout(ESPERA_BUSCA_MS)
                destino = self._esperar_endereco(page)
                if not destino["city"]:
                    raise RuntimeError(
                        f"o CNPJ {c['cnpj_destinatario']} não trouxe endereço "
                        f"de destino")
                evidencias += print_seguro(page, run / "etapa3_destino.png")
                self._avancar(page)

                if not self._chegou_na_carga(page):
                    raise RuntimeError(
                        "a etapa do destino não avançou. O site diz: "
                        + self._erros_da_tela(page))

                # -------------------------------------------------- 4. Carga
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

                # A conferência que importa: peso e dinheiro passam por máscara
                avisos += self._conferir(page, {
                    'input[name="cubageValues.0.weight"]': c["peso"],
                    'input[name="cubageValues.0.height"]': c["altura"],
                    'input[name="cubageValues.0.width"]': c["largura"],
                    'input[name="cubageValues.0.length"]': c["comprimento"],
                    'input[name="totalMerchandiseValue"]': c["valor_nf"]})
                self._escolher_embalagem(page, run)
                self._digitar(page, 'input[name="observation"]',
                              c["observacao"])
                evidencias += print_seguro(page, run / "etapa4_carga.png")
                self._avancar(page)

                # --------------------------------------------- 5. Conferência
                if not self._chegou_no_resumo(page):
                    raise RuntimeError(
                        "a etapa da Carga não avançou. O site diz: "
                        + self._erros_da_tela(page))
                evidencias += print_seguro(page, run / "resumo.png")

                if not confirmar_envio:
                    return ResultadoCotacao(
                        self.slug, StatusCotacao.RASCUNHO, enviado_em=enviado,
                        raw_response="DRY-RUN: 4 etapas preenchidas, "
                                     "nada enviado.",
                        erro="; ".join(avisos) if avisos else None,
                        evidencias=evidencias)

                page.get_by_role("button", name=BOTAO_CONFIRMAR).last.click()
                page.wait_for_timeout(8_000)
                evidencias += print_seguro(page, run / "resultado.png")

                res = self.normalizar_resposta(
                    page.locator("body").inner_text())
                res.enviado_em = enviado
                res.respondido_em = datetime.now()
                res.evidencias = evidencias
                if avisos and not res.erro:
                    res.erro = "; ".join(avisos)
                return res

            except Exception as exc:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.ERRO, enviado_em=enviado,
                    erro=f"{type(exc).__name__}: {exc}",
                    evidencias=evidencias
                    + print_seguro(page, run / "erro.png"))
            finally:
                browser.close()
