"""Aceitar a cotação pelo site — a tela, a rota e o que elas recusam.

NENHUM teste daqui abre navegador: a função que fala com o portal é trocada
por uma falsa, e o que se verifica é o que o Cotafrete decide ANTES de chamar
a Generoso. É onde moram as decisões que custam caro:

- quem pode aceitar (a cotação de outro vendedor não abre nem por URL);
- o que pode ser aceito (vencida não, sem preço não, já aceita não);
- o que chega ao adapter (data, hora, almoço, observação).

O agendamento de verdade é o commit anterior, provado em dry-run contra o
portal. Aqui é a camada que decide SE ele deve rodar.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from fastapi.testclient import TestClient

from core.banco import Banco
from tests.apoio import entrar
from tests.test_web_cotacao import CARGA, linha_de


def _dia_util(daqui_a: int = 2) -> date:
    d = date.today() + timedelta(days=daqui_a)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    monkeypatch.setattr(modulo, "TENTATIVAS_EM_CURSO", {})
    return modulo


@pytest.fixture
def pedidos(app_web, monkeypatch):
    """Substitui o agendamento real. Guarda o que teria ido ao portal.

    Roda na hora, e não numa thread: o teste quer ver o resultado, e uma
    thread transformaria cada asserção numa corrida."""
    recebidos = []

    def falso(cotacao_id, slug, protocolo, ag, usuario):
        recebidos.append({"cotacao_id": cotacao_id, "slug": slug,
                          "protocolo": protocolo, "ag": ag,
                          "usuario": usuario})
        app_web.banco.concluir_aceite(cotacao_id, slug, status="agendado",
                                      protocolo=protocolo)

    monkeypatch.setattr(app_web, "_agendar", falso)
    monkeypatch.setattr(app_web.EXECUTOR, "submit",
                        lambda fn, *a, **kw: fn(*a, **kw))
    return recebidos


@pytest.fixture
def cliente(app_web):
    c = TestClient(app_web.app)
    entrar(c, app_web)
    return c


def _cotada(app_web, *, validade=None, valor=Decimal("152.16"),
            protocolo="2684352", usuario="enzo") -> int:
    """Cotação com TODAS as automáticas respondidas — senão a tela entra no
    modo "cotando…", que é outro estado e outra tela."""
    if validade is None:
        validade = date.today() + timedelta(days=7)
    cid = app_web.banco.salvar_cotacao(usuario, CARGA)
    for slug in app_web.AUTOMATICAS:
        eh_generoso = slug == "generoso"
        app_web.banco.salvar_resultado(
            cid, slug, status="cotado", valor=valor,
            protocolo=protocolo if eh_generoso else None,
            prazo="6", validade=validade if eh_generoso else None)
    return cid


def _form(**over) -> dict:
    base = {"data_coleta": _dia_util().isoformat(), "hora_limite": "16:30",
            "observacao": ""}
    base.update(over)
    return base


# ------------------------------------------------------- o botão na tabela
def test_generoso_cotada_e_valida_ganha_botao_aceitar(app_web, cliente):
    cid = _cotada(app_web)

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "generoso")

    assert f"/aceitar/{cid}/generoso" in linha
    assert "Aceitar" in linha


def test_cotacao_vencida_nao_tem_botao(app_web, cliente):
    """O preço continua na tela porque é histórico. O botão some porque o
    que ele faria — levar um preço vencido ao portal — não pode dar certo."""
    cid = _cotada(app_web, validade=date.today() - timedelta(days=1))

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "generoso")

    assert "/aceitar/" not in linha
    assert "venceu em" in linha


def test_transportadora_sem_aceite_nao_tem_botao(app_web, cliente):
    """Só a Generoso foi implementada. Oferecer o botão nas outras seria
    prometer o que o servidor recusa no clique seguinte."""
    cid = _cotada(app_web)

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "camilo")

    assert "/aceitar/" not in linha


def test_sem_preco_nao_tem_botao(app_web, cliente):
    cid = app_web.banco.salvar_cotacao("enzo", CARGA)
    for slug in app_web.AUTOMATICAS:
        app_web.banco.salvar_resultado(cid, slug, status="erro",
                                       erro="o site não respondeu")

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "generoso")

    assert "/aceitar/" not in linha


# ------------------------------------------------------ abrir o formulário
def test_a_tela_mostra_o_que_esta_sendo_aceito(app_web, cliente):
    """Quem confirma precisa ver o que está confirmando sem voltar uma
    página para conferir."""
    cid = _cotada(app_web)

    html = cliente.get(f"/aceitar/{cid}/generoso").text

    assert "152,16" in html
    assert "2684352" in html
    assert "6 dias" in html


def test_a_tela_traz_as_mesmas_opcoes_do_site_da_generoso(app_web, cliente):
    """O pedido do Enzo: as mesmas opções do portal. 08:00 às 18:00 para a
    coleta, e o almoço — medidos no recon."""
    cid = _cotada(app_web)

    html = cliente.get(f"/aceitar/{cid}/generoso").text

    assert "08:00" in html and "18:00" in html
    assert "fecha para almoço" in html
    assert "Observação para o coletador" in html


def test_a_tela_avisa_que_o_caminhao_vai_de_verdade(app_web, cliente):
    cid = _cotada(app_web)

    html = cliente.get(f"/aceitar/{cid}/generoso").text

    assert "de verdade" in html


def test_cotacao_de_outro_vendedor_nao_abre(app_web, cliente):
    """Trocar o número na URL não dá acesso ao alheio — a mesma checagem de
    dono que a tela da cotação já faz."""
    cid = _cotada(app_web, usuario="maria")

    assert cliente.get(f"/aceitar/{cid}/generoso").status_code == 404


def test_deslogado_vai_para_o_login(app_web):
    cid = _cotada(app_web)
    anonimo = TestClient(app_web.app)

    resposta = anonimo.get(f"/aceitar/{cid}/generoso", follow_redirects=False)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == "/login"


# -------------------------------------------------------------- confirmar
def test_confirmar_manda_os_dados_certos_ao_adapter(app_web, cliente, pedidos):
    dia = _dia_util()

    cliente.post(
        f"/aceitar/{_cotada(app_web)}/generoso",
        data=_form(data_coleta=dia.isoformat(), hora_limite="16:30",
                   fecha_almoco="on", almoco_inicio="12:00",
                   almoco_fim="13:30", observacao="Portaria dos fundos"),
        follow_redirects=False)

    assert len(pedidos) == 1
    ag = pedidos[0]["ag"]
    assert pedidos[0]["protocolo"] == "2684352"
    assert ag.data == dia
    assert ag.hora_limite == "16:30"
    assert ag.almoco_inicio == "12:00"
    assert ag.almoco_fim == "13:30"
    assert ag.observacao == "Portaria dos fundos"


def test_sem_marcar_almoco_os_horarios_sao_ignorados(app_web, cliente, pedidos):
    """Os selects vão no POST mesmo com a caixa desmarcada — eles existem no
    HTML. Sem esta regra, todo agendamento sairia com almoço que ninguém
    pediu, e o coletador programaria a rota por causa disso."""
    cliente.post(f"/aceitar/{_cotada(app_web)}/generoso",
                 data=_form(almoco_inicio="12:00", almoco_fim="13:00"),
                 follow_redirects=False)

    ag = pedidos[0]["ag"]
    assert ag.almoco_inicio is None
    assert ag.almoco_fim is None
    assert ag.fecha_para_almoco is False


def test_confirmar_registra_quem_aceitou(app_web, cliente, pedidos):
    cid = _cotada(app_web)

    cliente.post(f"/aceitar/{cid}/generoso", data=_form(),
                 follow_redirects=False)

    assert app_web.banco.aceites(cid)["generoso"]["usuario"] == "enzo"


def test_confirmar_volta_para_a_cotacao(app_web, cliente, pedidos):
    cid = _cotada(app_web)

    resposta = cliente.post(f"/aceitar/{cid}/generoso", data=_form(),
                            follow_redirects=False)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == f"/cotacao/{cid}"


def test_a_tabela_passa_a_dizer_que_a_coleta_foi_agendada(app_web, cliente,
                                                          pedidos):
    cid = _cotada(app_web)
    cliente.post(f"/aceitar/{cid}/generoso", data=_form(),
                 follow_redirects=False)

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "generoso")

    assert "coleta agendada" in linha
    assert "/aceitar/" not in linha         # e o botão some


# -------------------------------------------------------------- as recusas
def test_sabado_nao_passa_e_o_formulario_volta_preenchido(app_web, cliente,
                                                          pedidos):
    """Perder o formulário inteiro por causa de um sábado é o jeito mais
    rápido de fazer alguém desistir e ligar para a transportadora."""
    hoje = date.today()
    sabado = hoje + timedelta(days=(5 - hoje.weekday()) % 7 or 7)

    html = cliente.post(f"/aceitar/{_cotada(app_web)}/generoso",
                        data=_form(data_coleta=sabado.isoformat(),
                                   observacao="Falar com o João")).text

    assert pedidos == []                    # nada chegou ao portal
    assert "fim de semana" in html
    assert "Falar com o João" in html       # o que foi digitado voltou


def test_cotacao_vencida_recusa_no_post_tambem(app_web, cliente, pedidos):
    """Esconder o botão não basta: a URL continua existindo, e uma aba
    aberta desde ontem ainda a tem."""
    cid = _cotada(app_web, validade=date.today() - timedelta(days=1))

    html = cliente.post(f"/aceitar/{cid}/generoso", data=_form()).text

    assert pedidos == []
    assert "venceu" in html.lower()


def test_aceitar_duas_vezes_nao_pede_duas_coletas(app_web, cliente, pedidos):
    """O gesto mais banal que existe numa tela web: apertar de novo porque a
    primeira vez pareceu não responder. O segundo pedido para no banco."""
    cid = _cotada(app_web)

    cliente.post(f"/aceitar/{cid}/generoso", data=_form(),
                 follow_redirects=False)
    cliente.post(f"/aceitar/{cid}/generoso", data=_form(hora_limite="09:00"),
                 follow_redirects=False)

    assert len(pedidos) == 1


def test_transportadora_sem_aceite_recusa_no_post(app_web, cliente, pedidos):
    cid = _cotada(app_web)

    resposta = cliente.post(f"/aceitar/{cid}/camilo", data=_form())

    assert pedidos == []
    assert resposta.status_code == 404


def test_falha_no_portal_libera_nova_tentativa(app_web, cliente, monkeypatch):
    """Coleta que NÃO chegou a ser pedida não pode travar a cotação para
    sempre — só a que deu certo é definitiva."""
    cid = _cotada(app_web)

    def falhou(cotacao_id, slug, protocolo, ag, usuario):
        app_web.banco.concluir_aceite(cotacao_id, slug, status="erro",
                                      erro="o portal não abriu a tela")

    monkeypatch.setattr(app_web, "_agendar", falhou)
    monkeypatch.setattr(app_web.EXECUTOR, "submit",
                        lambda fn, *a, **kw: fn(*a, **kw))
    cliente.post(f"/aceitar/{cid}/generoso", data=_form(),
                 follow_redirects=False)

    linha = linha_de(cliente.get(f"/cotacao/{cid}").text, "generoso")
    assert "tentar de novo" in linha
    assert f"/aceitar/{cid}/generoso" in linha
