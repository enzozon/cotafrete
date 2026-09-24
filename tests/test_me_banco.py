"""Tabelas do Mercado Eletrônico em core/banco.py."""

from __future__ import annotations

import pytest

from core.banco import Banco


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


ITEM = {"numero": 10, "pagina": 1, "indice": 1, "produto_id": "65342757",
        "descricao": "POSTO DUPLO", "quantidade": "2,00", "unidade": "UND",
        "obs_comprador": "Mesa", "campos_adicionais": "…", "uf_destino": "ES",
        "origem_pedida": 0, "data_remessa": "2026-11-02"}


def test_criar_e_idempotente(banco):
    a = banco.me_criar("ventura", 23039029, empresa="Samarco")
    b = banco.me_criar("ventura", 23039029, empresa="outra")
    assert a == b
    assert banco.me_cotacao(a)["empresa"] == "Samarco"
    assert banco.me_cotacao(a)["status"] == "pendente"


def test_mesmo_numero_em_contas_diferentes(banco):
    assert banco.me_criar("ventura", 1) != banco.me_criar("uniao", 1)


def test_reler_itens_do_me_nao_apaga_o_que_o_usuario_digitou(banco):
    cid = banco.me_criar("ventura", 23039029)
    banco.me_gravar_itens_do_me(cid, [ITEM])
    banco.me_gravar_entrada(cid, 10, preco="150,00", ncm="94033000", marca="Bortolini")
    banco.me_gravar_itens_do_me(cid, [{**ITEM, "descricao": "POSTO DUPLO (rev)"}])
    (item,) = banco.me_cotacao(cid)["itens"]
    assert item["descricao"] == "POSTO DUPLO (rev)"
    assert (item["preco"], item["ncm"], item["marca"]) == ("150,00", "94033000", "Bortolini")


def test_troca_de_status_so_de_quem_esta_no_estado_certo(banco):
    """Dois cliques em "Salvar no ME": só o primeiro solta o robô."""
    cid = banco.me_criar("ventura", 1)
    abertos = ("pendente", "salva", "erro")
    assert banco.me_trocar_status(cid, abertos, "salvando")
    assert not banco.me_trocar_status(cid, abertos, "salvando")


def test_campo_estranho_nao_vira_sql(banco):
    cid = banco.me_criar("ventura", 1)
    with pytest.raises(ValueError):
        banco.me_atualizar(cid, **{"status = 'enviada', erro": "x"})
    with pytest.raises(ValueError):
        banco.me_gravar_entrada(cid, 10, descricao="não é do usuário")


def test_lista_abertas_primeiro_pelo_prazo(banco):
    banco.me_criar("ventura", 1, data_limite="2026-09-30T21:00")
    banco.me_criar("ventura", 2, data_limite="2026-09-23T21:00", status="enviada")
    banco.me_criar("uniao", 3, data_limite="2026-09-25T21:00")
    assert [c["numero"] for c in banco.me_cotacoes()] == [3, 1, 2]
    assert [c["numero"] for c in banco.me_cotacoes(conta="uniao")] == [3]
    assert [c["numero"] for c in banco.me_cotacoes(status="enviada")] == [2]


def test_conta_itens_com_preco(banco):
    cid = banco.me_criar("ventura", 1)
    banco.me_gravar_itens_do_me(cid, [ITEM, {**ITEM, "numero": 20, "indice": 2}])
    banco.me_gravar_entrada(cid, 20, preco="10,00")
    (c,) = banco.me_cotacoes()
    assert (c["n_itens"], c["n_com_preco"]) == (2, 1)


def test_historico_e_memoria_de_material(banco):
    cid = banco.me_criar("ventura", 1)
    banco.me_registrar(cid, "salva no ME", "ok", "enzo")
    assert [h["evento"] for h in banco.me_historico(cid)] == ["salva no ME"]
    banco.me_lembrar_material("263252", ncm="85076000", marca="DJI", origem=2)
    banco.me_lembrar_material("263252", ncm="85076000", marca="DJI TB65", origem=2)
    assert banco.me_material("263252")["marca"] == "DJI TB65"
    assert banco.me_material("nada") is None


def test_banco_antigo_ganha_as_tabelas(tmp_path):
    """Quem já tinha cotafrete.db: CREATE TABLE IF NOT EXISTS cria as novas."""
    import sqlite3
    caminho = tmp_path / "velho.db"
    sqlite3.connect(caminho).execute("CREATE TABLE x (y)").connection.commit()
    Banco(caminho).me_criar("ventura", 1)
