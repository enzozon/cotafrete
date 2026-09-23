"""Trava de rede do recon do Mercado Eletrônico — sem navegador, sem ME.

O recon roda logado na conta real. A trava é o que garante que abrir uma
cotação nunca vire proposta enviada: todo POST/PUT/PATCH/DELETE para os dois
domínios do ME morre, exceto o login (antes de logar) e a busca da listagem.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("recon_me", RAIZ / "recon" / "recon_me.py")
recon_me = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recon_me)


class _Req:
    def __init__(self, metodo, url, corpo=""):
        self.method, self.url, self.post_data = metodo, url, corpo
        self.resource_type = "document"


class _Route:
    def __init__(self):
        self.resultado = None

    def abort(self):
        self.resultado = "abortada"

    def continue_(self):
        self.resultado = "seguiu"


def _passar(trava, metodo, url, corpo=""):
    rota = _Route()
    trava(rota, _Req(metodo, url, corpo))
    return rota.resultado


@pytest.fixture
def trava(tmp_path):
    t = recon_me.Trava(tmp_path)
    t.logado = True
    return t


# Os dois POSTs que decidem tudo: mesmo form, mesma URL, só o Acao muda.
URL_FORM = "https://www.me.com.br/RespostaCotaItem.asp?Cotacao=23039029&FID="


@pytest.mark.parametrize("acao", ["1", "9", "2", "4", "12"])
def test_nenhum_post_do_formulario_da_cotacao_passa(trava, acao):
    assert _passar(trava, "POST", URL_FORM, f"Acao={acao}&Cotacao=23039029") == "abortada"


def test_recusa_bloqueada(trava):
    url = "https://www.me.com.br/RespCotaGrava.asp?Cotacao=23039029"
    assert _passar(trava, "POST", url, "Acao=2") == "abortada"


@pytest.mark.parametrize("metodo", ["PUT", "PATCH", "DELETE"])
def test_outros_metodos_de_escrita_bloqueados(trava, metodo):
    assert _passar(trava, metodo, "https://www.me.com.br/do/api/v2/qualquer") == "abortada"


def test_dominio_novo_do_me_tambem_e_travado(trava):
    url = "https://api.web.mercadoe.com/supplier/transactions/v1/transactions/answer"
    assert _passar(trava, "POST", url) == "abortada"


def test_busca_da_listagem_e_a_unica_escrita_liberada(trava):
    url = "https://api.web.mercadoe.com/supplier/transactions/v1/transactions/search"
    assert _passar(trava, "POST", url, '{"paging":{"page":1}}') == "seguiu"
    # prefixo parecido não serve
    assert _passar(trava, "POST", url + "/../answer") == "abortada"


def test_get_com_cara_de_envio_bloqueado(trava):
    url = "https://www.me.com.br/do/api/v2/supplier/pendencies/orders/confirmation/reasons"
    assert _passar(trava, "GET", url) == "abortada"


def test_leitura_comum_passa(trava):
    assert _passar(trava, "GET", URL_FORM.replace("&FID=", "&SuperCleanPage=")) == "seguiu"


def test_login_so_passa_antes_de_logar(tmp_path):
    t = recon_me.Trava(tmp_path)
    url = "https://www.me.com.br/do/Login.mvc/Login"
    assert _passar(t, "POST", url, "LoginName=x") == "seguiu"
    t.logado = True
    assert _passar(t, "POST", url, "LoginName=x") == "abortada"


def test_terceiros_nao_sao_problema_da_trava(trava):
    # analytics/chat não falam com o ME; bloquear só quebraria a página
    assert _passar(trava, "POST", "https://www.google-analytics.com/g/collect") == "seguiu"


def test_bloqueio_fica_registrado_com_o_corpo(trava, tmp_path):
    _passar(trava, "POST", URL_FORM, "Acao=1")
    linhas = (tmp_path / "requisicoes.jsonl").read_text(encoding="utf-8").splitlines()
    assert any('"bloqueado"' in l and "Acao=1" in l for l in linhas)
    assert trava.bloqueios[-1]["corpo"] == "Acao=1"
