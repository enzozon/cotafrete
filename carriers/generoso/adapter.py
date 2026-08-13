"""Transporte Generoso — formulário de cotação em ETAPAS.

    https://cliente.generoso.com.br/cotacao

⚠ A URL divulgada (generoso.com.br/cotacao) é 404; a página de erro é que
aponta para a área do cliente.

Cinco etapas, cada uma só libera a seguinte:
    1. Solicitante   e-mail, CNPJ, nome, WhatsApp
    2. Tipo pagador  select; com FOB o CNPJ do destinatário fica travado
    3. Origem        CNPJ do remetente preenche o endereço inteiro
    4. Destino       CNPJ travado; o endereço precisa ser destravado pelo CEP
    5. Carga         valor da NF, medidas, peso, quantidade

Assíncrono como a Della Volpe: a tela final só confirma o recebimento
("Recebemos seu pedido de cotação"), o preço vem por e-mail depois.

TRÊS REGRAS MEDIDAS NO SITE em 13/08/2026 — sem elas a cotação sai errada e
sem nenhum aviso na tela:

1. Na ORIGEM, não digitar o CEP. O CNPJ do remetente traz CEP, cidade,
   bairro, rua, número e complemento do cadastro da empresa. Digitar o CEP
   por cima troca tudo pelo endereço genérico daquele CEP — para o CNPJ
   60.042.686/0001-05 o cadastro é Santo André/Vila Metalúrgica e o CEP
   resolve para São Bernardo do Campo/Planalto. Cidade diferente, frete
   diferente.

2. No DESTINO é o oposto. O CNPJ vem travado e traz só o CEP; cidade,
   estado, bairro e rua ficam vazios. Redisparar o CEP preenche — e aqui
   pode, porque não há endereço bom para perder.

3. O campo de peso tem máscara de 2 casas, da direita para a esquerda:
   "1" vira 0.01 e "100" vira 1.00. Sempre 2 casas.

E a busca do site só acorda com digitação: `fill()` instantâneo não dispara.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from carriers.base import (
    CampoSpec, ErroValidacao, Modo, ResultadoCotacao, Severidade,
)
from core.models import CotacaoRequest, StatusCotacao

URL = "https://cliente.generoso.com.br/cotacao"

TIPO_PAGADOR_DESTINATARIO = "Destinatario (FOB)"
TIPO_PAGADOR_REMETENTE = "Remetente (CIF)"

BOTAO_PROXIMO = "Próximo"
BOTAO_CONFIRMAR = "Confirmar e ver resultado"

# Frases da tela final, medidas no site.
FRASES_CONFIRMACAO = (
    "recebemos seu pedido de cota",
    "entraremos em contato",
)

# Digitação humana: a busca de CNPJ/CEP do site não dispara com fill().
DELAY_DIGITACAO_MS = 60
ESPERA_BUSCA_MS = 4_500


def ler_resultado(texto: str) -> bool:
    """True se a tela confirma o recebimento da cotação."""
    t = (texto or "").lower()
    return any(f in t for f in FRASES_CONFIRMACAO)


def _inteiro(v: Decimal) -> str:
    """Medida em cm, sem casa decimal — o campo não tem máscara."""
    return str(int(v))


def _duas_casas(v: Decimal) -> str:
    """Peso e dinheiro: 2 casas com vírgula, pela máscara do campo."""
    return f"{v:.2f}".replace(".", ",")


class GenerosoAdapter:
    slug = "generoso"
    nome = "Transporte Generoso"
    modo: Modo = Modo.ASSINCRONO_LENTO      # preço volta por e-mail
    ativo = True
    fator_cubagem: Decimal = Decimal(300)   # ⚠ presumido; não confirmado ainda
    sla_esperado_min: int | None = None

    def __init__(self, headless: bool = True, timeout_ms: int = 45_000,
                 workdir: str = "teste_real/generoso",
                 tipo_pagador: str = TIPO_PAGADOR_DESTINATARIO) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.workdir = Path(workdir)
        self.tipo_pagador = tipo_pagador

    # ------------------------------------------------------- camada pura
    def campos_obrigatorios(self, req: CotacaoRequest) -> list[CampoSpec]:
        return [
            CampoSpec("E-mail", True, "email"),
            CampoSpec("CNPJ do solicitante", True, "text"),
            CampoSpec("Nome", True, "text"),
            CampoSpec("WhatsApp", True, "tel"),
            CampoSpec("CNPJ do remetente", True, "text"),
            CampoSpec("Valor total da nota fiscal", True, "text"),
            CampoSpec("Altura", True, "text"),
            CampoSpec("Largura", True, "text"),
            CampoSpec("Comprimento", True, "text"),
            CampoSpec("Peso unitário", True, "text"),
            CampoSpec("Quantidade", True, "text"),
        ]

    def validar(self, req: CotacaoRequest) -> list[ErroValidacao]:
        erros: list[ErroValidacao] = []
        if not req.solicitante.whatsapp:
            erros.append(ErroValidacao("whatsapp", "O site exige WhatsApp."))
        v = req.volumes[0]
        if v.peso_kg <= 0:
            erros.append(ErroValidacao("peso_kg",
                                       "Peso precisa ser maior que zero."))
        for rotulo, medida in (("comprimento", v.comprimento_cm),
                               ("largura", v.largura_cm),
                               ("altura", v.altura_cm)):
            if medida != medida.to_integral_value():
                erros.append(ErroValidacao(
                    rotulo,
                    f"O campo aceita centímetros inteiros; veio {medida}.",
                    Severidade.AVISO))
        return erros

    def preparar_payload(self, req: CotacaoRequest) -> dict[str, Any]:
        """Ficha -> campos do formulário. Endereços NÃO entram: vêm do CNPJ."""
        v = req.volumes[0]
        return {
            # etapa 1
            "email": req.solicitante.email,
            "cnpj_solicitante": req.pagador_frete.cnpj_formatado,
            "nome": req.solicitante.nome,
            "whatsapp": req.solicitante.whatsapp_formatado,
            # etapa 2
            "tipo_pagador": self.tipo_pagador,
            # etapa 3 — o endereço inteiro sai deste CNPJ
            "cnpj_remetente": req.remetente.cnpj_formatado,
            # etapa 5
            "valor_nf": _duas_casas(req.nota_fiscal.valor_total),
            "altura": _inteiro(v.altura_cm),
            "largura": _inteiro(v.largura_cm),
            "comprimento": _inteiro(v.comprimento_cm),
            "peso": _duas_casas(v.peso_kg),      # unitário; o site soma
            "quantidade": str(v.qtd),
        }

    def normalizar_resposta(self, raw: Any) -> ResultadoCotacao:
        texto = str(raw or "")
        if not ler_resultado(texto):
            return ResultadoCotacao(
                self.slug, StatusCotacao.ERRO, raw_response=texto[:800],
                erro="Confirmação de recebimento não apareceu na tela.")
        return ResultadoCotacao(
            transportadora=self.slug,
            status=StatusCotacao.AGUARDANDO_RETORNO,
            valor_frete=None,        # correto: o preço vem por e-mail
            raw_response=texto[:800],
        )
