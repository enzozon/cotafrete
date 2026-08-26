"""Quantas transportadoras rodam juntas, quantas vezes se tenta de novo, e
quando parar de tentar.

As quatro decisões moram no mesmo arquivo porque dependem umas das outras: o
número de vagas de navegador decide quanto tempo cada uma espera na fila, e
esse tempo tem que caber dentro do prazo em que a tela ainda está olhando.
Separadas, uma muda e a outra não vai junto.

## A regra de repetir

Ela NÃO olha o tipo da exceção. Olha o status:

    ERRO      -> "não sabemos o que aconteceu"  -> repete
    o resto   -> a transportadora já respondeu  -> não repete

Isso foi aprendido na cotação #46, em 24/08/2026. A Jadlog devolveu
`TimeoutError: Page.wait_for_function: Timeout 45000ms exceeded`, que tem
toda a cara de problema passageiro — e era recusa definitiva: o site tinha
desabilitado o botão porque a caixa passava de 30 kg, e o adapter ficou os
45 segundos inteiros esperando um preço que nunca ia renderizar. Uma regra
por tipo de exceção teria repetido aquilo três vezes.

Por isso a classificação é feita na FONTE: cada adapter marca recusa como
`RECUSADO`, e só o que ele realmente não entendeu vira `ERRO`.

## A fila

Não existe fila explícita: o semáforo já é uma. Quem falha solta a vaga,
espera a pausa e pede outra — e entra atrás de quem já estava esperando.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from carriers.base import ResultadoCotacao
from core.models import CotacaoRequest, StatusCotacao

# Cada transportadora abre um Chromium INTEIRO. Com duas dava para rodar todas
# juntas; com a Translovato virando a terceira, em 18/08/2026 o Camilo passou a
# estourar 45s esperando um formulário que, sozinho, carrega em 25s. Não foi o
# site: foi a máquina sem CPU sobrando.
#
# O limite é físico, não de threads — por isso um semáforo próprio e não
# max_workers: as tarefas continuam sendo aceitas na hora, só esperam vaga de
# navegador. Vale rever este número ao mudar de máquina/servidor.
NAVEGADORES_SIMULTANEOS = 2
VAGA_NAVEGADOR = threading.Semaphore(NAVEGADORES_SIMULTANEOS)

# Depois disto a tela para de recarregar e assume que não vem mais nada.
#
# Eram 240s, dimensionados quando a mais lenta era a Camilo com ~25s. Seis
# rodadas reais em 24/08/2026 mostraram que não cabia mais: uma tentativa da
# Translovato custa ~120s (timeout próprio de 60s, mais login e formulário),
# e a rodada em que a repetição dela DEU CERTO terminou em 274s — a tela já
# tinha dito "não responderam" aos 240s, com o preço certo no banco.
#
# 300s comporta duas tentativas da mais cara (120 + 5 de pausa + 120). O
# vendedor não fica olhando tela vazia: a Camilo responde em ~25s e a página
# se atualiza sozinha mostrando quem falta.
ESPERA_MAXIMA_S = 300

# Três cobre tropeço de rede e login que não pegou, e é pouco o bastante para
# não martelar a conta da Ventura: são três logins seguidos no mesmo usuário,
# e site nenhum gosta de mais que isso.
TENTATIVAS_MAXIMAS = 3

# Quem NÃO pode ser repetida, por slug.
#
# A regra normal ("repete quando o status é ERRO") supõe que uma tentativa a
# mais não custa nada além de uma vaga de navegador. Isso vale para as quatro
# primeiras: todas são auto-serviço, e repetir só refaz uma consulta.
#
# A Della Volpe não. Cada submissão do formulário público dela vira uma
# cotação na fila de um vendedor DE VERDADE — e `normalizar_resposta` devolve
# ERRO justamente no caso em que o site ACEITOU o envio e quem falhou foi a
# nossa leitura da confirmação. Repetir ali coloca a segunda cotação na mesa
# de uma pessoa, por um único clique do vendedor da Ventura.
#
# Nominal e não uma regra geral porque a repetição já salvou cotações reais
# (a Translovato na rodada de 24/08/2026): desligá-la por tabela custaria
# preço de verdade.
SEM_REPETICAO = frozenset({"dellavolpe"})

# Respirar entre as tentativas. Fica FORA da vaga de navegador de propósito:
# dormir segurando a vaga faria as outras transportadoras esperarem por nada.
PAUSA_ENTRE_TENTATIVAS_S = 5

def vale_repetir(res: ResultadoCotacao) -> bool:
    """Só `ERRO` se repete: é o único status que significa 'não sabemos'.

    `RECUSADO`, `COTADO` e `AGUARDANDO_RETORNO` são todos respostas da
    transportadora. Repetir qualquer um deles dá o mesmo resultado e rouba
    uma vaga de navegador de quem ainda pode dar preço.
    """
    return res.status is StatusCotacao.ERRO


def _cabe_outra(inicio: float, custo_da_ultima: float) -> bool:
    """Sobra prazo para mais uma tentativa antes de a tela desistir?

    O custo estimado da próxima é o custo MEDIDO da anterior — não um número
    fixo. A versão com margem fixa de 60s deixou uma cotação chegar a 308s
    num teto de 240s, porque uma tentativa da Translovato custa o dobro
    disso. Medir dispensa acertar o chute para cada transportadora, e se
    amanhã um site ficar mais lento a conta se ajusta sozinha.
    """
    return (time.monotonic() - inicio) + custo_da_ultima < ESPERA_MAXIMA_S


def cotar_com_retentativa(
    cotar_fn: Callable[[CotacaoRequest], ResultadoCotacao],
    req: CotacaoRequest,
    *,
    inicio: float | None = None,
    ao_tentar: Callable[[int], None] | None = None,
    repetir: bool = True,
) -> ResultadoCotacao:
    """Roda a transportadora, repetindo enquanto o erro for 'não sabemos'.

    `inicio` é o `time.monotonic()` da criação da cotação — é dele que sai o
    prazo. Omitido, assume agora, que é o caso de quem dispara na hora.

    `ao_tentar(n)` avisa a cada tentativa, antes de pedir vaga de navegador.
    É o que permite ao cartão dizer "tentando de novo (2 de 3)" em vez de
    ficar três minutos em "cotando…" sem explicar nada.

    A exceção da última tentativa ESCAPA de propósito: quem chama precisa
    dela para gravar o cartão vermelho. Engolir aqui deixaria o cartão
    girando para sempre.

    `repetir=False` roda UMA vez e entrega o que vier — é para quem está em
    SEM_REPETICAO, onde uma segunda tentativa custa o tempo de uma pessoa e
    não uma vaga de navegador.
    """
    inicio = time.monotonic() if inicio is None else inicio

    maximo = TENTATIVAS_MAXIMAS if repetir else 1

    for tentativa in range(1, maximo + 1):
        if ao_tentar is not None:
            ao_tentar(tentativa)

        # Cronometra a espera por vaga JUNTO com a cotação: as duas contam
        # para o prazo, e numa máquina ocupada a fila pesa tanto quanto o site.
        comecou = time.monotonic()
        try:
            with VAGA_NAVEGADOR:
                res = cotar_fn(req)
        except Exception:
            if tentativa == maximo or not _cabe_outra(
                    inicio, time.monotonic() - comecou):
                raise
        else:
            if (not vale_repetir(res) or tentativa == maximo
                    or not _cabe_outra(inicio, time.monotonic() - comecou)):
                return res

        time.sleep(PAUSA_ENTRE_TENTATIVAS_S)

    # Inalcançável: na volta `maximo`, `ultima` é sempre True e o laço sai
    # por `return` ou por `raise`.
    raise AssertionError("laço de retentativa terminou sem resultado")
