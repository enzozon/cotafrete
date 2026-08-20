"""Ficha de cotação em texto -> modelo central.

Formato que o Enzo digita à mão, uma linha por campo:

    Nome Completo: Enzo Zon
    UF Origem: SP
    ...

Camada PURA: só texto entra, só modelo sai. Nada de rede, nada de arquivo.

O casamento das chaves ignora acento, caixa e espaço repetido, porque ficha
digitada à mão varia toda vez ("Tipo de Serviço", "TIPO DE SERVICO", "tipo de
servico"). Linha que não bate com chave conhecida é ignorada de propósito:
ficha real vem com observação no fim e assinatura de e-mail junto.
"""

from __future__ import annotations

import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Callable

from core.models import (
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, TipoFrete, Volume, limpa_doc,
)

# CEP só com dígitos -> (cidade, uf, código IBGE). Injetado para este módulo
# não abrir rede: a implementação real mora em core/cep.py.
BuscaCEP = Callable[[str], tuple[str, str, str | None]]


class CamposFaltando(ValueError):
    """Diz QUAIS campos faltaram — conferir 19 linhas na mão é pior."""

    def __init__(self, faltando: list[str]) -> None:
        self.faltando = faltando
        super().__init__("Faltam campos na ficha: " + ", ".join(faltando))


def _normalizar(chave: str) -> str:
    """'Tipo  de  Serviço' e 'TIPO DE SERVICO' viram a mesma coisa."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", chave)
        if unicodedata.category(c) != "Mn")
    return " ".join(sem_acento.lower().split())


# Rótulo canônico -> apelidos aceitos. O canônico é o que aparece na mensagem
# de erro, então é o que a pessoa vai procurar na ficha.
APELIDOS: dict[str, tuple[str, ...]] = {
    "Nome Completo": ("nome completo", "nome"),
    "email": ("email", "e-mail"),
    "WhatsApp": ("whatsapp", "telefone", "celular"),
    "CEP ORIGEM": ("cep origem",),
    "CEP DESTINO": ("cep destino",),
    "CNPJ Remetente": ("cnpj remetente",),
    "CNPJ Destinatario": ("cnpj destinatario",),
    "CNPJ Pagador": ("cnpj pagador", "cnpj pagador do frete"),
    "Peso Total (kg)": ("peso total (kg)", "peso total", "peso"),
    "Quantidade de Volumes": ("quantidade de volumes", "qtd volumes", "volumes"),
    "Comprimento (cm)": ("comprimento (cm)", "comprimento"),
    "Largura (cm)": ("largura (cm)", "largura"),
    "Altura (cm)": ("altura (cm)", "altura"),
    "Valor Total Nota Fiscal": ("valor total nota fiscal", "valor da nota",
                                "valor nf", "valor total da nota fiscal"),
    "Material": ("material", "tipo de material"),
    "Tipo de Serviço": ("tipo de servico", "servico"),
}

# Opcionais: cidade e UF são lembrete humano — o CEP é a fonte de verdade.
# Ficaram fora de OBRIGATORIOS depois que uma ficha trouxe "São José dos
# Campos" com CEP de São Bernardo do Campo, e cada site cotou uma rota.
OPCIONAIS: dict[str, tuple[str, ...]] = {
    "Cidade Origem": ("cidade origem",),
    "UF Origem": ("uf origem", "estado origem"),
    "Cidade Destino": ("cidade destino",),
    "UF Destino": ("uf destino", "estado destino"),
    "Modalidade": ("modalidade", "modalidade jadlog"),
}

# apelido normalizado -> rótulo canônico
_DE_APELIDO = {_normalizar(a): canon
               for canon, apelidos in {**APELIDOS, **OPCIONAIS}.items()
               for a in apelidos}

SERVICO_POR_TEXTO = {
    "fracionado -ltl": Servico.FRACIONADO_LTL,
    "fracionado ltl": Servico.FRACIONADO_LTL,
    "fracionado": Servico.FRACIONADO_LTL,
    "ltl": Servico.FRACIONADO_LTL,
    "lotacao": Servico.LOTACAO_FTL,
    "carga lotacao": Servico.LOTACAO_FTL,
    "ftl": Servico.LOTACAO_FTL,
}

OBRIGATORIOS = tuple(APELIDOS)

# Códigos aceitos em "Modalidade". São os do <select> do simulador da Jadlog.
MODALIDADE_PADRAO = "expresso"
MODALIDADES_VALIDAS = ("expresso", "package", "rodoviario", "economico",
                       "doc", "com", "cargo")


def ler_modalidade(texto: str) -> str:
    """Modalidade da Jadlog em minúsculas. Fora do CotacaoRequest de propósito:
    é vocabulário de UMA transportadora, e o modelo central não conhece
    transportadora nenhuma."""
    escrito = separar_campos(texto).get("Modalidade")
    if not escrito:
        return MODALIDADE_PADRAO
    codigo = _normalizar(escrito)
    if codigo not in MODALIDADES_VALIDAS:
        raise ValueError(
            f"Modalidade não reconhecida: {escrito!r}. "
            f"Use uma de: {', '.join(MODALIDADES_VALIDAS)}")
    return codigo


def num(escrito: str) -> Decimal:
    """'568.77', '568,77' e '1.568,77' viram Decimal.

    Quem digita alterna entre ponto e vírgula sem avisar. A regra: se tem os
    dois, o ponto é separador de milhar; se só tem vírgula, ela é o decimal.
    """
    t = escrito.strip()
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation as exc:
        raise ValueError(f"número não reconhecido: {escrito!r}") from exc


def separar_campos(texto: str) -> dict[str, str]:
    """Linhas 'Chave: valor' -> dict com os rótulos canônicos."""
    campos: dict[str, str] = {}
    for linha in texto.splitlines():
        chave, sep, valor = linha.partition(":")
        if not sep:
            continue                      # linha solta, observação, assinatura
        canonico = _DE_APELIDO.get(_normalizar(chave))
        if canonico and valor.strip():
            campos[canonico] = valor.strip()
    return campos


def _local(c: dict[str, str], sufixo_cep: str, sufixo_cidade: str,
           buscar_cep: BuscaCEP | None) -> Local:
    """Monta origem/destino. O CEP manda; cidade digitada é só lembrete."""
    cep = c[f"CEP {sufixo_cep}"]
    cidade = c.get(f"Cidade {sufixo_cidade}")
    uf = c.get(f"UF {sufixo_cidade}", "")
    ibge = None

    if buscar_cep is not None:
        cidade, uf, ibge = buscar_cep(limpa_doc(cep))

    if not cidade or not uf:
        raise CamposFaltando([f"Cidade {sufixo_cidade}", f"UF {sufixo_cidade}"])

    return Local(uf=uf.upper(), cidade=cidade, cep=cep, codigo_ibge=ibge)


def _tipo_de_frete(c: dict) -> TipoFrete:
    """A ficha de papel traz "CNPJ Pagador"; o sistema trabalha com CIF/FOB.

    Deduz comparando com as duas pontas. Um pagador que não é nenhuma delas
    não tem mais representação — e inventar CIF ali faria a Camilo receber
    tp_frete=1 para um frete que ninguém pediu assim. Melhor parar e dizer."""
    pagador = limpa_doc(c.get("CNPJ Pagador") or "")
    if pagador == limpa_doc(c.get("CNPJ Remetente") or ""):
        return TipoFrete.CIF
    if pagador == limpa_doc(c.get("CNPJ Destinatario") or ""):
        return TipoFrete.FOB
    raise ValueError(
        f"O CNPJ Pagador da ficha ({c.get('CNPJ Pagador')}) não é nem o "
        f"remetente nem o destinatário. O frete só pode ser CIF (paga o "
        f"remetente) ou FOB (paga o destinatário).")


def ler_ficha(texto: str, buscar_cep: BuscaCEP | None = None) -> CotacaoRequest:
    """Ficha em texto -> CotacaoRequest. Levanta CamposFaltando se faltar algo.

    `buscar_cep` é injetado: sem ele este módulo continua puro, sem rede. Com
    ele, cidade e UF saem do CEP e vencem o que estiver escrito na ficha — foi
    escrever cidade à mão que fez uma ficha com CEP de São Bernardo do Campo
    dizer "São José dos Campos", e cada site cotar uma rota diferente.
    """
    c = separar_campos(texto)

    if faltando := [k for k in OBRIGATORIOS if k not in c]:
        raise CamposFaltando(faltando)

    qtd = int(num(c["Quantidade de Volumes"]))
    if qtd < 1:
        raise ValueError("Quantidade de Volumes precisa ser pelo menos 1.")

    # O peso é o de UM volume, não o do lote: "3 de 12kg" são 12 aqui e 3 na
    # quantidade, dando 36kg de carga. Dividir pela quantidade cotaria 12kg no
    # total — um terço da carga, e o frete sai barato demais calado.
    peso_por_volume = num(c["Peso Total (kg)"])

    servico = SERVICO_POR_TEXTO.get(_normalizar(c["Tipo de Serviço"]))
    if servico is None:
        raise ValueError(
            f"Tipo de Serviço não reconhecido: {c['Tipo de Serviço']!r}. "
            f"Use um de: {', '.join(sorted(set(SERVICO_POR_TEXTO)))}")

    return CotacaoRequest(
        solicitante=Solicitante(nome=c["Nome Completo"], email=c["email"],
                                whatsapp=c["WhatsApp"]),
        servico=servico,
        origem=_local(c, "ORIGEM", "Origem", buscar_cep),
        destino=_local(c, "DESTINO", "Destino", buscar_cep),
        remetente=Parte(cnpj=c["CNPJ Remetente"]),
        destinatario=Parte(cnpj=c["CNPJ Destinatario"]),
        tipo_frete=_tipo_de_frete(c),
        volumes=[Volume(
            qtd=qtd,
            comprimento_cm=num(c["Comprimento (cm)"]),
            largura_cm=num(c["Largura (cm)"]),
            altura_cm=num(c["Altura (cm)"]),
            peso_kg=peso_por_volume,
        )],
        mercadoria=Mercadoria(tipo_material=c["Material"]),
        nota_fiscal=NotaFiscal(valor_total=num(c["Valor Total Nota Fiscal"])),
    )
