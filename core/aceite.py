"""Até quando uma cotação ainda pode ser aceita.

Camada PURA: sem tela, sem navegador, sem banco. Três chamadores dependem
dela e precisam concordar — a tabela de resultados (mostrar ou não o botão),
a rota que recebe o clique (aceitar ou recusar o pedido) e o adapter (não
levar ao portal um preço vencido). Se a regra morasse em cada um, bastaria um
esquecer para o sistema oferecer um botão que o próprio servidor recusa.

Os dois erros possíveis são caros em direções opostas:

- cedo demais: o botão some enquanto ainda dava, e o vendedor liga para a
  transportadora para fazer à mão o que o sistema faria sozinho;
- tarde demais: o robô tenta agendar um preço vencido. Ou o portal recusa, e
  o vendedor leva um erro técnico sem entender por quê, ou o portal ACEITA
  por outro valor — e a Ventura combinou um frete que ninguém cotou.
"""

from __future__ import annotations

from datetime import date, timedelta


def vencida(validade: date | None, hoje: date | None = None) -> bool:
    """A cotação passou do dia em que ainda podia ser contratada?

    `None` devolve False, e isso é decisão, não descuido: cinco das seis
    transportadoras não informam validade, e tratar "não sabemos" como
    "venceu" esconderia o botão de todas elas para sempre. Quem chama é que
    decide o que fazer com a ignorância.

    `>` e não `>=`: "válida até 28/09" quer dizer que no dia 28 ainda dá —
    é o que o próprio site escreve, "válido para contratação até dia
    28/09/26". Trocar o sinal tira o botão no último dia em que ele mais
    importa, justamente quando o vendedor corre para fechar."""
    if validade is None:
        return False
    return (hoje or date.today()) > validade


def rotulo_validade(validade: date | None, hoje: date | None = None) -> str:
    """Como a tela diz isso em duas ou três palavras.

    "até 28/09" é verdade no dia 28 e não ajuda: quem lê não sabe que é a
    última chance sem conferir a data no relógio. Por isso os dois últimos
    dias ganham nome próprio.

    A vencida diz QUANDO venceu. Só "vencida" deixa o vendedor sem saber se
    perdeu por um dia ou por um mês, e isso muda o que ele faz em seguida."""
    if validade is None:
        return ""
    hoje = hoje or date.today()
    if hoje > validade:
        return f"venceu em {validade:%d/%m}"
    if hoje == validade:
        return "vence hoje"
    if hoje + timedelta(days=1) == validade:
        return "vence amanhã"
    return f"até {validade:%d/%m}"
