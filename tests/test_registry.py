"""Testes do fan-out. Adapters falsos em memória — nada de browser nem rede.

O registry era o único módulo em 0% de cobertura, e é onde mora a promessa de
que a falha de uma transportadora não derruba as outras.
"""

from __future__ import annotations

from decimal import Decimal

from carriers.base import ResultadoCotacao
from carriers.registry import cotar_em_todas, formatar_comparativo
from core.models import StatusCotacao
from tests.test_jadlog import montar


class AdapterFalso:
    def __init__(self, slug: str, resultado=None, excecao=None):
        self.slug = slug
        self._resultado = resultado
        self._excecao = excecao

    def cotar(self, req):
        if self._excecao:
            raise self._excecao
        return self._resultado


def cotado(slug: str, valor, prazo: int = 3) -> AdapterFalso:
    return AdapterFalso(slug, ResultadoCotacao(
        slug, StatusCotacao.COTADO, valor_frete=valor, prazo_dias=prazo))


# ------------------------------------------------------ isolamento de falha
def test_excecao_em_um_adapter_nao_derruba_os_outros():
    adapters = [
        AdapterFalso("explode", excecao=RuntimeError("browser morreu")),
        cotado("jadlog", Decimal("120.00")),
    ]
    res = cotar_em_todas(montar(), adapters)

    assert len(res) == 2
    ok = [r for r in res if r.status is StatusCotacao.COTADO]
    falhou = [r for r in res if r.status is StatusCotacao.ERRO]
    assert [r.transportadora for r in ok] == ["jadlog"]
    assert "RuntimeError: browser morreu" in falhou[0].erro


# ---------------------------------------------------------------- ordenação
def test_frete_zero_e_o_mais_barato_nao_o_ultimo():
    """`r.valor_frete or float('inf')` manda zero para o fim da fila.

    Frete bonificado é a melhor cotação possível; ordenar como se fosse
    infinito esconde exatamente a opção que o cliente deveria ver primeiro."""
    adapters = [cotado("cara", Decimal("300.00")),
                cotado("gratis", Decimal(0)),
                cotado("media", Decimal("150.00"))]

    res = cotar_em_todas(montar(), adapters)

    assert [r.transportadora for r in res] == ["gratis", "media", "cara"]


def test_cotado_vem_antes_de_aguardando_retorno():
    """Della Volpe devolve AGUARDANDO_RETORNO sem preço — resposta válida, mas
    não pode empurrar para baixo quem já tem número fechado."""
    espera = AdapterFalso("dellavolpe", ResultadoCotacao(
        "dellavolpe", StatusCotacao.AGUARDANDO_RETORNO))
    res = cotar_em_todas(montar(), [espera, cotado("jadlog", Decimal("90.00"))])

    assert [r.transportadora for r in res] == ["jadlog", "dellavolpe"]


def test_sem_preco_nao_quebra_a_ordenacao():
    """valor_frete=None convive com Decimal na mesma chave de ordenação."""
    res = cotar_em_todas(montar(), [
        AdapterFalso("sem_preco", ResultadoCotacao(
            "sem_preco", StatusCotacao.COTADO, valor_frete=None)),
        cotado("com_preco", Decimal("10.00")),
    ])
    assert res[0].transportadora == "com_preco"


# -------------------------------------------------------------- comparativo
def test_comparativo_mostra_valor_prazo_e_erro():
    req = montar()
    res = [
        ResultadoCotacao("jadlog", StatusCotacao.COTADO,
                         valor_frete=Decimal("120.50"), prazo_dias=5),
        ResultadoCotacao("dellavolpe", StatusCotacao.ERRO, erro="token ausente"),
    ]
    texto = formatar_comparativo(req, res)

    assert "JADLOG" in texto
    assert "120.50" in texto
    assert "Prazo: 5 dias" in texto
    assert "token ausente" in texto
    assert req.origem.cidade in texto
