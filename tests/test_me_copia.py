"""Cópia das cotações reais do ME (tests/fixtures/me_real) e a trava dela.

As três cotações pendentes de 23/09/2026 foram copiadas antes de fecharem:
VENTURA 23039029 (18 itens, 2 páginas) e 23049227 (1 item); UNIÃO 23052403
(3 itens). A única escrita liberada na cópia é a troca de página.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
FIX = RAIZ / "tests" / "fixtures" / "me_real"

_spec = importlib.util.spec_from_file_location("copia_me", RAIZ / "recon" / "copia_cotacoes_me.py")
copia = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(copia)


class _Req:
    def __init__(self, metodo, url, corpo=""):
        self.method, self.url, self.post_data = metodo, url, corpo
        self.resource_type = "document"


class _Route:
    resultado = None

    def abort(self):
        self.resultado = "abortada"

    def continue_(self):
        self.resultado = "seguiu"


FORM = "https://www.me.com.br/RespostaCotaItem.asp?Cotacao=23039029&FID="


def _passar(tmp_path, metodo, url, corpo=""):
    t = copia.TravaPaginacao(tmp_path)
    t.logado = True
    r = _Route()
    t(r, _Req(metodo, url, corpo))
    return r.resultado


@pytest.mark.parametrize("acao", ["11", "12", "19"])
def test_troca_de_pagina_passa(tmp_path, acao):
    assert _passar(tmp_path, "POST", FORM, f"Cotacao=23039029&Acao={acao}&CurrentPage=2") == "seguiu"


@pytest.mark.parametrize("acao", ["1", "9", "2", "4", "5", "0", "", "12x"])
def test_qualquer_outra_acao_aborta(tmp_path, acao):
    assert _passar(tmp_path, "POST", FORM, f"Cotacao=23039029&Acao={acao}") == "abortada"


def test_acao_duplicada_com_envio_aborta(tmp_path):
    # dois campos Acao no corpo: basta um não ser de página para abortar
    assert _passar(tmp_path, "POST", FORM, "Acao=12&Acao=1") == "abortada"


def test_troca_de_pagina_em_outra_url_aborta(tmp_path):
    url = "https://www.me.com.br/RespCotaGrava.asp?Cotacao=23039029"
    assert _passar(tmp_path, "POST", url, "Acao=12") == "abortada"


def test_token_some_da_copia():
    html = '<input type="hidden" name="RequestVerificationToken" value="5e8c5ee5" style="">'
    assert copia.sanitizar(html) == html.replace("5e8c5ee5", "TOKEN")


# -------------------------------------------------------- as cópias em si
ESPERADO = {  # arquivo → números dos itens na página
    "23039029_p1": [f"{n}." for n in range(10, 101, 10)],
    "23039029_p2": [f"{n}." for n in range(110, 181, 10)],
    "23049227_p1": ["10."],
    "23052403_p1": ["10.", "20.", "30."],
}


@pytest.mark.parametrize("nome, itens", ESPERADO.items())
def test_copia_tem_todos_os_itens(nome, itens):
    html = (FIX / f"{nome}.html").read_text(encoding="utf-8")
    achados = re.findall(r'id="spanItem_\d+"[^>]*>([^<]+)<', html)
    assert [a.strip() for a in achados] == itens
    assert (FIX / f"{nome}.jpg").exists()


def test_copias_sem_token_de_sessao():
    for f in FIX.glob("*.html"):
        for valor in re.findall(r'name="RequestVerificationToken"[^>]*value="([^"]*)"', f.read_text(encoding="utf-8")):
            assert valor == "TOKEN", f.name


@pytest.mark.parametrize("conta, numeros", [("ventura", {23039029, 23049227}), ("uniao", {23052403})])
def test_listagem_copiada(conta, numeros):
    lista = json.loads((FIX / f"lista_{conta}.json").read_text(encoding="utf-8"))
    linhas = lista["data"]["result"]
    assert {r["processId"] for r in linhas} == numeros
    assert all(r["answerStatus"] == "Não Respondida" for r in linhas)
