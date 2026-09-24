"""O Mercado Eletrônico no painel do administrador (/adm/me).

Pedido do usuário (24/09/2026): acompanhar erros e histórico do ME sem entrar
no ME. O teste confere o CONTEÚDO — o alerta certo, a falha de leitura
registrada, o filtro que filtra — e a porta (mesma senha do /adm).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core import painel_me as pm
from core.banco import Banco
from mercado_eletronico import lista
from mercado_eletronico import revisao as rv
from web import adm, adm_me, me_ui
from web import app as app_web

SENHA = "senha-de-teste-123"
FIX = Path(__file__).resolve().parent / "fixtures" / "me_real"
AGORA = datetime(2026, 9, 24, 17, 0)


def _lista(conta):
    return lista.ler_busca(json.loads((FIX / f"lista_{conta}.json").read_text(encoding="utf-8")))


@pytest.fixture
def banco(monkeypatch, tmp_path):
    b = Banco(tmp_path / "t.db")
    for mod in (adm, me_ui, app_web):
        monkeypatch.setattr(mod, "banco", b)
    monkeypatch.setattr(me_ui, "agora", lambda: AGORA)
    monkeypatch.setattr(adm_me, "agora", lambda: AGORA)
    monkeypatch.setattr(me_ui, "DISPARAR", lambda fn, *a: fn(*a))
    monkeypatch.setattr(me_ui, "FONTE", _lista)
    monkeypatch.setattr(me_ui, "LEITOR",
                        lambda c, n: [p.read_text(encoding="utf-8") for p in sorted(FIX.glob(f"{n}_p*.html"))])
    monkeypatch.setattr(me_ui, "VARREDURA", me_ui.EstadoVarredura())
    return b


@pytest.fixture
def cliente(monkeypatch, banco):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    c = TestClient(app_web.app)
    c.cookies.set(adm.COOKIE_ADM, adm.token_de(SENHA))
    return c


def _id(b, numero):
    return next(c["id"] for c in b.me_cotacoes() if c["numero"] == numero)


def _quebrar(monkeypatch, erro="TimeoutError: a lista do ME não respondeu"):
    def fonte(conta):
        raise TimeoutError(erro)
    monkeypatch.setattr(me_ui, "FONTE", fonte)


# ------------------------------------------------------------------- porta
def test_sem_senha_no_env_nao_existe(monkeypatch, banco):
    monkeypatch.delenv("COTAFRETE_ADM_SENHA", raising=False)
    assert TestClient(app_web.app).get("/adm/me").status_code == 404


def test_sem_cookie_vai_para_o_login(monkeypatch, banco):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    r = TestClient(app_web.app).get("/adm/me", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/adm/entrar"
    r = TestClient(app_web.app).get("/adm/me/agora", follow_redirects=False)
    assert r.status_code == 303


# ------------------------------------------------ a leitura vira histórico
def test_leitura_boa_e_ruim_ficam_gravadas(monkeypatch, banco):
    me_ui.atualizar(["ventura"])
    _quebrar(monkeypatch)
    me_ui.atualizar(["ventura"])
    with banco._conectar() as con:
        linhas = [dict(r) for r in con.execute("SELECT * FROM me_varredura ORDER BY id")]
    assert [l["ok"] for l in linhas] == [1, 0]
    assert linhas[0]["cotacoes"] == 2 and "TimeoutError" in linhas[1]["erro"]


def test_leitura_falhando_seguido_vira_alerta_critico(monkeypatch, banco, cliente):
    me_ui.atualizar(["uniao"])
    _quebrar(monkeypatch)
    for _ in range(3):
        me_ui.atualizar(["uniao"])
    with banco._conectar() as con:
        (l,) = [x for x in pm.leitura_por_conta(con, ("uniao",))]
        alertas = pm.atencao(con, AGORA, ("ventura", "uniao"))
    assert l["falhas_seguidas"] == 3 and l["ultima_ok"]["cotacoes"] == 1
    assert alertas[0]["nivel"] == "critico" and "Leitura do ME falhando — UNIÃO" in alertas[0]["titulo"]
    html = cliente.get("/adm/me").text
    assert "Leitura do ME falhando — UNIÃO" in html and "falhando (3×)" in html
    # a falha de leitura aparece também no histórico de eventos
    assert "falha ao ler a lista do ME" in html


def test_leitura_que_volta_limpa_o_alerta(monkeypatch, banco):
    _quebrar(monkeypatch)
    me_ui.atualizar(["uniao"])
    monkeypatch.setattr(me_ui, "FONTE", _lista)
    me_ui.atualizar(["uniao"])
    with banco._conectar() as con:
        assert not any("Leitura" in a["titulo"] for a in pm.atencao(con, AGORA, ("uniao",)))


def test_erro_ao_ler_itens_fica_no_historico(monkeypatch, banco, cliente):
    me_ui.atualizar(["uniao"])
    cid = _id(banco, 23052403)

    def quebra(conta, numero):
        raise RuntimeError("cotação 23052403 não abriu o formulário de resposta")
    monkeypatch.setattr(me_ui, "LEITOR", quebra)
    from tests.apoio import entrar
    vendedor = entrar(TestClient(app_web.app), app_web)
    vendedor.post(f"/me/{cid}/ler")
    eventos = [h["evento"] for h in banco.me_historico(cid)]
    assert "erro ao ler itens do ME" in eventos
    assert "erro ao ler itens do ME" in cliente.get("/adm/me?problemas=1").text


# ------------------------------------------------------- tela e alertas
def _cenario(banco, monkeypatch):
    """VENTURA 23049227 salva por leandro; UNIÃO 23052403 com o robô falhando."""
    me_ui.atualizar(["ventura", "uniao"])
    ids = {c["numero"]: c["id"] for c in banco.me_cotacoes()}
    for cid in ids.values():
        me_ui.carregar_itens(cid)
    me_ui.gravar_formulario(ids[23049227], {
        "validade_dias": "30", "preco_10": "1.234,50", "ncm_10": "85076000", "prazo_10": "45",
        "marca_10": "DJI", "obs_10": "", "origem_10": "2"})
    monkeypatch.setattr(me_ui, "ROBO", lambda *a: SimpleNamespace(
        ok=True, divergencias=[], prints=[], erro=None, avisos=[]))
    assert me_ui.mandar_robo(ids[23049227], "leandro", False) is None
    me_ui.gravar_formulario(ids[23052403], {
        "validade_dias": "30", "preco_10": "5,00", "ncm_10": "48219000", "prazo_10": "30",
        "marca_10": "3M", "obs_10": "", "origem_10": "0",
        "preco_20": "", "obs_20": "fora de linha", "preco_30": "", "obs_30": "sem estoque"})
    monkeypatch.setattr(me_ui, "ROBO", lambda *a: SimpleNamespace(
        ok=False, divergencias=[], prints=[], erro="TimeoutError: o Salvar não gerou o POST", avisos=[]))
    me_ui.mandar_robo(ids[23052403], "enzo", False)
    monkeypatch.setattr(me_ui, "REVISOR", lambda *a, **k: rv.Revisao(erro="falta ANTHROPIC_API_KEY no .env"))
    me_ui.rodar_revisao(ids[23049227], "leandro")
    return ids


def test_painel_mostra_numeros_alertas_e_quem_salvou(monkeypatch, banco, cliente):
    _cenario(banco, monkeypatch)
    html = cliente.get("/adm/me").text
    with banco._conectar() as con:
        r = pm.resumo(con, AGORA)
    assert (r["salvas"], r["erros"]) == (1, 1)
    assert "Robô falhou — 23052403 · UNIÃO" in html
    assert "TimeoutError: o Salvar não gerou o POST" in html
    assert "leandro" in html                               # quem salvou
    assert "revisão IA indisponível" in html               # problema no histórico
    assert 'href="/adm/me"' in html                        # link no menu lateral


def test_salva_esquecida_perto_do_prazo_vira_critico(monkeypatch, banco):
    _cenario(banco, monkeypatch)
    # 23049227 fecha 25/09 21:00: a 10 h do prazo, salva e não enviada
    perto = datetime(2026, 9, 25, 11, 0)
    with banco._conectar() as con:
        alertas = pm.atencao(con, perto, ("ventura", "uniao"))
    salva = [a for a in alertas if "23049227" in a["titulo"]]
    assert salva and salva[0]["nivel"] == "critico" and "NÃO enviada" in salva[0]["titulo"]


def test_filtros_de_conta_status_e_so_problemas(monkeypatch, banco, cliente):
    _cenario(banco, monkeypatch)
    uniao = cliente.get("/adm/me?conta=uniao").text
    assert "23052403" in uniao
    assert '/adm/me/' + str(_id(banco, 23049227)) + '"' not in uniao.split("me-cotacoes")[1].split("me-eventos")[0]
    so_erro = cliente.get("/adm/me?status=erro").text.split('id="me-cotacoes"')[1].split('id="me-eventos"')[0]
    assert "23052403" in so_erro and "23049227" not in so_erro
    problemas = cliente.get("/adm/me?problemas=1").text.split('id="me-eventos"')[1]
    assert "erro do robô" in problemas and "apareceu no ME" not in problemas


def test_periodo_estranho_na_url_vira_30_dias(monkeypatch, banco, cliente):
    assert cliente.get("/adm/me?dias=999999999").status_code == 200


def test_ao_vivo_so_manda_quando_muda(monkeypatch, banco, cliente):
    me_ui.atualizar(["ventura"])
    d = cliente.get("/adm/me/agora").json()
    assert set(d) >= {"v", "faixa", "atencao", "cotacoes", "eventos", "leitura"}
    assert cliente.get(f"/adm/me/agora?v={d['v']}").status_code == 204
    _quebrar(monkeypatch)
    me_ui.atualizar(["ventura"])
    assert cliente.get(f"/adm/me/agora?v={d['v']}").status_code == 200


def test_tela_de_uma_cotacao(monkeypatch, banco, cliente):
    ids = _cenario(banco, monkeypatch)
    html = cliente.get(f"/adm/me/{ids[23052403]}").text
    assert "Cotação 23052403 · UNIÃO" in html
    assert "recusado:</b> fora de linha" in html
    assert "erro do robô" in html
    assert "RespostaCotaItem.asp?Cotacao=23052403" in html      # abrir no ME
    html2 = cliente.get(f"/adm/me/{ids[23049227]}").text
    assert "Revisão IA indisponível: falta ANTHROPIC_API_KEY" in html2
    assert cliente.get("/adm/me/99999").status_code == 404


def test_painel_do_adm_nao_mudou(monkeypatch, banco, cliente):
    """O /adm de fretes continua lá, agora com o link do ME no menu."""
    html = cliente.get("/adm").text
    assert "Painel" in html and 'href="/adm/me"' in html
