"""Modelo central de carga. Independente de qualquer transportadora."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import (BaseModel, ConfigDict, Field, computed_field,
                      field_validator)

CM3_POR_M3 = 1_000_000


# --------------------------------------------------------------------- CNPJ
def limpa_doc(v: str) -> str:
    return "".join(c for c in v if c.isdigit())


def cnpj_valido(cnpj: str) -> bool:
    """Validação mod-11 do CNPJ."""
    n = limpa_doc(cnpj)
    if len(n) != 14 or n == n[0] * 14:
        return False
    for tam, pesos in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
                       (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        soma = sum(int(d) * p for d, p in zip(n[:tam], pesos))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if int(n[tam]) != dv:
            return False
    return True


def formata_cnpj(cnpj: str) -> str:
    n = limpa_doc(cnpj)
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"


# -------------------------------------------------------------------- enums
class Servico(str, Enum):
    FRACIONADO_LTL = "fracionado_ltl"
    LOTACAO_FTL = "lotacao_ftl"


class TipoFrete(str, Enum):
    """Quem paga o frete. Uma escolha, duas consequências.

    CIF  o REMETENTE paga     — a carga sai daqui e a Ventura banca
    FOB  o DESTINATÁRIO paga  — quem recebe é quem acerta com a transportadora

    Substituiu o campo "CNPJ de quem paga", digitado à parte. Os dois podiam
    discordar, e discordavam: o formulário mandava um CNPJ da Ventura como
    pagador (CIF) enquanto a Camilo recebia tp_frete=2 (FOB), fixo no código.
    Derivando o pagador da escolha, a contradição deixa de ser possível."""

    CIF = "cif"
    FOB = "fob"


class StatusCotacao(str, Enum):
    RASCUNHO = "rascunho"
    VALIDANDO = "validando"
    ENVIANDO = "enviando"
    SOLICITACAO_ENVIADA = "solicitacao_enviada"
    AGUARDANDO_RETORNO = "aguardando_retorno"
    COTADO = "cotado"
    RECUSADO = "recusado"
    INTERVENCAO_NECESSARIA = "intervencao_necessaria"
    ERRO = "erro"
    CANCELADO = "cancelado"


# ---------------------------------------------------------------- entidades
class Volume(BaseModel):
    """Um grupo de volumes idênticos. qtd=3 significa 3 caixas iguais."""

    qtd: Annotated[int, Field(ge=1)]
    comprimento_cm: Annotated[Decimal, Field(gt=0)]
    largura_cm: Annotated[Decimal, Field(gt=0)]
    altura_cm: Annotated[Decimal, Field(gt=0)]
    peso_kg: Annotated[Decimal, Field(gt=0)]  # peso UNITÁRIO
    descricao: str | None = None

    @computed_field
    @property
    def dimensoes(self) -> tuple[Decimal, Decimal, Decimal]:
        return (self.comprimento_cm, self.largura_cm, self.altura_cm)

    @computed_field
    @property
    def peso_total_kg(self) -> Decimal:
        return self.peso_kg * self.qtd

    @computed_field
    @property
    def cubagem_m3(self) -> Decimal:
        vol = self.comprimento_cm * self.largura_cm * self.altura_cm * self.qtd
        return vol / Decimal(CM3_POR_M3)


class Parte(BaseModel):
    cnpj: str
    razao_social: str | None = None
    inscricao_estadual: str | None = None

    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, v: str) -> str:
        if not cnpj_valido(v):
            raise ValueError(f"CNPJ inválido: {v}")
        return limpa_doc(v)

    @property
    def cnpj_formatado(self) -> str:
        return formata_cnpj(self.cnpj)


class Local(BaseModel):
    uf: Annotated[str, Field(min_length=2, max_length=2)]
    cidade: str
    codigo_ibge: str | None = None
    cep: str | None = None

    @field_validator("uf")
    @classmethod
    def _uf(cls, v: str) -> str:
        return v.upper()


class Solicitante(BaseModel):
    nome: str
    email: str
    whatsapp: str

    @property
    def whatsapp_formatado(self) -> str:
        n = limpa_doc(self.whatsapp)

        # Tira o +55. Os campos de telefone dos sites têm máscara brasileira,
        # de 10 ou 11 dígitos: mandar '+55 (27) 3063-1564' fez o formulário da
        # Della Volpe exibir '(55) 2730-631' — o código do país virou DDD e o
        # número escorregou inteiro. Medido em 13/08/2026.
        # Só corta quando sobra um número brasileiro válido, para não estragar
        # o DDD 55 (Santa Maria/RS), que tem 10 ou 11 dígitos no total.
        if len(n) in (12, 13) and n.startswith("55"):
            n = n[2:]

        if len(n) == 11:
            return f"({n[:2]}) {n[2:7]}-{n[7:]}"
        if len(n) == 10:
            return f"({n[:2]}) {n[2:6]}-{n[6:]}"
        return self.whatsapp


class Mercadoria(BaseModel):
    tipo_material: str
    is_perigoso: bool = False
    fispq_path: str | None = None


class NotaFiscal(BaseModel):
    valor_total: Annotated[Decimal, Field(gt=0)]
    numero: str | None = None


# ----------------------------------------------------------------- request
class CotacaoRequest(BaseModel):
    # extra="forbid" de propósito: `pagador_frete` era um campo e virou
    # propriedade. Sem isto, quem continuasse passando pagador_frete=... teria
    # o valor silenciosamente ignorado e cotaria com outro pagador sem saber.
    model_config = ConfigDict(extra="forbid")

    solicitante: Solicitante
    servico: Servico
    origem: Local
    destino: Local
    remetente: Parte
    destinatario: Parte
    tipo_frete: TipoFrete = TipoFrete.CIF
    volumes: Annotated[list[Volume], Field(min_length=1)]
    mercadoria: Mercadoria
    nota_fiscal: NotaFiscal
    veiculo_desejado: str | None = None
    observacoes: str | None = None

    # -------------------------------------------------- campos derivados
    @computed_field
    @property
    def peso_total_kg(self) -> Decimal:
        return sum((v.peso_total_kg for v in self.volumes), Decimal(0))

    @computed_field
    @property
    def quantidade_volumes(self) -> int:
        return sum(v.qtd for v in self.volumes)

    @computed_field
    @property
    def cubagem_m3(self) -> Decimal:
        return sum((v.cubagem_m3 for v in self.volumes), Decimal(0))

    @computed_field
    @property
    def tem_medidas_distintas(self) -> bool:
        return len({v.dimensoes for v in self.volumes}) > 1

    @property
    def pagador_frete(self) -> Parte:
        """DERIVADO do tipo de frete, nunca digitado. Ver TipoFrete."""
        return (self.remetente if self.tipo_frete is TipoFrete.CIF
                else self.destinatario)

    @property
    def maior_volume(self) -> Volume:
        return max(self.volumes, key=lambda v: v.comprimento_cm * v.largura_cm * v.altura_cm)

    def peso_cubado_kg(self, fator: Decimal) -> Decimal:
        """Peso cubado depende do fator DA TRANSPORTADORA (300, 250, 167...)."""
        return self.cubagem_m3 * fator
