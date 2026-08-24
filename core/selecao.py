"""Com quais transportadoras esta cotação vai falar.

Guardado numa coluna só (`cotacao.transportadoras`), com TRÊS estados:

    NULL    ninguém mexeu no filtro   -> TODAS
    ""      mexeu e desmarcou tudo    -> nenhuma
    "a,b"   escolheu essas            -> só essas

A diferença entre `NULL` e `""` é o que faz as cotações anteriores ao filtro
continuarem certas sem migrar dado nenhum — e é o erro caro se confundida:
num sentido o sistema para de cotar calado, no outro cota em quem o vendedor
tinha tirado de propósito.

`NULL` também é o que mantém a coisa correta no tempo: guardar a lista
inteira quando tudo está marcado funcionaria hoje e quebraria no dia em que
a transportadora nº 18 entrasse — as cotações antigas passariam a excluí-la
sem ninguém ter pedido.
"""

from __future__ import annotations

from collections.abc import Iterable

SEPARADOR = ","


def entra(slug: str, escolhidas: str | None) -> bool:
    """Esta transportadora participa da cotação?

    Compara item a item, e não com `in` na string crua: `"trans" in
    "translovato"` é verdadeiro, e bastaria um slug novo ser pedaço de outro
    para uma transportadora entrar de carona sem ninguém notar.
    """
    if escolhidas is None:
        return True
    return slug in escolhidas.split(SEPARADOR)


def para_guardar(escolhidas: Iterable[str],
                 todas: Iterable[str]) -> str | None:
    """O que gravar na coluna, a partir do que veio marcado no formulário.

    Descarta slug que não está em `todas`: o formulário é HTML numa rede
    interna, e não custa nada não acreditar nele.
    """
    conhecidas = list(todas)
    marcadas = [s for s in conhecidas if s in set(escolhidas)]
    if len(marcadas) == len(conhecidas):
        return None                      # todas — inclusive as futuras
    return SEPARADOR.join(marcadas)      # "" quando nada foi marcado
