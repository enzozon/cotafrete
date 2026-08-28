"""A Generoso dizendo que não conhece o CNPJ — e por que isso não é um erro.

Cotação #56 (28/08/2026), FOB saindo de um fornecedor em Lauro de Freitas:

    RuntimeError: o CNPJ 41.747.639/0001-12 nao trouxe o endereco de origem;
    sem isso a cotacao sairia de lugar nenhum. O site diz:
    (nenhuma mensagem visivel)

Duas coisas erradas nisso. A frase é técnica, e a classificação é `ERRO` —
que a retentativa entende como "não sabemos o que houve" e repete. A Generoso
rodou três vezes (09:23:06, 09:24:34, 09:25:07) para chegar três vezes na
mesma resposta. Aconteceu de novo com o destino, num CIF, com outro CNPJ.

"(nenhuma mensagem visível)" era verdade só da TELA. O recon de 28/08/2026
(recon/recon_generoso_cnpj.py) capturou a resposta do portal, e ela é
explícita:

    conhecido    {"erro":false,"mensagem":"OK","nome":"UNIAO INFO LTDA - ME",…}
    desconhecido {"status":400,"message":"Cliente 41747639000112 nao
                  cadastrado","error":true}

A fixture é essa captura, não texto escrito à mão: foi de ler DOM inventado
que nasceu o bug do popup da SSW.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from carriers.generoso import mapping as m
from carriers.generoso.adapter import ClienteNaoCadastrado, GenerosoAdapter
from core.models import StatusCotacao
from core.retentativa import vale_repetir
from tests.test_jadlog import montar

CAPTURA = json.loads(
    (Path(__file__).parent / "fixtures" / "generoso_busca_cnpj.json")
    .read_text(encoding="utf-8"))


def test_reconhece_o_cliente_que_a_generoso_nao_tem():
    caso = CAPTURA["desconhecido"]

    assert m.cliente_nao_cadastrado(caso["corpo"]) == "41747639000112"


def test_nao_confunde_resposta_boa_com_recusa():
    """O CNPJ conhecido volta com endereço. Recusar aqui mataria cotação boa."""
    caso = CAPTURA["conhecido"]

    assert m.cliente_nao_cadastrado(caso["corpo"]) is None
    assert caso["endereco"]["city"] == "Vila Velha"


def test_sem_resposta_nenhuma_nao_e_recusa():
    """AJAX que não voltou é erro comum, e erro comum REPETE.

    É a diferença que justifica o recon: sem ela, classificar o campo vazio
    como recusa esconderia uma falha de rede de verdade."""
    assert m.cliente_nao_cadastrado("") is None
    assert m.cliente_nao_cadastrado("0:{\"a\":\"$@1\"}") is None


@pytest.mark.parametrize("lado", ["origem", "destino"])
def test_a_recusa_nomeia_o_lado_e_o_cnpj(lado):
    """Numa cotação existem DOIS CNPJs. Não dizer qual deixa o vendedor
    procurando no escuro — a mesma lição de recusa_cep_nao_atendido."""
    frase = m.recusa_cliente_nao_cadastrado("41.747.639/0001-12", lado)

    assert "41.747.639/0001-12" in frase
    assert lado in frase
    assert "WhatsApp" in frase


def test_a_recusa_nao_fala_em_erro_de_sistema():
    """A Generoso respondeu. Não há nada para consertar aqui."""
    frase = m.recusa_cliente_nao_cadastrado("41.747.639/0001-12", "origem")

    for tecniques in ("RuntimeError", "Timeout", "None", "null"):
        assert tecniques not in frase


# ------------------------------------- o que faz a repetição inútil parar
def test_cliente_nao_cadastrado_vira_recusa_e_nao_repete(tmp_path, monkeypatch):
    """RECUSADO, não ERRO — é isso que impede a terceira rodada de navegador.

    Segue a forma de `test_carga_reprovada_na_validacao_vira_recusa_e_nao_erro`
    em test_retentativa.py: o que a retentativa lê é o STATUS, e enquanto isso
    saísse como ERRO ela repetiria três vezes para ouvir o mesmo não. O cartão
    da tela lê o mesmo status, então ERRO ainda fazia a recusa da Generoso
    parecer defeito do sistema.

    `_entrar` levanta a exceção no lugar de percorrer o site: o que está sob
    teste é o ramo do `except`, e ele não deveria depender de a Generoso estar
    no ar para ser exercido. Nenhuma rede é tocada."""
    def recusar(self, page):
        raise ClienteNaoCadastrado(
            m.recusa_cliente_nao_cadastrado("41.747.639/0001-12", "origem"))

    monkeypatch.setattr(GenerosoAdapter, "_entrar", recusar)

    # usuario/senha pelo construtor: o proprio __init__ diz que e para o
    # teste. Sem eles o adapter recusa antes de subir navegador, e o ramo
    # sob teste nem seria alcancado.
    res = GenerosoAdapter(workdir=str(tmp_path), usuario="teste",
                          senha="teste").cotar(montar())

    assert res.status is StatusCotacao.RECUSADO
    assert res.erro is None, "recusa não é erro; o cartão lê isso"
    assert "41.747.639/0001-12" in (res.motivo_recusa or "")
    assert not vale_repetir(res), "repetir daria o mesmo não, custando uma vaga"
