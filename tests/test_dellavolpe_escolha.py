"""A Della Volpe espera o vendedor escolher para onde vai a proposta.

Decidido em 23/09/2026: na tela da cotação, a linha dela mostra dois botões
— "Mostrar aqui (2 a 5 min)", que manda a resposta para a caixa do suporte e
faz o preço e o PDF aparecerem na tela, e "Mandar para o meu e-mail". Só
depois do clique o robô vai ao site dela.

O que estes testes travam:

- o /cotar NÃO solta a Della Volpe sozinho — o e-mail do formulário dela
  depende da escolha;
- um clique = um envio, mesmo com dois cliques, F5 ou aba duplicada;
- cada escolha chega ao adapter com o e-mail certo e aparece na tela com a
  mensagem certa;
- "ninguém escolheu" nunca vira "Sem retorno" nem "interrompida".
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from carriers.base import ResultadoCotacao
from core.banco import Banco
from core.models import Local, StatusCotacao
from tests.apoio import entrar
from tests.test_web_cotacao import CARGA, FORM_VALIDO, linha_de

IMAP = {"DV_IMAP_HOST": "imap.exemplo.com.br",
        "DV_IMAP_USUARIO": "suporte@ventura.com.br",
        "DV_IMAP_SENHA": "segredo"}
COM_SOLICITANTE = {**CARGA, "cnpj_remetente": "08.310.365/0001-24",
                   "cnpj_destinatario": "60.042.686/0001-05",
                   "cnpj_pagador": "08.310.365/0001-24",
                   "nome_solicitante": "Enzo Zon",
                   "whatsapp_solicitante": "(27) 99988-7766",
                   "transportadoras": "dellavolpe"}


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    monkeypatch.setattr(modulo, "TENTATIVAS_EM_CURSO", {})
    monkeypatch.setattr(modulo, "AUTOMATICAS", ("dellavolpe",))
    for chave in (*IMAP, "DV_EMAIL_RESPOSTA"):
        monkeypatch.delenv(chave, raising=False)
    return modulo


@pytest.fixture
def com_caixa(monkeypatch):
    for k, v in IMAP.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def cliente(app_web):
    c = TestClient(app_web.app)
    entrar(c, app_web)
    return c


@pytest.fixture
def disparos(app_web, monkeypatch):
    """O EXECUTOR anotando o que teria rodado, sem abrir navegador."""
    feitos = []
    monkeypatch.setattr(app_web.EXECUTOR, "submit",
                        lambda fn, *args: feitos.append(args))
    return feitos


def _cotacao(app_web) -> int:
    return app_web.banco.salvar_cotacao("enzo", COM_SOLICITANTE)


def _dv(app_web, cid):
    c = app_web.banco.buscar_cotacao(cid, "enzo")
    return next((r for r in c["resultados"]
                 if r["transportadora"] == "dellavolpe"), None)


def _texto(html: str) -> str:
    return " ".join(html.split())


# ------------------------------------------------------------ a escolha
def test_a_linha_dela_mostra_os_dois_botoes(app_web, cliente, com_caixa):
    cid = _cotacao(app_web)

    linha = _texto(cliente.get(f"/cotacao/{cid}").text)

    assert f'action="/cotacao/{cid}/dellavolpe"' in linha
    assert 'value="tela"' in linha and 'value="email"' in linha
    assert "2 a 5 min" in linha


def test_esperando_a_escolha_nao_diz_enviada(app_web, cliente, com_caixa):
    cid = _cotacao(app_web)

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "dellavolpe")

    assert "Falta escolher" in linha
    assert "Enviada" not in linha


def test_sem_caixa_do_suporte_so_existe_o_meu_email(app_web, cliente):
    """"Mostrar aqui" sem ninguém lendo o suporte perderia a proposta."""
    cid = _cotacao(app_web)

    html = cliente.get(f"/cotacao/{cid}").text

    assert 'value="email"' in html
    assert 'value="tela"' not in html


def test_esperando_a_escolha_nao_fica_recarregando(app_web, cliente,
                                                   com_caixa):
    """Recarregar de 3 em 3 segundos mudaria a página embaixo do dedo de
    quem está indo clicar no botão."""
    cid = _cotacao(app_web)

    assert 'http-equiv="refresh"' not in cliente.get(
        f"/cotacao/{cid}").text


def test_esperando_a_escolha_nunca_vira_sem_retorno(app_web, cliente,
                                                    com_caixa):
    cid = _cotacao(app_web)
    velho = (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds")
    with app_web.banco._conectar() as con:
        con.execute("UPDATE cotacao SET criado_em = ?", (velho,))

    html = cliente.get(f"/cotacao/{cid}").text

    assert "Sem retorno" not in html
    assert 'value="tela"' in html


def test_nem_e_carimbada_como_interrompida(app_web):
    """A varredura da subida não pode tratar "ninguém escolheu" como "o
    sistema foi fechado no meio"."""
    cid = _cotacao(app_web)
    velho = (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds")
    with app_web.banco._conectar() as con:
        con.execute("UPDATE cotacao SET criado_em = ?", (velho,))

    app_web.banco.marcar_interrompidas(
        {s: d for s, d in {"dellavolpe": "2000-01-01T00:00:00"}.items()
         if s != "dellavolpe"})

    assert _dv(app_web, cid) is None


# ------------------------------------------------------------ o clique
def test_mostrar_aqui_solta_o_robo_com_o_suporte(app_web, cliente, com_caixa,
                                                 disparos):
    cid = _cotacao(app_web)

    resposta = cliente.post(f"/cotacao/{cid}/dellavolpe",
                            data={"destino": "tela"}, follow_redirects=False)

    assert resposta.status_code == 303
    [(cid_, slug, fabrica, req)] = disparos
    assert (cid_, slug) == (cid, "dellavolpe")
    assert fabrica.keywords == {"cotacao_id": cid, "resposta_em": "tela"}
    assert req.origem.cidade == CARGA["cidade_origem"]
    r = _dv(app_web, cid)
    assert (r["status"], r["resposta_em"]) == ("enviando", "tela")


def test_meu_email_solta_o_robo_com_o_email_do_vendedor(app_web, cliente,
                                                        com_caixa, disparos):
    cid = _cotacao(app_web)

    cliente.post(f"/cotacao/{cid}/dellavolpe", data={"destino": "email"})

    [(_, _, fabrica, _)] = disparos
    assert fabrica.keywords["resposta_em"] == "email"


def test_dois_cliques_um_envio(app_web, cliente, com_caixa, disparos):
    """Cada envio é uma cotação na fila de uma pessoa da Della Volpe."""
    cid = _cotacao(app_web)

    cliente.post(f"/cotacao/{cid}/dellavolpe", data={"destino": "tela"})
    cliente.post(f"/cotacao/{cid}/dellavolpe", data={"destino": "email"})

    assert len(disparos) == 1
    assert _dv(app_web, cid)["resposta_em"] == "tela"


def test_mostrar_aqui_sem_caixa_vira_meu_email(app_web, cliente, disparos):
    """O .env perdeu a caixa entre a tela e o clique."""
    cid = _cotacao(app_web)

    cliente.post(f"/cotacao/{cid}/dellavolpe", data={"destino": "tela"})

    assert _dv(app_web, cid)["resposta_em"] == "email"


def test_cotacao_gravada_que_nao_vira_pedido_mostra_erro(app_web, cliente,
                                                         com_caixa, disparos):
    """CNPJ inválido no banco (cotação antiga, digitada antes da validação):
    o robô não sai, e a linha diz por quê em vez de ficar girando."""
    cid = app_web.banco.salvar_cotacao(
        "enzo", {**COM_SOLICITANTE, "cnpj_remetente": "11.111.111/1111-11"})

    cliente.post(f"/cotacao/{cid}/dellavolpe", data={"destino": "tela"})

    assert disparos == []
    assert "não deu para reenviar" in _dv(app_web, cid)["erro"]


def test_destino_inventado_nao_envia(app_web, cliente, com_caixa, disparos):
    cid = _cotacao(app_web)

    cliente.post(f"/cotacao/{cid}/dellavolpe", data={"destino": "outro"})

    assert disparos == [] and _dv(app_web, cid) is None


def test_sem_ela_automatica_o_botao_nao_envia(app_web, cliente, com_caixa,
                                              disparos, monkeypatch):
    monkeypatch.setattr(app_web, "AUTOMATICAS", ("camilo",))
    cid = _cotacao(app_web)

    cliente.post(f"/cotacao/{cid}/dellavolpe", data={"destino": "tela"})

    assert disparos == []


def test_cotacao_de_outro_vendedor_nao_envia(app_web, com_caixa, disparos):
    cid = _cotacao(app_web)
    outro = entrar(TestClient(app_web.app), app_web, "outra_pessoa")

    resposta = outro.post(f"/cotacao/{cid}/dellavolpe",
                          data={"destino": "tela"})

    assert resposta.status_code == 404 and disparos == []


def test_o_cotar_nao_solta_a_dellavolpe_sozinho(app_web, cliente, disparos,
                                                monkeypatch):
    from tests.test_dellavolpe_mapping import montar

    req = montar(origem=Local(uf="ES", cidade="Vila Velha", cep="29105770"),
                 destino=Local(uf="SP", cidade="São Paulo", cep="01310100"))
    monkeypatch.setattr(app_web, "montar_request", lambda dados: req)
    monkeypatch.setattr(app_web.buscador_cnpj, "buscar", lambda cnpj: "X")
    monkeypatch.setattr(app_web, "AUTOMATICAS", ("camilo", "dellavolpe"))
    monkeypatch.setattr(app_web, "FABRICAS", {
        "camilo": lambda r, cotacao_id=None: None,
        "dellavolpe": lambda r, cotacao_id=None, resposta_em="tela": None})

    cliente.post("/cotar", data={**FORM_VALIDO,
                                 "transportadora": ["camilo", "dellavolpe"]})

    assert [slug for _, slug, _, _ in disparos] == ["camilo"]


# ---------------------------------------------------- o que a fábrica usa
@pytest.mark.parametrize("resposta_em,esperado", [
    ("tela", "suporte@ventura.com.br"), ("email", None)])
def test_a_fabrica_poe_o_email_da_escolha(app_web, com_caixa, monkeypatch,
                                          resposta_em, esperado):
    visto = {}

    class AdapterFalso:
        def __init__(self, **kw):
            pass

        def cotar(self, req, **kw):
            visto.update(kw)
            return ResultadoCotacao("dellavolpe",
                                    StatusCotacao.AGUARDANDO_RETORNO)

    monkeypatch.setattr(app_web, "DellavolpeAdapter", AdapterFalso)

    app_web._cotar_dellavolpe(object(), cotacao_id=7, resposta_em=resposta_em)

    assert visto["email_resposta"] == esperado
    assert visto["cotacao_id"] == 7


def test_a_carga_gravada_volta_inteira_para_o_formulario(app_web):
    """O pedido original já não existe quando o vendedor clica. O que o site
    recebe tem de ser o que ele digitou — peso POR VOLUME inclusive."""
    cid = _cotacao(app_web)
    c = app_web.banco.buscar_cotacao(cid, "enzo")

    req = app_web.request_da_cotacao(c)

    assert req.origem.uf == "ES" and req.destino.cidade == "São Paulo"
    assert req.quantidade_volumes == 3
    assert req.peso_total_kg == Decimal("12")
    assert req.solicitante.nome == "Enzo Zon"
    assert req.nota_fiscal.valor_total == Decimal("1500.00")


# ------------------------------------------------ enviando, e depois dele
def _enviando(app_web, resposta_em: str) -> int:
    cid = _cotacao(app_web)
    app_web.banco.reservar_envio(cid, "dellavolpe", resposta_em=resposta_em)
    return cid


def test_enviando_para_a_tela_diz_que_esta_cotando_automaticamente(
        app_web, cliente, com_caixa):
    cid = _enviando(app_web, "tela")

    html = cliente.get(f"/cotacao/{cid}").text
    texto = _texto(html)

    assert "Cotando automaticamente na Della Volpe" in texto
    assert "2 a 5 minutos" in texto
    assert '<meta http-equiv="refresh" content="3">' in html


def test_enviando_para_o_email_diz_para_onde_vai(app_web, cliente, com_caixa):
    cid = _enviando(app_web, "email")

    texto = _texto(cliente.get(f"/cotacao/{cid}").text)

    assert "vai para o seu e-mail" in texto
    assert "vendas@ventura.com.br" in texto


def test_enviando_nao_oferece_o_formulario_de_novo(app_web, cliente,
                                                   com_caixa):
    cid = _enviando(app_web, "tela")

    assert f'href="/dellavolpe/{cid}"' not in cliente.get(
        f"/cotacao/{cid}").text


def test_escolheu_email_mostra_a_confirmacao_do_site(app_web, cliente,
                                                     com_caixa, tmp_path):
    png = tmp_path / "resposta.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    cid = _enviando(app_web, "email")
    app_web.banco.salvar_resultado(
        cid, "dellavolpe", status=StatusCotacao.AGUARDANDO_RETORNO.value,
        evidencia=str(png))

    texto = _texto(cliente.get(f"/cotacao/{cid}").text)

    assert "Confirmação do site da Della Volpe" in texto
    assert "vendas@ventura.com.br" in texto
    assert "aparece aqui sozinho" not in texto


def test_escolheu_tela_diz_que_o_preco_aparece_aqui(app_web, cliente,
                                                    com_caixa):
    cid = _enviando(app_web, "tela")
    app_web.banco.salvar_resultado(
        cid, "dellavolpe", status=StatusCotacao.AGUARDANDO_RETORNO.value)

    texto = _texto(cliente.get(f"/cotacao/{cid}").text)

    assert "O preço aparece aqui sozinho" in texto
    assert "2 a 5 minutos" in texto


def test_a_escolha_sobrevive_ao_resultado_final(app_web, com_caixa):
    """`salvar_resultado` sobrescreve a linha. A escolha e o relógio do
    clique não podem ir junto — a tela e o ingestor dependem deles."""
    cid = _enviando(app_web, "tela")
    app_web.banco.salvar_resultado(
        cid, "dellavolpe", status=StatusCotacao.AGUARDANDO_RETORNO.value)

    r = _dv(app_web, cid)
    assert r["resposta_em"] == "tela" and r["pedido_em"]


def test_enviando_que_o_processo_levou_junto_vira_interrompido(app_web):
    cid = _enviando(app_web, "tela")
    velho = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    with app_web.banco._conectar() as con:
        con.execute("UPDATE resultado SET pedido_em = ?", (velho,))

    app_web.banco.marcar_interrompidas({})

    assert _dv(app_web, cid)["status"] == "interrompido"


def test_enviando_recente_nao_e_interrompido(app_web):
    """Um segundo processo na mesma pasta (pytest, script) não pode matar o
    envio vivo do servidor — a mesma trava das outras automáticas."""
    cid = _enviando(app_web, "tela")

    app_web.banco.marcar_interrompidas({})

    assert _dv(app_web, cid)["status"] == "enviando"


def test_o_formulario_assistido_segue_a_escolha(app_web, cliente, com_caixa):
    """Escolheu o próprio e-mail e caiu no captcha: o formulário preenchido
    à mão também tem de mandar a resposta para ELE."""
    from urllib.parse import parse_qs, urlparse
    import base64
    import json
    import re

    cid = _enviando(app_web, "email")
    app_web.banco.salvar_resultado(
        cid, "dellavolpe",
        status=StatusCotacao.INTERVENCAO_NECESSARIA.value, erro="captcha")

    html = cliente.get(f"/dellavolpe/{cid}").text
    url = re.search(r'href="(https://dellavolpe\.com\.br/\?cf=[^"]+)"',
                    html).group(1).replace("&amp;", "&")
    dados = json.loads(base64.b64decode(
        parse_qs(urlparse(url).query)["cf"][0]))

    assert dados["email"] == "vendas@ventura.com.br"
