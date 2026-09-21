"""O prazo que a transportadora respondeu precisa CHEGAR no banco.

A coluna `resultado.prazo` existe desde o primeiro esquema e a tela desenha
a coluna "Prazo" desde 10/09/2026 — mas `_rodar` nunca passou o valor adiante.
Resultado medido no banco de produção em 21/09/2026: 414 linhas de resultado,
ZERO com prazo. A coluna da tela nascia vazia em toda cotação, para todas as
transportadoras, e ninguém tinha como notar olhando só a tela: "sem prazo" e
"prazo não gravado" se parecem iguais.

O adapter já fazia a parte dele: `ResultadoCotacao.prazo_dias` vem
preenchido da Generoso (datas da tela) e da Braspress desde sempre. O buraco
era um argumento de uma linha entre o adapter e o INSERT.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from carriers.base import ResultadoCotacao
from core.banco import Banco
from core.models import StatusCotacao

from tests.test_web_cotacao import CARGA


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    monkeypatch.setattr(modulo, "TENTATIVAS_EM_CURSO", {})
    return modulo


def _prazo_no_banco(app_web, cotacao_id: int, slug: str):
    c = app_web.banco.buscar_cotacao(cotacao_id, "enzo")
    return next(r["prazo"] for r in c["resultados"]
                if r["transportadora"] == slug)


def test_prazo_respondido_chega_no_banco(app_web):
    """O caso que estava quebrado: adapter devolve prazo, banco fica NULL."""
    cotacao_id = app_web.banco.salvar_cotacao("enzo", CARGA)

    app_web._rodar(cotacao_id, "generoso", lambda req: ResultadoCotacao(
        "generoso", StatusCotacao.COTADO, valor_frete=Decimal("152.16"),
        prazo_dias=6), req=None)

    assert _prazo_no_banco(app_web, cotacao_id, "generoso") == "6"


def test_sem_prazo_continua_nulo(app_web):
    """Nem toda transportadora responde prazo. Ausência não vira "0 dias"."""
    cotacao_id = app_web.banco.salvar_cotacao("enzo", CARGA)

    app_web._rodar(cotacao_id, "camilo", lambda req: ResultadoCotacao(
        "camilo", StatusCotacao.COTADO, valor_frete=Decimal("74.10")),
        req=None)

    assert _prazo_no_banco(app_web, cotacao_id, "camilo") is None


def test_prazo_zero_e_um_prazo(app_web):
    """Entrega no mesmo dia é 0 — e 0 é falso em Python.

    Escrito de propósito: a correção mais natural (`if res.prazo_dias`)
    jogaria fora justamente o prazo mais vendedor que existe."""
    cotacao_id = app_web.banco.salvar_cotacao("enzo", CARGA)

    app_web._rodar(cotacao_id, "jadlog", lambda req: ResultadoCotacao(
        "jadlog", StatusCotacao.COTADO, valor_frete=Decimal("30.00"),
        prazo_dias=0), req=None)

    assert _prazo_no_banco(app_web, cotacao_id, "jadlog") == "0"


# --------------------------------------------------------------- validade
# Mesma historia do prazo, um degrau adiante: o adapter da Generoso passou a
# ler "Cotacao valida ate" da tela, e esse valor precisa CHEGAR no banco.
# Uma coluna que ninguem preenche e pior que coluna nenhuma — ela faz a tela
# dizer "sem validade" com a mesma cara de "ainda da tempo".
def test_validade_respondida_chega_no_banco(app_web):
    from datetime import date

    cotacao_id = app_web.banco.salvar_cotacao("enzo", CARGA)

    app_web._rodar(cotacao_id, "generoso", lambda req: ResultadoCotacao(
        "generoso", StatusCotacao.COTADO, valor_frete=Decimal("152.16"),
        validade=date(2026, 9, 28)), req=None)

    c = app_web.banco.buscar_cotacao(cotacao_id, "enzo")
    assert c["resultados"][0]["validade"] == date(2026, 9, 28)


def test_transportadora_que_nao_diz_validade_fica_sem(app_web):
    """Cinco das seis nao informam. Ausencia nao vira data nenhuma."""
    cotacao_id = app_web.banco.salvar_cotacao("enzo", CARGA)

    app_web._rodar(cotacao_id, "camilo", lambda req: ResultadoCotacao(
        "camilo", StatusCotacao.COTADO, valor_frete=Decimal("74.10")),
        req=None)

    c = app_web.banco.buscar_cotacao(cotacao_id, "enzo")
    assert c["resultados"][0]["validade"] is None
