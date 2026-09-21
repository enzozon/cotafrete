"""Aceitar uma cotação: até quando dá, e o registro de quem aceitou.

Duas coisas nasceram juntas porque uma não serve sem a outra:

- `resultado.validade` — até quando aquele preço ainda fecha negócio. É o que
  decide se o botão "Aceitar" aparece ou se vira "cotação vencida".
- a tabela `aceite` — quem pediu a coleta, quando, e com que dados.

Aceitar é compromisso com caminhão na porta do cliente, e é a primeira coisa
neste sistema que combina algo com o mundo de fora em nome da Ventura. Por
isso tem UNIQUE: duas coletas para a mesma carga é o erro caro aqui, e ele
nasce do gesto mais banal que existe numa tela web — apertar o botão duas
vezes porque a primeira pareceu não responder.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from core import banco

from tests.test_banco import _carga


@pytest.fixture
def db(tmp_path):
    return banco.Banco(tmp_path / "teste.db")


def _cotada(db, validade: date | None = date(2026, 9, 28)) -> int:
    cid = db.salvar_cotacao("enzo", _carga())
    db.salvar_resultado(cid, "generoso", status="cotado",
                        valor=Decimal("152.16"), protocolo="2684352",
                        prazo="6", validade=validade)
    return cid


def _resultado(db, cid: int, slug: str = "generoso") -> dict:
    c = db.buscar_cotacao(cid, "enzo")
    return next(r for r in c["resultados"] if r["transportadora"] == slug)


# ----------------------------------------------------------------- validade
def test_validade_volta_como_date(db):
    """Guardada em ISO e devolvida como `date`: a tela COMPARA com hoje, e
    comparar "28/09/26" com hoje em texto funciona até virar o ano."""
    cid = _cotada(db)

    assert _resultado(db, cid)["validade"] == date(2026, 9, 28)


def test_resultado_sem_validade_continua_valendo(db):
    """Cinco das seis transportadoras não dizem até quando o preço vale.
    Ausência não pode virar data nenhuma, nem quebrar a linha."""
    cid = _cotada(db, validade=None)

    r = _resultado(db, cid)
    assert r["validade"] is None
    assert r["valor"] == Decimal("152.16")


def test_banco_antigo_ganha_a_coluna_validade(tmp_path):
    """As 414 linhas de resultado que já existem nasceram sem esta coluna.

    Mesmo motivo de sempre: CREATE TABLE IF NOT EXISTS não altera tabela
    existente. Sem a migração, o primeiro INSERT depois do deploy responderia
    "table resultado has no column named validade" — e o resultado da cotação
    seria perdido dentro de uma thread, com o cartão girando para sempre."""
    caminho = tmp_path / "antigo.db"
    with sqlite3.connect(caminho) as con:
        con.execute("""CREATE TABLE cotacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT NOT NULL,
            criado_em TEXT NOT NULL, cep_origem TEXT NOT NULL,
            cep_destino TEXT NOT NULL, peso_kg TEXT NOT NULL,
            quantidade INTEGER NOT NULL, comprimento_cm INTEGER NOT NULL,
            largura_cm INTEGER NOT NULL, altura_cm INTEGER NOT NULL,
            valor_nf TEXT NOT NULL)""")
        con.execute("""CREATE TABLE resultado (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cotacao_id INTEGER NOT NULL,
            transportadora TEXT NOT NULL, status TEXT NOT NULL, valor TEXT,
            protocolo TEXT, prazo TEXT, erro TEXT, evidencia TEXT)""")
        con.execute("INSERT INTO cotacao (usuario, criado_em, cep_origem,"
                    " cep_destino, peso_kg, quantidade, comprimento_cm,"
                    " largura_cm, altura_cm, valor_nf) VALUES"
                    " ('enzo','2026-08-01T10:00','09895-003','29105-770',"
                    "'1',1,30,30,30,'100')")
        con.execute("INSERT INTO resultado (cotacao_id, transportadora,"
                    " status, valor) VALUES (1, 'camilo', 'cotado', '74.10')")

    b = banco.Banco(caminho)
    b.salvar_resultado(1, "generoso", status="cotado",
                       valor=Decimal("152.16"), validade=date(2026, 9, 28))

    c = b.buscar_cotacao(1, "enzo")
    assert len(c["resultados"]) == 2           # a linha antiga continua lá
    nova = next(r for r in c["resultados"] if r["transportadora"] == "generoso")
    assert nova["validade"] == date(2026, 9, 28)
    velha = next(r for r in c["resultados"] if r["transportadora"] == "camilo")
    assert velha["validade"] is None


# ------------------------------------------------------------------- aceite
def test_registra_quem_aceitou_e_com_que_dados(db):
    cid = _cotada(db)

    assert db.registrar_aceite(
        cid, "generoso", "enzo", data_coleta="2026-09-23",
        hora_limite="18:00", almoco_inicio="12:00", almoco_fim="13:00",
        observacao="Procurar o Marcos na portaria") is True

    a = db.aceites(cid)["generoso"]
    assert a["usuario"] == "enzo"
    assert a["data_coleta"] == "2026-09-23"
    assert a["hora_limite"] == "18:00"
    assert a["almoco_inicio"] == "12:00"
    assert a["almoco_fim"] == "13:00"
    assert a["observacao"] == "Procurar o Marcos na portaria"
    assert a["status"] == "agendando"


def test_aceitar_duas_vezes_nao_agenda_duas_coletas(db):
    """O erro caro desta tela, e o gesto mais banal que existe: apertar o
    botão de novo porque a primeira vez pareceu não responder. O segundo
    pedido é RECUSADO aqui, no banco — não adianta só esconder o botão, que
    um F5 traz de volta."""
    cid = _cotada(db)
    db.registrar_aceite(cid, "generoso", "enzo", data_coleta="2026-09-23",
                        hora_limite="18:00")

    segunda = db.registrar_aceite(cid, "generoso", "maria",
                                  data_coleta="2026-09-25",
                                  hora_limite="09:00")

    assert segunda is False
    a = db.aceites(cid)["generoso"]
    assert a["usuario"] == "enzo"              # o primeiro é que vale
    assert a["data_coleta"] == "2026-09-23"
    assert len(db.aceites(cid)) == 1


def test_local_que_nao_fecha_para_almoco_fica_nulo(db):
    """O checkbox desmarcado não é "almoço das 00:00 às 00:00": é ausência
    de almoço, e os dois selects nem existem no DOM nessa hora."""
    cid = _cotada(db)

    db.registrar_aceite(cid, "generoso", "enzo", data_coleta="2026-09-23",
                        hora_limite="18:00")

    a = db.aceites(cid)["generoso"]
    assert a["almoco_inicio"] is None
    assert a["almoco_fim"] is None


def test_aceite_concluido_guarda_protocolo_e_print(db):
    """O site confirma o agendamento e dá um número. É a prova de que a
    coleta foi pedida — e o print vai junto, como em toda cotação."""
    cid = _cotada(db)
    db.registrar_aceite(cid, "generoso", "enzo", data_coleta="2026-09-23",
                        hora_limite="18:00")

    db.concluir_aceite(cid, "generoso", status="agendado",
                       protocolo="COL-99887",
                       evidencia="teste_real/generoso/x/agendado.png")

    a = db.aceites(cid)["generoso"]
    assert a["status"] == "agendado"
    assert a["protocolo"] == "COL-99887"
    assert a["evidencia"].endswith("agendado.png")


def test_aceite_que_falhou_guarda_o_motivo_e_libera_nova_tentativa(db):
    """Agendamento que NÃO chegou a acontecer não pode travar a cotação para
    sempre: o vendedor precisa poder tentar de novo. Só o aceite que deu
    certo é definitivo."""
    cid = _cotada(db)
    db.registrar_aceite(cid, "generoso", "enzo", data_coleta="2026-09-23",
                        hora_limite="18:00")

    db.concluir_aceite(cid, "generoso", status="erro",
                       erro="o portal da Generoso não abriu a tela de coleta")

    assert db.aceites(cid)["generoso"]["status"] == "erro"
    # e agora dá para tentar de novo
    assert db.registrar_aceite(cid, "generoso", "enzo",
                               data_coleta="2026-09-24",
                               hora_limite="17:00") is True
    assert db.aceites(cid)["generoso"]["data_coleta"] == "2026-09-24"


def test_aceites_nao_vazam_de_uma_cotacao_para_outra(db):
    uma = _cotada(db)
    outra = _cotada(db)

    db.registrar_aceite(uma, "generoso", "enzo", data_coleta="2026-09-23",
                        hora_limite="18:00")

    assert db.aceites(outra) == {}
