"""A porta da frente: quem entra, quem não entra, e o primeiro acesso.

Estes testes batem na rota de verdade, com HTTP, porque o buraco que eles
fecham era de rota: até 16/09/2026 qualquer pessoa digitava um nome e
entrava. O `test_nome_inventado_nao_entra` é o que mais importa — se um dia
ele passar a falhar, o sistema voltou a ser uma porta aberta.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from core import sessao
from core.banco import Banco


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    import web.app as modulo
    importlib.reload(modulo)
    banco = Banco(tmp_path / "cotafrete.db")
    monkeypatch.setattr(modulo, "banco", banco)
    monkeypatch.setattr(modulo.adm, "banco", banco)
    # Sem o atraso: ele existe para atrapalhar quem tenta mil senhas, e aqui
    # só atrasaria a suíte.
    monkeypatch.setattr(modulo, "PAUSA_SENHA_ERRADA_S", 0)
    return modulo


@pytest.fixture
def c(app_web):
    return TestClient(app_web.app, follow_redirects=False)


def _com_conta(app_web, nome="joao", senha="senha-do-joao"):
    app_web.banco.criar_conta(nome)
    if senha:
        app_web.banco.definir_senha(nome, sessao.hash_senha(senha))
    return nome


# --------------------------------------------------------- a porta fechada
def test_nome_inventado_nao_entra(c, app_web):
    """O buraco antigo. Antes isto criava sessão e abria o sistema."""
    r = c.post("/login", data={"usuario": "invasor", "senha": "qualquer"})

    assert r.status_code == 401
    assert app_web.COOKIE not in r.cookies


def test_senha_errada_nao_entra(c, app_web):
    _com_conta(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "chute"})

    assert r.status_code == 401
    assert app_web.COOKIE not in r.cookies


def test_a_tela_nao_repete_a_senha_digitada(c, app_web):
    """Senha errada não pode voltar escrita na tela: fica no histórico do
    navegador e na tela de quem estiver olhando por cima do ombro."""
    _com_conta(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "MinhaSenhaSecreta"})

    assert "MinhaSenhaSecreta" not in r.text


def test_sem_sessao_o_sistema_manda_para_o_login(c):
    for rota in ("/", "/historico"):
        r = c.get(rota)
        assert r.status_code == 303, rota
        assert r.headers["location"] == "/login", rota


def test_cookie_forjado_nao_abre_o_sistema(c, app_web):
    """O mesmo ataque do test_sessao, agora pela porta HTTP."""
    _com_conta(app_web)
    c.cookies.set(app_web.COOKIE, "joao")

    r = c.get("/")

    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_conta_removida_perde_o_acesso_na_hora(c, app_web):
    """Sem isto, tirar alguém do sistema só faria efeito quando o cookie dela
    vencesse — até uma semana depois."""
    _com_conta(app_web)
    c.cookies.set(app_web.COOKIE,
                  sessao.assinar("joao", app_web.banco.segredo_sessao()))
    assert c.get("/").status_code == 200

    app_web.banco.remover_conta("joao")

    assert c.get("/").status_code == 303


# --------------------------------------------------------- a porta abrindo
def test_senha_certa_entra(c, app_web):
    _com_conta(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "senha-do-joao"})

    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert sessao.dono_do_cookie(r.cookies[app_web.COOKIE],
                                 app_web.banco.segredo_sessao()) == "joao"


def test_o_cookie_entregue_nao_contem_o_nome_legivel(c, app_web):
    _com_conta(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "senha-do-joao"})

    assert "joao" not in r.cookies[app_web.COOKIE]


# ------------------------------------------- primeiro acesso (link de convite)
# O primeiro acesso NÃO acontece mais na tela de entrar digitando o nome. O
# admin gera um link com token (abrir_convite) e a pessoa escolhe a senha em
# /definir-senha?t=<token>. Antes, quem soubesse o nome do vendedor escolhia a
# senha dele antes dele (tomada de conta) — era o que a auditoria apontou.

def _convite(app_web, nome="joao", horas=72):
    """Cria a conta (convite aberto) e devolve o token do link."""
    app_web.banco.criar_conta(nome)
    return app_web.banco.abrir_convite(nome, horas=horas)


def test_a_tela_de_convite_mostra_o_nome_e_pede_a_senha(c, app_web):
    t = _convite(app_web)

    r = c.get("/definir-senha", params={"t": t})

    assert r.status_code == 200
    assert "Primeiro acesso" in r.text
    assert "joao" in r.text


def test_definir_a_senha_pelo_link_entra_de_uma_vez(c, app_web):
    t = _convite(app_web)

    r = c.post("/definir-senha", data={"t": t, "senha": "frase-boa-aqui",
                                       "confirmacao": "frase-boa-aqui"})

    assert r.status_code == 303
    assert app_web.COOKIE in r.cookies
    assert sessao.senha_confere("frase-boa-aqui",
                                app_web.banco.conta("joao")["senha_hash"])


def test_login_nao_define_mais_senha_pelo_nome(c, app_web):
    """O buraco principal: com o convite aberto, mandar senha na tela de
    entrar NÃO podia escolher a senha da conta. Agora /login nunca define."""
    _convite(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "a-do-invasor",
                               "confirmacao": "a-do-invasor"})

    assert r.status_code == 401
    assert app_web.banco.conta("joao")["senha_hash"] is None


def test_o_login_nao_revela_se_a_conta_existe_ou_espera_senha(c, app_web):
    """Enumeração: conta inexistente, convite aberto e senha errada têm de dar
    a MESMA resposta, senão a tela vira detector de nome e de alvo fácil."""
    _convite(app_web, nome="maria")                 # convite aberto
    _com_conta(app_web, nome="joao")                # já tem senha

    inexistente = c.post("/login", data={"usuario": "ninguem", "senha": "x"})
    convite = c.post("/login", data={"usuario": "maria", "senha": "x"})
    errada = c.post("/login", data={"usuario": "joao", "senha": "chute"})

    # A MENSAGEM é a mesma nos três casos (o nome digitado volta no campo, mas
    # isso é o input da pessoa, não um sinal de que a conta existe).
    msg = "Nome ou senha não conferem"
    assert inexistente.status_code == convite.status_code == errada.status_code == 401
    assert msg in inexistente.text and msg in convite.text and msg in errada.text
    # O caminho da conta com convite aberto não mostra a tela de escolher senha
    # (só o link, que a pessoa tem, leva a ela).
    assert "Salvar senha e entrar" not in convite.text


def test_token_invalido_e_recusado(c, app_web):
    _convite(app_web)

    get = c.get("/definir-senha", params={"t": "token-que-nao-existe"})
    post = c.post("/definir-senha", data={"t": "token-que-nao-existe",
                                          "senha": "uma-senha-boa",
                                          "confirmacao": "uma-senha-boa"})

    assert get.status_code == 400 and "inválido" in get.text.lower()
    assert post.status_code == 400
    assert app_web.banco.conta("joao")["senha_hash"] is None


def test_token_expirado_e_recusado(c, app_web):
    t = _convite(app_web, horas=-1)                 # já nasceu vencido

    r = c.post("/definir-senha", data={"t": t, "senha": "uma-senha-boa",
                                       "confirmacao": "uma-senha-boa"})

    assert r.status_code == 400
    assert app_web.banco.conta("joao")["senha_hash"] is None


def test_token_e_de_uso_unico(c, app_web):
    t = _convite(app_web)
    c.post("/definir-senha", data={"t": t, "senha": "primeira-senha",
                                   "confirmacao": "primeira-senha"})

    r = c.post("/definir-senha", data={"t": t, "senha": "segunda-senha",
                                       "confirmacao": "segunda-senha"})

    assert r.status_code == 400
    assert sessao.senha_confere("primeira-senha",
                                app_web.banco.conta("joao")["senha_hash"])


def test_senhas_diferentes_no_convite_nao_definem_nada(c, app_web):
    t = _convite(app_web)

    r = c.post("/definir-senha", data={"t": t, "senha": "frase-boa-aqui",
                                       "confirmacao": "frase-boa-daqui"})

    assert r.status_code == 200          # reexibe a tela de convite
    assert app_web.banco.conta("joao")["senha_hash"] is None


def test_senha_curta_no_convite_recusada_com_o_motivo(c, app_web):
    t = _convite(app_web)

    r = c.post("/definir-senha", data={"t": t, "senha": "1234",
                                       "confirmacao": "1234"})

    assert r.status_code == 200
    assert str(sessao.MINIMO_DA_SENHA) in r.text
    assert app_web.banco.conta("joao")["senha_hash"] is None


# ------------------------------------------- o administrador pela mesma porta
SENHA_DO_PAINEL = "senha-do-painel-de-teste"


@pytest.fixture
def com_painel(app_web, monkeypatch):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA_DO_PAINEL)
    return app_web


@pytest.mark.parametrize("como", ["adm", "ADMIN", "Administrador", "  adm  "])
def test_o_administrador_entra_pela_tela_do_vendedor(c, com_painel, como):
    """A única porta do painel: o /login, com a senha do painel."""
    r = c.post("/login", data={"usuario": como, "senha": SENHA_DO_PAINEL})

    assert r.status_code == 303
    assert r.headers["location"] == "/adm"
    assert com_painel.adm.COOKIE_ADM in r.cookies


def test_senha_errada_no_nome_reservado_nao_abre_o_painel(c, com_painel):
    r = c.post("/login", data={"usuario": "adm", "senha": "chute"})

    assert r.status_code == 401
    assert com_painel.adm.COOKIE_ADM not in r.cookies
    assert com_painel.COOKIE not in r.cookies, "nem sessão de vendedor"


def test_a_recusa_do_adm_e_igual_a_de_um_vendedor(c, com_painel):
    """Texto diferente transformaria a tela num detector de nome válido:
    quem estivesse tentando descobriria quais nomes existem."""
    _com_conta(com_painel)

    do_adm = c.post("/login", data={"usuario": "adm", "senha": "chute"}).text
    do_vendedor = c.post("/login", data={"usuario": "joao", "senha": "x"}).text

    assert "Nome ou senha não conferem" in do_adm
    assert "Nome ou senha não conferem" in do_vendedor


def test_sem_senha_de_painel_configurada_o_nome_reservado_nao_entra(c, app_web,
                                                                    monkeypatch):
    """Sem COTAFRETE_ADM_SENHA o painel nem existe (responde 404). O nome
    reservado não pode virar uma porta sem tranca."""
    monkeypatch.delenv("COTAFRETE_ADM_SENHA", raising=False)

    r = c.post("/login", data={"usuario": "adm", "senha": ""})

    assert r.status_code == 401
    assert app_web.adm.COOKIE_ADM not in r.cookies


def test_conta_de_vendedor_com_nome_reservado_nao_sequestra_o_painel(c, com_painel):
    """Se alguém conseguisse criar a conta "adm" por outro caminho, ela não
    pode servir para entrar no painel com a senha dela."""
    com_painel.banco.criar_conta("adm")
    com_painel.banco.definir_senha("adm", sessao.hash_senha("senha-do-espiao"))

    r = c.post("/login", data={"usuario": "adm", "senha": "senha-do-espiao"})

    assert r.status_code == 401
    assert com_painel.adm.COOKIE_ADM not in r.cookies
    assert com_painel.COOKIE not in r.cookies


# ------------------------------------------------------ a marca Secure
def test_por_padrao_o_cookie_nao_exige_https(c, app_web):
    """Desligado de propósito: a equipe também entra por
    http://192.168.1.250:8000, e ali `Secure` faria o navegador descartar o
    cookie em silêncio — login que não funciona e não dá erro."""
    _com_conta(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "senha-do-joao"})

    assert "secure" not in r.headers["set-cookie"].lower()


def test_a_variavel_liga_a_marca_nos_dois_cookies(c, app_web, monkeypatch):
    """Um cookie protegido e o outro não seria pior que nenhum: o do painel é
    justamente o mais poderoso."""
    monkeypatch.setenv("COTAFRETE_COOKIE_SEGURO", "1")
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "senha-do-painel-de-teste")
    _com_conta(app_web)

    do_vendedor = c.post("/login", data={"usuario": "joao",
                                         "senha": "senha-do-joao"})
    do_painel = c.post("/login", data={"usuario": "adm",
                                       "senha": "senha-do-painel-de-teste"})

    assert "secure" in do_vendedor.headers["set-cookie"].lower()
    assert "secure" in do_painel.headers["set-cookie"].lower()


def test_https_encaminhado_liga_a_marca_sozinho(c, app_web):
    """Atrás do Cloudflare o uvicorn vê http; o esquema real vem em
    `X-Forwarded-Proto`. Quando ele diz https, o Secure liga sem precisar da
    env — é o que fecha o cookie no endereço público sem tocar na LAN."""
    _com_conta(app_web)

    r = c.post("/login", data={"usuario": "joao", "senha": "senha-do-joao"},
               headers={"x-forwarded-proto": "https"})

    assert "secure" in r.headers["set-cookie"].lower()


def test_cabecalhos_de_seguranca_em_toda_resposta(c):
    r = c.get("/login")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "strict-origin" in r.headers["referrer-policy"]


def test_a_doc_da_api_nao_e_indexavel(c):
    """Mesmo aberta no desenvolvimento, a doc da API não pode ir para o
    buscador."""
    r = c.get("/openapi.json")

    assert "noindex" in r.headers.get("x-robots-tag", "")


def test_pagina_autenticada_nao_cacheia_nem_indexa(c, app_web):
    _com_conta(app_web)
    entrada = c.post("/login", data={"usuario": "joao",
                                     "senha": "senha-do-joao"})
    c.cookies.set(app_web.COOKIE, entrada.cookies[app_web.COOKIE])

    r = c.get("/")

    assert "no-store" in r.headers["cache-control"]
    assert "noindex" in r.headers["x-robots-tag"]


def test_sair_derruba_a_sessao(c, app_web):
    _com_conta(app_web)
    c.cookies.set(app_web.COOKIE,
                  sessao.assinar("joao", app_web.banco.segredo_sessao()))

    c.get("/sair")
    c.cookies.clear()

    assert c.get("/").status_code == 303


# ------------------------------------------------- revogar sessão
def test_esquecer_a_senha_derruba_a_sessao_aberta(app_web):
    """"Esquecer senha" é o que o admin usa quando a senha vazou. O cookie
    antigo continuava valendo até 7 dias."""
    from tests.apoio import entrar
    c = entrar(TestClient(app_web.app, follow_redirects=False), app_web, "joao")
    assert c.get("/").status_code == 200
    app_web.banco.esquecer_senha("joao")
    assert c.get("/").headers.get("location") == "/login"


def test_sair_corta_a_sessao_no_servidor(c, app_web):
    """"Sair" grava o corte no servidor — não só apaga o cookie no navegador.
    Antes, um cookie copiado sobrevivia ao logout até o prazo de 7 dias."""
    _com_conta(app_web)
    login = c.post("/login", data={"usuario": "joao", "senha": "senha-do-joao"})
    c.cookies.set(app_web.COOKIE, login.cookies[app_web.COOKIE])
    assert app_web.banco.conta("joao")["sessoes_ate"] is None

    c.get("/sair")

    assert app_web.banco.conta("joao")["sessoes_ate"] is not None


def test_cookie_emitido_antes_do_logout_nao_vale(app_web):
    """A lógica do corte, com tempos controlados (sem depender do relógio da
    suíte): cookie anterior ao `sessoes_ate` é recusado; um posterior vale."""
    from datetime import datetime
    seg = app_web.banco.segredo_sessao()
    base = {"senha_hash": "x", "definida_em": datetime(2020, 1, 1).isoformat()}
    antes = sessao.assinar("joao", seg, agora=datetime(2021, 1, 1))
    depois = sessao.assinar("joao", seg, agora=datetime(2022, 1, 1))

    # sem logout: vale
    assert app_web._cookie_vale_para({**base, "sessoes_ate": None}, antes)
    # logout em 2021-06: o cookie de 2021-01 (anterior) cai...
    corte = {**base, "sessoes_ate": datetime(2021, 6, 1).isoformat()}
    assert app_web._cookie_vale_para(corte, antes) is False
    # ...e um novo login (2022, posterior ao corte) volta a valer
    assert app_web._cookie_vale_para(corte, depois) is True


def test_conta_recriada_nao_herda_o_cookie_da_antiga(app_web):
    from datetime import datetime, timedelta
    app_web.banco.criar_conta("joao")
    app_web.banco.definir_senha("joao", sessao.hash_senha("senha-antiga-1"))
    antigo = sessao.assinar("joao", app_web.banco.segredo_sessao(),
                            agora=datetime.now() - timedelta(hours=1))
    app_web.banco.remover_conta("joao")
    app_web.banco.criar_conta("joao")
    app_web.banco.definir_senha("joao", sessao.hash_senha("senha-nova-12"))
    c = TestClient(app_web.app, follow_redirects=False)
    c.cookies.set(app_web.COOKIE, antigo)
    assert c.get("/").headers.get("location") == "/login"


def test_cookie_com_acento_e_recusado_sem_erro_500():
    """compare_digest com str não-ASCII levantava TypeError (500)."""
    assert sessao.dono_do_cookie("61|9999999999|é", "segredo") is None
