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


def test_numeros_com_hora_de_todos_os_davs_com_numero(banco):
    i = _dav(banco, "pronto")
    banco.dav_atualizar(i, numero="123", terminado_em="2026-11-04T10:00:00", iniciado_em="2026-11-04T09:59:00")
    j = _dav(banco, "incerto")
    banco.dav_atualizar(j, numero="124", iniciado_em="2026-11-04T11:00:00")
    _dav(banco, "erro")
    assert banco.dav_numeros_com_hora() == [("2026-11-04T10:00:00", 123), ("2026-11-04T11:00:00", 124)]


def test_numeros_conhecidos_menos_o_proprio(banco):
    ids = []
    for n in ("16402", "16553", None):
        ids.append(_dav(banco, "pronto"))
        banco.dav_atualizar(ids[-1], numero=n)
    assert banco.dav_numeros_conhecidos(exceto=ids[0]) == {16553}


def test_origem_da_correcao(banco):
    a, b = _dav(banco, "erro"), _dav(banco, "pronto")
    assert banco.dav_origem_da_correcao(b) is None
    banco.dav_vincular_correcao(a, b, "ana")
    assert banco.dav_origem_da_correcao(b)["id"] == a


def test_executor_passa_hora_ignorar_anterior_e_copia_campos(banco, tmp_path, monkeypatch):
    import orcamento.agente as agente
    import orcamento.config as config
    import orcamento.hse as hse
    import orcamento.provas as provas

    class Hse:
        bloqueados = []

        def __init__(self, cfg):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    vistos = {}

    def coletar(dav, pasta, buscar, ignorar=frozenset(), anterior=None):
        vistos.update(ignorar=ignorar, anterior=anterior and anterior["id"])
        return {"criados_no_hse": [], "motivo_nao_verificado": "", "rascunhos": [16492],
                "produtos_criados": ["76811 - terminal"]}

    monkeypatch.setattr(config, "config_do_ambiente",
                        lambda: config.Config(usuario="u", senha="s", client_id="v", dry_run=False, headless=True))
    monkeypatch.setattr(hse, "HseSoLeitura", Hse)
    monkeypatch.setattr(provas, "coletar", coletar)
    monkeypatch.setattr(agente, "diagnosticar", lambda p, cfg: {"culpa": "robo"})
    origem, outro, i = _dav(banco, "erro"), _dav(banco, "pronto"), _dav(banco, "erro")
    banco.dav_atualizar(outro, numero="16402")
    banco.dav_vincular_correcao(origem, i, "ana")
    FilaDiagnostico(banco, tmp_path, disparar=_na_hora).enfileirar(i)
    j = json.loads(banco.dav(i, None)["diagnostico"])
    assert vistos == {"ignorar": {16402}, "anterior": origem}
    assert j["rascunhos"] == [16492] and j["produtos_criados"] == ["76811 - terminal"]


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


def test_numeros_com_hora_ignora_numero_sujo(banco):
    for n in ("123abc", "456"):
        i = _dav(banco, "pronto")
        banco.dav_atualizar(i, numero=n, terminado_em="2026-11-04T10:00:00")
    assert banco.dav_numeros_com_hora() == [("2026-11-04T10:00:00", 456)]
    assert banco.dav_numeros_conhecidos(exceto=0) == {456}


def test_executor_nao_ignora_o_proprio_numero(banco, tmp_path, monkeypatch):
    import orcamento.agente as agente
    import orcamento.config as config
    import orcamento.hse as hse
    import orcamento.provas as provas

    class Hse:
        bloqueados = []

        def __init__(self, cfg):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    vistos = {}
    monkeypatch.setattr(config, "config_do_ambiente",
                        lambda: config.Config(usuario="u", senha="s", client_id="v", dry_run=False, headless=True))
    monkeypatch.setattr(hse, "HseSoLeitura", Hse)
    monkeypatch.setattr(provas, "coletar", lambda d, p, b, ignorar=frozenset(), anterior=None:
                        vistos.update(ignorar=ignorar) or {"criados_no_hse": []})
    monkeypatch.setattr(agente, "diagnosticar", lambda p, cfg: {})
    outro, i = _dav(banco, "pronto"), _dav(banco, "incerto")
    banco.dav_atualizar(outro, numero="16533")
    banco.dav_atualizar(i, numero="16533")
    FilaDiagnostico(banco, tmp_path, disparar=_na_hora).enfileirar(i)
    assert vistos["ignorar"] == set()


def test_gasto_do_diagnostico_vai_para_a_pasta_da_fila(banco, tmp_path, monkeypatch):
    import orcamento.agente as agente
    import orcamento.config as config

    vistos = []
    monkeypatch.setattr(config, "config_do_ambiente",
                        lambda: config.Config(usuario="u", senha="s", client_id="v", dry_run=False, headless=True))
    monkeypatch.setattr(agente, "diagnosticar", lambda provas, cfg: vistos.append(cfg.pasta_programa) or {})
    i = _dav(banco, "rejeitado")
    FilaDiagnostico(banco, tmp_path / "davs", disparar=_na_hora).enfileirar(i)
    assert vistos == [tmp_path / "davs"]


def test_alarme_de_bloqueio_vale_mesmo_com_excecao_na_busca(banco, tmp_path, monkeypatch):
    import orcamento.agente as agente
    import orcamento.config as config
    import orcamento.hse as hse
    import orcamento.provas as provas

    class Hse:
        bloqueados = ["clicou em Incluir"]

        def __init__(self, cfg):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def coletar(*a, **k):
        raise ValueError("estourou")

    monkeypatch.setattr(config, "config_do_ambiente",
                        lambda: config.Config(usuario="u", senha="s", client_id="v", dry_run=False, headless=True))
    monkeypatch.setattr(hse, "HseSoLeitura", Hse)
    monkeypatch.setattr(provas, "coletar", coletar)
    monkeypatch.setattr(agente, "diagnosticar", lambda p, cfg: {})
    i = _dav(banco, "erro")
    FilaDiagnostico(banco, tmp_path, disparar=_na_hora).enfileirar(i)
    d = banco.dav(i, None)
    assert d["diagnostico_estado"] == "falhou" and "bloqueou gravação" in d["diagnostico"]
