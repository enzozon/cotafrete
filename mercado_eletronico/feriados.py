"""Feriados que empurram a data de entrega para o próximo dia útil.

O prazo no Mercado Eletrônico é em dias CORRIDOS — o próprio site faz a conta
assim: 23/09/2026 + 45 dias = 07/11 (sábado), e ele mostra 09/11. A regra
daqui só entra no fim: se a data cair em sábado, domingo ou feriado, vai para
o próximo dia útil.

Nacionais + os móveis que o comércio observa (Carnaval e Corpus Christi são
ponto facultativo na lei, mas na prática ninguém entrega). Feriado municipal
fica de fora por decisão do usuário (23/09/2026).
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

FIXOS: tuple[tuple[int, int, str], ...] = (
    (1, 1, "Confraternização Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independência"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamação da República"),
    (11, 20, "Consciência Negra"),  # nacional desde a Lei 14.759/2023
    (12, 25, "Natal"),
)


def pascoa(ano: int) -> date:
    """Domingo de Páscoa pelo algoritmo de Meeus/Jones/Butcher (gregoriano)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


@lru_cache(maxsize=None)
def feriados(ano: int) -> dict[date, str]:
    p = pascoa(ano)
    lista = {date(ano, m, d): nome for m, d, nome in FIXOS}
    lista[p - timedelta(days=48)] = "Carnaval (segunda)"
    lista[p - timedelta(days=47)] = "Carnaval (terça)"
    lista[p - timedelta(days=2)] = "Sexta-feira Santa"
    lista[p + timedelta(days=60)] = "Corpus Christi"
    return lista


def eh_dia_util(dia: date) -> bool:
    return dia.weekday() < 5 and dia not in feriados(dia.year)


def proximo_dia_util(dia: date) -> date:
    """O próprio dia, se for útil; senão o primeiro útil depois dele."""
    while not eh_dia_util(dia):
        dia += timedelta(days=1)
    return dia
