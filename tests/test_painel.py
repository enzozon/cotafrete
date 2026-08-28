"""As contas do dashboard. Camada PURA: recebe conexão, devolve dicionário.

Nenhum HTML mora aqui, pelo mesmo motivo de carriers/*/mapping.py: o risco
está na conta, e conta se testa sem navegador.

Os números da tela são a razão de a tela existir. Um aproveitamento errado
manda o Enzo cobrar a transportadora errada."""

from __future__ import annotations

from decimal import Decimal

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


def test_historico_traz_cotacao_de_todos_os_usuarios(db):
    """É a diferença central em relação ao histórico do vendedor, que só
    mostra as dele. Aqui o adm vê a empresa inteira."""
    a = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(a, "camilo", status="cotado", valor=Decimal("100.00"))
    b = db.salvar_cotacao("leandro", CARGA)
    db.salvar_resultado(b, "camilo", status="cotado", valor=Decimal("90.00"))

    with db._conectar() as con:
        linhas = painel.historico(con)

    assert {l["usuario"] for l in linhas} == {"enzo", "leandro"}


def test_historico_mostra_o_melhor_preco_de_cada_cotacao(db):
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado", valor=Decimal("150.00"))
    db.salvar_resultado(cid, "generoso", status="cotado", valor=Decimal("90.50"))

    with db._conectar() as con:
        assert painel.historico(con)[0]["melhor_preco"] == Decimal("90.50")


def test_historico_sem_preco_nenhum_devolve_none_e_nao_zero(db):
    """Zero seria um preço. None é "não teve preço" — coisas diferentes."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="erro", erro="deu ruim")

    with db._conectar() as con:
        assert painel.historico(con)[0]["melhor_preco"] is None


def test_historico_filtra_por_usuario(db):
    db.salvar_cotacao("enzo", CARGA)
    db.salvar_cotacao("leandro", CARGA)

    with db._conectar() as con:
        linhas = painel.historico(con, usuario="leandro")

    assert [l["usuario"] for l in linhas] == ["leandro"]


def test_historico_filtra_so_as_que_tiveram_falha(db):
    """O filtro que o Enzo vai usar mais: mostra só o que deu problema."""
    boa = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(boa, "camilo", status="cotado", valor=Decimal("10.00"))
    ruim = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(ruim, "jadlog", status="erro", erro="timeout")

    with db._conectar() as con:
        linhas = painel.historico(con, so_com_falha=True)

    assert [l["id"] for l in linhas] == [ruim]


def test_historico_vem_do_mais_novo_para_o_mais_velho(db):
    primeiro = db.salvar_cotacao("enzo", CARGA)
    segundo = db.salvar_cotacao("enzo", CARGA)

    with db._conectar() as con:
        assert [l["id"] for l in painel.historico(con)] == [segundo, primeiro]


def test_historico_so_com_falha_nao_perde_falha_antiga_pro_limite(db):
    """O filtro tem que entrar ANTES do LIMIT. Aplicado depois, em Python, o
    SQL corta nas `limite` mais recentes e só então descarta as sem falha —
    com `limite=2` e 3 cotações, a mais antiga (a única com falha) seria
    cortada antes de chegar a ser considerada."""
    antiga_com_falha = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(antiga_com_falha, "jadlog", status="erro", erro="timeout")
    db.salvar_cotacao("enzo", CARGA)
    db.salvar_cotacao("enzo", CARGA)

    with db._conectar() as con:
        linhas = painel.historico(con, so_com_falha=True, limite=2)

    assert [l["id"] for l in linhas] == [antiga_com_falha]
