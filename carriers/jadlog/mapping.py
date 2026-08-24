"""Jadlog — camada PURA.

Diferente da Della Volpe: aqui existe API REST oficial e SÍNCRONA de verdade.
O preço volta no corpo da resposta HTTP, em segundos.

    POST https://www.jadlog.com.br/embarcador/api/frete/valor
    Authorization: Bearer <token>
    Content-Type: application/json

Duas diferenças estruturais em relação à Della Volpe:

1. Jadlog roteia por CEP, não por UF/cidade. CEP passa a ser obrigatório
   no modelo central (era opcional).
2. A doc é explícita: o campo `peso` deve receber o MAIOR entre peso real e
   peso cubado. Mandar o peso real de uma carga volumosa devolve preço abaixo
   do que será cobrado — erro silencioso, o pior tipo.

⚠ CÓDIGOS DE MODALIDADE E FATOR DE CUBAGEM: os valores abaixo são o default do
mercado, mas variam por contrato. Confira no PDF que a franquia te mandar junto
com o token, e ajuste em config. Não assuma que o default está certo.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from carriers.base import CampoSpec, ErroValidacao, Modo, ResultadoCotacao, Severidade
from core.models import CotacaoRequest, StatusCotacao, limpa_doc

SLUG = "jadlog"
NOME = "Jadlog"
MODO = Modo.SINCRONO
SLA_ESPERADO_MIN = None

URL_FRETE = "https://www.jadlog.com.br/embarcador/api/frete/valor"

# ⚠ confirmar no contrato
FATOR_CUBAGEM = Decimal(300)

# Limites operacionais divulgados publicamente (confirmar os do seu contrato)
PESO_MAX_PUDO_KG = Decimal(30)       # ponto de postagem parceiro
PESO_MAX_FRANQUIA_KG = Decimal(120)  # franquia Jadlog

# Limite POR CAIXA da calculadora do painel. Medido em 24/08/2026 (cotação
# #46): com 40 kg num volume ela pinta o campo de vermelho, escreve "Para
# caixas, o peso máximo permitido é 30kg" e DESABILITA o botão de calcular.
#
# Coincide em número com PESO_MAX_PUDO_KG e é outra regra: aquele vale só
# para retirada em ponto, este vale sempre. Separados de propósito — se um
# dos dois mudar, o outro não vai junto por acidente.
PESO_MAX_CAIXA_KG = Decimal(30)

# Os outros dois limites do MESMO pacote, ditados pelo Enzo em 24/08/2026 a
# partir do que o site responde. As três frases abaixo são as da própria
# Jadlog: o vendedor lê na tela do Cotafrete exatamente o que leria lá, e
# não uma tradução nossa que ele teria que reconciliar depois.
MEDIDA_MAX_CM = Decimal(80)
VALOR_MAX_COBERTURA = Decimal(30_000)

RECUSA_VALOR = "Cobertura máxima de R$30.000 excedida."
RECUSA_PESO = "Para caixas, o peso máximo permitido é 30kg"
RECUSA_MEDIDA = ("Altura, Largura ou Comprimento excedida. Aceitamos pacotes "
                 "com até 80cm x 80cm x 80cm.")

# VERIFICADO no simulador público da Jadlog (simulacao.jad), 12/08/2026 — são os
# códigos que o próprio <select name="modalidade"> da transportadora expõe.
# Os presumidos anteriores erravam 3 de 7: 6 é Doc (estava "corporate"), 12 é
# Cargo (estava "standard"), 9 (.Com) faltava, e 14/"pickup" não existe —
# retirada em ponto é tpentrega="R", não modalidade.
# Continua valendo conferir no contrato se a sua franquia habilita todas.
MODALIDADES = {
    "expresso": 0,      # JadLog Expresso
    "package": 3,       # JadLog Package
    "rodoviario": 4,    # JadLog Rodo
    "economico": 5,     # JadLog Econômico
    "doc": 6,           # JadLog Doc
    "com": 9,           # JadLog .Com
    "cargo": 12,        # JadLog Cargo
}

TP_ENTREGA_DOMICILIO = "D"
TP_ENTREGA_REDE = "R"      # retirada em ponto pickup
TP_SEGURO_NORMAL = "N"     # seguro da Jadlog
TP_SEGURO_APOLICE = "A"    # apólice própria do embarcador


def campos_obrigatorios(req: CotacaoRequest) -> list[CampoSpec]:
    return [
        CampoSpec("cepori", True, "string8"),
        CampoSpec("cepdes", True, "string8"),
        CampoSpec("peso", True, "double", "maior entre real e cubado"),
        CampoSpec("cnpj", True, "string", "tomador do serviço"),
        CampoSpec("modalidade", True, "int"),
        CampoSpec("tpentrega", True, "char"),
        CampoSpec("tpseguro", True, "char"),
        CampoSpec("vldeclarado", True, "double"),
        CampoSpec("conta", False, "string", "conta corrente Jadlog"),
        CampoSpec("contrato", False, "string"),
    ]


# ------------------------------------------------------------------ validação
def validar(req: CotacaoRequest, *, modalidade: str = "package",
            tpentrega: str = TP_ENTREGA_DOMICILIO) -> list[ErroValidacao]:
    erros: list[ErroValidacao] = []

    for lado, local in (("origem", req.origem), ("destino", req.destino)):
        cep = limpa_doc(local.cep or "")
        if len(cep) != 8:
            erros.append(ErroValidacao(
                f"{lado}.cep",
                "Jadlog roteia por CEP; informe 8 dígitos "
                f"(recebido: {local.cep!r}).",
            ))

    if modalidade not in MODALIDADES:
        erros.append(ErroValidacao(
            "modalidade",
            f"'{modalidade}' desconhecida. Opções: {', '.join(MODALIDADES)}."))

    peso = peso_para_api(req)
    if peso > PESO_MAX_FRANQUIA_KG:
        erros.append(ErroValidacao(
            "peso",
            f"{peso} kg excede o limite de franquia Jadlog "
            f"({PESO_MAX_FRANQUIA_KG} kg). Esta carga é perfil de "
            f"transportadora de carga fracionada pesada, não de expresso.",
        ))
    # quem define retirada em ponto é tpentrega, não a modalidade: não existe
    # modalidade "pickup" no select da Jadlog.
    elif peso > PESO_MAX_PUDO_KG and tpentrega == TP_ENTREGA_REDE:
        erros.append(ErroValidacao(
            "peso",
            f"{peso} kg passa do limite de ponto de postagem "
            f"({PESO_MAX_PUDO_KG} kg).", Severidade.AVISO,
        ))

    # Por VOLUME, não pelo total: a calculadora cota UM pacote por vez e é o
    # peso unitário que vai no campo (ver painel.py). Uma carga de 80 kg em
    # duas caixas de 40 passa folgada no limite de franquia e é recusada aqui
    # — que é exatamente o que a #46 descobriu gastando 45s de navegador.
    pesada = max((v.peso_kg for v in req.volumes), default=Decimal(0))
    if pesada > PESO_MAX_CAIXA_KG:
        erros.append(ErroValidacao(
            "peso", f"{RECUSA_PESO} (esta tem {_kg(pesada)} kg).",
        ))

    # Também por VOLUME: o site mede a CAIXA, não a soma. Três caixas de
    # 60 cm passam; uma de 81 não passa, mesmo sozinha.
    maior = max((m for v in req.volumes for m in v.dimensoes),
                default=Decimal(0))
    if maior > MEDIDA_MAX_CM:
        erros.append(ErroValidacao(
            "medidas", f"{RECUSA_MEDIDA} (esta tem {maior:.0f} cm).",
        ))

    # Valor da NOTA, não do volume: a cobertura é do que está sendo enviado.
    if req.nota_fiscal.valor_total > VALOR_MAX_COBERTURA:
        erros.append(ErroValidacao(
            "valor_nf",
            f"{RECUSA_VALOR} (esta nota é de "
            f"R$ {_kg(req.nota_fiscal.valor_total)}).",
        ))

    if req.mercadoria.is_perigoso:
        erros.append(ErroValidacao(
            "mercadoria.is_perigoso",
            "Produto perigoso normalmente não é aceito em modal expresso; "
            "confirme com a franquia.", Severidade.AVISO,
        ))

    return erros


def _kg(v: Decimal) -> str:
    """Número com vírgula decimal, do jeito que o vendedor lê."""
    return f"{v:.2f}".replace(".", ",")


def bloqueantes(erros: list[ErroValidacao]) -> list[ErroValidacao]:
    return [e for e in erros if e.severidade is Severidade.ERRO]


# -------------------------------------------------------------------- payload
CASAS_PESO = Decimal("0.001")     # grama
CASAS_DINHEIRO = Decimal("0.01")  # centavo


def _para_json(v: Decimal, casas: Decimal) -> float:
    """JSON não tem Decimal, então a conversão para float é inevitável.

    O que é evitável é o arredondamento ficar implícito: quantizar ANTES do
    float() faz a última casa sair da regra comercial (ROUND_HALF_UP) em vez de
    sair do binário. Com fator de cubagem fracionário a diferença aparece — e é
    sobre esse número que a franquia fatura."""
    return float(v.quantize(casas, rounding=ROUND_HALF_UP))


def peso_para_api(req: CotacaoRequest, fator: Decimal = FATOR_CUBAGEM) -> Decimal:
    """Regra explícita da doc Jadlog: o MAIOR entre peso real e peso cubado."""
    return max(req.peso_total_kg, req.peso_cubado_kg(fator))


def preparar_payload(
    req: CotacaoRequest,
    *,
    modalidade: str = "package",
    conta: str | None = None,
    contrato: str | None = None,
    tpentrega: str = TP_ENTREGA_DOMICILIO,
    tpseguro: str = TP_SEGURO_NORMAL,
    frap: str = "N",
    fator: Decimal = FATOR_CUBAGEM,
) -> dict[str, Any]:
    """FUNÇÃO PURA. Modelo central -> corpo JSON da API Jadlog."""
    item: dict[str, Any] = {
        "cepori": limpa_doc(req.origem.cep or ""),
        "cepdes": limpa_doc(req.destino.cep or ""),
        "frap": frap,
        "peso": _para_json(peso_para_api(req, fator), CASAS_PESO),
        "cnpj": limpa_doc(req.pagador_frete.cnpj),
        "modalidade": MODALIDADES.get(modalidade, MODALIDADES["package"]),
        "tpentrega": tpentrega,
        "tpseguro": tpseguro,
        "vldeclarado": _para_json(req.nota_fiscal.valor_total, CASAS_DINHEIRO),
        "vlcoleta": 0,
    }
    if conta:
        item["conta"] = conta
    if contrato:
        item["contrato"] = contrato
    return {"frete": [item]}


# ------------------------------------------------------------------- resposta
def _num(v: Any) -> Decimal | None:
    """Só None e string vazia são AUSÊNCIA.

    Zero é valor legítimo: frete bonificado, rota com franquia de valor,
    promoção da franquia, e prazo=0 é entrega no mesmo dia. Tratar 0 como
    ausente apagava a cotação mais barata do comparativo e devolvia
    'Resposta sem valor de frete' para uma resposta que a API considerou boa."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def normalizar_resposta(raw: Any) -> ResultadoCotacao:
    """Tolerante a variação de nomes entre versões da API.
    ⚠ conferir contra a resposta real assim que tiver token."""
    if not isinstance(raw, dict):
        return ResultadoCotacao(SLUG, StatusCotacao.ERRO,
                                raw_response=raw, erro="Resposta não-JSON.")

    itens = raw.get("frete") or []
    if not itens:
        return ResultadoCotacao(SLUG, StatusCotacao.ERRO, raw_response=raw,
                                erro="Resposta sem o array 'frete'.")

    item = itens[0]

    erro = item.get("erro")
    if isinstance(erro, dict) and (erro.get("id") or erro.get("descricao")):
        return ResultadoCotacao(
            SLUG, StatusCotacao.RECUSADO, raw_response=raw,
            erro=f"{erro.get('id', '?')}: {erro.get('descricao', 'sem descrição')}",
        )

    # `or` encadeado escorregaria de um vltotal legítimo igual a 0 para vlfrete
    # e reportaria outro número: a checagem tem que ser contra None.
    valor = _num(item.get("vltotal"))
    if valor is None:
        valor = _num(item.get("vlfrete"))
    prazo = _num(item.get("prazo"))

    if valor is None:
        return ResultadoCotacao(SLUG, StatusCotacao.ERRO, raw_response=raw,
                                erro="Resposta sem valor de frete.")

    return ResultadoCotacao(
        transportadora=SLUG,
        status=StatusCotacao.COTADO,
        valor_frete=valor,
        prazo_dias=int(prazo) if prazo is not None else None,
        raw_response=raw,
    )
