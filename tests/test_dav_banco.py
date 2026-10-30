"""Tabela dav (Gerar DAV) em core/banco.py."""

from __future__ import annotations

import pytest

from core.banco import Banco


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def _novo(banco, usuario="ana", hash_="h1", estado=None):
    i = banco.dav_criar(usuario, "plan.xlsx", hash_, "Cliente X")
    if estado:
        banco.dav_atualizar(i, estado=estado)
    return i


def test_criar_e_ler_pelo_dono(banco):
    i = banco.dav_criar("ana", "plan.xlsx", "h1", "Cliente X")
    d = banco.dav(i, "ana")
    assert d["estado"] == "rascunho"
    assert d["arquivo"] == "plan.xlsx" and d["cliente"] == "Cliente X"
    assert d["criado_em"]


def test_outro_usuario_nao_ve_e_admin_ve(banco):
    i = _novo(banco)
    assert banco.dav(i, "outro") is None
    assert banco.dav(i, None)["id"] == i
    assert banco.dav(999, None) is None


def test_davs_filtra_usuario_sem_rascunho_mais_novo_primeiro(banco):
    a1 = _novo(banco, "ana", "a", "pronto")
    a2 = _novo(banco, "ana", "b", "fila")
    _novo(banco, "ana", "c")  # rascunho
    _novo(banco, "bia", "d", "pronto")
    assert [d["id"] for d in banco.davs("ana")] == [a2, a1]
    assert len(banco.davs(None)) == 3
    assert len(banco.davs(None, limite=1)) == 1


def test_ja_gerado(banco):
    for estado in ("pronto", "incerto", "fila", "gerando"):
        i = _novo(banco, "ana", estado, estado)
        assert banco.dav_ja_gerado("ana", estado)["id"] == i
    _novo(banco, "ana", "e", "erro")
    _novo(banco, "ana", "r")
    assert banco.dav_ja_gerado("ana", "e") is None
    assert banco.dav_ja_gerado("ana", "r") is None
    assert banco.dav_ja_gerado("bia", "pronto") is None


def test_interromper(banco):
    g = _novo(banco, "ana", "g", "gerando")
    f1 = _novo(banco, "ana", "f1", "fila")
    f2 = _novo(banco, "bia", "f2", "fila")
    assert banco.dav_interromper() == [f1, f2]
    d = banco.dav(g, None)
    assert d["estado"] == "incerto"
    assert d["erro"] == ("O servidor reiniciou durante o DAV: "
                         "confira no HSE antes de gerar de novo.")
    assert d["terminado_em"]
    assert banco.dav(f1, None)["estado"] == "fila"


def test_atualizar_campo_invalido(banco):
    i = _novo(banco)
    with pytest.raises(ValueError):
        banco.dav_atualizar(i, senha="x")
    banco.dav_atualizar(i, numero="123", pdf="a.pdf")
    assert banco.dav(i, None)["numero"] == "123"


def test_rejeicao_nao_e_tentativa_no_hse(banco):
    i = banco.dav_rejeitar("ana", "invalida.xls", ["Use .xlsx"])
    d = banco.dav(i, "ana")
    assert d["estado"] == "rejeitado" and d["hash_planilha"] == ""
    assert d["erro"] == "Use .xlsx" and not d["numero"] and not d["pdf"]
    assert banco.dav_ja_gerado("ana", "") is None
    assert banco.dav_interromper() == []


def test_vinculo_valida_dono_estado_e_ciclo(banco):
    a = _novo(banco, estado="erro")
    b = banco.dav_rejeitar("ana", "a.xls", ["formato"])
    outro = _novo(banco, "bia", "b", "erro")
    for origem, destino in ((a, a), (a, outro), (outro, b), (999, b)):
        with pytest.raises(ValueError):
            banco.dav_vincular_correcao(origem, destino, "ana")
    banco.dav_vincular_correcao(a, b, "ana")
    banco.dav_vincular_correcao(a, b, "ana")
    with pytest.raises(ValueError):
        banco.dav_vincular_correcao(b, a, "ana")
    for estado in ("incerto", "pronto", "gerando", "fila"):
        banco.dav_atualizar(a, estado=estado)
        with pytest.raises(ValueError):
            banco.dav_vincular_correcao(a, b, "ana")


def test_duas_origens_podem_apontar_para_mesmo_pronto(banco):
    pronto = _novo(banco, hash_="p", estado="pronto")
    a = _novo(banco, hash_="a", estado="erro")
    b = _novo(banco, hash_="b", estado="erro")
    banco.dav_vincular_correcao(a, pronto, "ana")
    banco.dav_vincular_correcao(b, pronto, "ana")
    from contextlib import closing
    with closing(banco._conectar()) as con:
        assert con.execute("SELECT count(*) FROM dav_correcao").fetchone()[0] == 2
    assert banco.dav(a, "ana")["estado"] == "erro"


def test_erro_com_numero_nao_autoriza_reenvio(banco):
    a = _novo(banco, estado="erro")
    b = _novo(banco, hash_="b")
    banco.dav_atualizar(a, numero="16410")
    assert banco.dav_ja_gerado("ana", "h1")["id"] == a
    with pytest.raises(ValueError):
        banco.dav_vincular_correcao(a, b, "ana")


def test_migracao_antiga_repetida_preserva_dav(banco):
    i = _novo(banco, estado="erro")
    from contextlib import closing
    with closing(banco._conectar()) as con:
        con.execute("DROP TABLE IF EXISTS dav_correcao")
        con.commit()
    Banco(banco.caminho)
    novo = Banco(banco.caminho)
    b = novo.dav_rejeitar("ana", "reenvio.xls", ["formato"])
    novo.dav_vincular_correcao(i, b, "ana")
    assert novo.dav(i, "ana")["estado"] == "erro"
