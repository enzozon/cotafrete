"""Fila de conferência (orcamento/conferencia.py): simula o DAV no HSE só leitura."""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from core.banco import Banco
from orcamento.conferencia import SEM_HSE, SEM_LOGIN, FilaConferencia
from orcamento.config import Config
from orcamento.processador import Conferencia, HseIndisponivel


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


def test_banco_travado_tenta_de_novo_e_grava(banco, tmp_path, monkeypatch):
    monkeypatch.setattr("orcamento.fila.ESPERA_BANCO_S", 0)
    i = _rascunho(banco)
    real, falhas = banco.dav_atualizar, []

    def trava_uma_vez(*a, **kw):
        if not falhas:
            falhas.append(1)
            raise sqlite3.OperationalError("database is locked")
        return real(*a, **kw)

    monkeypatch.setattr(banco, "dav_atualizar", trava_uma_vez)
    _fila(banco, tmp_path, lambda p: _conf("ok")).enfileirar(i)
    assert falhas and _gravado(banco, i)[0] == "ok"


def test_log_nao_vaza_senha(banco, tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HSE_SENHA", "s3gredo")
    i = _rascunho(banco)

    def executar(p):
        raise Exception("login com s3gredo falhou")

    _fila(banco, tmp_path, executar).enfileirar(i)
    assert "s3gredo" not in caplog.text and caplog.text


def _config():
    return Config(usuario="u", senha="s", client_id="ventura", dry_run=False, headless=True)


def test_executor_padrao_forca_dry_run_e_pasta_programa(banco, tmp_path, monkeypatch):
    visto = {}

    class HseFalso:
        def __init__(self, cfg):
            visto["hse_cfg"] = cfg

        def __enter__(self):
            return "hse"

        def __exit__(self, *a):
            return False

    def conferir_falso(planilha, cfg, hse):
        visto.update(cfg=cfg, hse=hse)
        return _conf("ok")

    monkeypatch.setattr("orcamento.config.config_do_ambiente", _config)
    monkeypatch.setattr("orcamento.hse.HseSoLeitura", HseFalso)
    monkeypatch.setattr("orcamento.conferencia.conferir", conferir_falso)
    i = _rascunho(banco)
    FilaConferencia(banco, tmp_path, disparar=lambda t: t()).enfileirar(i)
    assert visto["cfg"].dry_run is True and visto["cfg"].pasta_programa == tmp_path
    assert visto["hse_cfg"] is visto["cfg"] and visto["hse"] == "hse"
    assert _gravado(banco, i)[0] == "ok"


def test_hse_indisponivel_vira_nao_conferido(banco, tmp_path, monkeypatch):
    def hse_fora(cfg):
        raise HseIndisponivel("fora do ar")

    monkeypatch.setattr("orcamento.config.config_do_ambiente", _config)
    monkeypatch.setattr("orcamento.hse.HseSoLeitura", hse_fora)
    i = _rascunho(banco)
    FilaConferencia(banco, tmp_path, disparar=lambda t: t()).enfileirar(i)
    estado, conf = _gravado(banco, i)
    assert estado == "nao_conferido" and conf.relatorio == SEM_HSE


def test_sem_login_vira_nao_conferido(banco, tmp_path, monkeypatch):
    def sem_login():
        raise ValueError("Faltam no .env: HSE_USUARIO")

    monkeypatch.setattr("orcamento.config.config_do_ambiente", sem_login)
    i = _rascunho(banco)
    FilaConferencia(banco, tmp_path, disparar=lambda t: t()).enfileirar(i)
    estado, conf = _gravado(banco, i)
    assert estado == "nao_conferido" and conf.relatorio == SEM_LOGIN


def test_thread_real_segue_depois_de_tarefa_que_quebra(banco, tmp_path):
    a, b = _rascunho(banco), _rascunho(banco)
    pronto = threading.Event()

    def executar(p):
        if p.stem == str(a):
            raise RuntimeError("quebrou")
        pronto.set()
        return _conf("ok")

    fila = FilaConferencia(banco, tmp_path, executar=executar)
    fila.enfileirar(a)
    fila.enfileirar(b)
    assert pronto.wait(2)
    for _ in range(40):   # a gravação vem logo depois do executor
        if banco.dav(b, None)["conferencia"] == "ok":
            break
        time.sleep(0.05)
    assert _gravado(banco, a)[0] == "nao_conferido" and _gravado(banco, b)[0] == "ok"
