"""Configuração comum dos testes.

Só UMA coisa aqui, e de propósito estreita: o plano B da proposta da Della
Volpe (carriers/dellavolpe/proposta_ia.py) fica DESLIGADO por padrão. Sem
isso, os testes do ingestor que usam PDF sem valor chamariam a IA de verdade
sempre que o .env tivesse chave (web/app.py carrega o .env ao ser importado).

NÃO desliga a IA em geral: core/ia.py, IA_MODELOS e as chaves ficam como
estão, porque test_ia, test_me_revisao, test_extrair_carga, test_me_ncm,
test_adm_me e test_contraste ligam a IA de propósito com provedor falso.
Quem testa o plano B religa com `monkeypatch.setattr(proposta_ia, "LIGADA", True)`.
"""

from __future__ import annotations

import os
import re
import threading
import time
import zlib

import pytest

# O banco guarda hora local sem fuso, e produção roda no horário de Brasília.
# Numa máquina em UTC (CI, container) as conversões de `Date:` de e-mail
# davam 3 h de diferença e o teste falhava sem defeito no código. Fixa o fuso
# de produção antes de qualquer import. `tzset` só existe fora do Windows; lá
# a máquina já está em Brasília e o TZ não pode entrar no ambiente: o C
# runtime não entende "America/Sao_Paulo" e os processos do xdist, que herdam
# o ambiente, passavam a ler a hora como UTC.
if hasattr(time, "tzset"):
    os.environ["TZ"] = "America/Sao_Paulo"
    time.tzset()

# A Della Volpe só é automática com DV_AUTOMATICA_DESDE no .env — e o .env é
# o de QUEM RODA os testes. Numa máquina com ela ligada, os testes que supõem
# "assistida" quebravam; numa sem, quebravam os que supõem "automática". Os
# testes rodam sempre como numa máquina SEM ela ligada: vazio aqui, antes de
# qualquer import, e o load_dotenv(override=False) do app e de
# web/transportadoras.py não sobrescreve. Quem testa o modo automático liga
# com monkeypatch.setenv (ver test_dellavolpe_caixa.py). Só esta variável:
# IA_MODELOS e as chaves de IA ficam como estão.
os.environ["DV_AUTOMATICA_DESDE"] = ""

# Mesmo motivo para os logins do ME dos clientes (Nestlé, WEG...; 28/09/2026):
# com eles no .env de quem roda, a varredura dos testes tentaria ler 12 contas
# que as fixtures não têm. Vazio = login não configurado (logins.credenciais).
# O ME geral (ME_VENTURA/ME_UNIAO) fica como estava: os testes o ligam com
# monkeypatch.setenv. Quem testa um login de cliente liga do mesmo jeito.
from mercado_eletronico import logins as _logins_me  # noqa: E402

for _l in _logins_me.LOGINS:
    if _l.chave not in ("ventura", "uniao"):
        os.environ[f"{_l.prefixo}_LOGIN"] = ""
        os.environ[f"{_l.prefixo}_SENHA"] = ""

from carriers.dellavolpe import proposta_ia  # noqa: E402
from core import explicar_erro  # noqa: E402


@pytest.fixture(autouse=True)
def _plano_b_della_volpe_desligado(monkeypatch):
    monkeypatch.setattr(proposta_ia, "LIGADA", False)
    # Mesmo motivo: o cartão de uma cotação com erro pediria a explicação à
    # IA de verdade (core/explicar_erro.py). Quem testa religa.
    monkeypatch.setattr(explicar_erro, "LIGADA", False)


# Os vigias que o LIFESPAN do app liga (web/app.py, _vida): a varredura do
# Mercado Eletrônico e o leitor da caixa do suporte da Della Volpe. Com as
# senhas do .env da máquina, um teste que sobe o uvicorn sem lifespan="off"
# entra no ME de verdade e lê a caixa de e-mail de verdade — e as threads
# sobram rodando, atropelando os testes seguintes (a falha intermitente do
# test_me_tela, 25/09/2026). Esta trava reprova o teste que os deixou vivos.
VIGIAS = ("me-vigia", "ingestor-dellavolpe")
_ja_acusados: set[int] = set()


@pytest.fixture(autouse=True)
def _nenhum_vigia_real_sobrando():
    yield
    vivos = [t for t in threading.enumerate()
             if t.name in VIGIAS and t.is_alive() and t.ident not in _ja_acusados]
    if vivos:
        _ja_acusados.update(t.ident for t in vivos)
        pytest.fail(f"o teste deixou rodando {[t.name for t in vivos]}: suba o uvicorn "
                    "com lifespan=\"off\" (ver tests/conftest.py)", pytrace=False)


# Marcação `navegador`: todo teste de arquivo que abre Chromium (playwright) ou
# sobe uvicorn. São ~30 arquivos e ~2/3 do tempo da suíte. No dia a dia,
# `pytest tests -m "not navegador"`; a CI roda tudo. Pelo IMPORT e não por
# lista de arquivos: um teste de navegador novo cai na marcação sozinho, e um
# arquivo que só cita "sync_playwright" num texto (test_generoso_fora_de_area)
# não cai.
_USA_NAVEGADOR = re.compile(
    r"^\s*(from playwright|import playwright|import uvicorn)"
    r"|importorskip\(\s*[\"']playwright", re.M)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "navegador: abre Chromium ou sobe uvicorn (lento; marcado "
        "sozinho pelo tests/conftest.py)")
    # Em paralelo (-n), o web/app.py faz Banco() ao ser importado na coleta,
    # nos 4 processos ao mesmo tempo. Numa máquina sem cotafrete.db (a CI)
    # os quatro criam o mesmo arquivo juntos e caem em "database is locked".
    # O processo controlador cria antes de os outros nascerem. Só com xdist:
    # o job do Python 3.8 não importa o core.
    if getattr(config.option, "numprocesses", None) and \
            not os.environ.get("PYTEST_XDIST_WORKER"):
        from core.banco import Banco
        Banco()


def pytest_collection_modifyitems(config, items):
    lidos = {}
    for item in items:
        caminho = item.path
        if caminho not in lidos:
            lidos[caminho] = bool(_USA_NAVEGADOR.search(
                caminho.read_text(encoding="utf-8")))
        if lidos[caminho]:
            item.add_marker(pytest.mark.navegador)
    # PARTE_DA_SUITE=2/4: só os arquivos desta parte, para a CI rodar a suíte
    # em várias máquinas ao mesmo tempo. Por ARQUIVO, para não abrir o mesmo
    # navegador de módulo em duas máquinas; crc32 e não hash() porque o
    # hash() muda a cada processo e o xdist coleta em todos eles.
    parte = os.environ.get("PARTE_DA_SUITE")
    if parte:
        i, n = (int(x) for x in parte.split("/"))
        fica, sai = [], []
        for item in items:
            arquivo = item.nodeid.split("::")[0]
            (fica if zlib.crc32(arquivo.encode()) % n == i - 1 else sai).append(item)
        config.hook.pytest_deselected(items=sai)
        items[:] = fica
