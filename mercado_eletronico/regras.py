"""Regras da resposta de cotação no Mercado Eletrônico — sem navegador.

Camada PURA: o que é fixo, o que se calcula e o que bloqueia o salvamento.
O robô só traduz isto para cliques; a tela só mostra. Se a regra do ICMS
morasse no robô, um teste de tela nunca a pegaria errada.

Decisões do usuário (23/09/2026):

- UNIÃO cobra só ICMS; VENTURA cobra tudo menos IPI.
- ICMS: origem 0 ou 2 → 17% dentro do ES, 12% fora. Outras origens a empresa
  não usa: bloqueiam, em vez de chutar uma alíquota.
- Prazo em dias CORRIDOS (é como o ME conta); se a data cair em fim de semana
  ou feriado, vai para o próximo dia útil.
- Validade da proposta: hoje + N dias.
- Condição de pagamento, contato, telefone e IE são os mesmos nas duas contas.
- Item sem preço só passa se tiver observação explicando.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum

from mercado_eletronico.feriados import eh_dia_util, proximo_dia_util

UF_EMPRESA = "ES"
ORIGENS_ACEITAS = frozenset({0, 2})
UFS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)


class Conta(str, Enum):
    VENTURA = "ventura"
    UNIAO = "uniao"


class RegraDesconhecida(ValueError):
    """Combinação que a empresa nunca definiu — melhor parar do que chutar."""


# ------------------------------------------------------------ valores fixos
CAMPOS_FIXOS_COTACAO: dict[str, str] = {
    "tipo_frete": "FOB",
    "frete": "Frete FOB",
    "condicao_pagamento": "60DDL",
    "nome_contato": "Eliziane Amorim",
    "telefone_contato": "2732991664",
    "moeda": "Real - Brasil",
    "inscricao_estadual": "082582190 - ES",
}

CAMPOS_FIXOS_ITEM: dict[str, str] = {
    "unidade": "UNIDADE",
    "ipi": "0",
    "ipi_incluso": "Isento",
    "substituicao_tributaria": "NÃO",
    "aliquota_st": "0,00",
    "valor_st": "0,00",
    "base_calculo_icms": "100,00",
    "base_calculo_icms_ipi": "sem IPI",
}


# ------------------------------------------------------------------ formato
def formatar_decimal(valor: Decimal, casas: int = 2) -> str:
    """`Decimal("17")` → `"17,00"`, do jeito que o ME escreve."""
    q = valor.quantize(Decimal(1).scaleb(-casas))
    inteiro, _, frac = f"{q:.{casas}f}".partition(".")
    return f"{inteiro},{frac}" if casas else inteiro


def ler_decimal(texto: str | None) -> Decimal | None:
    """`"1.234,50"`, `"1234,5"`, `"17"` → Decimal. Vazio/lixo → None."""
    if texto is None:
        return None
    t = str(texto).strip().replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def normalizar_ncm(texto: str) -> str:
    """Só os dígitos: `"8467.29.92"` → `"84672992"`."""
    return re.sub(r"\D", "", texto or "")


def formatar_ncm(texto: str) -> str:
    """`"84672992"` → `"8467.29.92"`, como o ME mostra no campo."""
    d = normalizar_ncm(texto)
    if len(d) != 8:
        raise ValueError(f"NCM precisa de 8 dígitos, veio {texto!r}")
    return f"{d[:4]}.{d[4:6]}.{d[6:]}"


# ---------------------------------------------------------------- impostos
@dataclass(frozen=True)
class Impostos:
    icms: Decimal
    icms_incluso: str
    pis: Decimal
    pis_incluso: str
    cofins: Decimal
    cofins_incluso: str

    def como_campos(self) -> dict[str, str]:
        return {
            "icms": formatar_decimal(self.icms),
            "icms_incluso": self.icms_incluso,
            "pis": formatar_decimal(self.pis),
            "pis_incluso": self.pis_incluso,
            "cofins": formatar_decimal(self.cofins),
            "cofins_incluso": self.cofins_incluso,
        }


def aliquota_icms(origem: int, uf_destino: str) -> Decimal:
    if origem not in ORIGENS_ACEITAS:
        raise RegraDesconhecida(
            f"Origem {origem} não tem regra de ICMS definida (só 0 e 2)."
        )
    uf = (uf_destino or "").strip().upper()
    if uf not in UFS:
        raise RegraDesconhecida(f"UF de destino desconhecida: {uf_destino!r}")
    return Decimal("17") if uf == UF_EMPRESA else Decimal("12")


def impostos(conta: Conta, origem: int, uf_destino: str) -> Impostos:
    icms = aliquota_icms(origem, uf_destino)
    if conta is Conta.VENTURA:
        return Impostos(icms, "sim", Decimal("0.65"), "sim", Decimal("3.00"), "sim")
    if conta is Conta.UNIAO:
        return Impostos(icms, "sim", Decimal("0"), "Isento", Decimal("0"), "Isento")
    raise RegraDesconhecida(f"Conta desconhecida: {conta!r}")


# ------------------------------------------------------------------- datas
def data_entrega(prazo_dias: int, hoje: date) -> date:
    """Hoje + prazo em dias corridos; se cair em dia não útil, o próximo útil."""
    if prazo_dias < 1:
        raise ValueError("Prazo precisa ser de pelo menos 1 dia.")
    return proximo_dia_util(hoje + timedelta(days=prazo_dias))


def validade_proposta(dias: int, hoje: date) -> date:
    if dias < 1:
        raise ValueError("Validade precisa ser de pelo menos 1 dia.")
    return hoje + timedelta(days=dias)


# ---------------------------------------- o que o comprador escreveu no item
@dataclass(frozen=True)
class PedidoDoComprador:
    """O que dá para tirar dos "Campos Adicionais" do item."""

    uf_destino: str | None = None
    origem: int | None = None
    data_remessa: date | None = None


_RE_UF = re.compile(
    r"End\.?\s*entrega:.*?-\s*([A-Z]{2})\s*-\s*\d{5}-?\d{3}", re.IGNORECASE | re.DOTALL
)
_RE_ORIGEM = re.compile(r"Origem\s+do\s+Material:\s*(\d)", re.IGNORECASE)
_RE_REMESSA = re.compile(r"Data\s+de\s+Remessa:\s*(\d{2})[./](\d{2})[./](\d{4})", re.IGNORECASE)


def ler_campos_adicionais(texto: str) -> PedidoDoComprador:
    t = " ".join((texto or "").split())
    uf = m.group(1).upper() if (m := _RE_UF.search(t)) else None
    origem = int(m.group(1)) if (m := _RE_ORIGEM.search(t)) else None
    remessa = None
    if m := _RE_REMESSA.search(t):
        try:
            remessa = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            remessa = None
    return PedidoDoComprador(uf if uf in UFS else None, origem, remessa)


# ------------------------------------------------- o que o usuário preenche
@dataclass
class EntradaItem:
    numero: int
    preco: str = ""
    ncm: str = ""
    prazo_dias: int | None = None
    marca: str = ""
    obs: str = ""
    origem: int | None = None
    pedido: PedidoDoComprador = field(default_factory=PedidoDoComprador)

    @property
    def sem_cotacao(self) -> bool:
        return not (self.preco or "").strip()


@dataclass
class Resultado:
    erros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def pode_salvar(self) -> bool:
        return not self.erros


def campos_do_item(conta: Conta, item: EntradaItem, hoje: date) -> dict[str, str]:
    """Tudo o que o robô vai digitar no item, já no formato do ME.

    Só chamar depois de `validar` sem erros: aqui uma regra desconhecida
    explode em vez de virar aviso."""
    uf = item.pedido.uf_destino
    campos = dict(CAMPOS_FIXOS_ITEM)
    campos.update(impostos(conta, item.origem, uf).como_campos())
    campos.update(
        {
            "preco": formatar_decimal(ler_decimal(item.preco)),
            "ncm": formatar_ncm(item.ncm),
            "prazo_dias": str(item.prazo_dias),
            "data_entrega": data_entrega(item.prazo_dias, hoje).strftime("%d/%m/%Y"),
            "marca": item.marca.strip(),
            "obs": item.obs.strip(),
            "origem": str(item.origem),
        }
    )
    return campos


def validar_item(item: EntradaItem, hoje: date) -> Resultado:
    r = Resultado()
    n = f"Item {item.numero}"

    if item.sem_cotacao:
        if not item.obs.strip():
            r.erros.append(f"{n}: sem preço — escreva na observação por que não será cotado.")
        return r

    preco = ler_decimal(item.preco)
    if preco is None or preco <= 0:
        r.erros.append(f"{n}: preço inválido ({item.preco!r}).")

    if len(normalizar_ncm(item.ncm)) != 8:
        r.erros.append(f"{n}: NCM precisa ter 8 dígitos ({item.ncm!r}).")

    if item.prazo_dias is None or item.prazo_dias < 1:
        r.erros.append(f"{n}: prazo de entrega obrigatório (dias corridos).")

    if item.origem is None:
        r.erros.append(f"{n}: origem da mercadoria obrigatória.")
    elif item.origem not in ORIGENS_ACEITAS:
        r.erros.append(f"{n}: origem {item.origem} sem regra de ICMS (só 0 e 2).")

    if item.pedido.uf_destino is None:
        r.erros.append(f"{n}: não achei a UF de entrega na cotação — ICMS indefinido.")

    if not item.marca.strip():
        r.avisos.append(f"{n}: fabricante/marca em branco.")

    if item.pedido.origem is not None and item.origem is not None and item.pedido.origem != item.origem:
        r.avisos.append(
            f"{n}: comprador pediu origem {item.pedido.origem}, preenchida {item.origem}."
        )

    if item.prazo_dias and item.prazo_dias >= 1 and item.pedido.data_remessa:
        entrega = data_entrega(item.prazo_dias, hoje)
        if entrega > item.pedido.data_remessa:
            r.avisos.append(
                f"{n}: entrega em {entrega:%d/%m/%Y}, depois da data de remessa "
                f"pedida ({item.pedido.data_remessa:%d/%m/%Y})."
            )
    return r


def validar_cotacao(itens: list[EntradaItem], validade_dias: int | None, hoje: date) -> Resultado:
    r = Resultado()
    if not validade_dias or validade_dias < 1:
        r.erros.append("Validade da proposta obrigatória (em dias).")
    if not itens or all(i.sem_cotacao for i in itens):
        r.erros.append("Nenhum item com preço — não há o que salvar.")
    for item in itens:
        ri = validar_item(item, hoje)
        r.erros += ri.erros
        r.avisos += ri.avisos
    return r


# ---------------------------------------------- conferência pós-salvamento
def _igual(esperado: str, lido: str) -> bool:
    a, b = ler_decimal(esperado), ler_decimal(lido)
    if a is not None and b is not None:  # "17,00" == "17"
        return a == b
    return " ".join(esperado.split()).casefold() == " ".join((lido or "").split()).casefold()


def conferir(esperado: dict[str, str], lido: dict[str, str]) -> list[str]:
    """Campo a campo: o que foi digitado × o que o ME gravou. Lista vazia = ok."""
    divergencias = []
    for campo, valor in esperado.items():
        if campo not in lido:
            divergencias.append(f"{campo}: não encontrado na página relida")
        elif not _igual(valor, lido[campo]):
            divergencias.append(f"{campo}: enviado {valor!r}, gravado {lido[campo]!r}")
    return divergencias
