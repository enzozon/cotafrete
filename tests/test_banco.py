"""Histórico de cotações, separado por usuário.

O que precisa ser verdade: a cotação de um usuário não aparece para outro, e
uma cotação guarda TODOS os resultados (uma linha por transportadora), para
dar para reabrir e comparar depois.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core import banco


@pytest.fixture
def db(tmp_path):
    return banco.Banco(tmp_path / "teste.db")


def _carga(**over):
    base = dict(
        cep_origem="09895-003", cep_destino="29105-770",
        cidade_origem="São Bernardo do Campo", uf_origem="SP",
        cidade_destino="Vila Velha", uf_destino="ES",
        peso_kg=Decimal("1"), quantidade=1,
        comprimento_cm=30, largura_cm=30, altura_cm=30,
        valor_nf=Decimal("568.77"), material="LUVA DE BOMBEIRO",
    )
    base.update(over)
    return base


# ------------------------------------------------------- separação por usuário
def test_cotacao_de_um_usuario_nao_aparece_para_outro(db):
    """A regra que o Enzo pediu: cada um vê as suas."""
    db.salvar_cotacao("enzo", _carga())
    db.salvar_cotacao("maria", _carga(material="Parafusos"))

    do_enzo = db.listar_cotacoes("enzo")
    da_maria = db.listar_cotacoes("maria")

    assert len(do_enzo) == 1
    assert len(da_maria) == 1
    assert do_enzo[0]["material"] == "LUVA DE BOMBEIRO"
    assert da_maria[0]["material"] == "Parafusos"


def test_usuario_sem_cotacao_ve_lista_vazia(db):
    assert db.listar_cotacoes("ninguem") == []


def test_cotacao_de_outro_usuario_nao_abre_pelo_id(db):
    """Sem isto, trocar o número na URL daria acesso à cotação alheia."""
    id_enzo = db.salvar_cotacao("enzo", _carga())

    assert db.buscar_cotacao(id_enzo, "enzo") is not None
    assert db.buscar_cotacao(id_enzo, "maria") is None


# ------------------------------------------------------ resultados por carrier
def test_uma_cotacao_guarda_varios_resultados(db):
    """É o ponto do histórico: reabrir e ver o preço de cada transportadora
    lado a lado, sem precisar cotar de novo."""
    cid = db.salvar_cotacao("enzo", _carga())
    db.salvar_resultado(cid, "camilo", status="cotado",
                        valor=Decimal("69.91"), protocolo="2799505")
    db.salvar_resultado(cid, "jadlog", status="cotado",
                        valor=Decimal("33.35"))

    achado = db.buscar_cotacao(cid, "enzo")
    por_nome = {r["transportadora"]: r for r in achado["resultados"]}

    assert por_nome["camilo"]["valor"] == Decimal("69.91")
    assert por_nome["camilo"]["protocolo"] == "2799505"
    assert por_nome["jadlog"]["valor"] == Decimal("33.35")


def test_resultado_com_erro_e_guardado_tambem(db):
    """Sumir com quem falhou esconde informação: o histórico tem que mostrar
    que a transportadora foi tentada e não respondeu."""
    cid = db.salvar_cotacao("enzo", _carga())
    db.salvar_resultado(cid, "generoso", status="erro",
                        erro="Timeout ao abrir a etapa 3")

    r = db.buscar_cotacao(cid, "enzo")["resultados"][0]
    assert r["status"] == "erro"
    assert r["valor"] is None
    assert "Timeout" in r["erro"]


def test_valor_volta_como_decimal_nao_float(db):
    """Dinheiro em float acumula erro de arredondamento. O banco guarda
    string e devolve Decimal."""
    cid = db.salvar_cotacao("enzo", _carga())
    db.salvar_resultado(cid, "camilo", status="cotado",
                        valor=Decimal("1234.56"))

    valor = db.buscar_cotacao(cid, "enzo")["resultados"][0]["valor"]
    assert isinstance(valor, Decimal)
    assert valor == Decimal("1234.56")


# --------------------------------------------------------------- listagem
def test_mais_recente_primeiro(db):
    """Quem abre o histórico quer a última cotação, não a primeira."""
    primeira = db.salvar_cotacao("enzo", _carga(material="Antiga"))
    segunda = db.salvar_cotacao("enzo", _carga(material="Nova"))

    ids = [c["id"] for c in db.listar_cotacoes("enzo")]
    assert ids == [segunda, primeira]


def test_listagem_traz_o_menor_preco(db):
    """A lista mostra o melhor preço de cada cotação sem abrir uma por uma."""
    cid = db.salvar_cotacao("enzo", _carga())
    db.salvar_resultado(cid, "camilo", status="cotado", valor=Decimal("69.91"))
    db.salvar_resultado(cid, "jadlog", status="cotado", valor=Decimal("33.35"))
    db.salvar_resultado(cid, "generoso", status="erro", erro="falhou")

    assert db.listar_cotacoes("enzo")[0]["melhor_preco"] == Decimal("33.35")


def test_cotacao_sem_resultado_nao_inventa_preco(db):
    db.salvar_cotacao("enzo", _carga())
    assert db.listar_cotacoes("enzo")[0]["melhor_preco"] is None


def test_banco_e_criado_sozinho(tmp_path):
    """Primeira execução não pode exigir passo manual de instalação."""
    caminho = tmp_path / "sub" / "novo.db"
    b = banco.Banco(caminho)
    b.salvar_cotacao("enzo", _carga())

    assert caminho.exists()
    assert len(b.listar_cotacoes("enzo")) == 1
