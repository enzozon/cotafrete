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
    "cnpj_remetente": "12345678000190", "cnpj_destinatario": "98765432000110",
    "cnpj_pagador": "12345678000190", "nome_remetente": "Ventura",
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
