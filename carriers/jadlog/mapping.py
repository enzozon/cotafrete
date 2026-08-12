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

# ⚠ confirmar no PDF do contrato — variam por cliente
MODALIDADES = {
    "expresso": 0,
    "package": 3,
    "rodoviario": 4,
    "economico": 5,
    "corporate": 6,
    "standard": 12,
    "pickup": 14,
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
def validar(req: CotacaoRequest, *, modalidade: str = "package") -> list[ErroValidacao]:
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
    elif peso > PESO_MAX_PUDO_KG and modalidade == "pickup":
        erros.append(ErroValidacao(
            "peso",
            f"{peso} kg passa do limite de ponto de postagem "
            f"({PESO_MAX_PUDO_KG} kg).", Severidade.AVISO,
        ))

    if req.mercadoria.is_perigoso:
        erros.append(ErroValidacao(
            "mercadoria.is_perigoso",
            "Produto perigoso normalmente não é aceito em modal expresso; "
            "confirme com a franquia.", Severidade.AVISO,
        ))

    return erros


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
