"""Sugestão 4: resposta pronta para o cliente — preços do banco, IA só no texto."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core import ia
from core import resposta_cliente as rc
from core.banco import Banco
from tests.apoio import entrar
from tests.test_ia import Provedor, Resp
from tests.test_web_cotacao import CARGA

C = {"cidade_origem": "Serra", "uf_origem": "ES", "cidade_destino": "Anchieta",
     "uf_destino": "ES", "peso_kg": "12.5", "quantidade": 2,
     "resultados": [
         {"transportadora": "braspress", "valor": Decimal("1399.64"), "prazo": "2", "validade": None},
         {"transportadora": "camilo", "valor": Decimal("208.89"), "prazo": None,
          "validade": "2026-10-20"},
         {"transportadora": "jadlog", "valor": None, "prazo": None, "validade": None}]}


@pytest.fixture
def prov(monkeypatch):
    p = Provedor()
    monkeypatch.setattr(ia, "POST", p)
    monkeypatch.setattr(ia, "_castigo", {})
    monkeypatch.setattr(ia, "REGISTRO", None)
    monkeypatch.setenv("IA_MODELOS", "groq:melhor,openrouter:reserva:free")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "y")
    return p


def test_opcoes_do_banco_da_mais_barata_para_a_mais_cara():
    ops = rc.opcoes(C, str.title)
    assert [(o["transportadora"], o["preco"], o["prazo"], o["validade"]) for o in ops] == [
        ("Camilo", "R$ 208,89", None, "20/10/2026"),
        ("Braspress", "R$ 1.399,64", "2 dias", None)]


def test_texto_padrao_tem_todos_os_precos():
    t = rc.texto_padrao(C, rc.opcoes(C))
    assert "Serra/ES para Anchieta/ES (2 volumes, 12,5 kg)" in t
    assert "camilo: R$ 208,89, válido até 20/10/2026" in t
    assert "braspress: R$ 1.399,64, prazo de 2 dias" in t


def test_ia_que_muda_preco_ou_inventa_numero_e_descartada(prov):
    ops = rc.opcoes(C)
    prov.roteiro["melhor"] = [Resp(conteudo=json.dumps(
        {"texto": "camilo R$ 208,89\nbraspress R$ 1.399,64 com 15% de desconto"}))]
    prov.roteiro["reserva:free"] = [Resp(conteudo=json.dumps(
        {"texto": "Oi!\ncamilo sai R$ 208,89 (vale até 20/10/2026)\nbraspress R$ 1.399,64 em 2 dias."}))]

    r = rc.pedir(C, ops, "oi, quanto fica?")

    assert r.modelo == "openrouter:reserva:free" and "R$ 1.399,64" in r.dados


def test_ia_que_esquece_um_preco_e_descartada(prov):
    prov.roteiro["melhor"] = [Resp(conteudo=json.dumps({"texto": "Camilo R$ 208,89."}))]
    prov.roteiro["reserva:free"] = [Resp(conteudo=json.dumps({"texto": "Camilo R$ 208,89."}))]
    with pytest.raises(ia.IAIndisponivel):
        rc.pedir(C, rc.opcoes(C))


def test_tela_mostra_o_texto_padrao(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "t.db"))
    monkeypatch.setattr(modulo, "TENTATIVAS_EM_CURSO", {})
    cli = TestClient(modulo.app)
    entrar(cli, modulo)
    cid = modulo.banco.salvar_cotacao("enzo", CARGA)
    modulo.banco.salvar_resultado(cid, "camilo", status="cotado", valor=Decimal("208.89"),
                                  validade=date(2026, 10, 20))

    html = cli.get(f"/resposta/{cid}").text

    assert "R$ 208,89, válido até 20/10/2026" in html
    assert f'href="/resposta/{cid}"' in cli.get(f"/cotacao/{cid}").text


def _valida(texto):
    return rc._validador(C, rc.opcoes(C))({"texto": texto})


def test_precos_trocados_entre_transportadoras_sao_recusados():
    with pytest.raises(ValueError, match="trocado"):
        _valida("camilo: R$ 1.399,64\nbraspress: R$ 208,89")


def test_pedaco_de_preco_nao_vale_como_numero():
    """"399" existe dentro de 1.399,64, mas não como número da cotação."""
    with pytest.raises(ValueError, match="não estão"):
        _valida("camilo: R$ 208,89\nbraspress: R$ 1.399,64, entrega em 399 dias")


def test_preco_menor_nao_e_achado_dentro_de_um_maior():
    c = C | {"resultados": [
        {"transportadora": "camilo", "valor": Decimal("99"), "prazo": None, "validade": None},
        {"transportadora": "jadlog", "valor": Decimal("199"), "prazo": None, "validade": None}]}
    validar = rc._validador(c, rc.opcoes(c))
    with pytest.raises(ValueError):
        validar({"texto": "camilo: R$ 199,00\njadlog: R$ 199,00"})
    assert validar({"texto": "camilo: R$ 99,00\njadlog: R$ 199,00"})
