"""Revisão por IA — sem rede: o provedor falso de tests/test_ia.py responde
no lugar do Groq/OpenRouter. Confere o pedido (texto do comprador e cálculos
vão junto, esquema no formato certo) e que toda falha vira "revisão IA
indisponível" em vez de exceção."""

from __future__ import annotations

import json

import pytest

from core import ia
from mercado_eletronico import revisao as rv
from tests.test_ia import Provedor, Resp

COTACAO = {
    "conta": "ventura", "numero": 23039029, "empresa": "Samarco Mineração",
    "comprador": "Mayanna", "data_limite": "2026-09-23T21:00", "validade_dias": 30,
    "itens": [{
        "numero": 10, "descricao": "POSTO DUPLO", "quantidade": "2,00", "unidade": "UND",
        "obs_comprador": "Mesa 120x120x73cm Marca Bortolini Linha Square.\nENTREGAR EM BSB",
        "campos_adicionais": "End. entrega: Rodovia do Sol, S/N - Ponta Ubu - Anchieta - ES - 29230-000",
        "preco": "1,00", "ncm": "94033000", "prazo_dias": 30, "marca": "Genérica",
        "obs": "", "origem": 0,
    }],
}
PREVIA = {10: {"icms": "17,00", "data_entrega": "23/10/2026"}}


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


def _json(*alertas):
    return json.dumps({"alertas": [dict(zip(("item", "nivel", "mensagem"), a)) for a in alertas]})


def test_pedido_no_formato_certo(prov, monkeypatch):
    monkeypatch.setattr(ia, "COM_ESQUEMA", {"groq:melhor"})
    prov.roteiro["melhor"] = [Resp(conteudo=_json())]
    rv.revisar(COTACAO, PREVIA, [], ["Item 10: aviso x"], "NÃO SERÃO ACEITAS MARCAS SIMILARES")
    ((provedor, modelo, corpo),) = prov.pedidos
    assert (provedor, modelo) == ("groq", "melhor")
    assert corpo["response_format"]["json_schema"]["schema"] == rv.ESQUEMA
    assert corpo["messages"][0]["content"] == rv.SISTEMA
    texto = corpo["messages"][1]["content"]
    for trecho in ("ENTREGAR EM BSB", "Bortolini", "Genérica", "NÃO SERÃO ACEITAS MARCAS SIMILARES",
                   "Item 10: aviso x", "17,00"):
        assert trecho in texto


def test_o_esquema_vale_no_modo_estrito():
    """Groq estrito: todo campo `required` e `additionalProperties: false`."""
    def conferir(esq):
        if esq.get("type") == "object":
            assert esq["additionalProperties"] is False
            assert set(esq["required"]) == set(esq["properties"])
            for v in esq["properties"].values():
                conferir(v)
        if esq.get("type") == "array":
            conferir(esq["items"])
    conferir(rv.ESQUEMA)


def test_alertas_ordenados_por_gravidade(prov):
    prov.roteiro["melhor"] = [Resp(conteudo=_json(
        (10, "info", "detalhe"), (10, "critico", "marca Genérica, pedida Bortolini"),
        (None, "atencao", "entrega em BSB × ES")))]
    r = rv.revisar(COTACAO, PREVIA, [], [])
    assert not r.indisponivel and r.modelo == "groq:melhor"
    assert [a.nivel for a in r.alertas] == ["critico", "atencao", "info"]
    assert r.alertas[1].item is None


def test_nivel_desconhecido_e_mensagem_vazia_somem(prov):
    prov.roteiro["melhor"] = [Resp(conteudo=_json((10, "urgente", "x"), (10, "info", "  "), ("20", "info", "y")))]
    r = rv.revisar(COTACAO, PREVIA, [], [])
    assert [(a.item, a.mensagem) for a in r.alertas] == [(20, "y")]   # "20" em texto vira 20


def test_resposta_ruim_passa_para_o_proximo_modelo(prov):
    prov.roteiro["melhor"] = [Resp(conteudo="Não encontrei problemas.")]
    prov.roteiro["reserva:free"] = [Resp(conteudo=_json((10, "critico", "marca")))]
    r = rv.revisar(COTACAO, PREVIA, [], [])
    assert r.modelo == "openrouter:reserva:free" and len(r.alertas) == 1


def test_todos_falharam_vira_indisponivel_com_o_motivo(prov):
    prov.roteiro["melhor"] = [Resp(429, headers={"retry-after": "20"})]
    prov.roteiro["reserva:free"] = [Resp(503)]
    r = rv.revisar(COTACAO, PREVIA, [], [])
    assert r.indisponivel and r.alertas == []
    assert "groq:melhor: limite por minuto" in r.erro and "fora do ar (503)" in r.erro


def test_sem_chave_nem_tenta(prov, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    r = rv.revisar(COTACAO, PREVIA, [], [])
    assert r.indisponivel and "GROQ_API_KEY" in r.erro and prov.pedidos == []


def test_ida_e_volta_pelo_banco():
    r = rv.Revisao([rv.Alerta(10, "critico", "x")], None, "groq:openai/gpt-oss-120b")
    assert rv.Revisao.de_json(r.como_json()) == r
    assert rv.Revisao.de_json("lixo") is None and rv.Revisao.de_json(None) is None


def test_assinatura_muda_com_o_preenchimento():
    a = rv.assinatura(COTACAO)
    outro = {**COTACAO, "itens": [{**COTACAO["itens"][0], "marca": "Bortolini"}]}
    assert rv.assinatura(outro) != a
    # o que veio do ME não conta: reler os itens não "envelhece" a revisão
    relido = {**COTACAO, "itens": [{**COTACAO["itens"][0], "descricao": "POSTO DUPLO (rev)"}]}
    assert rv.assinatura(relido) == a
