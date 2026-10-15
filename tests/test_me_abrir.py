"""Sessao.abrir: o formulário basta; o "load" completo não é condição.

Em 15/10/2026, na nuvem, a mesma cotação abriu em 4 s numa rodada e estourou
60 s esperando o "load" na seguinte, com o formulário já na página. Era essa
espera que fazia a leitura cair em "não abriu o formulário de resposta"
(75 falhas de 09 a 15/10/2026, sem print nenhum).
"""

from __future__ import annotations

import pytest

from mercado_eletronico import robo as R


class _Pagina:
    def __init__(self, tem_form: bool, load_trava: bool) -> None:
        self.tem_form, self.load_trava = tem_form, load_trava
        self.url, self.visitas = "", []

    def goto(self, url, wait_until=None):
        self.url = url
        self.visitas.append(url)

    def wait_for_selector(self, *_a, **_k):
        if not self.tem_form:
            raise TimeoutError("form")

    def wait_for_load_state(self, *_a, **_k):
        if self.load_trava:
            raise TimeoutError("load")

    def title(self):
        return "Mercado Eletrônico - Login"


def _sessao(page, tmp_path):
    s = R.Sessao.__new__(R.Sessao)
    s.page, s.timeout_ms, s.pasta = page, 1_000, tmp_path
    s.print = lambda nome: str(tmp_path / f"{nome}.png")
    return s


def test_formulario_presente_com_load_travado_abre(tmp_path):
    page = _Pagina(tem_form=True, load_trava=True)
    _sessao(page, tmp_path).abrir(23164242)
    assert len(page.visitas) == 1   # nem precisou do caminho pela lista


def test_sem_formulario_diz_a_tela_e_guarda_print(tmp_path):
    page = _Pagina(tem_form=False, load_trava=False)
    with pytest.raises(R.RoboRecusou) as excinfo:
        _sessao(page, tmp_path).abrir(23164242)
    msg = str(excinfo.value)
    assert "não abriu o formulário de resposta" in msg
    assert "Mercado Eletrônico - Login" in msg and "FornShowCotacao" in msg
    assert excinfo.value.prints == [str(tmp_path / "23164242_nao_abriu.png")]
