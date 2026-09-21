"""Até quando ainda dá para aceitar — a regra, longe de tela e de navegador.

Uma função de três linhas com teste desproporcional de propósito: é ela que
decide se o botão "Aceitar" aparece, e os dois erros que ela pode cometer são
caros em direções opostas.

Esconder cedo demais faz o vendedor ligar para a transportadora para fazer à
mão uma coisa que o sistema faria sozinho. Esconder tarde demais manda o robô
tentar agendar um preço que venceu — e aí, ou o portal recusa (e o vendedor
leva um erro técnico na cara sem entender o porquê), ou o portal ACEITA por
outro valor, e a Ventura combinou um frete que ninguém cotou.

O dia da validade CONTA. "Cotação válida até 28/09" quer dizer que no dia 28
ainda dá — é o que o próprio site escreve logo abaixo: "válido para
contratação até dia 28/09/26".
"""

from __future__ import annotations

from datetime import date

from core import aceite


# ------------------------------------------------------------ vencida ou não
def test_antes_da_validade_ainda_da():
    assert aceite.vencida(date(2026, 9, 28), hoje=date(2026, 9, 21)) is False


def test_no_proprio_dia_da_validade_ainda_da():
    """O erro de sinal mais fácil de cometer aqui, e o mais caro: usar `<`
    em vez de `<=` tira o botão no último dia em que ele deveria existir —
    justamente o dia em que o vendedor corre para fechar."""
    assert aceite.vencida(date(2026, 9, 28), hoje=date(2026, 9, 28)) is False


def test_no_dia_seguinte_venceu():
    assert aceite.vencida(date(2026, 9, 28), hoje=date(2026, 9, 29)) is True


def test_sem_validade_nao_e_considerada_vencida():
    """Cinco das seis transportadoras não dizem até quando o preço vale.

    NULL é "não sabemos", e "não sabemos" não pode virar "venceu": isso
    esconderia o botão de toda transportadora que nunca informou validade.
    Quem decide o que fazer com a ignorância é quem chama."""
    assert aceite.vencida(None, hoje=date(2026, 9, 29)) is False


# ------------------------------------------------------------------ rótulo
def test_rotulo_diz_ate_quando_vale():
    assert aceite.rotulo_validade(
        date(2026, 9, 28), hoje=date(2026, 9, 21)) == "até 28/09"


def test_rotulo_do_ultimo_dia_avisa_que_e_hoje():
    """"até 28/09" no dia 28 é verdade e não ajuda: o vendedor precisa saber
    que é a última chance HOJE, sem ter que conferir a data no relógio."""
    assert aceite.rotulo_validade(
        date(2026, 9, 28), hoje=date(2026, 9, 28)) == "vence hoje"


def test_rotulo_de_amanha_tambem_avisa():
    assert aceite.rotulo_validade(
        date(2026, 9, 28), hoje=date(2026, 9, 27)) == "vence amanhã"


def test_rotulo_de_vencida_diz_quando_venceu():
    """Não basta dizer "vencida": sem a data, o vendedor não sabe se perdeu
    por um dia ou por um mês — e isso muda o que ele faz em seguida."""
    assert aceite.rotulo_validade(
        date(2026, 9, 28), hoje=date(2026, 10, 5)) == "venceu em 28/09"


def test_sem_validade_nao_inventa_rotulo():
    assert aceite.rotulo_validade(None, hoje=date(2026, 9, 21)) == ""


def test_hoje_e_opcional_e_usa_o_dia_de_verdade():
    """Quem chama da tela não passa `hoje` — o default precisa ser o dia de
    hoje de verdade, senão a validade congela no dia do deploy."""
    assert aceite.vencida(date.today()) is False
    assert aceite.rotulo_validade(date.today()) == "vence hoje"
