"""Login da Braspress atrás de reCAPTCHA (10/11/2026): erro claro, sem repetir."""
from __future__ import annotations

import pytest

from carriers.base import CredencialRecusada, erro_do_adapter
from carriers.braspress.adapter import (
    BraspressAdapter, LoginBarradoPorCaptcha, _falhar_login,
)
from core.models import StatusCotacao
from core.retentativa import vale_repetir


class _Loc:
    def __init__(self, n=0, texto="", valor=""):
        self._n, self._t, self._v = n, texto, valor
        self.first = self

    def count(self):
        return self._n

    def inner_text(self):
        return self._t

    def input_value(self):
        return self._v

    def wait_for(self): ...


class _Pagina:
    def __init__(self, captcha: bool, logado: bool = False):
        self.captcha, self.logado = captcha, logado

    def goto(self, *a, **k): ...

    def locator(self, seletor):
        if seletor == "#tipoFrete:visible":
            return _Loc(n=1 if self.logado else 0)
        if "recaptcha" in seletor:
            return _Loc(n=1 if self.captcha else 0)
        if seletor == "body":
            return _Loc(texto="Confirme que você não é um robô." if self.captcha else "")
        return _Loc()


def test_captcha_vira_intervencao_necessaria_e_nao_repete():
    with pytest.raises(LoginBarradoPorCaptcha) as e:
        _falhar_login(_Pagina(captcha=True))
    assert isinstance(e.value, CredencialRecusada)
    r = erro_do_adapter("braspress", e.value)
    assert r.status == StatusCotacao.INTERVENCAO_NECESSARIA
    assert "reCAPTCHA" in r.erro
    assert not vale_repetir(r)


def test_sem_captcha_segue_o_caminho_antigo():
    with pytest.raises(RuntimeError) as e:
        _falhar_login(_Pagina(captcha=False))
    assert not isinstance(e.value, LoginBarradoPorCaptcha)


def test_texto_do_captcha_sem_acento_e_em_maiuscula_tambem_conta():
    class _SoTexto(_Pagina):
        def locator(self, seletor):
            if seletor == "body":
                return _Loc(texto="CONFIRME QUE VOCE NAO E UM ROBO.")
            return _Loc()

    with pytest.raises(LoginBarradoPorCaptcha):
        _falhar_login(_SoTexto(captcha=False))


def test_cotacao_que_volta_para_o_login_erra_na_hora():
    """#653 a #661: em vez de 45 s esperando `#tipoFrete`, erro de login."""
    with pytest.raises(RuntimeError, match="voltou para a tela de login") as e:
        BraspressAdapter._abrir_cotacao(_Pagina(captcha=False))
    assert not isinstance(e.value, CredencialRecusada)


def test_cotacao_que_volta_para_o_login_com_captcha_nao_repete():
    with pytest.raises(LoginBarradoPorCaptcha) as e:
        BraspressAdapter._abrir_cotacao(_Pagina(captcha=True))
    assert not vale_repetir(erro_do_adapter("braspress", e.value))


def test_formulario_na_tela_e_login_passado():
    BraspressAdapter._abrir_cotacao(_Pagina(captcha=False, logado=True))


def test_frase_conhecida_nao_vai_para_ia_nem_issue():
    import web.app as app_web
    with pytest.raises(LoginBarradoPorCaptcha) as e:
        _falhar_login(_Pagina(captcha=True))
    erro = erro_do_adapter("braspress", e.value).erro
    assert "à mão" in app_web.mensagem_amigavel("braspress", erro)


def test_braspress_headless_vem_do_env(monkeypatch):
    import web.app as app_web
    monkeypatch.delenv("BRASPRESS_HEADLESS", raising=False)
    assert app_web._braspress_headless() is True
    monkeypatch.setenv("BRASPRESS_HEADLESS", "0")
    assert app_web._braspress_headless() is False
