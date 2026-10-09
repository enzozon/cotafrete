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
import threading

import pytest

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


@pytest.fixture(autouse=True)
def _me_sem_memoria_de_leitura(monkeypatch):
    # Cada teste tem banco novo e os ids se repetem: a lista de cotações que a
    # varredura já tentou ler (web/me_ui.py) não pode passar de um para outro.
    from web import me_ui
    monkeypatch.setattr(me_ui, "JA_TENTOU_LER", set())


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
