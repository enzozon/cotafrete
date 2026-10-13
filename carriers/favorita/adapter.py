"""Favorita Transportes — o MESMO portal da Generoso, com outra conta.

    https://cliente.favorita.com.br/cotacao

Medido em 13/10/2026 por recon/recon_favorita.py, logado: login em /login com
`email`/`password`, quatro etapas (tipo pagador, origem travada no CNPJ da
conta, destino pelo CNPJ, carga), os mesmos `name=` em todos os campos, a
mesma máscara de peso (type "100" -> "1.00") e os mesmos cards de embalagem.
Por isso a Favorita não tem mecânica própria: herda tudo de GenerosoAdapter
e troca só o que é da conta. Se um dia o portal dela divergir, é aqui que o
método sobrescrito entra — não numa cópia das 1.200 linhas.

A diferença que importa: o "Alterar empresa" da conta da Favorita só tem a
VENTURA (o outro item é "Adicionar empresa"). Aliança e União não existem
lá, então elas não contam como "grupo": uma cotação com a Aliança na ponta
travada é barrada por `ponta_travada_sem_o_grupo`, em vez de sair com o
endereço da Ventura no lugar.
"""

from __future__ import annotations

import threading
from decimal import Decimal

from carriers.generoso.adapter import GenerosoAdapter
from carriers.generoso.mapping import Empresa

# Como o menu da conta escreve, medido no recon. O CNPJ é o que manda.
EMPRESAS = (
    Empresa("08.310.365/0001-24",
            "Ventura Comercio Varejista de Tecnologia Ltda"),
)


class FavoritaAdapter(GenerosoAdapter):
    slug = "favorita"
    nome = "Favorita Transportes"
    nome_curto = "Favorita"
    url_base = "https://cliente.favorita.com.br"
    prefixo_env = "FAVORITA"
    empresas = EMPRESAS
    # O link de unidades parceiras é da Generoso (Rodonaves). Não há um
    # equivalente medido para a Favorita — melhor nenhum que o de outra.
    link_unidades = None
    # Conta própria, trava própria: cotar Favorita e Generoso ao mesmo
    # tempo não mexe na empresa ativa de ninguém.
    trava_conta = threading.Lock()
    fator_cubagem: Decimal = Decimal(300)   # ⚠ presumido, como na Generoso

    def __init__(self, workdir: str = "teste_real/favorita", **kw) -> None:
        super().__init__(workdir=workdir, **kw)

    def agendar_coleta(self, *args, **kwargs):
        """Não medido na Favorita: o herdado abriria a tela da Generoso.
        Falhar alto é melhor que pedir coleta no portal errado."""
        raise NotImplementedError(
            "o agendamento de coleta da Favorita ainda não foi levantado")
