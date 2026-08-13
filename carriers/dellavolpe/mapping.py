"""Della Volpe — camada PURA (sem browser, sem rede).

Converte o modelo central nos campos exatos do formulário e aplica as regras
que a própria transportadora declara na página.

As chaves do payload são os RÓTULOS do formulário. A camada de browser localiza
cada campo por label/placeholder, nunca por XPath posicional — é o que mantém a
automação viva quando eles mexerem no layout.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from carriers.base import CampoSpec, ErroValidacao, Modo, Severidade
from core.models import CotacaoRequest, Servico, StatusCotacao
from carriers.base import ResultadoCotacao

SLUG = "dellavolpe"
NOME = "Transportes Della Volpe"
MODO = Modo.ASSINCRONO_RAPIDO
SLA_ESPERADO_MIN = 15
# CONFIRMADO em 13/08/2026 por quatro propostas reais da Della Volpe, que
# declaram o peso cubado calculado por eles: 7,20 kg para 0,024 m³; 18,00 para
# 0,06; 28,80 para 0,096; 72,00 para 0,24. Todas dão 300. Propostas
# 13320/26, 13322/26, 13324/26 e 13326/26.
FATOR_CUBAGEM = Decimal(300)

PESO_MIN_KG = Decimal(1)
PESO_MAX_KG = Decimal(34_000)

# Rótulos exatos do <select> de serviço (atenção ao espaço antes do hífen)
ROTULO_SERVICO = {
    Servico.FRACIONADO_LTL: "Fracionado -LTL",
    Servico.LOTACAO_FTL: "Lotação/Dedicado-FTL",
}

# Opções do select de veículo, com o limite que a própria DV declara
VEICULOS: dict[str, Decimal | None] = {
    "Fiorino (até 500 kg)": Decimal(500),
    "Van (até 1000 kg)": Decimal(1_000),
    "Truck (até 12.500 kg)": Decimal(12_500),
    "Carreta Simples (até 27.000 kg)": Decimal(27_000),
    "Carreta LS (até 30.000 kg)": Decimal(30_000),
    "Carreta Vanderleia (até 34.000 kg)": Decimal(34_000),
    "Bug 20": None,
    "Bug 40": None,
}


# ------------------------------------------------------------- formatadores
def num_br(v: Decimal, casas: int = 2) -> str:
    """1234.5 -> '1.234,50' (formato que o campo brasileiro espera)."""
    q = v.quantize(Decimal(10) ** -casas, rounding=ROUND_HALF_UP)
    inteiro, _, dec = f"{q:.{casas}f}".partition(".")
    neg = inteiro.startswith("-")
    inteiro = inteiro.lstrip("-")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    out = ".".join(grupos) + ("," + dec if casas else "")
    return ("-" if neg else "") + out


def peso_br(v: Decimal) -> str:
    """Peso sem separador de milhar: o campo aceita '350' ou '1500,5'."""
    q = v.normalize()
    s = f"{q:f}"
    return s.replace(".", ",")


def medida_br(v: Decimal) -> str:
    """Medida em cm com UMA casa decimal — formato que o site declara e exige.

    O campo tem máscara que reserva uma casa: digitar '100' vira '10,0' e a
    carga é cotada 10x menor, sem nenhum aviso. O placeholder do próprio
    formulário documenta o formato: 'Comprimento (ex. 12,5m = 1.250,0cm)'.
    Medido no site em produção — não usar peso_br() aqui."""
    return num_br(v, 1)


# ------------------------------------------------------------- especificação
def campos_obrigatorios(req: CotacaoRequest) -> list[CampoSpec]:
    campos = [
        CampoSpec("Nome completo", True, "text"),
        CampoSpec("E-mail", True, "email"),
        CampoSpec("WhatsApp", True, "tel"),
        CampoSpec("Qual o serviço que você procura?", True, "select"),
        CampoSpec("CNPJ - Remetente", True, "text"),
        CampoSpec("Selecione o estado de origem", True, "select"),
        CampoSpec("Selecione a cidade de origem", True, "select"),
        CampoSpec("CNPJ - Destinatário", True, "text"),
        CampoSpec("Selecione o estado de destino", True, "select"),
        CampoSpec("Selecione a cidade de destino", True, "select"),
        CampoSpec("Peso total", True, "number"),
        CampoSpec("Quantidade de Volumes", True, "number"),
        CampoSpec("Comprimento", True, "number"),
        CampoSpec("Largura", True, "number"),
        CampoSpec("Altura", True, "number"),
        CampoSpec("Valor total da nota fiscal", True, "money"),
        CampoSpec("Tipo de Material que será transportado", True, "text"),
        CampoSpec("CNPJ da empresa que pagará o frete", True, "text"),
    ]
    if req.servico is Servico.LOTACAO_FTL:
        campos.append(CampoSpec("Escolha o tipo de veículo", True, "select", "servico=FTL"))
    if req.tem_medidas_distintas:
        campos.append(CampoSpec("Anexar Planilha", True, "file", "volumes com medidas distintas"))
    if req.mercadoria.is_perigoso:
        campos.append(CampoSpec("Anexar FISPQ / Licença", True, "file", "produto químico"))
    return campos


# ------------------------------------------------------------------ validação
def validar(req: CotacaoRequest) -> list[ErroValidacao]:
    erros: list[ErroValidacao] = []
    peso = req.peso_total_kg

    if peso < PESO_MIN_KG or peso > PESO_MAX_KG:
        erros.append(ErroValidacao(
            "peso_total_kg",
            f"Della Volpe aceita de {PESO_MIN_KG} a {num_br(PESO_MAX_KG, 0)} kg; "
            f"a carga tem {peso_br(peso)} kg.",
        ))

    if req.servico is Servico.LOTACAO_FTL:
        if not req.veiculo_desejado:
            erros.append(ErroValidacao(
                "veiculo_desejado", "Obrigatório na modalidade Lotação/Dedicado-FTL."))
        elif req.veiculo_desejado not in VEICULOS:
            erros.append(ErroValidacao(
                "veiculo_desejado",
                f"'{req.veiculo_desejado}' não está no select da Della Volpe."))
        else:
            cap = VEICULOS[req.veiculo_desejado]
            if cap is not None and peso > cap:
                erros.append(ErroValidacao(
                    "veiculo_desejado",
                    f"{req.veiculo_desejado} suporta {num_br(cap, 0)} kg, "
                    f"mas a carga tem {peso_br(peso)} kg.",
                ))

    if req.mercadoria.is_perigoso and not req.mercadoria.fispq_path:
        erros.append(ErroValidacao(
            "mercadoria.fispq_path",
            "Produto químico exige anexo da FISPQ."))

    if req.tem_medidas_distintas:
        erros.append(ErroValidacao(
            "volumes",
            "Volumes com medidas distintas: planilha será gerada e anexada "
            "automaticamente; C/L/A do formulário usam o maior volume.",
            Severidade.AVISO,
        ))

    return erros


def bloqueantes(erros: list[ErroValidacao]) -> list[ErroValidacao]:
    return [e for e in erros if e.severidade is Severidade.ERRO]


# ------------------------------------------------------------------- payload
def preparar_payload(req: CotacaoRequest) -> dict[str, Any]:
    """FUNÇÃO PURA. É o coração do 'está pegando as informações certas'."""
    mv = req.maior_volume

    payload: dict[str, Any] = {
        "Nome completo": req.solicitante.nome,
        "E-mail": req.solicitante.email,
        "WhatsApp": req.solicitante.whatsapp_formatado,
        "Qual o serviço que você procura?": ROTULO_SERVICO[req.servico],

        "CNPJ - Remetente": req.remetente.cnpj_formatado,
        "Selecione o estado de origem": req.origem.uf,
        "Selecione a cidade de origem": req.origem.cidade,

        "CNPJ - Destinatário": req.destinatario.cnpj_formatado,
        "Selecione o estado de destino": req.destino.uf,
        "Selecione a cidade de destino": req.destino.cidade,

        # DV pede peso TOTAL e QUANTIDADE — não m³. Cubagem é interna nossa.
        "Peso total": peso_br(req.peso_total_kg),
        "Quantidade de Volumes": str(req.quantidade_volumes),

        # Medidas em cm, do MAIOR volume quando há medidas distintas.
        # medida_br, não peso_br: o campo tem máscara de 1 casa decimal.
        "Comprimento": medida_br(mv.comprimento_cm),
        "Largura": medida_br(mv.largura_cm),
        "Altura": medida_br(mv.altura_cm),

        "Valor total da nota fiscal": num_br(req.nota_fiscal.valor_total),
        "Tipo de Material que será transportado": req.mercadoria.tipo_material,
        "CNPJ da empresa que pagará o frete": req.pagador_frete.cnpj_formatado,
    }

    if req.servico is Servico.LOTACAO_FTL and req.veiculo_desejado:
        payload["Escolha o tipo de veículo"] = req.veiculo_desejado

    anexos: list[str] = []
    if req.tem_medidas_distintas:
        anexos.append("__PLANILHA_VOLUMES__")  # resolvido pela camada de browser
    if req.mercadoria.is_perigoso and req.mercadoria.fispq_path:
        payload["Anexar FISPQ / Licença"] = req.mercadoria.fispq_path
    if anexos:
        payload["Anexar Planilha"] = anexos

    # metadados internos — NÃO vão para o formulário
    payload["_meta"] = {
        "cubagem_m3": str(req.cubagem_m3),
        "peso_cubado_kg": str(req.peso_cubado_kg(FATOR_CUBAGEM)),
        "medidas_distintas": req.tem_medidas_distintas,
        "grupos_de_volume": len(req.volumes),
    }
    return payload


def campos_do_formulario(payload: dict[str, Any]) -> dict[str, Any]:
    """Só o que realmente é digitado no site."""
    return {k: v for k, v in payload.items() if not k.startswith("_")}


CAMPOS_ARQUIVO = ("Anexar Planilha", "Anexar FISPQ / Licença")


def separar_anexos(campos: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Divide em (campos de texto, campos de arquivo).

    Existe porque anexo NÃO pode passar pelo fill() do Playwright: input[type=file]
    só aceita set_input_files(). Misturar os dois derruba o envio de produto
    químico, que é exatamente o caso em que o anexo é obrigatório."""
    texto = {k: v for k, v in campos.items() if k not in CAMPOS_ARQUIVO}
    arquivos = {k: v for k, v in campos.items() if k in CAMPOS_ARQUIVO}
    return texto, arquivos


# ---------------------------------------------------------------- resposta
# Texto de dentro da div de resposta do CF7 — é lá que a confirmação aparece.
RE_RESPOSTA_CF7 = re.compile(
    r'<div[^>]*wpcf7-response-output[^>]*>(.*?)</div>', re.DOTALL)

FRASES_DE_CONFIRMACAO = (
    "agradecemos a sua mensagem",   # texto exato deste site
    "agradecemos sua mensagem",
    "retornaremos seu contato",
    "obrigado",
    "recebemos",
)


def normalizar_resposta(raw: Any) -> ResultadoCotacao:
    """O POST da DV não devolve preço — devolve confirmação de envio.
    O valor chega depois, pelo ingestor de e-mail."""
    texto = (str(raw) or "").lower()

    # O que prova envio é o TEXTO DENTRO da div de resposta do Contact Form 7.
    # Duas versões erradas antes desta:
    #   1. procurar "sucesso" no HTML inteiro — a página tem uma seção "Casos
    #      de sucesso", então toda página parecia enviada;
    #   2. exigir a classe wpcf7-mail-sent-ok — este site NÃO a usa. A div
    #      continua `wpcf7-response-output aria-hidden="true"` e só o texto de
    #      dentro muda. Exigir a classe recusaria toda confirmação real.
    # Confirmação real, medida em 13/08/2026:
    #   <div class="wpcf7-response-output" aria-hidden="true">Olá Enzo Zon.
    #    Agradecemos a sua mensagem. Em breve retornaremos seu contato.</div>
    dentro = " ".join(RE_RESPOSTA_CF7.findall(texto)).strip()

    # Bloqueio antispam do CF7 (Akismet/reCAPTCHA v3). Medido em 13/08/2026:
    # "A submissão mencionou-se como spam. Clique em 'Pedir orçamento'
    # novamente". Não é falha nossa nem recusa comercial: é o site julgando o
    # remetente. Precisa de status próprio, senão vira "erro" genérico e
    # ninguém entende por que o e-mail nunca chega.
    if "spam" in dentro or "wpcf7-spam-blocked" in texto:
        return ResultadoCotacao(
            transportadora=SLUG,
            status=StatusCotacao.INTERVENCAO_NECESSARIA,
            valor_frete=None,
            raw_response=raw,
            motivo_recusa="Envio barrado como spam pelo formulário. "
                          "Nenhum e-mail foi gerado.",
        )

    falhou = ("wpcf7-mail-sent-ng" in texto
              or any(t in dentro for t in ("erro", "falha", "não foi possível")))
    sucesso = (not falhou
               and any(t in dentro for t in FRASES_DE_CONFIRMACAO))
    return ResultadoCotacao(
        transportadora=SLUG,
        status=StatusCotacao.AGUARDANDO_RETORNO if sucesso else StatusCotacao.ERRO,
        valor_frete=None,   # correto: ainda não existe preço
        raw_response=raw,
        erro=None if sucesso else "Confirmação de envio não identificada na resposta.",
    )
