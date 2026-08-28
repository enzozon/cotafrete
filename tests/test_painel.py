"""As contas do dashboard. Camada PURA: recebe conexão, devolve dicionário.

Nenhum HTML mora aqui, pelo mesmo motivo de carriers/*/mapping.py: o risco
está na conta, e conta se testa sem navegador.

Os números da tela são a razão de a tela existir. Um aproveitamento errado
manda o Enzo cobrar a transportadora errada."""

from __future__ import annotations

import pytest

from core.banco import Banco
from core import painel

CARGA = {"cep_origem": "29105770", "cep_destino": "01310100",
         "cidade_origem": "Vila Velha", "cidade_destino": "São Paulo",
         "peso_kg": "10", "quantidade": 1, "comprimento_cm": 30,
         "largura_cm": 30, "altura_cm": 30, "valor_nf": "1000",
         "material": "PLACA DE VIDEO"}


@pytest.fixture
def db(tmp_path):
    return Banco(tmp_path / "painel.db")


def test_classifica_cada_status_como_a_spec_manda():
    assert painel.categoria("cotado") == "sucesso"
    assert painel.categoria("aguardando_retorno") == "sucesso"
    assert painel.categoria("recusado") == "recusa"
    assert painel.categoria("erro") == "falha"
    assert painel.categoria("intervencao_necessaria") == "falha"
    assert painel.categoria("interrompido") == "nossa"
    assert painel.categoria("coisa_nova") == "inesperado"


def test_aguardando_retorno_e_sucesso_e_nao_falha():
    """A Della Volpe recebeu e o preço vem por e-mail. Contar como falha
    jogaria ela para o vermelho todo dia, sem nada de errado."""
    assert painel.categoria("aguardando_retorno") == "sucesso"


def test_interrompido_fica_fora_do_aproveitamento(db):
    """É o servidor reiniciando no meio — coisa nossa. Descontar isso da
    transportadora seria puni-la por um restart que ela não causou."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado")
    db.salvar_resultado(cid, "jadlog", status="interrompido")

    with db._conectar() as con:
        linhas = {l["transportadora"]: l
                  for l in painel.saude_das_transportadoras(con, dias=30)}

    assert linhas["camilo"]["aproveitamento"] == 1.0
    assert linhas["jadlog"]["nossa"] == 1
    assert linhas["jadlog"]["aproveitamento"] is None, \
        "sem nada no denominador, aproveitamento é desconhecido, não zero"


def test_aproveitamento_conta_recusa_no_denominador(db):
    """Recusa não é defeito, mas também não é preço: entra na conta."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado")
    cid2 = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid2, "camilo", status="recusado")

    with db._conectar() as con:
        linha = painel.saude_das_transportadoras(con, dias=30)[0]

    assert linha["sucesso"] == 1 and linha["recusa"] == 1
    assert linha["aproveitamento"] == 0.5


def test_resumo_conta_cotacao_que_ficou_sem_nenhum_preco(db):
    """A métrica que mais importa: o vendedor ficou na mão."""
    boa = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(boa, "camilo", status="cotado")
    ruim = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(ruim, "camilo", status="erro")
    db.salvar_resultado(ruim, "jadlog", status="recusado")

    with db._conectar() as con:
        r = painel.resumo_do_dia(con)

    assert r["cotacoes"] == 2
    assert r["com_preco"] == 1
    assert r["sem_nenhum_preco"] == 1


def test_banco_vazio_nao_quebra(db):
    """Pasta nova, primeiro dia. A tela precisa abrir mesmo assim."""
    with db._conectar() as con:
        assert painel.saude_das_transportadoras(con, dias=30) == []
        assert painel.resumo_do_dia(con)["cotacoes"] == 0
