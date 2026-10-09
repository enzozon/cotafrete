"""Sugestão 6: resumo da semana no /adm — só números do banco."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from core import resumo_semana as rs
from core.banco import Banco

HOJE = date(2026, 10, 9)


@pytest.fixture
def con(tmp_path):
    Banco(tmp_path / "t.db")
    c = sqlite3.connect(tmp_path / "t.db")
    yield c
    c.close()


def _cotacao(con, quando, destino="Anchieta", resultados=()):
    cid = con.execute(
        "INSERT INTO cotacao (usuario, criado_em, cep_origem, cep_destino, cidade_origem, uf_origem,"
        " cidade_destino, uf_destino, peso_kg, quantidade, comprimento_cm, largura_cm, altura_cm,"
        " valor_nf) VALUES ('enzo', ?, '1', '2', 'Serra', 'ES', ?, 'ES', '10', 1, 1, 1, 1, '1')",
        (quando, destino)).lastrowid
    for slug, valor in resultados:
        con.execute("INSERT INTO resultado (cotacao_id, transportadora, status, valor)"
                    " VALUES (?, ?, ?, ?)", (cid, slug, "cotado" if valor else "erro", valor))


def test_tendencia_rotas_e_sem_preco(con):
    # semana anterior: camilo 2/2 com preço
    _cotacao(con, "2026-09-28T10:00:00", resultados=[("camilo", "10")])
    _cotacao(con, "2026-09-29T10:00:00", resultados=[("camilo", "10")])
    # esta semana: camilo 1/3 → piorou; uma cotação sem preço nenhum
    _cotacao(con, "2026-10-05T10:00:00", resultados=[("camilo", "10")])
    _cotacao(con, "2026-10-08T10:00:00", resultados=[("camilo", None)])
    _cotacao(con, "2026-10-09T18:00:00", destino="Vitória", resultados=[("camilo", None)])
    _cotacao(con, "2026-09-01T10:00:00", resultados=[("camilo", None)])    # fora das duas semanas
    _cotacao(con, "2026-10-09T18:05:00")                                   # ainda cotando

    f = rs.fatos(con, HOJE)

    assert f["cotacoes"] == 4 and f["sem_preco"] == 2
    (t,) = f["transportadoras"]
    assert (t["aproveitamento"], t["antes"], t["pedidos"], t["tendencia"]) == (33, 100, 3, "piorou")
    assert f["rotas"][0] == {"rota": "Serra/ES → Anchieta/ES", "cotacoes": 3}
    texto = rs.linhas(f)
    assert texto[0] == "4 cotações de 03/10 a 09/10; 2 ficaram sem preço nenhum."
    assert "camilo: 33% com preço em 3 pedidos (piorou: era 100% na semana anterior)." in texto


def test_semana_vazia(con):
    assert rs.linhas(rs.fatos(con, HOJE)) == ["Nenhuma cotação nos últimos 7 dias."]


def test_cartao_da_semana_tem_numeros_tabela_tendencia_e_rotas(con):
    from web import painel_ui as ui
    _cotacao(con, "2026-09-28T10:00:00", resultados=[("camilo", "10")])
    _cotacao(con, "2026-10-08T10:00:00", resultados=[("camilo", None), ("jadlog", "5")])

    f = rs.fatos(con, HOJE)
    html = ui.resumo_da_semana(f)

    assert f["aproveitamento_geral"] == 50
    assert "50%</b><span>aproveitamento geral" in html
    assert "▼ piorou -100 p.p." in html and ">novo<" in html
    assert "Rotas mais cotadas" in html and "Serra/ES → Anchieta/ES" in html
