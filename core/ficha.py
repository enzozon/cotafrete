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

from core.models import (
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, Volume,
)


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
    "UF Origem": ("uf origem", "estado origem"),
    "Cidade Origem": ("cidade origem",),
    "CEP ORIGEM": ("cep origem",),
    "UF Destino": ("uf destino", "estado destino"),
    "Cidade Destino": ("cidade destino",),
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

# apelido normalizado -> rótulo canônico
_DE_APELIDO = {_normalizar(a): canon
               for canon, apelidos in APELIDOS.items() for a in apelidos}

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


def ler_ficha(texto: str) -> CotacaoRequest:
    """Ficha em texto -> CotacaoRequest. Levanta CamposFaltando se faltar algo."""
    c = separar_campos(texto)

    if faltando := [k for k in OBRIGATORIOS if k not in c]:
        raise CamposFaltando(faltando)

    qtd = int(num(c["Quantidade de Volumes"]))
    if qtd < 1:
        raise ValueError("Quantidade de Volumes precisa ser pelo menos 1.")

    # A ficha diz peso TOTAL; o modelo guarda peso POR volume. Copiar o total
    # para cada volume multiplicaria a carga pela quantidade.
    peso_por_volume = num(c["Peso Total (kg)"]) / qtd

    servico = SERVICO_POR_TEXTO.get(_normalizar(c["Tipo de Serviço"]))
    if servico is None:
        raise ValueError(
            f"Tipo de Serviço não reconhecido: {c['Tipo de Serviço']!r}. "
            f"Use um de: {', '.join(sorted(set(SERVICO_POR_TEXTO)))}")

    return CotacaoRequest(
        solicitante=Solicitante(nome=c["Nome Completo"], email=c["email"],
                                whatsapp=c["WhatsApp"]),
        servico=servico,
        origem=Local(uf=c["UF Origem"].upper(), cidade=c["Cidade Origem"],
                     cep=c["CEP ORIGEM"]),
        destino=Local(uf=c["UF Destino"].upper(), cidade=c["Cidade Destino"],
                      cep=c["CEP DESTINO"]),
        remetente=Parte(cnpj=c["CNPJ Remetente"]),
        destinatario=Parte(cnpj=c["CNPJ Destinatario"]),
        pagador_frete=Parte(cnpj=c["CNPJ Pagador"]),
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
