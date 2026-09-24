"""A tela /me de ponta a ponta, sem ME e sem navegador.

A lista vem do JSON real copiado em 23/09/2026 (via lista.ler_busca), os
itens das páginas reais copiadas, e o robô é um falso que só registra o que
receberia. O que se confere é o CONTEÚDO: o status certo, o imposto certo na
prévia, o robô recebendo os itens certos — e nenhum botão de enviar.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from mercado_eletronico import lista
from tests.apoio import entrar
from web import app as app_web
from web import me_ui

FIX = Path(__file__).resolve().parent / "fixtures" / "me_real"
AGORA = datetime(2026, 9, 23, 17, 0)


def _lista(conta):
    return lista.ler_busca(json.loads((FIX / f"lista_{conta}.json").read_text(encoding="utf-8")))


def _paginas(conta, numero):
    return [p.read_text(encoding="utf-8") for p in sorted(FIX.glob(f"{numero}_p*.html"))]


class RoboFalso:
    def __init__(self, resultado=None):
        self.chamadas = []
        self.resultado = resultado or SimpleNamespace(ok=True, divergencias=[], prints=["p.png"], erro=None)

    def __call__(self, conta, numero, itens, validade_dias, dry_run):
        self.chamadas.append((conta, numero, itens, validade_dias, dry_run))
        return self.resultado


@pytest.fixture
def robo():
    return RoboFalso()


@pytest.fixture
def cliente(monkeypatch, tmp_path, robo):
    banco = Banco(tmp_path / "t.db")
    monkeypatch.setattr(app_web, "banco", banco)
    monkeypatch.setattr(me_ui, "banco", banco)
    monkeypatch.setattr(me_ui, "agora", lambda: AGORA)
    monkeypatch.setattr(me_ui, "FONTE", _lista)
    monkeypatch.setattr(me_ui, "LEITOR", _paginas)
    monkeypatch.setattr(me_ui, "ROBO", robo)
    monkeypatch.setattr(me_ui, "DISPARAR", lambda fn, *a: fn(*a))
    monkeypatch.setattr(me_ui, "VARREDURA", me_ui.EstadoVarredura())
    for c in ("VENTURA", "UNIAO"):
        monkeypatch.setenv(f"ME_{c}_LOGIN", "x")
        monkeypatch.setenv(f"ME_{c}_SENHA", "x")
    return entrar(TestClient(app_web.app), app_web)


def _id(numero):
    return next(c["id"] for c in me_ui.banco.me_cotacoes() if c["numero"] == numero)


def test_precisa_de_login(monkeypatch, tmp_path):
    monkeypatch.setattr(app_web, "banco", Banco(tmp_path / "t.db"))
    r = TestClient(app_web.app).get("/me", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_lista_das_duas_contas(cliente):
    cliente.post("/me/atualizar")
    html = cliente.get("/me").text
    for n in ("23039029", "23049227", "23052403"):
        assert n in html
    assert "VENTURA" in html and "UNIÃO" in html
    # 23039029 fecha hoje 21:00: 4 h de prazo, destaque na linha
    assert "Fecha em 4 h 00 min" in html
    c = me_ui.banco.me_cotacao(_id(23052403))
    assert c["data_limite"] == "2026-09-28T21:00"   # dueDate UTC → Brasília
    assert c["comprador"] == "Mayanna Cristina Goncalves de Aguirre"


def test_filtro_por_conta(cliente):
    cliente.post("/me/atualizar")
    html = cliente.get("/me?conta=uniao").text
    assert "23052403" in html and "23039029" not in html


def test_leitura_que_falha_nao_da_nada_como_enviado(cliente, monkeypatch):
    cliente.post("/me/atualizar")

    def quebra(conta):
        raise TimeoutError("ME fora do ar")

    monkeypatch.setattr(me_ui, "FONTE", quebra)
    cliente.post("/me/atualizar")
    assert {c["status"] for c in me_ui.banco.me_cotacoes()} == {"pendente"}
    assert "Falha ao ler VENTURA" in cliente.get("/me").text


def test_sumiu_da_lista_antes_do_prazo_vira_enviada(cliente, monkeypatch):
    cliente.post("/me/atualizar")
    monkeypatch.setattr(me_ui, "FONTE", lambda conta: [
        p for p in _lista(conta) if p.numero != 23049227])
    cliente.post("/me/atualizar")
    c = me_ui.banco.me_cotacao(_id(23049227))
    assert c["status"] == "enviada" and c["na_lista"] == 0
    assert "saiu de Oportunidades a Responder" in [h["evento"] for h in me_ui.banco.me_historico(c["id"])]


def test_ler_itens_das_duas_paginas(cliente):
    cliente.post("/me/atualizar")
    cid = _id(23039029)
    r = cliente.post(f"/me/{cid}/ler")
    assert "18 itens lidos" in r.text
    itens = me_ui.banco.me_cotacao(cid)["itens"]
    assert [i["numero"] for i in itens] == list(range(10, 181, 10))
    assert {(i["pagina"], i["indice"]) for i in itens if i["numero"] in (100, 110)} == {(1, 10), (2, 1)}


def _preencher(cliente, cid, **extra):
    form = {"validade_dias": "30", "preco_10": "1.234,50", "ncm_10": "8507.60.00",
            "prazo_10": "45", "marca_10": "DJI", "obs_10": "", "origem_10": "0",
            "acao": "conferir", **extra}
    return cliente.post(f"/me/{cid}", data=form)


def test_previa_com_o_imposto_da_uf_de_entrega(cliente):
    """VENTURA entregando em MG: ICMS 12, PIS/COFINS da VENTURA, entrega em
    23/09 + 45 = 07/11 (sábado) → 09/11."""
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    html = _preencher(cliente, cid).text
    assert "ICMS 12,00%" in html
    assert "PIS 0,65 sim" in html and "COFINS 3,00 sim" in html
    assert "entrega 09/11/2026" in html
    # remessa pedida 29/11: sem aviso de atraso
    assert "depois da data de remessa" not in html


def test_marca_e_origem_lembradas_para_o_mesmo_material(cliente):
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    _preencher(cliente, cid, origem_10="2")
    assert me_ui.banco.me_material("263252") == {
        **me_ui.banco.me_material("263252"), "ncm": "8507.60.00", "marca": "DJI", "origem": 2}


def test_salvar_no_me_chama_o_robo_e_marca_salva(cliente, robo):
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    html = _preencher(cliente, cid, acao="salvar").text
    ((conta, numero, itens, validade, dry),) = robo.chamadas
    assert (conta, numero, validade, dry) == ("ventura", 23049227, 30, False)
    assert (itens[0].numero, itens[0].preco, itens[0].pedido.uf_destino) == (10, "1.234,50", "MG")
    c = me_ui.banco.me_cotacao(cid)
    assert c["status"] == "salva" and c["salvo_por"] == "enzo"
    assert "Salva no ME" in html


def test_rascunho_salvo_continua_salva_na_proxima_varredura(cliente):
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    _preencher(cliente, cid, acao="salvar")
    cliente.post("/me/atualizar")  # o ME ainda diz "Não Respondida"
    assert me_ui.banco.me_cotacao(cid)["status"] == "salva"


def test_com_erro_o_robo_nem_sai(cliente, robo):
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    html = _preencher(cliente, cid, acao="salvar", ncm_10="123").text
    assert robo.chamadas == []
    assert "Corrija os erros antes" in html
    assert me_ui.banco.me_cotacao(cid)["status"] == "pendente"


def test_divergencia_depois_de_salvar_vira_erro(cliente, robo):
    robo.resultado = SimpleNamespace(ok=True, divergencias=["preco: enviado '1,00', gravado '0,00'"],
                                     prints=[], erro=None)
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    _preencher(cliente, cid, acao="salvar")
    c = me_ui.banco.me_cotacao(cid)
    assert c["status"] == "erro" and "divergência" in c["erro"]


def test_dry_run_nao_muda_o_status(cliente, robo):
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    _preencher(cliente, cid, acao="dry_run")
    assert robo.chamadas[0][4] is True
    assert me_ui.banco.me_cotacao(cid)["status"] == "pendente"


def test_tela_nao_tem_como_enviar(cliente):
    """A regra crítica, vista da tela: nenhum botão manda proposta."""
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    html = cliente.get(f"/me/{cid}").text.lower()
    assert "confirmar" not in html.replace("confirm(", "")
    assert 'value="enviar"' not in html
    rotas = {r.path for r in me_ui.router.routes}
    assert not any("envi" in r and not r.endswith("/enviada") for r in rotas)


def test_marcar_como_enviada_e_manual_e_final(cliente):
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/enviada")
    assert me_ui.banco.me_cotacao(cid)["status"] == "enviada"
    cliente.post("/me/atualizar")  # continua "Não Respondida" no ME
    assert me_ui.banco.me_cotacao(cid)["status"] == "enviada"
    # fechada para edição
    _preencher(cliente, cid, acao="salvar")
    assert me_ui.banco.me_cotacao(cid)["itens"] == []


def test_menu_tem_o_link(cliente):
    assert 'href="/me"' in cliente.get("/historico").text


def test_ligacao_padrao_com_o_robo_e_a_ponte(monkeypatch):
    """Sem os falsos: a tela chama ponte.* e robo.salvar_cotacao com a Conta
    certa e dry_run nomeado (a assinatura do robô é keyword-only)."""
    from mercado_eletronico import ponte, robo
    from mercado_eletronico.regras import Conta
    chamadas = []
    monkeypatch.setattr(ponte, "pendencias", lambda conta: chamadas.append(("lista", conta)) or [])
    monkeypatch.setattr(ponte, "ler_paginas", lambda conta, n: chamadas.append(("ler", conta, n)) or [])
    monkeypatch.setattr(robo, "salvar_cotacao",
                        lambda conta, n, itens, validade, *, dry_run: chamadas.append(("robo", conta, n, dry_run)))
    me_ui._fonte_padrao("uniao")
    me_ui._leitor_padrao("ventura", 1)
    me_ui._robo_padrao("uniao", 2, [], 30, True)
    assert chamadas == [("lista", "uniao"), ("ler", "ventura", 1), ("robo", Conta.UNIAO, 2, True)]


def _revisor(alertas=None, erro=None):
    from mercado_eletronico import revisao as rv
    chamadas = []

    def revisar(c, previa, erros, avisos, obs_geral=""):
        chamadas.append((c["numero"], obs_geral))
        return rv.Revisao([rv.Alerta(*a) for a in (alertas or [])], erro, "claude-opus-5")
    return revisar, chamadas


def test_revisao_por_ia_mostra_alertas_no_item_e_na_cotacao(cliente, monkeypatch):
    revisar, chamadas = _revisor([(10, "critico", "marca DJI; comprador pediu outra"),
                                  (None, "atencao", "validade curta")])
    monkeypatch.setattr(me_ui, "REVISOR", revisar)
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    html = _preencher(cliente, cid, acao="revisar").text
    # o texto geral do comprador vai junto
    assert chamadas[0][0] == 23049227 and "Prezado Fornecedor" in chamadas[0][1]
    assert "IA · Crítico: marca DJI; comprador pediu outra" in html
    assert "Atenção: validade curta" in html
    assert "revise de novo" not in html
    # mudou o preenchimento → revisão marcada como velha
    html = _preencher(cliente, cid, marca_10="Outra").text
    assert "revise de novo" in html
    assert "revisão IA: 2 alertas" in [h["evento"] for h in me_ui.banco.me_historico(cid)]


def test_ia_indisponivel_nao_bloqueia_salvar(cliente, monkeypatch, robo):
    revisar, _ = _revisor(erro="falta ANTHROPIC_API_KEY no .env")
    monkeypatch.setattr(me_ui, "REVISOR", revisar)
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    html = _preencher(cliente, cid, acao="revisar").text
    assert "Revisão IA indisponível: falta ANTHROPIC_API_KEY" in html
    _preencher(cliente, cid, acao="salvar")
    assert me_ui.banco.me_cotacao(cid)["status"] == "salva"


def test_documentacao_com_os_numeros_do_codigo(cliente, monkeypatch):
    """A aba Documentação explica o ME com os números que a tela usa: mudou a
    constante, muda a ajuda — e nunca promete um botão de enviar."""
    from mercado_eletronico import regras as rg
    monkeypatch.setattr(me_ui, "INTERVALO_S", 9 * 60)
    monkeypatch.setattr(me_ui, "MAX_OBS", 77)
    html = cliente.get("/documentacao").text
    assert "Mercado Eletrônico: responder cotações" in html
    assert "a cada <b>9 minutos</b>" in html
    assert f"até {rg.MAX_MARCA} caracteres" in html and "até 77)" in html
    assert "Quem envia é sempre você" in html
    assert 'href="/me"' in html


def test_alerta_da_cotacao_inteira_aparece_uma_vez(cliente, monkeypatch):
    revisar, _ = _revisor([(None, "atencao", "falta o nº da proposta")])
    monkeypatch.setattr(me_ui, "REVISOR", revisar)
    cliente.post("/me/atualizar")
    cid = _id(23049227)
    cliente.post(f"/me/{cid}/ler")
    html = _preencher(cliente, cid, acao="revisar").text
    assert html.count("falta o nº da proposta") == 1
