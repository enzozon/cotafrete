"""Status das cotações do ME no nosso lado — regra pura.

O caso-âncora: o teste real de Salvar (23/09/2026) mostrou que o ME não marca
rascunho. "Salva no ME" tem de sobreviver a toda varredura que diz
"Não Respondida".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mercado_eletronico import painel as P
from mercado_eletronico.painel import Status

AGORA = datetime(2026, 9, 23, 16, 50)
LIMITE = datetime(2026, 9, 23, 21, 0)


def _depois(atual, **kw):
    base = dict(status_resposta="Não Respondida", na_lista=True,
                data_limite=LIMITE, agora=AGORA)
    return P.status_apos_varredura(atual, **{**base, **kw})


def test_rascunho_salvo_sobrevive_a_nao_respondida():
    assert _depois(Status.SALVA) is Status.SALVA


@pytest.mark.parametrize("resposta", ["Parcialmente Respondida", "Totalmente Respondida"])
@pytest.mark.parametrize("atual", [Status.PENDENTE, Status.SALVA, Status.ERRO])
def test_respondida_no_me_e_enviada(atual, resposta):
    assert _depois(atual, status_resposta=resposta) is Status.ENVIADA


def test_recusada():
    assert _depois(Status.PENDENTE, status_resposta="Recusada") is Status.RECUSADA


def test_sumiu_antes_do_prazo_e_enviada():
    assert _depois(Status.SALVA, na_lista=False, status_resposta=None) is Status.ENVIADA


def test_sumiu_depois_do_prazo_e_vencida():
    tarde = LIMITE + timedelta(minutes=1)
    assert _depois(Status.SALVA, na_lista=False, status_resposta=None, agora=tarde) is Status.VENCIDA


@pytest.mark.parametrize("final", [Status.ENVIADA, Status.RECUSADA])
def test_final_nao_volta_atras(final):
    assert _depois(final) is final
    assert _depois(final, na_lista=False, agora=LIMITE + timedelta(days=1)) is final


def test_vencida_que_volta_para_a_lista_reabre():
    assert _depois(Status.VENCIDA) is Status.PENDENTE


def test_hora_do_me_vem_em_utc():
    # dueDate 2026-09-29T00:00:00Z = 28/09 21:00 em Brasília
    assert P.hora_de_brasilia("2026-09-29T00:00:00Z") == datetime(2026, 9, 28, 21, 0)
    utc = datetime(2026, 9, 29, tzinfo=timezone.utc)
    assert P.hora_de_brasilia(utc) == datetime(2026, 9, 28, 21, 0)
    assert P.hora_de_brasilia(LIMITE) == LIMITE  # sem fuso = já é Brasília
    assert P.hora_de_brasilia("lixo") is None
    assert P.hora_de_brasilia(None) is None


@pytest.mark.parametrize("falta, texto, urgente", [
    (timedelta(days=2, hours=5, minutes=3), "2 d 5 h", False),
    (timedelta(hours=4, minutes=10), "4 h 10 min", True),
    (timedelta(minutes=7), "7 min", True),
    (timedelta(seconds=-1), "venceu", True),
])
def test_prazo(falta, texto, urgente):
    p = P.prazo(AGORA + falta, AGORA)
    assert (p.texto, p.urgente) == (texto, urgente)


def test_alerta_do_rascunho_esquecido():
    assert P.alerta(Status.SALVA, LIMITE, AGORA) == "Salva no ME mas NÃO enviada — fecha em 4 h 10 min"
    assert P.alerta(Status.PENDENTE, LIMITE, AGORA) == "Fecha em 4 h 10 min"
    assert P.alerta(Status.ENVIADA, LIMITE, AGORA) == ""
    assert P.alerta(Status.SALVA, LIMITE + timedelta(days=3), AGORA) == ""


@pytest.mark.parametrize("descricao, chave", [
    ("000000000000263252 - BATERIA RECARR;DRON", "263252"),
    ("  Posto   duplo ", "POSTO DUPLO"),
    ("TV65", "TV65"),
])
def test_chave_material(descricao, chave):
    assert P.chave_material(descricao) == chave
