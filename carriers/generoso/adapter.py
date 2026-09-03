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

3. A ponta que o grupo ocupa vem TRAVADA — no CIF é a origem, no FOB é o
   destino — e o CEP dela não se digita. O que DÁ para trocar é a empresa:
   o cartão do Solicitante tem um "Alterar empresa" com as três do grupo.
   Até 25/08/2026 o robô não mexia nele e toda cotação saía com a da conta;
   hoje ele escolhe pelo CNPJ do formulário (ver `mapping.empresa_alvo`).

   Daí sai também a recusa por CIF/FOB trocado: marcar CIF com uma empresa
   do grupo no DESTINO faz as duas pontas virarem a mesma casa. Ver
   `mapping.conflito_cif_fob`.

4. O campo de peso tem máscara de 2 casas, da direita para a esquerda:
   "1" vira 0.01 e "100" vira 1.00. Sempre 2 casas.

E a busca do site só acorda com digitação: `fill()` instantâneo não dispara.
"""

from __future__ import annotations

import os
import re
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from datetime import datetime

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao, Severidade, print_seguro,
    CredencialRecusada, argumentos_de_navegador_real, erro_do_adapter,
    recusa_por_validacao,
)
from carriers.generoso.mapping import (
    AVISO_CEP_NAO_ATENDIDO, AVISO_MESMO_CEP, cliente_nao_cadastrado,
    conflito_cif_fob, empresa_alvo, empresa_de, recusa_cep_nao_atendido,
    recusa_cliente_nao_cadastrado, recusa_mesmo_cep,
)
from core.models import CotacaoRequest, StatusCotacao, TipoFrete, limpa_doc

URL = "https://cliente.generoso.com.br/cotacao"
URL_LOGIN = "https://cliente.generoso.com.br/login"

# O CNPJ com que a conta ABRE. Continua sendo a ponta travada quando o
# formulario nao traz nenhuma das tres empresas do grupo; quando traz, o
# `_escolher_empresa` troca antes da etapa 1.
CNPJ_CONTA = "08.310.365/0001-24"
ESPERA_LOGIN_MS = 30_000

# A empresa "ativa" (Alterar empresa) é estado da CONTA na Generoso, não da
# aba do navegador — o próprio site conta com isso: "a conta abre na empresa
# que cotou por último" (ver _escolher_empresa). Duas cotações concorrentes
# logadas com o mesmo usuário se pisam: a #130 pediu Alianca
# (05.954.058/0001-98), rodou junto com a #131 às 16:27-16:28 de 03/09/2026,
# e saiu com o CNPJ da Ventura (o padrão da conta) — sem erro nenhum no
# caminho. Repetida sozinha minutos depois (#132), saiu certa. Por isso o
# `cotar` inteiro (login até fechar o navegador) roda sob esta trava: só uma
# sessão da Generoso mexe na empresa da conta por vez.
_TRAVA_CONTA = threading.Lock()

# O CNPJ que da para digitar. Na origem o site trava o da conta
# (input desabilitado); no destino ele vem vazio e editavel.
SELETOR_CNPJ_LIVRE = 'input[name="document"]:not([disabled])'

# O menu "Alterar empresa", medido em 25/08/2026 por
# recon/recon_generoso_empresa.py. E um dropdown do Radix: o menu nao existe
# no DOM ate o clique, e o `id` do gatilho e gerado por render
# (radix-_R_6j9qnpfiv9fl97b_), entao nao serve de seletor.
#
# O menu tem QUATRO itens; o quarto e "Adicionar empresa". Por isso a escolha
# e sempre pelo CNPJ dentro do texto do item — nunca por posicao.
SELETOR_TROCAR_EMPRESA = 'button[data-slot="dropdown-menu-trigger"]'
SELETOR_ITEM_EMPRESA = '[data-slot="dropdown-menu-item"]'

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

# A QUARTA tela, medida em 24/08/2026. Ela derrubou as cotacoes #6 a #9 de
# producao, todas com o generico "a tela nao trouxe preco nem confirmacao".
#
# Nao e erro nem recusa de carga: a Generoso ATENDE aquela origem, so que
# atraves de uma unidade parceira que cota por fora do portal. Tem
# transporte — o vendedor so precisa falar com outra pessoa.
#
# Duas ancoras, e as duas precisam bater: "aguardando validacao" sozinho
# pode aparecer noutra situacao, e "unidades parceiras" pode aparecer num
# texto de ajuda qualquer.
FRASES_UNIDADE_PARCEIRA = (
    "aguardando valida",
    "unidades parceiras",
)
LINK_UNIDADES = "rodonaves.com.br/cidades-atendidas"

# Frases da tela final, medidas no site.
FRASES_CONFIRMACAO = (
    "recebemos seu pedido de cota",
    "entraremos em contato",
)

# A carga passou dos limites do site (peso, cubagem ou peso por volume).
# Medida em duas cotações reais de 03/09/2026 (#120 e #122, mesma origem e
# tipo de carga): "A carga ultrapassou os limites permitidos para o site."
# seguida dos três limites. Até aqui essa tela caía no ERRO genérico do
# fallback — não é falha nossa, é a Generoso dizendo que não atende aquele
# volume, o mesmo tipo de recusa que peso/cubagem já são para a Jadlog.
FRASE_LIMITE_EXCEDIDO = "ultrapassou os limites"

RE_LIMITE_PESO = re.compile(r"peso m[aá]ximo:\s*([\d.,]+)", re.IGNORECASE)
RE_LIMITE_CUBAGEM = re.compile(r"cubagem m[aá]xima:\s*([\d.,]+)", re.IGNORECASE)
RE_LIMITE_POR_VOLUME = re.compile(
    r"peso m[aá]ximo por volume:\s*([\d.,]+)", re.IGNORECASE)

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


def e_unidade_parceira(texto: str) -> bool:
    """A origem sai por uma unidade parceira, que cota fora do portal.

    Exige as DUAS frases: uma só delas é frágil demais para decidir que uma
    cotação foi recusada."""
    t = (texto or "").lower()
    return all(f in t for f in FRASES_UNIDADE_PARCEIRA)


def carga_excede_limites(texto: str) -> bool:
    """True quando a Generoso recusou por a carga passar do peso, da
    cubagem ou do peso por volume que o site aceita."""
    return FRASE_LIMITE_EXCEDIDO in (texto or "").lower()


def motivo_limite_excedido(texto: str) -> str:
    """Mensagem para o vendedor, com os limites que a própria tela deu —
    quando algum não aparece (site pode mudar a lista), a frase genérica
    ainda deixa claro que é recusa e não falha nossa."""
    limites = []
    peso = RE_LIMITE_PESO.search(texto)
    cubagem = RE_LIMITE_CUBAGEM.search(texto)
    por_volume = RE_LIMITE_POR_VOLUME.search(texto)
    if peso:
        limites.append(f"peso total até {peso.group(1)} kg")
    if cubagem:
        limites.append(f"cubagem até {cubagem.group(1)} m³")
    if por_volume:
        limites.append(f"até {por_volume.group(1)} kg por volume")
    detalhe = f" ({'; '.join(limites)})" if limites else ""
    return (f"A Generoso não atende esta carga: ela ultrapassa os limites "
            f"do site{detalhe}. Fale com a Generoso pelo WhatsApp, no botão "
            f"aqui embaixo, ou reduza a carga.")


def _e_busca_de_cnpj(resposta) -> bool:
    """A resposta da busca de CNPJ, entre as ~190 que o portal dispara.

    É uma server action do Next.js: POST para a própria /cotacao, com o
    resultado no corpo em formato RSC. Medida em 28/08/2026 por
    recon/recon_generoso_cnpj.py. O `endswith` evita casar com os prefetch
    `/cotacao?_rsc=…` e com `/cotacao/listar`."""
    return (resposta.request.method == "POST"
            and resposta.url.split("?")[0].rstrip("/").endswith("/cotacao"))


class ClienteNaoCadastrado(Exception):
    """A Generoso não tem esse CNPJ como cliente.

    Resposta da transportadora, não falha nossa: vira RECUSADO, e portanto
    NÃO é repetida. Como `ForaDeArea` e `SemTabela` na Translovato."""


class ForaDeArea(Exception):
    """Praça fora da malha da Generoso. Resposta da transportadora, não
    falha nossa: vira RECUSADO. Mesmo nome que a exceção equivalente na
    Translovato, pelo mesmo motivo."""


def pontas_a_digitar(req: CotacaoRequest) -> tuple[str | None, str | None]:
    """(origem, destino). None = essa ponta é a conta e já vem travada.

    FUNÇÃO PURA, e é aqui que mora o erro caro: digitar na ponta travada não
    adianta, e deixar a livre em branco faz a cotação não ter de onde nem
    para onde ir. Medido nos dois modos em 20/08/2026."""
    if req.tipo_frete is TipoFrete.CIF:
        return None, req.destinatario.cnpj_formatado
    return req.remetente.cnpj_formatado, None


def _falhar_login(page) -> None:
    """Olha a tela parada, diz o que de fato aconteceu e levanta.

    O TIPO da exceção decide se a cotação vai ser repetida: senha recusada é
    `CredencialRecusada` e não repete (três logins por cotação, com a equipe
    cotando o dia inteiro, travam a conta); formulário que não foi enviado é
    erro comum e ganha outra chance.

    A mensagem antiga mandava conferir GENEROSO_USUARIO e GENEROSO_SENHA no
    .env em qualquer caso. Na cotação #46 (24/08/2026) isso mandou procurar
    no lugar errado: as credenciais estavam certas — tinham funcionado duas
    vezes minutos antes — e o print mostrava o e-mail preenchido com o campo
    de SENHA vazio. O formulário é que não tinha ido.

    A senha nunca aparece na mensagem; o que se lê dela é só se está vazia.
    """
    try:
        preenchida = bool(
            page.locator('input[name="password"]').first.input_value().strip())
    except Exception:
        # Página navegou ou morreu no meio: sem diagnóstico, mas sem esconder
        # o problema original atrás de uma exceção nova.
        raise RuntimeError("o login na Generoso não passou e não deu para "
                           "ver a tela para dizer por quê.")

    if preenchida:
        raise CredencialRecusada(
            "a Generoso não aceitou o login. Os dados foram enviados e o site "
            "não deixou entrar: pode ser senha trocada, conta bloqueada ou "
            "outra sessão aberta no mesmo usuário. Confira GENEROSO_USUARIO e "
            f"GENEROSO_SENHA no .env, ou entre à mão em {URL_LOGIN} para ver "
            "a mensagem do site. Não vou tentar de novo para não travar a "
            "conta.")
    raise RuntimeError(
        "o login na Generoso não passou: a tela ficou em /login com o campo "
        "de senha vazio, ou seja, o formulário nem chegou a ser enviado. "
        "Costuma passar sozinho na tentativa seguinte.")


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

    def opcoes_do_navegador(self) -> dict:
        """Como o Chromium sobe. Janela de verdade, e sem marca de automação.

        Não é preferência: desde 28/08/2026 o portal está atrás do checkpoint
        de segurança da Vercel, que reprova navegador automatizado ANTES de
        entregar qualquer página — a cotação #57 morreu esperando o campo de
        e-mail que estava atrás de "Falha ao verificar seu navegador, Código
        21". `self.headless` fica ignorado de propósito: headless não passa, e
        cotação que não passa não é opção de configuração.

        Método, e não argumentos soltos no `launch`, para o teste poder subir
        o navegador EXATAMENTE como a produção sobe e perguntar a ele quem ele
        diz que é. Conferir a lista de argumentos não serviria: foi um
        argumento certo com efeito nenhum que deixou este bug passar."""
        return {"headless": False, "args": argumentos_de_navegador_real()}

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

    def _escolher_empresa(self, page, empresa) -> None:
        """Deixa `empresa` selecionada no "Alterar empresa". None = não mexe.

        Casa pelo CNPJ dentro do texto do item, nunca pela posição: o quarto
        item do menu é "Adicionar empresa", que abre cadastro de empresa nova
        no portal do cliente.

        Não encontrar o CNPJ é motivo para PARAR. Seguir em silêncio cotaria
        com a empresa errada, e cotação sai com CNPJ no papel — é o tipo de
        erro que ninguém percebe olhando o preço."""
        if empresa is None:
            return

        procurado = limpa_doc(empresa.cnpj)
        page.locator(SELETOR_TROCAR_EMPRESA).first.click()
        page.wait_for_timeout(800)

        itens = page.locator(SELETOR_ITEM_EMPRESA)
        textos = itens.all_inner_texts()
        for i, texto in enumerate(textos):
            if procurado not in limpa_doc(texto):
                continue
            # A empresa JA selecionada vem desabilitada — nao da para clicar
            # no que ja esta ativo. Isso e sucesso, nao falha: e o caso mais
            # comum, porque a conta abre na empresa que cotou por ultimo.
            if not itens.nth(i).is_enabled():
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
                return
            itens.nth(i).click()
            page.wait_for_timeout(1_200)
            return

        page.keyboard.press("Escape")       # não deixa o menu aberto por cima
        raise RuntimeError(
            f"a empresa {empresa.cnpj} não está no menu 'Alterar empresa' da "
            f"Generoso. O menu oferece: "
            + "; ".join(t.replace("\n", " ") for t in textos))

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        erros: list[ErroValidacao] = []
        # Vem primeiro porque é o único que torna a cotação inteira sem
        # sentido: os outros erros são campo a campo, este é a DIREÇÃO da
        # carga. Sem ele o site gastava 40s para travar num `aria-invalid`
        # que ninguém lê — e a retentativa fazia isso três vezes.
        conflito = conflito_cif_fob(req)
        if conflito:
            erros.append(ErroValidacao("CIF/FOB", conflito))
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
            "tipo_pagador": (TIPO_PAGADOR_REMETENTE
                             if req.tipo_frete is TipoFrete.CIF
                             else TIPO_PAGADOR_DESTINATARIO),
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
            _falhar_login(page)

    def _reativar_cep(self, page) -> None:
        """Acorda a busca de endereço SEM apagar o CEP.

        Apaga o último dígito e redigita só ele. Redigitar o CEP inteiro
        resolveria igual — e foi exatamente o que comeu o zero à esquerda de
        09.220-570, que chegou no resumo como "92.205-70". Um dígito dispara
        o mesmo evento e não encosta no resto do número."""
        campo = self._campo(page, 'input[name="cep"]')
        valor = campo.input_value()
        if not valor:
            return
        campo.click()
        campo.press("End")
        campo.press("Backspace")
        page.wait_for_timeout(200)
        campo.type(valor[-1], delay=DELAY_DIGITACAO_MS)
        campo.blur()
        page.wait_for_timeout(ESPERA_BUSCA_MS)

    def _preencher_ponta(self, page, cnpj: str | None) -> tuple[dict, str]:
        """Preenche uma ponta. Devolve (endereço achado, resposta da busca).

        cnpj=None quer dizer "esta ponta é a conta": vem travada. Nunca
        digitar o CEP — cada ponta é preenchida pelo CNPJ.

        A resposta da busca vem junto porque é ONDE a Generoso diz que não
        conhece o CNPJ. Na tela ela não diz nada — a cotação #56 registrou
        "(nenhuma mensagem visível)" e foi repetida três vezes por causa
        disso.

        O ouvinte é ESTREITO e some no fim. Ler o corpo de tudo que passa não
        serve: o portal dispara ~190 respostas por cotação, fonte binária
        estoura UnicodeDecodeError e o custo chega atrasado na hora de
        decidir. E `expect_response` sozinho também não: ele entrega a
        PRIMEIRA que casa, e o `fill("")` do `_digitar` já dispara uma server
        action antes da busca — a resposta que interessa é a segunda."""
        if cnpj is not None:
            corpos: list[str] = []

            def guardar(resposta) -> None:
                if not _e_busca_de_cnpj(resposta):
                    return
                try:
                    corpos.append(resposta.text())
                except Exception:
                    # Corpo já consumido ou ilegível. Some em silêncio: quem
                    # manda na decisão continua sendo o endereço.
                    pass

            page.on("response", guardar)
            try:
                self._digitar(page, SELETOR_CNPJ_LIVRE, cnpj)
                self._campo(page, SELETOR_CNPJ_LIVRE).blur()
                page.wait_for_timeout(ESPERA_BUSCA_MS)
                achado = self._esperar_endereco(page)
            finally:
                page.remove_listener("response", guardar)
            return achado, "\n".join(corpos)

        # Ponta travada. No CIF (origem) ela vem completa. No FOB (destino) o
        # CNPJ traz SÓ o CEP: cidade e rua ficam vazias e o "Próximo" não
        # avança — sem mensagem nenhuma na tela. Medido em 20/08/2026.
        achado = self._esperar_endereco(page, tentativas=3)
        if not achado["city"]:
            self._reativar_cep(page)
            achado = self._esperar_endereco(page)
        # Ponta travada não tem busca: ninguém digitou CNPJ nenhum aqui.
        return achado, ""

    @staticmethod
    def _conferir_cobertura(page, lado: str, req: CotacaoRequest) -> None:
        """Levanta ForaDeArea se a Generoso recusou esta ponta — praça fora
        da malha, ou origem/destino colidindo no mesmo CEP.

        O CEP É resolvido (cidade/rua vêm preenchidas) mas um aviso vermelho
        pode aparecer embaixo do campo — `_erros_da_tela` não pega nenhuma
        das duas frases (ver AVISO_CEP_NAO_ATENDIDO e AVISO_MESMO_CEP).
        Checar AQUI, antes do Próximo: depois ele só trava calado, e vira o
        genérico "etapa não avançou" (6 cotações reais entre 24/08 e
        31/08/2026 — 4 do primeiro aviso, 2 do segundo)."""
        texto_tela = page.locator("body").inner_text().lower()
        if AVISO_CEP_NAO_ATENDIDO in texto_tela:
            cep = (req.origem if lado == "origem" else req.destino).cep or ""
            raise ForaDeArea(recusa_cep_nao_atendido(cep, lado))
        if AVISO_MESMO_CEP in texto_tela:
            raise ForaDeArea(recusa_mesmo_cep())

    def _avancar(self, page) -> None:
        page.get_by_role("button", name=BOTAO_PROXIMO).last.click()
        page.wait_for_timeout(2_500)

    def _esperar_endereco(self, page, tentativas: int = 12) -> dict[str, str]:
        """Espera cidade e rua chegarem, e devolve o endereço que o site achou.

        Sem essa espera o "Próximo" é clicado com o endereço em branco e a
        etapa nem avança — ou pior, avança com endereço incompleto."""
        for _ in range(tentativas):
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

        if e_unidade_parceira(texto):
            return ResultadoCotacao(
                self.slug, StatusCotacao.RECUSADO, raw_response=texto[:800],
                motivo_recusa=(
                    "A Generoso atende esta origem por uma UNIDADE PARCEIRA, "
                    "que cota por fora do portal — por isso não veio preço "
                    "aqui. Tem transporte: fale direto com a unidade "
                    f"responsável. Contatos em {LINK_UNIDADES}"))

        if carga_excede_limites(texto):
            return ResultadoCotacao(
                self.slug, StatusCotacao.RECUSADO, raw_response=texto[:800],
                motivo_recusa=motivo_limite_excedido(texto))

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
            return recusa_por_validacao(self.slug, erros)

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
        run = self.workdir / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        run.mkdir(parents=True, exist_ok=True)
        enviado = datetime.now()
        evidencias: list[str] = []
        avisos: list[str] = []

        with _TRAVA_CONTA, sync_playwright() as p:
            browser = p.chromium.launch(**self.opcoes_do_navegador())
            page = browser.new_context(
                locale="pt-BR",
                viewport={"width": 1400, "height": 1400}).new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                self._entrar(page)
                page.goto(URL, wait_until="domcontentloaded")
                page.wait_for_selector("select")
                page.wait_for_timeout(3_000)

                # ------------------------------------- 0. Empresa solicitante
                # ANTES de qualquer etapa: é o cartão do Solicitante, no topo
                # da tela, e é ele que decide com QUAL das três empresas do
                # grupo a cotação sai. Até 25/08/2026 saía sempre com a da
                # conta, e a tela final do Cotafrete tinha um aviso só para
                # explicar isso ao vendedor.
                alvo = empresa_alvo(req)
                self._escolher_empresa(page, alvo)
                if alvo is not None:
                    evidencias += print_seguro(page, run / "etapa0_empresa.png")

                # -------------------------------------------- 1. Tipo pagador
                page.locator("select:visible").last.select_option(
                    label=c["tipo_pagador"])
                page.wait_for_timeout(1_500)
                evidencias += print_seguro(page, run / "etapa1_pagador.png")
                self._avancar(page)

                # ------------------------------- 2. Origem e 3. Destino
                # A ponta que a Ventura ocupa vem TRAVADA no CNPJ da conta; a
                # outra e digitada. Qual e qual depende do CIF/FOB — ver
                # pontas_a_digitar. Digitar na travada nao adianta, e deixar a
                # livre em branco faz a cotacao nao ter para onde ir.
                for numero, (lado, cnpj) in enumerate(
                        zip(("origem", "destino"), pontas_a_digitar(req)), 2):
                    achado, resposta_da_busca = self._preencher_ponta(
                        page, cnpj)
                    if not achado["city"]:
                        # A Generoso pode ter respondido que não conhece este
                        # CNPJ. Se respondeu, é recusa dela e repetir dá o
                        # mesmo resultado — foi o que a #56 fez três vezes.
                        sem_cadastro = cliente_nao_cadastrado(
                            resposta_da_busca)
                        if sem_cadastro:
                            raise ClienteNaoCadastrado(
                                recusa_cliente_nao_cadastrado(
                                    cnpj or sem_cadastro, lado))

                        # Ela NÃO disse nada: aí continua sendo "não sabemos",
                        # e não sabemos mesmo. Erro comum, que repete.
                        de_onde = (f"o CNPJ {cnpj}" if cnpj
                                   else "a conta da Generoso")
                        raise RuntimeError(
                            f"{de_onde} nao trouxe o endereco de {lado}; sem "
                            f"isso a cotacao sairia de lugar nenhum. O site "
                            f"diz: {self._erros_da_tela(page)}")
                    self._conferir_cobertura(page, lado, req)
                    evidencias += print_seguro(
                        page, run / f"etapa{numero}_{lado}.png")
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

            except ClienteNaoCadastrado as sem_cadastro:
                # A Generoso respondeu. RECUSADO, com as palavras dela — e
                # sem retentativa, que só gastaria vaga de navegador para
                # ouvir o mesmo não.
                return ResultadoCotacao(
                    self.slug, StatusCotacao.RECUSADO, enviado_em=enviado,
                    motivo_recusa=str(sem_cadastro),
                    evidencias=evidencias
                    + print_seguro(page, run / "sem_cadastro.png"))
            except ForaDeArea as fora:
                return ResultadoCotacao(
                    self.slug, StatusCotacao.RECUSADO, enviado_em=enviado,
                    motivo_recusa=str(fora),
                    evidencias=evidencias
                    + print_seguro(page, run / "fora_de_area.png"))
            except Exception as exc:
                return erro_do_adapter(
                    self.slug, exc, enviado_em=enviado,
                    evidencias=evidencias
                    + print_seguro(page, run / "erro.png"))
            finally:
                browser.close()
