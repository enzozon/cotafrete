"""Revisão por IA — sem rede: um cliente falso registra o pedido e devolve
respostas prontas. Confere o formato do pedido (modelo, fallback, esquema)
e que toda falha vira "revisão IA indisponível" em vez de exceção."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from mercado_eletronico import revisao as rv

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


class Falso:
    def __init__(self, texto=None, stop="end_turn", erro=None, modelo="claude-opus-5"):
        self.pedidos = []
        self._r = SimpleNamespace(stop_reason=stop, model=modelo,
                                  content=[SimpleNamespace(type="text", text=texto or "")])
        self._erro = erro
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.pedidos.append(kw)
        if self._erro:
            raise self._erro
        return self._r


def _json(*alertas):
    return json.dumps({"alertas": [dict(zip(("item", "nivel", "mensagem"), a)) for a in alertas]})


def test_pedido_no_formato_certo():
    f = Falso(_json())
    rv.revisar(COTACAO, PREVIA, [], ["Item 10: aviso x"], "NÃO SERÃO ACEITAS MARCAS SIMILARES", cliente=f)
    (p,) = f.pedidos
    assert p["model"] == "claude-opus-5"
    assert p["thinking"] == {"type": "adaptive"}
    assert p["fallbacks"] == "default" and p["betas"] == ["server-side-fallback-2026-07-01"]
    assert p["output_config"]["format"]["schema"] == rv.ESQUEMA
    texto = p["messages"][0]["content"]
    for trecho in ("ENTREGAR EM BSB", "Bortolini", "Genérica", "NÃO SERÃO ACEITAS MARCAS SIMILARES",
                   "Item 10: aviso x", "17,00"):
        assert trecho in texto


def test_alertas_ordenados_por_gravidade():
    f = Falso(_json((10, "info", "detalhe"), (10, "critico", "marca Genérica, pedida Bortolini"),
                    (None, "atencao", "entrega em BSB × ES")))
    r = rv.revisar(COTACAO, PREVIA, [], [], cliente=f)
    assert not r.indisponivel and r.modelo == "claude-opus-5"
    assert [a.nivel for a in r.alertas] == ["critico", "atencao", "info"]
    assert r.alertas[1].item is None


def test_nivel_desconhecido_e_mensagem_vazia_somem():
    f = Falso(_json((10, "urgente", "x"), (10, "info", "  ")))
    assert rv.revisar(COTACAO, PREVIA, [], [], cliente=f).alertas == []


@pytest.mark.parametrize("falso, motivo", [
    (Falso(stop="refusal"), "recusou"),
    (Falso("{", stop="max_tokens"), "cortada"),
    (Falso("não é json"), "ilegível"),
    (Falso(erro=ConnectionError("sem rede")), "ConnectionError"),
])
def test_falha_vira_indisponivel(falso, motivo):
    r = rv.revisar(COTACAO, PREVIA, [], [], cliente=falso)
    assert r.indisponivel and motivo in r.erro and r.alertas == []


def test_sem_chave_nem_tenta(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    r = rv.revisar(COTACAO, PREVIA, [], [])
    assert r.indisponivel and "ANTHROPIC_API_KEY" in r.erro


def test_ida_e_volta_pelo_banco():
    r = rv.Revisao([rv.Alerta(10, "critico", "x")], None, "claude-opus-5")
    assert rv.Revisao.de_json(r.como_json()) == r
    assert rv.Revisao.de_json("lixo") is None and rv.Revisao.de_json(None) is None


def test_assinatura_muda_com_o_preenchimento():
    a = rv.assinatura(COTACAO)
    outro = {**COTACAO, "itens": [{**COTACAO["itens"][0], "marca": "Bortolini"}]}
    assert rv.assinatura(outro) != a
    # o que veio do ME não conta: reler os itens não "envelhece" a revisão
    relido = {**COTACAO, "itens": [{**COTACAO["itens"][0], "descricao": "POSTO DUPLO (rev)"}]}
    assert rv.assinatura(relido) == a
