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


MAX_JUSTIFICATIVA = 200  # maxlength do txtJustificativaRecusa_N no ME


class PlanoInvalido(ValueError):
    """Entrada que o ME recusaria (ou que a empresa nunca definiu)."""


@dataclass
class PlanoPagina:
    campos: dict[str, str]
    marcar: list[int]  # índices com chkItem_N marcado (itens respondidos)
    avisos: list[str] = field(default_factory=list)
    # índice → justificativa: itens sem preço, recusados pelo "Deseja Recusar
    # o Item?" do ME (decisão do usuário, 24/09/2026). É só um estado da
    # página; vai no MESMO POST do Salvar (Acao=9), nunca sozinho.
    recusar: dict[int, str] = field(default_factory=dict)


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

    Item fora da lista do usuário fica TOTALMENTE vazio: o ME traz
    BaseCalculo=100,00 e trata isso como item começado.

    Item sem preço (com a observação explicando, que `regras` exige) é
    RECUSADO no ME com essa observação como justificativa — o "Deseja Recusar
    o Item?" do próprio ME. O ME limpa e trava os campos dele; o robô não
    digita nada neles."""
    if not validade_dias or validade_dias < 1:
        raise PlanoInvalido("Validade da proposta obrigatória (em dias).")
    erros, avisos = [], []
    campos: dict[str, str] = {}
    marcar: list[int] = []
    recusar: dict[int, str] = {}
    for indice, item in sorted(itens.items()):
        if item is None:
            campos[f"BaseCalculo{indice}"] = ""
            continue
        if item.sem_cotacao:
            r = R.validar_item(item, hoje)
            erros += r.erros
            justificativa = " ".join(item.obs.split())
            if len(justificativa) > MAX_JUSTIFICATIVA:
                erros.append(f"Item {item.numero}: justificativa da recusa passa de "
                             f"{MAX_JUSTIFICATIVA} caracteres (limite do ME).")
            elif justificativa:
                recusar[indice] = justificativa
                campos[f"txtJustificativaRecusa_{indice}"] = justificativa
            continue
        r = R.validar_item(item, hoje)
        erros += r.erros
        avisos += r.avisos
        if not r.erros:
            campos.update(campos_item(conta, item, indice, hoje))
            marcar.append(indice)
    if recusar and len(recusar) == len(itens) and not marcar:
        # Recusar todos os itens faz o ME perguntar "Você está recusando todos
        # os itens..." e, aceito, virar RECUSA DA COTAÇÃO (RespCotaGrava.asp,
        # vai ao comprador). A trava já cancela esse confirm e bloqueia a URL;
        # isto aqui nem deixa chegar lá.
        erros.append("Todos os itens da página sem preço: recusar tudo seria recusar a "
                     "cotação inteira — isso é com um humano, pelo site do ME.")
    if erros:
        raise PlanoInvalido(" | ".join(erros))
    return PlanoPagina({**campos_cabecalho(validade_dias, hoje, obs_geral.strip()), **campos},
                       marcar, avisos, recusar)
