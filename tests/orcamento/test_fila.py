"""Fila do DAV (orcamento/fila.py): um por vez, sobrevive a reinício."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.banco import Banco
from orcamento.fila import FilaDav
from orcamento.processador import Resultado


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def _na_fila(banco, estado="fila", hash_="h"):
    i = banco.dav_criar("ana", "plan.xlsx", f"{hash_}{time.monotonic_ns()}", "Cliente X")
    banco.dav_atualizar(i, estado=estado)
    return i


def _na_hora(tarefa):
    tarefa()


def _pronto(planilha, pasta_pdf):
    return Resultado("pronto", "123", pasta_pdf / "DAV_123.pdf", "relatorio ok", "8411 - BELO")


def test_pronto_grava_numero_pdf_relatorio(banco, tmp_path):
    vistos = []

    def executar(planilha, pasta_pdf):
        vistos.append((planilha, pasta_pdf))
        assert banco.dav(i, None)["estado"] == "gerando"
        assert banco.dav(i, None)["iniciado_em"]
        return _pronto(planilha, pasta_pdf)

    fila = FilaDav(banco, tmp_path / "davs", executar, _na_hora)
    i = _na_fila(banco)
    fila.enfileirar(i)
    d = banco.dav(i, None)
    assert d["estado"] == "pronto" and d["numero"] == "123"
    assert d["pdf"] == str(tmp_path / "davs" / "pdf" / "DAV_123.pdf")
    assert d["relatorio"] == "relatorio ok" and d["cliente"] == "8411 - BELO"
    assert d["terminado_em"]
    assert vistos == [(fila.planilha(i), tmp_path / "davs" / "pdf")]
    assert fila.planilha(i) == tmp_path / "davs" / "entrada" / f"{i}.xlsx"


def test_adiado_vira_erro_com_mensagem(banco, tmp_path):
    fila = FilaDav(banco, tmp_path, lambda p, d: Resultado("adiado", None, None, "rel", ""), _na_hora)
    i = _na_fila(banco)
    fila.enfileirar(i)
    d = banco.dav(i, None)
    assert d["estado"] == "erro"
    assert d["erro"] == "O HSE está fora do ar agora. Tente de novo em alguns minutos."


def test_excecao_vira_erro_e_o_proximo_ainda_roda_na_thread(banco, tmp_path):
    def executar(planilha, pasta_pdf):
        if planilha.stem == str(a):
            raise RuntimeError("quebrou feio")
        return _pronto(planilha, pasta_pdf)

    fila = FilaDav(banco, tmp_path, executar)     # disparar padrão: thread
    a, b = _na_fila(banco), _na_fila(banco)
    fila.enfileirar(a)
    fila.enfileirar(b)
    limite = time.monotonic() + 10
    while fila.em_curso and time.monotonic() < limite:
        time.sleep(0.02)
    assert fila.em_curso == 0
    assert banco.dav(a, None)["estado"] == "erro"
    assert "quebrou feio" in banco.dav(a, None)["erro"]
    assert banco.dav(b, None)["estado"] == "pronto"


def test_em_curso_sobe_e_volta_a_zero(banco, tmp_path):
    adiadas = []
    durante = []

    def executar(planilha, pasta_pdf):
        durante.append(fila.em_curso)
        return _pronto(planilha, pasta_pdf)

    fila = FilaDav(banco, tmp_path, executar, adiadas.append)
    a, b = _na_fila(banco), _na_fila(banco)
    assert fila.em_curso == 0
    assert fila.enfileirar(a) == 1
    assert fila.enfileirar(b) == 2
    assert fila.enfileirar(a) == 1          # o mesmo id não entra duas vezes
    assert fila.em_curso == 2
    for tarefa in adiadas:
        tarefa()
    assert durante == [2, 1]                # o que está gerando conta
    assert fila.em_curso == 0


def test_retomar_gerando_vira_incerto_e_filas_rodam_em_ordem(banco, tmp_path):
    ordem = []

    def executar(planilha, pasta_pdf):
        ordem.append(int(planilha.stem))
        return _pronto(planilha, pasta_pdf)

    g = _na_fila(banco, "gerando")
    f1, f2 = _na_fila(banco), _na_fila(banco)
    fila = FilaDav(banco, tmp_path, executar, _na_hora)
    fila.retomar()
    assert banco.dav(g, None)["estado"] == "incerto"
    assert ordem == [f1, f2]
    assert banco.dav(f1, None)["estado"] == banco.dav(f2, None)["estado"] == "pronto"


def test_senha_nao_aparece_no_erro(banco, tmp_path, monkeypatch):
    monkeypatch.setenv("HSE_SENHA", "s3cr3t!")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-abc")

    def executar(planilha, pasta_pdf):
        raise RuntimeError("login com s3cr3t! e sk-abc falhou")

    fila = FilaDav(banco, tmp_path, executar, _na_hora)
    i = _na_fila(banco)
    fila.enfileirar(i)
    erro = banco.dav(i, None)["erro"]
    assert "s3cr3t!" not in erro and "sk-abc" not in erro
    assert "***" in erro


def test_nao_sobrescreve_quem_saiu_de_gerando(banco, tmp_path):
    def executar(planilha, pasta_pdf):
        banco.dav_atualizar(i, estado="incerto")   # alguém mexeu no meio
        return _pronto(planilha, pasta_pdf)

    fila = FilaDav(banco, tmp_path, executar, _na_hora)
    i = _na_fila(banco)
    fila.enfileirar(i)
    assert banco.dav(i, None)["estado"] == "incerto"


def test_sem_login_no_servidor_vira_erro(banco, tmp_path, monkeypatch):
    monkeypatch.delenv("HSE_USUARIO", raising=False)
    monkeypatch.delenv("HSE_SENHA", raising=False)
    fila = FilaDav(banco, tmp_path, disparar=_na_hora)   # executar padrão
    i = _na_fila(banco)
    fila.enfileirar(i)
    d = banco.dav(i, None)
    assert d["estado"] == "erro"
    assert d["erro"] == "Robô do HSE sem login configurado no servidor."


def test_numero_gravado_logo_apos_salvar_mesmo_se_o_executor_quebra(banco, tmp_path):
    def executar(planilha, pasta_pdf, ao_salvar=None, nome=None):
        ao_salvar("16400")
        raise RuntimeError("caiu no download do PDF")

    i = _na_fila(banco)
    FilaDav(banco, tmp_path, executar, _na_hora).enfileirar(i)
    d = banco.dav(i, None)
    assert d["estado"] == "erro" and d["numero"] == "16400"


def test_retomar_incerto_mantem_numero_gravado_no_salvar(banco, tmp_path):
    i = _na_fila(banco, "gerando")
    banco.dav_atualizar(i, numero="16400")   # o que ao_salvar gravou antes da queda
    FilaDav(banco, tmp_path, _pronto, _na_hora).retomar()
    d = banco.dav(i, None)
    assert d["estado"] == "incerto" and d["numero"] == "16400"


def test_executor_recebe_o_nome_original_do_arquivo(banco, tmp_path):
    vistos = []

    def executar(planilha, pasta_pdf, ao_salvar=None, nome=None):
        vistos.append(nome)
        return _pronto(planilha, pasta_pdf)

    i = _na_fila(banco)
    FilaDav(banco, tmp_path, executar, _na_hora).enfileirar(i)
    assert vistos == ["plan.xlsx"]
