"""A validade na tabela de resultados.

A tela comparava preço contra prazo e não dizia até quando o preço valia. Era
a informação que a Generoso devolve e o Cotafrete jogava fora — e é ela que
decide se ainda dá para fechar negócio com aquele número.

A coluna é a mesma que vai abrigar o botão "Aceitar": validade e ação moram
juntas de propósito. Separadas, o vendedor lê "vence hoje" num canto da linha
e aperta um botão no outro canto sem ligar uma coisa à outra.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from fastapi.testclient import TestClient

from core.banco import Banco
from tests.apoio import entrar
from tests.test_web_cotacao import CARGA, linha_de


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    monkeypatch.setattr(modulo, "TENTATIVAS_EM_CURSO", {})
    return modulo


@pytest.fixture
def cliente(app_web):
    c = TestClient(app_web.app)
    entrar(c, app_web)
    return c


def _cotacao_com(app_web, *, validade, slug="generoso") -> int:
    """Uma cotação com TODAS as automáticas respondidas.

    Todas, e não só a que interessa: faltando alguma, a tela entra no modo
    "cotando…" e se recarrega sozinha, que é outro estado e outra tela."""
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    for automatica in app_web.AUTOMATICAS:
        app_web.banco.salvar_resultado(
            cid, automatica, status="cotado", valor=Decimal("152.16"),
            validade=validade if automatica == slug else None)
    return cid


def test_cotacao_com_validade_mostra_ate_quando_vale(app_web, cliente):
    daqui_a_uma_semana = date.today() + timedelta(days=7)
    cid = _cotacao_com(app_web, validade=daqui_a_uma_semana)

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "generoso")

    assert f"até {daqui_a_uma_semana:%d/%m}" in linha


def test_ultimo_dia_avisa_que_vence_hoje(app_web, cliente):
    """O dia em que a informação mais vale, e o único em que "até 28/09"
    sozinho não ajudaria ninguém."""
    cid = _cotacao_com(app_web, validade=date.today())

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "generoso")

    assert "vence hoje" in linha


def test_cotacao_vencida_diz_quando_venceu(app_web, cliente):
    ontem = date.today() - timedelta(days=1)
    cid = _cotacao_com(app_web, validade=ontem)

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "generoso")

    assert f"venceu em {ontem:%d/%m}" in linha


def test_transportadora_sem_validade_nao_inventa_nada(app_web, cliente):
    """Cinco das seis não informam. A célula fica vazia — nunca "vence
    hoje" por engano, que mandaria o vendedor correr atrás de um prazo que
    ninguém estabeleceu."""
    cid = _cotacao_com(app_web, validade=date.today() + timedelta(days=7))

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "camilo")

    assert "vence" not in linha
    assert "até " not in linha


def test_a_tabela_tem_cabecalho_para_a_coluna_nova(app_web, cliente):
    """Coluna sem cabeçalho desalinha a tabela inteira: são sete <th> para
    sete <td>, e errar isso joga todo o conteúdo uma casa para o lado."""
    cid = _cotacao_com(app_web, validade=date.today())

    html = cliente.get(f"/cotacao/{cid}").text

    assert "Validade" in html
    cabecalhos = html.count('<th class="r-')
    colunas = linha_de(html, "generoso").count('<td class="r-')
    assert cabecalhos == colunas


def test_linha_sem_preco_nao_promete_validade(app_web, cliente):
    """Transportadora que não cotou não tem preço — e validade é até quando
    um PREÇO vale. Sem preço, não há o que vencer."""
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    for automatica in app_web.AUTOMATICAS:
        app_web.banco.salvar_resultado(cid, automatica, status="erro",
                                       erro="o site não respondeu")

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "generoso")

    assert "vence" not in linha
