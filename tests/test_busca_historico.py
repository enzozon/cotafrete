"""Sugestão 5: busca em português no histórico — filtros de lista fechada."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core import busca_historico as bh
from core import ia
from core.banco import Banco
from tests.apoio import entrar
from tests.test_ia import Provedor, Resp
from tests.test_web_cotacao import CARGA

SLUGS = {"camilo": "Camilo dos Santos", "jadlog": "Jadlog Entregas"}


def _c(**k):
    base = {"cidade_origem": "Serra", "uf_origem": "ES", "cidade_destino": "Anchieta",
            "uf_destino": "ES", "material": "Bomba", "peso_kg": Decimal("150"),
            "criado_em": "2026-08-10T10:00:00", "com_preco": ["camilo"],
            "melhor_preco": Decimal("100")}
    return base | k


def test_limpar_so_aceita_a_lista_fechada_com_o_tipo_certo():
    f = bh.limpar({"destino": " Anchieta ", "peso_min": 100, "peso_max": "abc",
                   "desde": "2026-08-01", "ate": "31/08/2026", "transportadora": "Acme",
                   "status": "tudo", "sql": "DROP TABLE cotacao"}, SLUGS)
    assert f == {"destino": "Anchieta", "peso_min": "100", "desde": "2026-08-01"}


def test_aplicar_filtra_destino_peso_periodo_e_transportadora():
    leve, julho, sp = _c(peso_kg=Decimal("50")), _c(criado_em="2026-07-30T09:00:00"), _c(
        cidade_destino="São Paulo", uf_destino="SP")
    certa = _c()
    f = {"destino": "anchieta", "peso_min": "100", "desde": "2026-08-01",
         "ate": "2026-08-31", "transportadora": "camilo"}
    assert bh.aplicar([leve, julho, sp, certa], f) == [certa]
    assert bh.aplicar([sp, certa], {"destino": "SP"}) == [sp]
    assert bh.aplicar([certa], {"transportadora": "jadlog"}) == []
    assert bh.aplicar([certa, _c(melhor_preco=None)], {"status": "sem_preco"})[0]["melhor_preco"] is None


def test_descrever_mostra_o_que_foi_entendido():
    assert bh.descrever({"destino": "Anchieta", "peso_min": "100", "desde": "2026-08-01",
                         "status": "sem_preco"}) == [
        "destino: Anchieta", "peso a partir de: 100 kg", "de: 01/08/2026",
        "situação: sem preço nenhum"]


@pytest.fixture
def prov(monkeypatch):
    p = Provedor()
    monkeypatch.setattr(ia, "POST", p)
    monkeypatch.setattr(ia, "_castigo", {})
    monkeypatch.setattr(ia, "REGISTRO", None)
    monkeypatch.setenv("IA_MODELOS", "groq:melhor")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    return p


def test_interpretar_descarta_o_que_a_ia_inventou(prov):
    prov.roteiro["melhor"] = [Resp(conteudo=json.dumps({
        "origem": None, "destino": "Anchieta", "material": None, "peso_min": 100,
        "peso_max": None, "desde": "2026-08-01", "ate": "2026-08-31",
        "transportadora": "fedex", "status": None}))]
    f = bh.interpretar("para Anchieta acima de 100 kg em agosto", date(2026, 10, 9), SLUGS)
    assert f == {"destino": "Anchieta", "peso_min": "100", "desde": "2026-08-01", "ate": "2026-08-31"}


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "t.db"))
    cli = TestClient(modulo.app)
    entrar(cli, modulo)
    modulo.banco.salvar_cotacao("enzo", CARGA)
    modulo.banco.salvar_cotacao("enzo", CARGA | {"cidade_destino": "Anchieta", "uf_destino": "ES"})
    return cli, modulo


def test_tela_com_filtros_na_url(cliente):
    cli, _ = cliente
    html = cli.get("/historico?destino=Anchieta&q=x").text
    assert "Entendi assim:" in html and "destino: Anchieta" in html
    assert "Anchieta/ES" in html and "São Paulo/SP" not in html


def test_frase_vira_filtros_na_url(cliente, prov):
    cli, _ = cliente
    prov.roteiro["melhor"] = [Resp(conteudo=json.dumps(dict.fromkeys(bh.FILTROS) | {"destino": "Anchieta"}))]
    r = cli.get("/historico?q=para+anchieta", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/historico?destino=Anchieta&q=para+anchieta"


def test_sem_ia_busca_por_trecho(cliente, monkeypatch):
    cli, _ = cliente
    monkeypatch.setattr(ia, "configurada", lambda: False)
    html = cli.get("/historico?q=anchieta").text
    assert "Busca simples por &quot;anchieta&quot;" in html
    assert "Anchieta/ES" in html and "São Paulo/SP" not in html


def test_peso_absurdo_na_url_e_ignorado():
    assert bh.limpar({"peso_min": "1e30", "peso_max": "500"}, SLUGS) == {"peso_max": "500"}


def test_sigla_de_uf_nao_acha_pedaco_de_cidade():
    jaspe = _c(cidade_destino="Jaspe", uf_destino="MG")
    assert bh.aplicar([jaspe], {"destino": "sp"}) == []
    assert bh.aplicar([jaspe], {"destino": "MG"}) == [jaspe]
