"""A tela da cotação, no estado em que o usuário SEMPRE a vê primeiro.

Logo depois de enviar o formulário nenhuma transportadora respondeu ainda.
Esse é o caminho normal — e era exatamente ele que quebrava com HTTP 500,
porque a tela decidia "já desisti de esperar?" DEPOIS de desenhar os cartões
que dependem dessa resposta.

Os testes daqui batem na rota de verdade, com banco de verdade em pasta
temporária. Testar a função solta não pegaria o erro: ele só aparece quando
existe uma transportadora pendente.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco

CARGA = {
    "cep_origem": "29010-000", "cep_destino": "01310-100",
    "cidade_origem": "Vitória", "uf_origem": "ES",
    "cidade_destino": "São Paulo", "uf_destino": "SP",
    "peso_kg": "12", "quantidade": 3,
    "comprimento_cm": 80, "largura_cm": 60, "altura_cm": 50,
    "valor_nf": "1500.00", "material": "Bomba",
    # Com máscara porque é assim que /cotar grava (cnpj_formatado). O
    # fixture guardava 14 dígitos crus, que a tela nunca recebe na prática.
    "cnpj_remetente": "12.345.678/0001-90",
    "cnpj_destinatario": "98.765.432/0001-10",
    "cnpj_pagador": "12.345.678/0001-90", "nome_remetente": "Ventura",
    "nome_destinatario": "Cliente", "nome_pagador": "Ventura",
}


@pytest.fixture
def app_web(tmp_path, monkeypatch):
    """Banco isolado por teste: o histórico real do Enzo não entra aqui."""
    from web import app as modulo
    monkeypatch.setattr(modulo, "banco", Banco(tmp_path / "teste.db"))
    return modulo


@pytest.fixture
def cliente(app_web):
    c = TestClient(app_web.app)
    c.cookies.set(app_web.COOKIE, "enzo")
    return c


def _criar(app_web, *, criado_em: str | None = None) -> int:
    cotacao_id = app_web.banco.salvar_cotacao("enzo", CARGA)
    if criado_em:
        with app_web.banco._conectar() as con:
            con.execute("UPDATE cotacao SET criado_em = ? WHERE id = ?",
                        (criado_em, cotacao_id))
    return cotacao_id


def test_tela_abre_com_todas_as_transportadoras_ainda_cotando(app_web, cliente):
    """O bug do 500: `desistiu` era lido antes de existir.

    Só quebrava quando faltava alguma transportadora — ou seja, em 100% das
    cotações recém-enviadas, e em nenhum teste que olhasse só o resultado
    pronto."""
    cotacao_id = _criar(app_web)

    resposta = cliente.get(f"/cotacao/{cotacao_id}")

    assert resposta.status_code == 200
    assert "cotando" in resposta.text
    assert 'http-equiv="refresh"' in resposta.text


def test_depois_do_teto_para_de_recarregar_e_avisa(app_web, cliente):
    """Passou o tempo máximo: assume que não vem mais e para de piscar."""
    velha = (datetime.now()
             - timedelta(seconds=app_web.ESPERA_MAXIMA_S + 60)).isoformat()
    cotacao_id = _criar(app_web, criado_em=velha)

    resposta = cliente.get(f"/cotacao/{cotacao_id}")

    assert resposta.status_code == 200
    assert "Sem retorno" in resposta.text
    assert "não responderam" in resposta.text
    assert 'http-equiv="refresh"' not in resposta.text


def test_cotacao_pronta_nao_recarrega(app_web, cliente):
    """Tudo respondido: recarregar faria a imagem piscar na cara de quem lê."""
    from decimal import Decimal

    cotacao_id = _criar(app_web)
    for slug in app_web.AUTOMATICAS:
        app_web.banco.salvar_resultado(cotacao_id, slug, status="cotado",
                                       valor=Decimal("69.91"))

    resposta = cliente.get(f"/cotacao/{cotacao_id}")

    assert resposta.status_code == 200
    assert 'http-equiv="refresh"' not in resposta.text
    assert "cotando…" not in resposta.text


def test_cotacao_de_outro_usuario_nao_abre(app_web, cliente):
    """Trocar o número na URL não pode dar acesso à cotação alheia."""
    cotacao_id = app_web.banco.salvar_cotacao("outra_pessoa", CARGA)

    assert cliente.get(f"/cotacao/{cotacao_id}").status_code == 404


def test_regex_da_mascara_chega_inteira_no_browser():
    """As regex do JS da máscara vivem dentro de uma f-string do Python.

    Sem prefixo `r`, `\\d` é sequência de escape inválida: hoje o Python só
    avisa, mas na versão em que isso virar erro o servidor não sobe. E se
    alguém "consertar" o aviso escapando errado, a máscara para de casar
    dígito e o CNPJ vai torto para a transportadora."""
    import inspect

    from web import app as modulo

    fonte = inspect.getsource(modulo._render_formulario)

    assert r"replace(/\D/g" in fonte
    assert r"/^(\d{{2}})(\d)/" in fonte


# --------------------------------------------------------------- ficha
# O Enzo pediu em 19/08/2026: a tela de resultado tem que mostrar os dados
# que geraram aquela cotação, depois dos botões de WhatsApp. Antes disso o
# vendedor via só os preços — e para conferir de onde vieram tinha que
# abrir o histórico e comparar de cabeça.
def test_ficha_mostra_o_que_foi_preenchido(app_web, cliente):
    html = cliente.get(f"/cotacao/{_criar(app_web)}").text

    for esperado in ("29010-000", "01310-100", "Vitória", "São Paulo",
                     "12.345.678/0001-90", "98.765.432/0001-10",
                     "Ventura", "Cliente", "Bomba"):
        assert esperado in html, f"a ficha não mostrou {esperado!r}"


def test_ficha_separa_peso_total_do_peso_por_volume(app_web, cliente):
    """CARGA são 3 volumes e 12 kg no TOTAL — 4 kg cada.

    O campo do formulário pede o peso de UM volume; o banco guarda o total.
    Escrever só "Peso: 12" deixa o vendedor sem saber qual dos dois é, e é
    esse número que ele redigita ao repetir a cotação."""
    html = cliente.get(f"/cotacao/{_criar(app_web)}").text

    assert "Peso total" in html
    assert "12" in html
    assert "4" in html          # o unitário, para conferir com a ficha


# ------------------------------------------- repetir sem inflar o peso (19/08)
def test_repetir_cotacao_devolve_o_peso_de_UM_volume(app_web, cliente):
    """BUG: `/cotar` grava req.peso_total_kg e `_valores_de` devolvia esse
    total para o campo "Peso de UM volume".

    Com 3 volumes de 4 kg (total 12), repetir preenchia 12 no campo unitário
    e a cotação seguinte saía com 36 kg — três vezes a carga real, sem aviso
    nenhum na tela, porque 36 kg é um peso perfeitamente válido. Repetindo de
    novo virava 108. Quanto maior a quantidade, maior o erro."""
    cotacao_id = _criar(app_web)

    html = cliente.get(f"/?repetir={cotacao_id}").text
    campo_peso = html.split('id="peso"')[1].split(">")[0]

    assert 'value="4"' in campo_peso, (
        f"o campo do peso unitário veio com {campo_peso!r} — "
        "o total de 12 kg voltaria multiplicado por 3 volumes")


def test_peso_quebrado_usa_virgula_como_o_resto_da_tela(app_web, cliente):
    """"12.5 kg" ao lado de "R$ 568,77" na mesma tela é o tipo de detalhe que
    faz o vendedor desconfiar do número — e desconfiar do peso é desconfiar
    do frete inteiro."""
    carga = {**CARGA, "peso_kg": "12.5", "quantidade": 1}
    html = cliente.get(f"/cotacao/{app_web.banco.salvar_cotacao('enzo', carga)}").text

    assert "12,5 kg" in html
    assert "12.5 kg" not in html


# ------------------------------------------- recusa que o vendedor entende
def test_recusa_da_transportadora_chega_na_tela(app_web, cliente):
    """BUG: `_rodar` gravava só `res.erro`, e os caminhos de recusa da
    Translovato preenchem `res.motivo_recusa`. A frase escrita para o
    vendedor era jogada fora e o cartão caía no genérico "o site respondeu:
    recusado" — exatamente o que essas mensagens existem para evitar."""
    from carriers.base import ResultadoCotacao
    from core.models import StatusCotacao

    cotacao_id = _criar(app_web)
    recusa = ResultadoCotacao(
        "translovato", StatusCotacao.RECUSADO,
        motivo_recusa="A Translovato só cota frete saindo da Ventura.")
    app_web._rodar(cotacao_id, "translovato", lambda _: recusa, None)

    html = cliente.get(f"/cotacao/{cotacao_id}").text

    assert "só cota frete saindo da Ventura" in html
    assert "o site respondeu" not in html
