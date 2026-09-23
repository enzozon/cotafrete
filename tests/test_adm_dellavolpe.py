"""A tela /adm/dellavolpe: o que o ingestor fez com cada e-mail da Della
Volpe que chegou na caixa do suporte.

Existe para ninguém precisar abrir o log\\servidor.log nem rodar comando
para saber se uma proposta entrou. O que importa aqui:

- a tela é do painel: sem a senha do painel, não abre;
- o e-mail cujo preço NÃO entrou em cotação nenhuma aparece destacado —
  é o que alguém tem de lançar à mão;
- o detalhe e o assunto vêm de fora (do e-mail), então saem escapados.
"""

from __future__ import annotations

import importlib
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from tests.test_dellavolpe_ingestor import CARGA

SENHA_DO_PAINEL = "senha-do-painel-de-teste"


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA_DO_PAINEL)
    import web.app as modulo
    importlib.reload(modulo)
    banco = Banco(tmp_path / "cotafrete.db")
    monkeypatch.setattr(modulo, "banco", banco)
    monkeypatch.setattr(modulo.adm, "banco", banco)
    monkeypatch.setattr(modulo.adm, "ingestor", None)
    return modulo


@pytest.fixture
def chefe(app_web):
    c = TestClient(app_web.app, follow_redirects=False)
    c.cookies.set(app_web.adm.COOKIE_ADM,
                  app_web.adm.token_de(SENHA_DO_PAINEL))
    return c


def _registrar(banco, mid, desfecho, **k):
    banco.registrar_email(mid, "dellavolpe", desfecho=desfecho, **k)


def test_sem_a_senha_do_painel_nao_abre(app_web):
    anonimo = TestClient(app_web.app, follow_redirects=False)

    r = anonimo.get("/adm/dellavolpe")

    assert r.status_code == 303
    assert r.headers["location"] == "/adm/entrar"


def test_sem_painel_montado_e_404(app_web, monkeypatch):
    monkeypatch.delenv("COTAFRETE_ADM_SENHA")

    r = TestClient(app_web.app).get("/adm/dellavolpe")

    assert r.status_code == 404


def test_lista_cada_email_com_desfecho_e_link_da_cotacao(app_web, chefe):
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    _registrar(app_web.banco, "<a@dv>", "gravado", cotacao_id=cid,
               detalhe=f"R$ 1873.91 na cotação #{cid}",
               assunto="Proposta 15693", recebido_em="2026-09-23T14:05:09")

    html = chefe.get("/adm/dellavolpe").text

    assert "Proposta 15693" in html
    assert "23/09 14:05" in html
    assert "Gravado" in html
    assert f'href="/adm/cotacao/{cid}"' in html
    assert "R$ 1873.91" in html
    assert "Precisa de atenção" not in html


def test_o_que_nao_entrou_em_cotacao_fica_destacado(app_web, chefe):
    _registrar(app_web.banco, "<b@dv>", "sem_par",
               detalhe="nenhuma cotação esperando proposta",
               assunto="Proposta 15700")
    _registrar(app_web.banco, "<c@dv>", "sem_pdf", assunto="Confirmação")

    html = chefe.get("/adm/dellavolpe").text

    assert "Precisa de atenção" in html
    assert "1 e-mail da Della Volpe" in html
    # Só a linha do sem_par ganha o destaque; o sem_pdf é o e-mail de
    # confirmação que vem junto, e não pede nada.
    assert html.count('<tr class="precisa">') == 1
    assert "Sem cotação" in html and "Sem PDF" in html


def test_assunto_e_detalhe_saem_escapados(app_web, chefe):
    _registrar(app_web.banco, "<d@dv>", "ambigua",
               detalhe="<script>alert(1)</script>",
               assunto="<img src=x onerror=alert(2)>")

    html = chefe.get("/adm/dellavolpe").text

    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html


def test_sem_email_ainda_diz_isso(chefe):
    html = chefe.get("/adm/dellavolpe").text

    assert "ainda não leu nenhum e-mail" in html


def test_ingestor_desligado_explica_o_que_falta(chefe):
    html = chefe.get("/adm/dellavolpe").text

    assert "desligado" in html
    assert "DV_IMAP_HOST" in html
    # E nunca a senha, nem o nome da variável com valor.
    assert "DV_IMAP_SENHA=" not in html


def _vigia(**k):
    base = dict(cx=SimpleNamespace(usuario="suporte@ventura.com.br",
                                   intervalo_s=60),
                ultima_volta=datetime(2026, 9, 23, 14, 6, 0),
                ultimo_erro=None)
    base.update(k)
    return SimpleNamespace(**base)


def test_ingestor_ligado_mostra_a_ultima_volta(app_web, chefe, monkeypatch):
    monkeypatch.setattr(app_web.adm, "ingestor", _vigia())

    html = chefe.get("/adm/dellavolpe").text

    assert "suporte@ventura.com.br" in html
    assert "23/09 14:06:00" in html
    assert "A caixa abriu." in html


def test_ingestor_com_erro_mostra_o_erro(app_web, chefe, monkeypatch):
    monkeypatch.setattr(app_web.adm, "ingestor", _vigia(
        ultimo_erro="error: [AUTHENTICATIONFAILED] Invalid credentials"))

    html = chefe.get("/adm/dellavolpe").text

    assert "NÃO abriu a caixa" in html
    assert "AUTHENTICATIONFAILED" in html


def test_o_menu_do_painel_leva_a_tela(chefe):
    html = chefe.get("/adm").text

    assert 'href="/adm/dellavolpe"' in html
