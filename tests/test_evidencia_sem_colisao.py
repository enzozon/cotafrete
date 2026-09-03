"""A pasta de evidência (print) de cada cotação real usava só data+hora até
o SEGUNDO ("%Y%m%d-%H%M%S") como nome. Duas cotações da MESMA transportadora
rodando no mesmo segundo caem na mesma pasta, e a segunda sobrescreve o
print da primeira.

Achado em 03/09/2026 comparando as cotações #130 e #131: o print salvo no
banco para a #130 (teste_real/generoso/20260903-162917/erro.png) na verdade
mostra os dados da #131 (BRX Sistemas), não os da #130 (Aliança/Profarma) —
as duas rodaram próximas o suficiente para colidir na mesma pasta.

O texto do erro em si (coluna `erro` do banco) não é afetado — é gravado
direto, sem passar pelo disco. Só a IMAGEM de evidência pode estar trocada.

Vale para as seis transportadoras que tiram print (todas menos Jadlog-API,
que não abre navegador), porque todas usavam o mesmo `strftime`.
"""

from __future__ import annotations

import inspect

import pytest

ADAPTERS = (
    ("carriers.braspress.adapter", "BraspressAdapter", "cotar"),
    ("carriers.camilo.adapter", "CamiloAdapter", "cotar"),
    ("carriers.dellavolpe.adapter", "DellavolpeAdapter", "cotar"),
    ("carriers.generoso.adapter", "GenerosoAdapter", "cotar"),
    ("carriers.translovato.adapter", "TranslovatoAdapter", "cotar"),
    ("carriers.jadlog.painel", "JadlogPainelAdapter", "cotar"),
)


@pytest.mark.parametrize("modulo,classe,metodo", ADAPTERS,
                         ids=[c for _, c, _ in ADAPTERS])
def test_pasta_de_evidencia_tem_precisao_de_microssegundo(modulo, classe, metodo):
    """Smoke test: mais barato que rodar duas cotações reais concorrentes, e
    quebra se alguém voltar a truncar o timestamp em segundo — a mesma forma
    já usada para test_cotar_esta_protegido_pela_trava_da_conta."""
    mod = __import__(modulo, fromlist=[classe])
    fonte = inspect.getsource(getattr(getattr(mod, classe), metodo))

    assert '"%Y%m%d-%H%M%S-%f"' in fonte, (
        f"{classe}.{metodo} voltou a usar timestamp só até o segundo — "
        f"duas cotações concorrentes podem sobrescrever o print uma da outra")
