"""Das regras para o formulário do ME — camada PURA, sem navegador.

`regras` fala a língua do negócio ("icms_incluso": "sim"); o formulário do
ME quer `ICMSIncluso{N}` = "S". Aqui mora essa tradução, com os nomes e
códigos que o ME aceitou e devolveu iguais no teste real de Salvar
(23/09/2026). O índice N é a posição do item NA PÁGINA (recomeça em 1 a
cada página de 10), não o número do item ("110.").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from mercado_eletronico import regras as R
from mercado_eletronico.regras import Conta, EntradaItem

# chave de regras.campos_do_item → name do campo no ME (sem o índice)
NOMES_ITEM = {
    "preco": "Preco", "unidade": "UnidadeResp", "tipo_imposto": "TipoImposto",
    "ipi": "IPI", "ipi_incluso": "IPIIncluso", "icms": "ICMS", "icms_incluso": "ICMSIncluso",
    "pis": "PIS", "pis_incluso": "PISIncluso", "cofins": "COFINS",
    "cofins_incluso": "COFINSIncluso", "ncm": "NCM", "prazo_dias": "Prazo",
    "data_entrega": "DataEntregaItemAux", "marca": "Fabricante", "obs": "Observacao",
    "origem": "OrigMat", "substituicao_tributaria": "SubstituicaoTributaria",
    "aliquota_st": "AliquotaSubstituicaoTributaria", "valor_st": "ValorSubstituicaoTributaria",
    "base_calculo_icms": "BaseCalculo", "base_calculo_icms_ipi": "BaseCalculoImposto",
}

# valor de negócio → value da <option> no ME
CODIGOS = {
    "unidade": {"UNIDADE": "UN"},
    "tipo_imposto": {"IPI": "1"},
    "origem": {"0": "992", "2": "994"},
    "substituicao_tributaria": {"NÃO": "N"},
    "base_calculo_icms_ipi": {"sem IPI": "S"},
}
_INCLUSO = {"sim": "S", "isento": "I", "não": "N"}
_DECIMAIS = ("ipi",)  # regras manda "0"; o ME mostra "0,00"

CABECALHO_FIXO = {
    "IcoTerms": "FOB",
    "atrib_CidadeEstado_1_1_0_0": R.CAMPOS_FIXOS_COTACAO["frete"],
    "CondicaoPagamento": "F060",  # 60DDL
    "NumFoneCota": R.CAMPOS_FIXOS_COTACAO["telefone_contato"],
    "MoedaCot": "BRL",
}


class PlanoInvalido(ValueError):
    """Entrada que o ME recusaria (ou que a empresa nunca definiu)."""


@dataclass
class PlanoPagina:
    campos: dict[str, str]
    marcar: list[int]  # índices com chkItem_N marcado (itens respondidos)
    avisos: list[str] = field(default_factory=list)


def _codigo(chave: str, valor: str) -> str:
    if chave.endswith("_incluso"):
        return _INCLUSO[valor.casefold()]
    if chave in CODIGOS:
        return CODIGOS[chave][valor]
    if chave in _DECIMAIS:
        return R.formatar_decimal(R.ler_decimal(valor))
    return valor


def campos_item(conta: Conta, item: EntradaItem, indice: int, hoje: date) -> dict[str, str]:
    """Campos do item no formato do ME, no índice da página."""
    negocio = R.campos_do_item(conta, item, hoje)
    return {f"{NOMES_ITEM[k]}{indice}": _codigo(k, v) for k, v in negocio.items()}


def campos_cabecalho(validade_dias: int, hoje: date, obs: str) -> dict[str, str]:
    validade = R.validade_proposta(validade_dias, hoje)
    return {**CABECALHO_FIXO, "ValidadePropostaAux": validade.strftime("%d/%m/%Y"),
            "ObsForn": obs}


def plano_pagina(conta: Conta, itens: dict[int, EntradaItem | None],
                 validade_dias: int | None, hoje: date, obs_geral: str = "") -> PlanoPagina:
    """Tudo o que o robô digita numa página. `itens`: índice → entrada (None = não responder).

    Item sem resposta fica TOTALMENTE vazio: o ME traz BaseCalculo=100,00 e
    trata isso como item começado. A justificativa de item sem preço vai para
    a observação geral (o campo do item também contaria como começado)."""
    if not validade_dias or validade_dias < 1:
        raise PlanoInvalido("Validade da proposta obrigatória (em dias).")
    erros, avisos, justificativas = [], [], []
    campos: dict[str, str] = {}
    marcar: list[int] = []
    for indice, item in sorted(itens.items()):
        if item is None or item.sem_cotacao:
            campos[f"BaseCalculo{indice}"] = ""
            if item is not None:
                r = R.validar_item(item, hoje)
                erros += r.erros
                if item.obs.strip():
                    justificativas.append(f"Item {item.numero}: {item.obs.strip()}")
            continue
        r = R.validar_item(item, hoje)
        erros += r.erros
        avisos += r.avisos
        if not r.erros:
            campos.update(campos_item(conta, item, indice, hoje))
            marcar.append(indice)
    if erros:
        raise PlanoInvalido(" | ".join(erros))
    obs = "\n".join(filter(None, [obs_geral.strip(), *justificativas]))
    return PlanoPagina({**campos_cabecalho(validade_dias, hoje, obs), **campos}, marcar, avisos)
