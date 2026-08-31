"""O que a tela do painel mostra.

Os números são a razão de a tela existir: um aproveitamento errado manda o
Enzo cobrar a transportadora errada. Por isso o teste confere o CONTEÚDO, não
só o status 200.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from web import adm, app as app_web

SENHA = "senha-de-teste-123"
CARGA = {"cep_origem": "29105770", "cep_destino": "01310100",
         "cidade_origem": "Vila Velha", "cidade_destino": "São Paulo",
         "peso_kg": "10", "quantidade": 1, "comprimento_cm": 30,
         "largura_cm": 30, "altura_cm": 30, "valor_nf": "1000",
         "material": "PLACA DE VIDEO"}


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))
    c = TestClient(app_web.app)
    c.cookies.set(adm.COOKIE_ADM, adm.token_de(SENHA))
    return c


def test_tela_mostra_cotacao_de_outro_usuario(cliente):
    """É o ponto do painel: o adm vê a empresa inteira, não só as dele."""
    cid = adm.banco.salvar_cotacao("leandro", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                                   valor=Decimal("123.45"))

    html = cliente.get("/adm").text

    assert "leandro" in html
    assert "123,45" in html


def test_tela_separa_falha_de_recusa(cliente):
    """Juntar as duas mandaria o Enzo cacar um problema que nao existe: as
    recusas da Jadlog por peso sao a transportadora funcionando.

    A versao antiga desta asserção só conferia "Recusas" e "Falhas" no HTML —
    e esses são os CABEÇALHOS ESTÁTICOS da tabela, presentes mesmo se as
    colunas viessem trocadas no render. Esta versão confere a LINHA montada de
    cada transportadora, coluna por coluna, com a mesma precisão do teste do
    travessão."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "jadlog", status="recusado",
                                   erro="peso acima de 120 kg")
    adm.banco.salvar_resultado(cid, "generoso", status="erro",
                                   erro="TimeoutError: nao abriu")

    html = cliente.get("/adm").text

    # Ordem das colunas em _saude: transportadora, sucesso, recusa, falha,
    # nossa, inesperado.
    assert '<td>jadlog</td><td>0</td><td>1</td><td>0</td><td>0</td><td>0</td>' in html
    assert '<td>generoso</td><td>0</td><td>0</td><td>1</td><td>0</td><td>0</td>' in html


def test_tela_vazia_nao_quebra(cliente):
    """Pasta nova, primeiro dia, banco sem nada."""
    assert cliente.get("/adm").status_code == 200


def test_o_periodo_escolhido_fica_marcado(cliente):
    """Sem marcar, ninguém sabe qual recorte está vendo — e um número lido
    no período errado é pior que número nenhum."""
    html = cliente.get("/adm?dias=7").text

    assert 'class="periodo atual"' in html
    assert "?dias=7" in html


def test_faixa_ao_vivo_e_um_fragmento_e_nao_a_pagina(cliente):
    """A faixa troca sozinha a cada 10s. Se devolvesse a página inteira, o
    JavaScript recolocaria uma página dentro dela mesma."""
    fragmento = cliente.get("/adm/agora").text

    assert "<!doctype" not in fragmento.lower()
    assert "<html" not in fragmento.lower()


def test_faixa_ao_vivo_tambem_exige_cookie(monkeypatch, tmp_path):
    """O fragmento tem os mesmos dados da tela: não pode ser porta dos
    fundos."""
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))

    resposta = TestClient(app_web.app).get("/adm/agora",
                                           follow_redirects=False)

    assert resposta.status_code == 303


def test_transportadora_so_com_interrompido_mostra_sem_dados(cliente):
    """`aproveitamento` None é DESCONHECIDO, não zero. Se a tela confundir os
    dois, uma transportadora que só viu o servidor reiniciar aparece com
    "0%" — igual a quem nunca acerta uma cotação, o que é mentira."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "jadlog", status="interrompido")

    html = cliente.get("/adm").text

    assert "sem dados ainda" in html
    # Não "0%" cru: a CSS já tem "width:100%" espalhada, que contém "0%"
    # como substring. O que não pode aparecer é a barra de _barra() marcando
    # zero — o texto exato que ela escreve depois do </div>.
    assert "</div> 0%" not in html


def test_cotacao_sem_resultado_mostra_travessao(cliente):
    """`melhor_preco` None é "não teve preço", não "R$ 0,00" — zero seria um
    preço de verdade, e a diferença é a razão de a coluna existir.

    O travessão em si já está no `<title>` de toda página (o "—" de "Painel
    — Cotafrete"), então `assert "—" in html` passaria mesmo se a célula do
    preço saísse vazia. A asserção precisa do fragmento exato que
    `_historico` escreve para a célula: `<td>{moeda(...)}</td>`."""
    adm.banco.salvar_cotacao("enzo", CARGA)

    html = cliente.get("/adm").text

    assert "<td>—</td>" in html
    assert "R$ 0,00" not in html


def test_login_aceita_senha_acentuada(monkeypatch, tmp_path):
    """hmac.compare_digest com `str` só aceita ASCII: qualquer acento levanta
    TypeError (que vira 500). O time vai escrever COTAFRETE_ADM_SENHA no .env
    de produção — se usar acento ou cedilha, a senha CERTA também derrubaria
    o painel para sempre sem o .encode() dos dois lados."""
    senha = "señha-com-acentuação"
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", senha)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))
    c = TestClient(app_web.app)

    errada = c.post("/adm/entrar", data={"senha": "outra-señha-ã"})
    assert errada.status_code == 401

    certa = c.post("/adm/entrar", data={"senha": senha},
                   follow_redirects=False)
    assert certa.status_code == 303


def test_dias_fora_da_lista_cai_em_trinta(cliente):
    """?dias=999999999 estourava OverflowError no timedelta dentro de
    _desde(); ?dias=15 renderizava sem marcar período nenhum como atual; e
    ?dias=-5 buscava no futuro e devolvia tudo vazio. Os três precisam cair
    no mesmo lugar: 30, o padrão."""
    for bruto in ("999999999", "15", "-5"):
        r = cliente.get(f"/adm?dias={bruto}")
        assert r.status_code == 200
        assert '<a class="periodo atual" href="/adm?dias=30">30 dias</a>' \
            in r.text
