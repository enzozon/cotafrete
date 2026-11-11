"""Login da Braspress atrás de reCAPTCHA (10/11/2026): erro claro, sem repetir."""
from __future__ import annotations

import pytest

from carriers.base import CredencialRecusada, erro_do_adapter
from carriers.braspress.adapter import LoginBarradoPorCaptcha, _falhar_login
from core.models import StatusCotacao


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


class _Pagina:
    def __init__(self, captcha: bool):
        self.captcha = captcha

    def locator(self, seletor):
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


def test_sem_captcha_segue_o_caminho_antigo():
    with pytest.raises(RuntimeError) as e:
        _falhar_login(_Pagina(captcha=False))
    assert not isinstance(e.value, LoginBarradoPorCaptcha)
