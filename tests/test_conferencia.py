"""Conferir com o vendedor antes de cotar (core/conferencia.py).

Casos reais do levantamento de 15/10/2026: CIF com destinatário do grupo
(#411, #412, #415) e medida de 1 cm (#342, #374)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core import conferencia
from core.banco import Banco
from core.models import Parte, TipoFrete, Volume
from tests.apoio import entrar
from tests.test_jadlog import montar
from tests.test_web_cotacao import FORM_VALIDO

VENTURA = Parte(cnpj="08.310.365/0001-24")


def test_cif_com_o_grupo_recebendo_sugere_fob():
    [a] = conferencia.avisos(montar(destinatario=VENTURA))
    assert "FOB" in a.texto and a.correcao == {"tipo_frete": "fob"}


def test_fob_com_o_grupo_enviando_sugere_cif():
    [a] = conferencia.avisos(montar(remetente=VENTURA, tipo_frete=TipoFrete.FOB))
    assert a.correcao == {"tipo_frete": "cif"}


def test_medida_de_1cm_pede_conferencia():
    """#342: freezer de 63 kg com 1 cm de largura."""
    req = montar(volumes=[Volume(qtd=6, comprimento_cm=Decimal(85),
                                 largura_cm=Decimal(1), altura_cm=Decimal(77),
                                 peso_kg=Decimal(63))])
    [a] = conferencia.avisos(req)
    assert "largura" in a.texto and "1 cm" in a.texto and "63 kg" in a.texto
    assert not a.correcao


def test_carga_densa_demais_pede_conferencia():
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(10),
                                 largura_cm=Decimal(10), altura_cm=Decimal(10),
                                 peso_kg=Decimal(50))])
    assert "aço" in conferencia.avisos(req)[0].texto


def test_carga_normal_nao_avisa_nada():
    assert conferencia.avisos(montar(remetente=VENTURA)) == []


# ------------------------------------------------------------- a rota
@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "t.db"))
    monkeypatch.setattr(modulo, "TENTATIVAS_EM_CURSO", {})
    # Sem rede: CEP e CNPJ respondem fixo (o primeiro POST dependia do ViaCEP).
    monkeypatch.setattr(modulo.buscador_cep, "buscar",
                        lambda cep: ("Vila Velha", "ES", None))
    monkeypatch.setattr(modulo.buscador_cnpj, "buscar", lambda cnpj: "EMPRESA")
    disparadas = []
    monkeypatch.setattr(modulo.EXECUTOR, "submit",
                        lambda fn, cid, slug, *a: disparadas.append(slug))
    c = TestClient(modulo.app)
    entrar(c, modulo)
    c.modulo, c.disparadas = modulo, disparadas
    return c


GRUPO_RECEBENDO = {**FORM_VALIDO, "cnpj_remetente": "60.042.686/0001-05",
                   "cnpj_destinatario": "08.310.365/0001-24",
                   "transportadora": ["generoso", "braspress"]}


def test_aviso_para_antes_de_gravar(cliente):
    r = cliente.post("/cotar", data=GRUPO_RECEBENDO)
    assert "Confira antes de cotar" in r.text
    assert "Trocar para FOB e cotar" in r.text
    # a seleção do vendedor volta junto
    assert r.text.count('name="transportadora"') == 2
    assert cliente.modulo.banco.listar_cotacoes("enzo") == []
    assert cliente.disparadas == []


def test_corrigir_troca_para_fob_e_cota(cliente):
    r = cliente.post("/cotar", data={**GRUPO_RECEBENDO, "corrigir": "fob"},
                     follow_redirects=False)
    assert r.status_code == 303
    [c] = cliente.modulo.banco.listar_cotacoes("enzo")
    assert cliente.modulo.banco.buscar_cotacao(c["id"], "enzo")["tipo_frete"] == "fob"
    assert set(cliente.disparadas) == {"generoso", "braspress"}


def test_confirmar_cota_como_estava(cliente):
    r = cliente.post("/cotar", data={**GRUPO_RECEBENDO, "conferido": "1"},
                     follow_redirects=False)
    assert r.status_code == 303
    [c] = cliente.modulo.banco.listar_cotacoes("enzo")
    assert cliente.modulo.banco.buscar_cotacao(c["id"], "enzo")["tipo_frete"] == "cif"
