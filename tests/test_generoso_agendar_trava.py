"""As travas do agendamento — o que impede uma coleta de ser pedida sem querer.

NENHUM teste daqui abre navegador. Todos param nas guardas de
`agendar_coleta`, que rodam ANTES do Playwright — e isso é justamente o que
precisa ser verdade: uma guarda que só age depois de abrir o portal já perdeu
metade da graça, porque o custo que ela deveria evitar já foi pago.

A trava do agendamento é SEPARADA da trava do envio da cotação de propósito.
Uma cotação a mais é uma linha na conta da Ventura; uma coleta a mais é um
caminhão na porta do cliente. Quem liga a segunda precisa estar dizendo isso,
não herdando de uma decisão tomada para outra coisa.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from carriers.generoso.adapter import (VAR_AGENDAMENTO_AUTORIZADO,
                                       GenerosoAdapter)
from carriers.generoso.mapping import Agendamento


def _dia_util_futuro() -> date:
    """Depois de amanhã, empurrado para a segunda se cair no fim de semana.

    Calculado e não fixo: uma data escrita à mão vira passado sozinha, e o
    teste passaria a falhar por velhice em vez de por defeito."""
    d = date.today() + timedelta(days=2)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


@pytest.fixture
def adapter():
    return GenerosoAdapter(usuario="quem", senha="segredo")


@pytest.fixture(autouse=True)
def sem_autorizacao(monkeypatch):
    """O padrão do .env de produção: a variável NÃO existe."""
    monkeypatch.delenv(VAR_AGENDAMENTO_AUTORIZADO, raising=False)


def _ag(**over) -> Agendamento:
    base = dict(data=_dia_util_futuro(), hora_limite="18:00")
    base.update(over)
    return Agendamento(**base)


def test_confirmar_sem_a_variavel_no_env_nao_agenda(adapter):
    """A trava principal. Sem ela, mesclar a PR já ligaria o agendamento real
    em produção — e o primeiro clique de um vendedor viraria caminhão."""
    res = adapter.agendar_coleta("2684352", _ag(), confirmar=True)

    assert res.ok is False
    assert VAR_AGENDAMENTO_AUTORIZADO in res.erro
    assert res.protocolo is None


def test_a_recusa_diz_que_nada_foi_pedido(adapter):
    """Quem lê precisa saber que a coleta NÃO foi pedida. Um erro técnico
    sem essa frase deixa a dúvida — e na dúvida o vendedor liga para a
    transportadora para conferir, ou pior, tenta de novo."""
    res = adapter.agendar_coleta("2684352", _ag(), confirmar=True)

    assert "não foi" in res.erro


def test_sem_credencial_nao_abre_navegador(monkeypatch):
    """Descobrir a falta de senha depois de subir o Chromium custa uma vaga
    de navegador que as cotações estão esperando."""
    adapter = GenerosoAdapter(usuario="", senha="")
    monkeypatch.setenv(VAR_AGENDAMENTO_AUTORIZADO, "1")

    res = adapter.agendar_coleta("2684352", _ag(), confirmar=True)

    assert res.ok is False
    assert "GENEROSO_USUARIO" in res.erro


def test_agendamento_invalido_nao_chega_ao_portal(adapter, monkeypatch):
    """Sábado. A validação pura barra aqui, antes do login — e a mensagem é
    a escrita para o vendedor, não um timeout de 45 segundos."""
    monkeypatch.setenv(VAR_AGENDAMENTO_AUTORIZADO, "1")
    hoje = date.today()
    sabado = hoje + timedelta(days=(5 - hoje.weekday()) % 7 or 7)

    res = adapter.agendar_coleta("2684352", _ag(data=sabado), confirmar=True)

    assert res.ok is False
    assert "útil" in res.erro or "hoje" in res.erro


def test_hora_fora_da_grade_nao_chega_ao_portal(adapter, monkeypatch):
    monkeypatch.setenv(VAR_AGENDAMENTO_AUTORIZADO, "1")

    res = adapter.agendar_coleta("2684352", _ag(hora_limite="18:20"),
                                 confirmar=True)

    assert res.ok is False
    assert "18:20" in res.erro


def test_almoco_invertido_nao_chega_ao_portal(adapter, monkeypatch):
    monkeypatch.setenv(VAR_AGENDAMENTO_AUTORIZADO, "1")

    res = adapter.agendar_coleta(
        "2684352", _ag(almoco_inicio="13:00", almoco_fim="12:00"),
        confirmar=True)

    assert res.ok is False


def test_a_validacao_vem_antes_da_trava_do_env(adapter):
    """Ordem de propósito: um agendamento malformado é erro de quem
    preencheu, e dizer "ligue a variável no .env" para quem escolheu 03:00
    manda a pessoa mexer no lugar errado."""
    res = adapter.agendar_coleta(
        "2684352", _ag(hora_limite="03:00"), confirmar=True)

    assert VAR_AGENDAMENTO_AUTORIZADO not in (res.erro or "")
    assert "03:00" in res.erro
