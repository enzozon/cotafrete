"""O que a Generoso aceita como data e hora de coleta — camada pura.

Tudo aqui saiu de `recon/recon_generoso_agendar.py`, rodado na conta real em
21/09/2026, e não de print nem de suposição. Vale repetir o que o recon mediu
no calendário daquele dia (uma segunda-feira):

    liberados   22, 23, 24, 25, 28, 29, 30
    bloqueados  1 a 21 (passado, e o PRÓPRIO dia 21), 26 e 27 (fim de semana)

Ou seja: dia útil, e sempre no futuro. Não existe coleta no mesmo dia.

Validar aqui, e não só no navegador, é o que separa "o sistema explica" de "o
robô fica clicando num sábado". A célula bloqueada do calendário não recusa o
clique com mensagem nenhuma — ela simplesmente não faz nada, e o painel fica
parado com cara de travado.
"""

from __future__ import annotations

from datetime import date

import pytest

from carriers.generoso import mapping


SEGUNDA = date(2026, 9, 21)          # o "hoje" de todos os testes daqui
TERCA = date(2026, 9, 22)
QUARTA = date(2026, 9, 23)
SABADO = date(2026, 9, 26)
DOMINGO = date(2026, 9, 27)


def _ag(**over):
    base = dict(data=QUARTA, hora_limite="18:00")
    base.update(over)
    return mapping.Agendamento(**base)


# ------------------------------------------------------ o que o site aceita
def test_horarios_de_coleta_sao_os_medidos_no_site():
    """08:00 às 18:00, de 30 em 30. Escritos e não gerados: se a Generoso
    mudar a grade, o teste falha e alguém vai olhar — uma lista gerada por
    `range` continuaria "certa" enquanto o site recusava."""
    assert mapping.HORARIOS_COLETA[0] == "08:00"
    assert mapping.HORARIOS_COLETA[-1] == "18:00"
    assert len(mapping.HORARIOS_COLETA) == 21
    assert "12:30" in mapping.HORARIOS_COLETA


def test_horarios_de_almoco_sao_outra_grade():
    """10:00 às 14:30 — MENOR que a da coleta. Reaproveitar a lista da
    coleta ofereceria 08:00 para o começo do almoço, e o select do site não
    tem essa opção."""
    assert mapping.HORARIOS_ALMOCO[0] == "10:00"
    assert mapping.HORARIOS_ALMOCO[-1] == "14:30"
    assert "08:00" not in mapping.HORARIOS_ALMOCO


# -------------------------------------------------------------------- data
def test_dia_util_futuro_passa():
    assert mapping.validar_agendamento(_ag(data=QUARTA), hoje=SEGUNDA) == []


def test_amanha_passa():
    assert mapping.validar_agendamento(_ag(data=TERCA), hoje=SEGUNDA) == []


def test_hoje_nao_passa():
    """O calendário do site bloqueia o próprio dia: não há coleta no mesmo
    dia. Medido — em 21/09 o dia 21/09 veio `data-disabled`."""
    erros = mapping.validar_agendamento(_ag(data=SEGUNDA), hoje=SEGUNDA)

    assert erros
    assert "hoje" in erros[0].lower()


def test_ontem_nao_passa():
    erros = mapping.validar_agendamento(_ag(data=date(2026, 9, 20)),
                                        hoje=SEGUNDA)
    assert erros


@pytest.mark.parametrize("fim_de_semana", [SABADO, DOMINGO])
def test_fim_de_semana_nao_passa(fim_de_semana):
    """Sábado e domingo vêm bloqueados no calendário. Clicar numa célula
    bloqueada não dá erro: não faz NADA, e o painel fica parado com cara de
    travado — o pior jeito de falhar que existe."""
    erros = mapping.validar_agendamento(_ag(data=fim_de_semana), hoje=SEGUNDA)

    assert erros
    assert "útil" in erros[0].lower() or "semana" in erros[0].lower()


# -------------------------------------------------------------------- hora
def test_hora_fora_da_grade_nao_passa():
    """18:20 não existe no select. Mandar isso faria o robô procurar uma
    opção que não está lá e desistir no timeout, 45 segundos depois."""
    erros = mapping.validar_agendamento(_ag(hora_limite="18:20"), hoje=SEGUNDA)

    assert erros
    assert "18:20" in erros[0]


def test_hora_depois_do_expediente_nao_passa():
    assert mapping.validar_agendamento(_ag(hora_limite="19:00"), hoje=SEGUNDA)


# ------------------------------------------------------------------ almoço
def test_sem_almoco_passa():
    """O caso comum: o checkbox fica desmarcado e os dois selects nem
    existem no DOM."""
    assert mapping.validar_agendamento(
        _ag(almoco_inicio=None, almoco_fim=None), hoje=SEGUNDA) == []


def test_almoco_completo_passa():
    assert mapping.validar_agendamento(
        _ag(almoco_inicio="12:00", almoco_fim="13:00"), hoje=SEGUNDA) == []


def test_almoco_pela_metade_nao_passa():
    """Só o começo, sem o fim. O site tem os dois selects sempre juntos, e
    meia informação viraria um horário que ninguém escolheu."""
    erros = mapping.validar_agendamento(
        _ag(almoco_inicio="12:00", almoco_fim=None), hoje=SEGUNDA)

    assert erros


def test_almoco_que_termina_antes_de_comecar_nao_passa():
    """O site deixa escolher os dois livremente — nada impede 13:00 às
    12:00 lá. Aqui impede: é um almoço que não existe, e o coletador leria
    uma janela invertida."""
    erros = mapping.validar_agendamento(
        _ag(almoco_inicio="13:00", almoco_fim="12:00"), hoje=SEGUNDA)

    assert erros


def test_almoco_de_duracao_zero_nao_passa():
    erros = mapping.validar_agendamento(
        _ag(almoco_inicio="12:00", almoco_fim="12:00"), hoje=SEGUNDA)

    assert erros


def test_almoco_fora_da_grade_do_almoco_nao_passa():
    """08:00 existe na grade da COLETA e não na do almoço."""
    erros = mapping.validar_agendamento(
        _ag(almoco_inicio="08:00", almoco_fim="12:00"), hoje=SEGUNDA)

    assert erros


# --------------------------------------------------------------- observação
def test_observacao_e_opcional():
    assert mapping.validar_agendamento(_ag(observacao=""), hoje=SEGUNDA) == []


def test_observacao_longa_demais_nao_passa():
    """Campo de texto sem limite visível no site é convite para colar um
    e-mail inteiro. O coletador lê isso num aplicativo de celular."""
    erros = mapping.validar_agendamento(
        _ag(observacao="x" * 1000), hoje=SEGUNDA)

    assert erros


# ------------------------------------------------- vários erros de uma vez
def test_junta_todos_os_erros_em_vez_de_parar_no_primeiro():
    """Quem preencheu errado merece ver tudo de uma vez, e não descobrir um
    problema por vez a cada tentativa."""
    erros = mapping.validar_agendamento(
        _ag(data=SABADO, hora_limite="19:00", almoco_inicio="13:00",
            almoco_fim="12:00"), hoje=SEGUNDA)

    assert len(erros) >= 3
