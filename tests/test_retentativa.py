"""Repetir o que falhou; nunca repetir o que foi recusado.

A diferenca que este arquivo protege e a que custou a cotacao #46 em
24/08/2026: a Jadlog devolveu `TimeoutError: Page.wait_for_function: Timeout
45000ms exceeded`, que TEM cara de problema passageiro — e era recusa
definitiva. O site tinha bloqueado o botao porque a caixa passava de 30 kg, e
o adapter ficou 45 segundos esperando um preco que nunca ia renderizar.

Por isso a regra NAO olha o tipo da excecao. Ela olha o status:

    ERRO      -> "nao sabemos o que aconteceu"  -> repete
    o resto   -> a transportadora ja respondeu  -> nao repete

`RECUSADO`, `COTADO` e `AGUARDANDO_RETORNO` sao todos respostas. Repetir
qualquer um deles da exatamente o mesmo resultado e gasta uma vaga de
navegador que outra transportadora esta esperando.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from carriers.base import (
    CredencialRecusada, ResultadoCotacao, erro_do_adapter,
)
from carriers.camilo.adapter import CamiloAdapter
from carriers.generoso.adapter import GenerosoAdapter
from carriers.jadlog.painel import JadlogPainelAdapter
from carriers.translovato.adapter import TranslovatoAdapter
from core import retentativa as r
from core.models import Local, Solicitante, StatusCotacao, Volume
from tests.test_jadlog import montar


@pytest.fixture
def sem_pausa(monkeypatch):
    """A pausa entre tentativas existe para nao martelar o login das
    transportadoras. Num teste ela so faria a suite levar 10 segundos."""
    monkeypatch.setattr(r, "PAUSA_ENTRE_TENTATIVAS_S", 0)


def _resultado(status: StatusCotacao, **kw) -> ResultadoCotacao:
    return ResultadoCotacao("teste", status, **kw)


def _contador(*respostas):
    """Transportadora de mentira que devolve `respostas` em ordem, repetindo
    a ultima quando acabam.

    Nao e mock: e uma funcao de verdade, com a mesma assinatura de
    `_cotar_camilo` e companhia. O que ela guarda e quantas vezes foi
    chamada — que e exatamente o que os testes precisam afirmar.
    """
    chamadas: list[int] = []

    def cotar(req):
        chamadas.append(len(chamadas) + 1)
        resposta = respostas[min(len(chamadas), len(respostas)) - 1]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    return cotar, chamadas


# ------------------------------------------------------- o que NAO se repete
def test_recusa_nao_repete():
    """A Translovato dizendo 'so cota saindo da Ventura'. Repetir da a mesma
    resposta e rouba a vaga de navegador de quem ainda pode dar preco."""
    cotar, chamadas = _contador(
        _resultado(StatusCotacao.RECUSADO, motivo_recusa="so sai da Ventura"))

    res = r.cotar_com_retentativa(cotar, montar())

    assert chamadas == [1]
    assert res.status is StatusCotacao.RECUSADO


def test_cotacao_bem_sucedida_nao_repete():
    cotar, chamadas = _contador(_resultado(StatusCotacao.COTADO))

    res = r.cotar_com_retentativa(cotar, montar())

    assert chamadas == [1]
    assert res.status is StatusCotacao.COTADO


def test_resposta_por_email_nao_repete():
    """A Generoso deslogada confirma o recebimento e manda o preco por e-mail.
    E resposta valida, nao falha."""
    cotar, chamadas = _contador(_resultado(StatusCotacao.AGUARDANDO_RETORNO))

    r.cotar_com_retentativa(cotar, montar())

    assert chamadas == [1]


# ---------------------------------------------------------- o que se repete
def test_erro_repete_ate_o_limite(sem_pausa):
    cotar, chamadas = _contador(_resultado(StatusCotacao.ERRO,
                                           erro="TimeoutError"))

    res = r.cotar_com_retentativa(cotar, montar())

    assert chamadas == [1, 2, 3]
    assert r.TENTATIVAS_MAXIMAS == 3
    assert res.status is StatusCotacao.ERRO


def test_erro_que_passa_na_segunda_para_ali(sem_pausa):
    """O caso da Generoso: o login nao passou uma vez, passou na seguinte."""
    cotar, chamadas = _contador(
        _resultado(StatusCotacao.ERRO, erro="login nao passou"),
        _resultado(StatusCotacao.COTADO))

    res = r.cotar_com_retentativa(cotar, montar())

    assert chamadas == [1, 2]
    assert res.status is StatusCotacao.COTADO


def test_excecao_tambem_repete_e_a_ultima_escapa(sem_pausa):
    """Excecao que sobe do adapter e o mesmo que ERRO: ninguem sabe o que
    houve. Depois da ultima ela precisa escapar, para o `_rodar` gravar o
    cartao vermelho — engolir aqui deixaria o cartao girando para sempre."""
    cotar, chamadas = _contador(RuntimeError("navegador morreu"))

    with pytest.raises(RuntimeError):
        r.cotar_com_retentativa(cotar, montar())

    assert chamadas == [1, 2, 3]


def test_excecao_seguida_de_sucesso_nao_escapa(sem_pausa):
    cotar, chamadas = _contador(RuntimeError("navegador morreu"),
                                _resultado(StatusCotacao.COTADO))

    res = r.cotar_com_retentativa(cotar, montar())

    assert chamadas == [1, 2]
    assert res.status is StatusCotacao.COTADO


# --------------------------------------------------------- orcamento de tempo
def test_nao_comeca_tentativa_que_nao_cabe_no_prazo(sem_pausa):
    """A tela desiste em ESPERA_MAXIMA_S contados da CRIACAO da cotacao.

    Comecar uma tentativa faltando poucos segundos para o teto produz um
    resultado que chega depois de a tela ter desistido — trabalho jogado
    fora, com uma vaga de navegador ocupada no caminho.
    """
    cotar, chamadas = _contador(_resultado(StatusCotacao.ERRO, erro="timeout"))
    ja_estourou = time.monotonic() - r.ESPERA_MAXIMA_S

    res = r.cotar_com_retentativa(cotar, montar(), inicio=ja_estourou)

    assert chamadas == [1], "sem tempo para a segunda, devia parar na primeira"
    assert res.status is StatusCotacao.ERRO


def test_com_tempo_de_sobra_usa_todas_as_tentativas(sem_pausa):
    cotar, chamadas = _contador(_resultado(StatusCotacao.ERRO, erro="timeout"))

    r.cotar_com_retentativa(cotar, montar(), inicio=time.monotonic())

    assert chamadas == [1, 2, 3]


def test_o_custo_da_proxima_e_medido_pela_anterior(sem_pausa, monkeypatch):
    """A rodada real de 24/08/2026 estourou o teto por causa de um chute.

    A Translovato falhou aos ~120s, o orcamento supunha que a proxima
    custaria 60s (MARGEM_TENTATIVA_S) e liberou — a cotacao terminou em
    308s, com a tela tendo desistido aos 240s. O resultado chegou certo no
    banco e a tela ja tinha dito "nao responderam".

    O melhor palpite para o custo da proxima tentativa e o custo da
    anterior. Nao e chute: e medicao.
    """
    monkeypatch.setattr(r, "ESPERA_MAXIMA_S", 1)
    chamadas: list[int] = []

    def cotar_caro(req):
        chamadas.append(len(chamadas) + 1)
        time.sleep(0.6)          # sozinha ja gasta mais da metade do teto
        return _resultado(StatusCotacao.ERRO, erro="timeout")

    r.cotar_com_retentativa(cotar_caro, montar())

    assert chamadas == [1], "duas dessas nao cabem no teto; nao podia repetir"


def test_tentativa_barata_ainda_ganha_as_tres_chances(sem_pausa, monkeypatch):
    """O contrario: falha rapida cabe de sobra e continua sendo repetida."""
    monkeypatch.setattr(r, "ESPERA_MAXIMA_S", 1)
    cotar, chamadas = _contador(_resultado(StatusCotacao.ERRO, erro="login"))

    r.cotar_com_retentativa(cotar, montar())

    assert chamadas == [1, 2, 3]


# ------------------------------------------- senha errada nao pode ser martelo
def test_credencial_recusada_pede_intervencao_em_vez_de_repetir():
    """Senha errada repetida 3x por cotacao, com a equipe cotando o dia
    inteiro, TRAVA a conta da Ventura — e aí toda cotacao passa a falhar.

    O historico justifica o cuidado: em 51 cotacoes ate 24/08/2026 houve 5
    falhas de login na Jadlog e 1 na Generoso. Repetir uma recusa de
    credencial nao conserta nada; alguem tem que ir no .env.
    """
    res = erro_do_adapter("jadlog", CredencialRecusada("senha trocada"))

    assert res.status is StatusCotacao.INTERVENCAO_NECESSARIA
    assert not r.vale_repetir(res)
    assert "senha trocada" in res.erro


def test_erro_desconhecido_continua_repetivel():
    """O contrario da regra acima: timeout ninguem sabe explicar, entao
    tenta de novo."""
    res = erro_do_adapter("jadlog", TimeoutError("Timeout 45000ms exceeded"))

    assert res.status is StatusCotacao.ERRO
    assert r.vale_repetir(res)


# -------------------------------------- a classificacao na fonte: os adapters
def _sem_cep():
    return montar(origem=Local(uf="ES", cidade="Vitória"))


def _caixa_de_40kg():
    return montar(volumes=[Volume(qtd=2, comprimento_cm=Decimal(40),
                                  largura_cm=Decimal(40),
                                  altura_cm=Decimal(80),
                                  peso_kg=Decimal(40))])


def _sem_whatsapp():
    return montar(solicitante=Solicitante(nome="Enzo", email="e@ex.com",
                                          whatsapp=""))


@pytest.mark.parametrize("construir_adapter, construir_req", [
    (lambda: CamiloAdapter(), _sem_cep),
    (lambda: JadlogPainelAdapter(), _caixa_de_40kg),
    (lambda: TranslovatoAdapter(), _sem_cep),
    (lambda: GenerosoAdapter(), _sem_whatsapp),
])
def test_carga_reprovada_na_validacao_vira_recusa_e_nao_erro(
        construir_adapter, construir_req):
    """Carga que a transportadora nao aceita e RECUSA, nao erro.

    Enquanto isso saia como `ERRO`, a retentativa nao tem como saber que
    repetir e inutil — e gastaria tres tentativas para chegar na mesma
    resposta. E como o cartao da tela le o status, `ERRO` ainda fazia a
    recusa aparecer como se o sistema tivesse quebrado.

    Nenhum destes abre navegador: os quatro validam antes de subir o
    Chromium, e e justamente por isso que a resposta e instantanea.
    """
    res = construir_adapter().cotar(construir_req())

    assert res.status is StatusCotacao.RECUSADO
    assert res.motivo_recusa, "a recusa precisa dizer o motivo para o vendedor"
    assert res.erro is None
    assert not r.vale_repetir(res)


# ---------------------------------------------------------- aviso para a tela
def test_avisa_cada_tentativa_para_a_tela_poder_mostrar(sem_pausa):
    """Sem isto o cartao fica 'cotando...' por tres minutos sem explicar."""
    cotar, _ = _contador(_resultado(StatusCotacao.ERRO, erro="timeout"))
    vistas: list[int] = []

    r.cotar_com_retentativa(cotar, montar(), ao_tentar=vistas.append)

    assert vistas == [1, 2, 3]
