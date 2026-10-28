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
