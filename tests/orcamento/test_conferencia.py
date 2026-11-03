"""Fila de conferência (orcamento/conferencia.py): simula o DAV no HSE só leitura."""

from __future__ import annotations

import time

import pytest

from core.banco import Banco
from orcamento.conferencia import SEM_HSE, FilaConferencia
from orcamento.processador import Conferencia


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def _rascunho(banco, estado="rascunho", conferencia="conferindo"):
    i = banco.dav_criar("ana", "plan.xlsx", f"h{time.monotonic_ns()}", "Cliente X")
    banco.dav_atualizar(i, estado=estado, conferencia=conferencia)
    return i


def _conf(estado="ok", cliente="6303 - TANGARA", erros=()):
    return Conferencia(estado, f"relatorio {cliente}", cliente, "", "", (), (), tuple(erros))


def _fila(banco, tmp_path, executar, **kw):
    return FilaConferencia(banco, tmp_path, executar=executar, disparar=lambda t: t(), **kw)


def _gravado(banco, i):
    linha = banco.dav(i, None)
    return linha["conferencia"], Conferencia.de_json(linha["conferencia_relatorio"])


def test_ok_grava_estado_e_json(banco, tmp_path):
    i = _rascunho(banco)
    _fila(banco, tmp_path, lambda p: _conf("ok")).enfileirar(i)
    estado, conf = _gravado(banco, i)
    assert estado == "ok" and conf.cliente == "6303 - TANGARA"


def test_erros_grava_erros(banco, tmp_path):
    i = _rascunho(banco)
    _fila(banco, tmp_path, lambda p: _conf("erros", erros=["Item 1 sem estoque"])).enfileirar(i)
    estado, conf = _gravado(banco, i)
    assert estado == "erros" and conf.erros == ("Item 1 sem estoque",)


def test_excecao_vira_nao_conferido_sem_senha(banco, tmp_path, monkeypatch):
    monkeypatch.setenv("HSE_SENHA", "s3gredo")
    i = _rascunho(banco)

    def executar(p):
        raise RuntimeError("falhou com s3gredo no meio")

    _fila(banco, tmp_path, executar).enfileirar(i)
    estado, conf = _gravado(banco, i)
    assert estado == "nao_conferido" and conf.estado == "nao_conferido"
    assert "s3gredo" not in conf.relatorio and "***" in conf.relatorio


def test_tempo_estourado_vira_nao_conferido(banco, tmp_path):
    i = _rascunho(banco)

    def lento(p):
        time.sleep(0.3)
        return _conf("ok")

    _fila(banco, tmp_path, lento, limite_s=0.05).enfileirar(i)
    estado, conf = _gravado(banco, i)
    assert estado == "nao_conferido" and conf.relatorio == SEM_HSE
    time.sleep(0.4)   # o resultado atrasado não pode aparecer depois
    assert _gravado(banco, i)[0] == "nao_conferido"


def test_resultado_atrasado_nao_sobrescreve(banco, tmp_path):
    i = _rascunho(banco)

    def executar(p):   # enquanto conferia, o DAV saiu de rascunho/conferindo
        banco.dav_atualizar(i, estado="fila", conferencia=None)
        return _conf("ok")

    _fila(banco, tmp_path, executar).enfileirar(i)
    linha = banco.dav(i, None)
    assert linha["estado"] == "fila" and linha["conferencia"] is None
    assert not linha["conferencia_relatorio"]


def test_duas_planilhas_do_mesmo_vendedor_cada_uma_no_seu_dav(banco, tmp_path):
    a, b = _rascunho(banco), _rascunho(banco)
    vistas = []

    def executar(p):
        vistas.append(p)
        return _conf("ok", cliente=f"cliente do {p.stem}")

    fila = _fila(banco, tmp_path, executar)
    fila.enfileirar(a)
    fila.enfileirar(b)
    assert vistas == [tmp_path / "entrada" / f"{a}.xlsx", tmp_path / "entrada" / f"{b}.xlsx"]
    assert _gravado(banco, a)[1].cliente == f"cliente do {a}"
    assert _gravado(banco, b)[1].cliente == f"cliente do {b}"


def test_retomar_marca_nao_conferido(banco, tmp_path):
    i = _rascunho(banco)
    _fila(banco, tmp_path, lambda p: _conf()).retomar()
    assert banco.dav(i, None)["conferencia"] == "nao_conferido"
