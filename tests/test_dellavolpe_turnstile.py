"""Se a Della Volpe religar o Cloudflare Turnstile: o robô para, NADA sai, e
a tela manda o vendedor para o formulário preenchido.

O robô de verdade (DellavolpeAdapter.cotar, com envio confirmado) contra o
formulário de mentira do projeto (mock/server.py), que desenha a caixinha
"confirme que é humano" em dois momentos:

- ?turnstile=antes  — já na página quando ela abre;
- ?turnstile=depois — só depois que o serviço é escolhido, no meio do
  preenchimento. É o caso da segunda olhada do adapter, logo antes do
  clique: clicar com a caixinha na tela é o envio que volta como spam sem
  gerar e-mail (cotações #78 a #84, 31/08/2026).

"Nada saiu" é conferido do lado do servidor: /ultimo-envio fica vazio.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request

import pytest

from carriers.dellavolpe.adapter import CAPTCHA_NA_TELA, DellavolpeAdapter
from core.models import StatusCotacao
from tests.test_dellavolpe_adapter import carga


@pytest.fixture(scope="module")
def mock_dv():
    pytest.importorskip("playwright.sync_api")
    import uvicorn

    from mock.server import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta,
                                             log_level="error"))
    threading.Thread(target=servidor.run, daemon=True).start()
    while not servidor.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{porta}"
    servidor.should_exit = True


def _o_mock_recebeu(base: str) -> dict:
    with urllib.request.urlopen(f"{base}/ultimo-envio") as r:
        return json.loads(r.read())


def _cotar(base: str, pagina: str, tmp_path):
    from mock import server

    server.ULTIMO_ENVIO.clear()
    adapter = DellavolpeAdapter(base_url=f"{base}/{pagina}", headless=True,
                                timeout_ms=15_000, workdir=str(tmp_path))
    return adapter.cotar(carga(), confirmar_envio=True, cotacao_id=7,
                         email_resposta="suporte@ventura.com.br")


def test_sem_caixinha_o_robo_envia(mock_dv, tmp_path):
    """O controle: sem Turnstile o mesmo robô chega a enviar — então as
    paradas abaixo são da caixinha, e não de outra coisa."""
    _cotar(mock_dv, "", tmp_path)

    recebido = _o_mock_recebeu(mock_dv)
    assert recebido.get("campos"), "o envio não chegou ao mock"


def test_caixinha_ao_abrir_para_antes_de_digitar(mock_dv, tmp_path):
    res = _cotar(mock_dv, "?turnstile=antes", tmp_path)

    assert res.status is StatusCotacao.INTERVENCAO_NECESSARIA
    assert res.erro == CAPTCHA_NA_TELA
    assert _o_mock_recebeu(mock_dv) == {}


def test_caixinha_no_meio_para_antes_do_clique(mock_dv, tmp_path):
    res = _cotar(mock_dv, "?turnstile=depois", tmp_path)

    assert res.status is StatusCotacao.INTERVENCAO_NECESSARIA
    assert res.erro == CAPTCHA_NA_TELA
    assert _o_mock_recebeu(mock_dv) == {}


def test_parada_deixa_print_para_conferir(mock_dv, tmp_path):
    res = _cotar(mock_dv, "?turnstile=depois", tmp_path)

    assert res.evidencias and res.evidencias[-1].endswith("captcha.png")


def test_captcha_nao_e_repetido(mock_dv, tmp_path):
    """INTERVENCAO não entra na retentativa: repetir não faz a caixinha
    sumir, e a Della Volpe nem repete em nenhum caso (SEM_REPETICAO)."""
    from core.retentativa import SEM_REPETICAO, vale_repetir

    res = _cotar(mock_dv, "?turnstile=antes", tmp_path)

    assert "dellavolpe" in SEM_REPETICAO
    assert not vale_repetir(res)
