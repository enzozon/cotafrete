"""Fila do diagnóstico (orcamento/fila_diagnostico.py) e os gatilhos nas outras filas."""

from __future__ import annotations

import json
import time

import pytest

from core.banco import Banco
from orcamento.conferencia import FilaConferencia
from orcamento.fila import FilaDav
from orcamento.fila_diagnostico import FilaDiagnostico, deve_diagnosticar
from orcamento.processador import Conferencia, Resultado


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def _dav(banco, estado="erro", conferencia=None):
    i = banco.dav_criar("ana", "plan.xlsx", f"h{time.monotonic_ns()}", "Cliente X")
    banco.dav_atualizar(i, estado=estado, conferencia=conferencia)
    return i


def _na_hora(t):
    t()


def test_enfileira_so_quem_falhou(banco):
    for estado, conf, esperado in [("pronto", None, False), ("fila", None, False), ("gerando", None, False),
                                   ("erro", None, True), ("incerto", None, True), ("rejeitado", None, True),
                                   ("rascunho", "erros", True), ("rascunho", "ok", False)]:
        assert deve_diagnosticar(banco.dav(_dav(banco, estado, conf), None)) is esperado


def test_grava_feito_e_json(banco, tmp_path):
    i = _dav(banco)
    FilaDiagnostico(banco, tmp_path, executar=lambda d: {"culpa": "robo", "p": tmp_path},
                    disparar=_na_hora).enfileirar(i)
    d = banco.dav(i, None)
    assert d["diagnostico_estado"] == "feito" and json.loads(d["diagnostico"])["culpa"] == "robo"


def test_excecao_vira_falhou_sem_travar(banco, tmp_path):
    a, b = _dav(banco), _dav(banco)

    def executar(i):
        if i == a:
            raise RuntimeError("quebrou")
        return {"culpa": "x"}

    f = FilaDiagnostico(banco, tmp_path, executar=executar, disparar=_na_hora)
    f.enfileirar(a)
    f.enfileirar(b)
    assert banco.dav(a, None)["diagnostico_estado"] == "falhou"
    assert "quebrou" in json.loads(banco.dav(a, None)["diagnostico"])["motivo"]
    assert banco.dav(b, None)["diagnostico_estado"] == "feito"


def test_retomar_pendentes(banco, tmp_path):
    a, b = _dav(banco), _dav(banco)
    banco.dav_atualizar(a, diagnostico_estado="pendente")
    vistos = []
    FilaDiagnostico(banco, tmp_path, executar=lambda i: vistos.append(i) or {}, disparar=_na_hora).retomar()
    assert vistos == [a] and banco.dav(b, None)["diagnostico_estado"] in (None, "")


def test_numeros_prontos(banco):
    i = _dav(banco, "pronto")
    banco.dav_atualizar(i, numero="123", terminado_em="2026-11-04T10:00:00")
    _dav(banco, "erro")
    assert banco.dav_numeros_prontos() == [("2026-11-04T10:00:00", 123)]


def test_fila_dav_chama_ao_terminar(banco, tmp_path):
    i = _dav(banco, "fila")
    vistos = []
    FilaDav(banco, tmp_path, executar=lambda p, q: Resultado("erro", None, None, "x", ""),
            disparar=_na_hora, ao_terminar=vistos.append).enfileirar(i)
    assert vistos == [i]


def test_fila_dav_callback_que_quebra_so_loga(banco, tmp_path):
    i = _dav(banco, "fila")

    def quebra(_):
        raise RuntimeError("x")

    FilaDav(banco, tmp_path, executar=lambda p, q: Resultado("erro", None, None, "x", ""),
            disparar=_na_hora, ao_terminar=quebra).enfileirar(i)
    assert banco.dav(i, None)["estado"] == "erro"


def test_conferencia_chama_ao_terminar(banco, tmp_path):
    i = _dav(banco, "rascunho", "conferindo")
    vistos = []
    conf = Conferencia("erros", "r", "C", "", "", (), (), ("e",))
    FilaConferencia(banco, tmp_path, executar=lambda p: conf, disparar=_na_hora,
                    ao_terminar=vistos.append).enfileirar(i)
    assert vistos == [i]


def test_hse_indisponivel_vira_nao_verificado(banco, tmp_path, monkeypatch):
    import orcamento.agente as agente
    import orcamento.config as config
    import orcamento.hse as hse
    from orcamento.processador import HseIndisponivel

    class SemHse:
        def __init__(self, cfg):
            raise HseIndisponivel("fora do ar")

    monkeypatch.setattr(config, "config_do_ambiente",
                        lambda: config.Config(usuario="u", senha="s", client_id="v", dry_run=False, headless=True))
    monkeypatch.setattr(hse, "HseSoLeitura", SemHse)
    monkeypatch.setattr(agente, "diagnosticar", lambda provas, cfg: provas)
    i = _dav(banco, "erro")
    FilaDiagnostico(banco, tmp_path, disparar=_na_hora).enfileirar(i)
    d = banco.dav(i, None)
    j = json.loads(d["diagnostico"])
    assert d["diagnostico_estado"] == "feito" and j["criados_no_hse"] == "nao_verificado"
    assert "fora do ar" in j["motivo_nao_verificado"]


def test_numeros_prontos_ignora_numero_sujo(banco):
    for n in ("123abc", "456"):
        i = _dav(banco, "pronto")
        banco.dav_atualizar(i, numero=n, terminado_em="2026-11-04T10:00:00")
    assert banco.dav_numeros_prontos() == [("2026-11-04T10:00:00", 456)]
