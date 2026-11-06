"""A cadeia de modelos grátis (core/ia.py), sem rede.

Um "provedor" falso responde por modelo o que o teste mandar (200 com JSON,
429, 401, texto solto...) e registra cada pedido. O relógio é trocado por um
contador, para provar o castigo e a volta aos melhores sem esperar de verdade.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from core import busca_historico, explicar_erro, extrair_carga, ia, resposta_cliente

CADEIA = "groq:melhor,openrouter:segundo:free,groq:terceiro"


class Resp:
    def __init__(self, status=200, conteudo=None, headers=None, texto="", finish="stop", corpo=None):
        self.status_code, self.headers, self.text = status, headers or {}, texto
        self._corpo = corpo if corpo is not None else {
            "choices": [{"message": {"content": conteudo}, "finish_reason": finish}]}

    def json(self):
        return self._corpo


class Provedor:
    """Responde por modelo; o que não foi programado responde JSON bom."""

    def __init__(self):
        self.roteiro: dict[str, list[Resp]] = {}
        self.pedidos: list[tuple[str, str, dict]] = []
        self.prazos: list[float] = []
        self.demora = 0

    def __call__(self, url, chave, corpo, provedor, timeout=None):
        self.pedidos.append((provedor, corpo["model"], corpo))
        self.prazos.append(timeout)
        if self.demora:
            self.relogio.t += self.demora
        fila = self.roteiro.get(corpo["model"])
        if fila:
            return fila.pop(0) if len(fila) > 1 else fila[0]
        return Resp(conteudo=json.dumps({"ok": corpo["model"]}))

    def modelos(self):
        return [m for _, m, _ in self.pedidos]


@pytest.fixture
def prov(monkeypatch):
    p = Provedor()
    relogio = SimpleNamespace(t=1_790_000_000.0)   # 2026-09-21, meio do dia UTC
    monkeypatch.setattr(ia, "POST", p)
    monkeypatch.setattr(ia, "agora", lambda: relogio.t)
    monkeypatch.setattr(ia, "_castigo", {})
    monkeypatch.setattr(ia, "REGISTRO", None)
    monkeypatch.setenv("IA_MODELOS", CADEIA)
    monkeypatch.setenv("GROQ_API_KEY", "chave-groq")
    monkeypatch.setenv("OPENROUTER_API_KEY", "chave-or")
    p.relogio = relogio
    return p


def test_usa_o_primeiro_da_lista(prov):
    r = ia.completar_json("sis", "pedido", {"type": "object"})
    assert r.modelo == "groq:melhor" and r.dados == {"ok": "melhor"}
    assert prov.modelos() == ["melhor"]


def test_limite_passa_para_o_proximo_e_castiga(prov):
    prov.roteiro["melhor"] = [Resp(429, headers={"retry-after": "30"})]
    r = ia.completar_json("sis", "pedido")
    assert r.modelo == "openrouter:segundo:free"
    assert "groq:melhor: limite por minuto atingido" in r.tentativas
    # o próximo pedido nem tenta o castigado
    prov.pedidos.clear()
    assert ia.completar_json("sis", "pedido").modelo == "openrouter:segundo:free"
    assert prov.modelos() == ["segundo:free"]


def test_volta_ao_melhor_quando_o_limite_passa(prov):
    """A promessa ao usuário: acabou o castigo, o melhor volta a ser o primeiro."""
    prov.roteiro["melhor"] = [Resp(429, headers={"retry-after": "30"}), Resp(conteudo='{"ok": "de volta"}')]
    assert ia.completar_json("sis", "p").modelo == "openrouter:segundo:free"
    prov.relogio.t += 31
    r = ia.completar_json("sis", "p")
    assert r.modelo == "groq:melhor" and r.dados == {"ok": "de volta"}


def test_limite_diario_fica_fora_ate_a_meia_noite_utc(prov):
    prov.roteiro["melhor"] = [Resp(429, texto='{"error":{"message":"Rate limit reached ... requests per day (RPD)"}}')]
    ia.completar_json("sis", "p")
    ate, motivo = ia.castigados()["groq:melhor"]
    assert motivo == "limite diário atingido"
    from datetime import datetime, timezone
    assert datetime.fromtimestamp(ate, tz=timezone.utc).strftime("%H:%M") == "00:00"
    prov.relogio.t = ate + 1
    assert "groq:melhor" not in ia.castigados()


def test_json_quebrado_passa_para_o_proximo_sem_castigo(prov):
    prov.roteiro["melhor"] = [Resp(conteudo="Claro! Aqui está a revisão: nada a apontar.")]
    r = ia.completar_json("sis", "p", {"type": "object"})
    assert r.modelo == "openrouter:segundo:free"
    assert "groq:melhor" not in ia.castigados()      # na próxima ele tenta de novo
    assert any("fora do formato" in t for t in r.tentativas)


def test_json_dentro_de_cerca_de_codigo_vale():
    assert ia.extrair_json('Segue:\n```json\n{"alertas": []}\n```') == {"alertas": []}
    assert ia.extrair_json('Resposta: {"alertas": [1]} fim') == {"alertas": [1]}


def test_validacao_que_falha_conta_como_resposta_ruim(prov):
    def exigir_alertas(d):
        return d["alertas"]
    prov.roteiro["melhor"] = [Resp(conteudo='{"outra": 1}')]
    prov.roteiro["segundo:free"] = [Resp(conteudo='{"alertas": ["x"]}')]
    r = ia.completar_json("sis", "p", validar=exigir_alertas)
    assert r.dados == ["x"] and r.modelo == "openrouter:segundo:free"


def test_sem_chave_pula_o_provedor(prov, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    r = ia.completar_json("sis", "p")
    assert r.modelo == "openrouter:segundo:free"
    assert "groq:melhor: sem GROQ_API_KEY no .env" in r.tentativas
    assert [p for p, _, _ in prov.pedidos] == ["openrouter"]


def test_chave_errada_fica_fora_meia_hora(prov):
    prov.roteiro["melhor"] = [Resp(401, texto="invalid api key")]
    ia.completar_json("sis", "p")
    ate, motivo = ia.castigados()["groq:melhor"]
    assert motivo == "chave recusada (401)" and ate - prov.relogio.t == ia.CASTIGO_CHAVE_S


def test_chave_recusada_vale_para_o_provedor_inteiro(prov):
    prov.roteiro["melhor"] = [Resp(401, texto="invalid api key")]
    r = ia.completar_json("sis", "p")
    assert r.modelo == "openrouter:segundo:free"
    assert "groq:terceiro" in ia.castigados()           # mesma chave: nem tenta
    prov.pedidos.clear()
    ia.completar_json("sis", "p")
    assert [p for p, _, _ in prov.pedidos] == ["openrouter"]


def test_tudo_falhou_diz_o_motivo_de_cada_um(prov):
    for m in ("melhor", "segundo:free", "terceiro"):
        prov.roteiro[m] = [Resp(503, texto="overloaded")]
    with pytest.raises(ia.IAIndisponivel) as e:
        ia.completar_json("sis", "p")
    msg = str(e.value)
    assert all(m in msg for m in ("groq:melhor", "openrouter:segundo:free", "groq:terceiro"))
    assert "fora do ar (503)" in msg


def test_rede_caida_nao_levanta(prov, monkeypatch):
    def cai(*a):
        raise TimeoutError("sem rede")
    monkeypatch.setattr(ia, "POST", cai)
    with pytest.raises(ia.IAIndisponivel, match="sem resposta"):
        ia.completar_json("sis", "p")


def test_esquema_estrito_so_para_quem_aceita(prov, monkeypatch):
    monkeypatch.setattr(ia, "COM_ESQUEMA", {"groq:melhor"})
    esquema = {"type": "object", "properties": {"a": {"type": "string"}}}
    prov.roteiro["melhor"] = [Resp(503)]
    ia.completar_json("sis", "p", esquema)
    (_, _, c1), (_, _, c2) = prov.pedidos
    assert c1["response_format"]["json_schema"]["strict"] is True
    assert "response_format" not in c2 and '"properties"' in c2["messages"][0]["content"]


def test_esquema_recusado_tenta_de_novo_sem_estrito(prov, monkeypatch):
    monkeypatch.setattr(ia, "COM_ESQUEMA", {"groq:melhor"})
    prov.roteiro["melhor"] = [Resp(400, texto="invalid response_format"), Resp(conteudo='{"ok": 1}')]
    r = ia.completar_json("sis", "p", {"type": "object"})
    assert r.modelo == "groq:melhor" and r.dados == {"ok": 1}
    assert [("response_format" in c) for _, _, c in prov.pedidos] == [True, False]


def test_openrouter_com_erro_dentro_do_200(prov):
    prov.roteiro["melhor"] = [Resp(corpo={"error": {"message": "upstream rate limited"}})]
    assert ia.completar_json("sis", "p").modelo == "openrouter:segundo:free"


def test_resposta_cortada_nao_vale(prov):
    prov.roteiro["melhor"] = [Resp(conteudo='{"alertas": [', finish="length")]
    assert ia.completar_json("sis", "p").modelo == "openrouter:segundo:free"


def test_registro_de_cada_chamada(prov, monkeypatch):
    linhas = []
    monkeypatch.setattr(ia, "REGISTRO", lambda **kw: linhas.append(kw))
    prov.roteiro["melhor"] = [Resp(429)]
    ia.completar_json("sis", "p", funcao="revisão ME")
    assert [(l["modelo"], l["ok"], l["funcao"]) for l in linhas] == [
        ("groq:melhor", False, "revisão ME"), ("openrouter:segundo:free", True, "revisão ME")]


def test_cadeia_padrao_e_configuracao(monkeypatch):
    monkeypatch.delenv("IA_MODELOS", raising=False)
    assert ia.cadeia()[0] == "groq:openai/gpt-oss-120b"
    monkeypatch.setenv("IA_MODELOS", "openrouter:x:free, inventado:y ,groq:z")
    assert ia.cadeia() == ["openrouter:x:free", "groq:z"]     # provedor desconhecido some
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert not ia.configurada()


def test_corpo_no_formato_openai():
    c = ia._corpo("openai/gpt-oss-120b", "sis", "pedido", {"type": "object"}, True, 4000)
    assert c["model"] == "openai/gpt-oss-120b" and c["max_tokens"] == 4000
    assert [m["role"] for m in c["messages"]] == ["system", "user"]
    assert c["response_format"]["type"] == "json_schema"


def test_limite_total_corta_a_cadeia_e_encurta_a_ultima_espera(prov):
    """Com gente olhando a tela: 40 s no pedido inteiro, não 90 s por modelo."""
    prov.demora = 25
    prov.roteiro = {m: [Resp(500)] for m in ("melhor", "segundo:free", "terceiro")}

    with pytest.raises(ia.IAIndisponivel, match="tempo esgotado"):
        ia.completar_json("sis", "p", limite_s=40)

    assert prov.prazos == [40, 15]          # o terceiro nem foi chamado


def test_sem_limite_cada_modelo_tem_o_prazo_inteiro(prov):
    ia.completar_json("sis", "p")
    assert prov.prazos == [ia.TIMEOUT_S]


@pytest.mark.parametrize("chamar", [
    lambda: extrair_carga.extrair("Pedido de frete para Vitória, 10 kg"),
    lambda: busca_historico.interpretar("acima de 100 kg", date(2026, 11, 6), {}),
    lambda: explicar_erro.pedir("Camilo", "erro"),
    lambda: resposta_cliente.pedir({}, []),
])
def test_quem_tem_tela_esperando_usa_o_limite(prov, chamar, monkeypatch):
    monkeypatch.setattr(resposta_cliente, "_rota", lambda c: "")
    monkeypatch.setattr(resposta_cliente, "_carga", lambda c: "")
    monkeypatch.setattr(resposta_cliente, "_validador", lambda c, ops: None)
    prov.roteiro = {m: [Resp(500)] for m in ("melhor", "segundo:free", "terceiro")}

    with pytest.raises(ia.IAIndisponivel):
        chamar()

    assert prov.prazos[0] == ia.LIMITE_TELA_S
