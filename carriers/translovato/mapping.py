"""Translovato — camada PURA.

Portal do cliente, com login. Não há API: o preço sai de um formulário web que
responde na própria página (SÍNCRONO, igual à Jadlog e diferente da Della
Volpe, que responde por e-mail horas depois).

    https://www.translovato.com.br/portal-do-cliente/solicitacao-de-cotacao

Tudo aqui foi MEDIDO contra o site real em 18/08/2026 — 5 dry-runs com
conferência campo a campo e 5 cotações reais. Nada é presumido.

As três armadilhas, todas silenciosas (o site aceita e devolve preço plausível):

1. MEDIDAS EM METROS. A ficha do Enzo e as outras transportadoras falam em
   centímetros; este formulário fala em metros, com vírgula. 30 cm é "0,3".
   Mandar "30" cota uma caixa de 30 metros.
2. O FATOR DE CUBAGEM VEM DO PRODUTO, não é constante do site. Com o produto
   em branco o site usa fator 1 e o peso cubado sai 270x menor — frete
   barato, sem nenhum erro na tela. Por isso o produto é obrigatório aqui.
3. CEP SEM MÁSCARA (8 dígitos), CNPJ COM MÁSCARA (18 caracteres). Os campos
   têm maxlength diferente; trocar os formatos trunca em silêncio.

REGRA DE NEGÓCIO (Enzo, 18/08/2026): a carga sai SEMPRE da Ventura — remetente
é a Ventura, destinatário é o cliente. E o produto é SEMPRE SUPR.INFORMATICA,
qualquer que seja a mercadoria real.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao, Severidade,
)
from core.models import CotacaoRequest, StatusCotacao, limpa_doc

SLUG = "translovato"
NOME = "Translovato"
MODO = Modo.SINCRONO
SLA_ESPERADO_MIN = None

BASE = "https://www.translovato.com.br"
URL_LOGIN = f"{BASE}/fale-conosco/solicitacao-de-cotacao#portal-do-cliente"
URL_COTACAO = f"{BASE}/portal-do-cliente/solicitacao-de-cotacao"

# Único produto que a conta da Ventura enxerga, e o que o Enzo usa sempre.
# É ele que define o FATOR abaixo — os dois andam juntos.
PRODUTO = "SUPR.INFORMATICA"
FATOR_CUBAGEM = Decimal(300)      # kg/m3, medido: 0,027 m3 -> 8,10 kg

CM_POR_M = Decimal(100)
CASAS_MEDIDA = Decimal("0.001")   # milímetro; o campo tem maxlength 6
CASAS_DINHEIRO = Decimal("0.01")

PAGADOR_REMETENTE = "1"           # value[payer_type]; o CNPJ vem sozinho
REDESPACHO_NAO = "0"

# Frase do site quando a praça está fora da malha. Não é erro do robô.
AVISO_FORA_DE_AREA = "não está em nossa regi"


def campos_obrigatorios(req: CotacaoRequest) -> list[CampoSpec]:
    return [
        CampoSpec("value[sender_cpnj]", True, "cnpj-mascarado"),
        CampoSpec("value[sender_zipcode]", True, "cep8"),
        CampoSpec("value[receiver_cnpj_cpf]", True, "cnpj-mascarado"),
        CampoSpec("value[receiver_zipcode]", True, "cep8"),
        CampoSpec("value[volume_product]", True, "select",
                  "define o fator de cubagem"),
        CampoSpec("value[volume_nf]", True, "decimal-virgula"),
        CampoSpec("value[volume_weigth]", True, "decimal-virgula",
                  "peso TOTAL da carga"),
        CampoSpec("cubing_qnt[]", True, "int"),
        CampoSpec("cubing_height[]", True, "metros-virgula"),
        CampoSpec("cubing_length[]", True, "metros-virgula"),
        CampoSpec("cubing_depth[]", True, "metros-virgula"),
    ]


# ------------------------------------------------------------------ formatos
def _br(valor: Decimal, casas: Decimal) -> str:
    """Decimal -> texto do jeito que o campo espera: vírgula, sem expoente.

    `f"{v:f}"` em vez de `str(v)` de propósito: str(Decimal("1E+2")) devolve
    "1E+2", que num campo de texto entra como lixo e cota uma carga que não
    existe."""
    return f"{valor.quantize(casas, rounding=ROUND_HALF_UP):f}".replace(
        ".", ",")


def _enxuto(valor: Decimal, casas: Decimal) -> str:
    """Como _br, mas sem zeros à direita: 1,000 -> "1" e 0,300 -> "0,3".

    O campo tem maxlength 6; gastar caracteres com zero à toa faz uma medida
    legítima ser truncada."""
    texto = f"{valor.quantize(casas, rounding=ROUND_HALF_UP):f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return (texto or "0").replace(".", ",")


def _metros(cm: Decimal) -> str:
    """Centímetros da ficha -> metros do formulário. A armadilha nº 1."""
    return _enxuto(cm / CM_POR_M, CASAS_MEDIDA)


def _cnpj_mascarado(doc: str) -> str:
    """00000000000000 -> 00.000.000/0000-00. O campo tem maxlength 18."""
    d = limpa_doc(doc)
    if len(d) != 14:
        return doc
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


# ---------------------------------------------------------------- validação
def validar(req: CotacaoRequest) -> list[ErroValidacao]:
    erros: list[ErroValidacao] = []

    for lado, local in (("origem", req.origem), ("destino", req.destino)):
        cep = limpa_doc(local.cep or "")
        if len(cep) != 8:
            erros.append(ErroValidacao(
                f"{lado}.cep",
                "A Translovato roteia por CEP; informe 8 dígitos "
                f"(recebido: {local.cep!r})."))

    # O formulário tem UMA linha de cubagem; há um "adicionar linha" que ainda
    # não automatizamos. Cotar só o primeiro grupo devolveria preço de menos.
    if req.tem_medidas_distintas:
        erros.append(ErroValidacao(
            "volumes",
            "Esta carga tem volumes com medidas diferentes, e o formulário da "
            "Translovato cota uma medida por vez. Cotar assim daria um preço "
            "menor que o real — separe em cotações, ou peça o suporte a "
            "várias linhas."))

    if req.mercadoria.is_perigoso:
        erros.append(ErroValidacao(
            "mercadoria.is_perigoso",
            "A Translovato não transporta produtos químicos (consta nas "
            "condições do formulário deles).", Severidade.AVISO))

    return erros


def bloqueantes(erros: list[ErroValidacao]) -> list[ErroValidacao]:
    return [e for e in erros if e.severidade is Severidade.ERRO]


# ------------------------------------------------------------------ payload
def preparar_payload(req: CotacaoRequest) -> dict[str, Any]:
    """FUNÇÃO PURA. Modelo central -> campos do formulário, prontos para digitar.

    As chaves são os `name` reais dos inputs, medidos no recon: casar por
    posição quebraria no primeiro campo que eles mexerem de lugar."""
    v = req.volumes[0]
    return {
        # 1. remetente — SEMPRE a Ventura (regra do Enzo)
        "value[sender_cpnj]": _cnpj_mascarado(req.remetente.cnpj),
        "value[sender_zipcode]": limpa_doc(req.origem.cep or ""),
        # 2. destinatário — o cliente
        "value[receiver_redispatch]": REDESPACHO_NAO,
        "value[receiver_cnpj_cpf]": _cnpj_mascarado(req.destinatario.cnpj),
        "value[receiver_zipcode]": limpa_doc(req.destino.cep or ""),
        # 3. pagador — o CNPJ é preenchido pelo próprio site
        "value[payer_type]": PAGADOR_REMETENTE,
        # 4. volume
        "value[volume_product]": PRODUTO,
        "value[volume_nf]": _br(req.nota_fiscal.valor_total, CASAS_DINHEIRO),
        "value[volume_weigth]": _enxuto(req.peso_total_kg, CASAS_DINHEIRO),
        "cubing_qnt[]": str(v.qtd),
        # A ordem dos três campos na tela é Altura, Largura, Profundidade.
        # Comprimento da ficha = profundidade deles.
        "cubing_height[]": _metros(v.altura_cm),
        "cubing_length[]": _metros(v.largura_cm),
        "cubing_depth[]": _metros(v.comprimento_cm),
    }


def cubagem_esperada(req: CotacaoRequest) -> dict[str, str]:
    """O que o site DEVE calcular sozinho, para conferir contra a tela.

    Conferir em vez de confiar é o que pega a armadilha nº 2: se o produto não
    entrou, o peso cubado vem 300x menor e nada na tela denuncia."""
    cubagem = req.cubagem_m3
    return {
        "cubagem": _br(cubagem, Decimal("0.0001")),
        "peso_cubado": _br(cubagem * FATOR_CUBAGEM, CASAS_DINHEIRO),
    }


# ----------------------------------------------------------------- resposta
RE_VALOR = re.compile(r"R\$\s*([\d.]+,\d{2})")
RE_PRAZO = re.compile(r"(\d+)\s*dias?", re.I)
MARCA_FAIXA = "Consulta de Valor"


def _num_br(texto: str) -> Decimal | None:
    try:
        return Decimal(texto.replace(".", "").replace(",", "."))
    except Exception:
        return None


def normalizar_resposta(raw: Any) -> ResultadoCotacao:
    """`raw` é o texto da tela depois de simular."""
    texto = str(raw or "")

    if AVISO_FORA_DE_AREA in texto:
        return ResultadoCotacao(
            SLUG, StatusCotacao.RECUSADO, raw_response=texto[:800],
            motivo_recusa="A Translovato não atende este CEP.")

    # Corta a partir da faixa de resultado. Sem isto, o "R$" do VALOR DA NF —
    # que fica na mesma tela, logo acima — vira o valor do frete.
    corte = texto.find(MARCA_FAIXA)
    faixa = texto[corte:corte + 400] if corte >= 0 else texto

    achado = RE_VALOR.search(faixa)
    valor = _num_br(achado.group(1)) if achado else None
    if valor is None:
        return ResultadoCotacao(
            SLUG, StatusCotacao.ERRO, raw_response=texto[:800],
            erro="A tela da Translovato não mostrou valor de frete.")

    prazo = RE_PRAZO.search(faixa)
    return ResultadoCotacao(
        transportadora=SLUG,
        status=StatusCotacao.COTADO,
        valor_frete=valor,
        prazo_dias=int(prazo.group(1)) if prazo else None,
        raw_response=texto[:800],
    )
