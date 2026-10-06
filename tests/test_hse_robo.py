"""Robô do HSE (cruzar_nf/hse_robo.py), sem navegador: as telas são simuladas."""

from __future__ import annotations

import datetime as dt

import pytest

from cruzar_nf import hse_robo
from cruzar_nf.hse_robo import ErroHSE, RoboHSE, janelas_mensais, preferencias_chrome

D = dt.date


def test_janelas_mensais_cortam_no_fim_de_cada_mes():
    assert janelas_mensais(D(2025, 1, 15), D(2025, 3, 2)) == [
        (D(2025, 1, 15), D(2025, 1, 31)), (D(2025, 2, 1), D(2025, 2, 28)), (D(2025, 3, 1), D(2025, 3, 2))]
    assert janelas_mensais(D(2026, 10, 1), D(2026, 10, 5)) == [(D(2026, 10, 1), D(2026, 10, 5))]


def test_chrome_libera_varios_downloads(tmp_path):
    prefs = preferencias_chrome(tmp_path)
    assert prefs["profile.default_content_setting_values.automatic_downloads"] == 1
    assert prefs["download.default_directory"] == str(tmp_path)


class DriverLogin:
    """Login do HSE em duas etapas: usuário/senha e depois empresa/filial + Entrar de novo."""

    def __init__(self):
        self.etapa = "login"
        self.cliques = 0
        self.switch_to = self

    def default_content(self):
        pass

    def get(self, _url):
        pass

    def find_elements(self, _by, seletor):
        if seletor == "#frmLogin":
            return [1] if self.etapa != "dentro" else []
        if seletor == "iframe":
            return [1]
        return []

    def find_element(self, _by, ident):
        driver = self

        class Campo:
            def clear(self):
                pass

            def send_keys(self, _texto):
                pass

            def click(self):
                driver.cliques += 1
                driver.etapa = "empresa"

        return Campo()

    def execute_script(self, js, *_args):
        if js == hse_robo.JS_EMPRESA_FILIAL:
            if self.etapa != "empresa":
                return False
            self.cliques += 1
            self.etapa = "dentro"
            return True
        raise AssertionError("script inesperado")


def test_login_escolhe_empresa_e_filial_e_clica_entrar_de_novo(tmp_path, monkeypatch):
    monkeypatch.setattr(hse_robo.time, "sleep", lambda _s: None)
    robo = RoboHSE(tmp_path, usuario="u", senha="s", progresso=lambda _m: None)
    robo.driver = DriverLogin()
    robo.entrar()
    assert robo.driver.etapa == "dentro" and robo.driver.cliques == 2


def test_script_da_segunda_etapa_escolhe_a_matriz():
    assert "MATRIZ" in hse_robo.JS_EMPRESA_FILIAL and "validarLogin" in hse_robo.JS_EMPRESA_FILIAL


def excel(tmp_path, nome, n):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([])
    ws.append([])
    ws.append([None, "Tipo", "Código", "Emissão", "Ordem Compra", "Total Líq.", "Filial", "NF"])
    for i in range(n):
        ws.append([None, "VEN", i + 1, dt.datetime(2025, 1, 15), "4100000000", 100.0, "VENTURA MATRIZ", 15000 + i])
    caminho = tmp_path / nome
    wb.save(caminho)
    return caminho


class RoboFalso(RoboHSE):
    """Telas do HSE simuladas: {(de, ate): (vendas na tela, vendas no Excel)}."""

    def __init__(self, tmp_path, meses):
        super().__init__(tmp_path, progresso=lambda _m: None)
        self.meses, self.tmp, self.atual, self.fechou = meses, tmp_path, None, False

    def abrir(self):
        pass

    def entrar(self):
        pass

    def abrir_vendas(self):
        pass

    def fechar(self):
        self.fechou = True

    def consultar(self, de, ate):
        self.atual = (de, ate)
        return self.meses[(de, ate)][0]

    def baixar_excel(self):
        de, _ = self.atual
        return excel(self.tmp, f"{de:%Y%m}.xlsx", self.meses[self.atual][1])


def test_exporta_mes_a_mes_e_pula_mes_sem_venda(tmp_path):
    robo = RoboFalso(tmp_path, {(D(2025, 1, 1), D(2025, 1, 31)): (2, 2),
                                (D(2025, 2, 1), D(2025, 2, 28)): (0, 0),
                                (D(2025, 3, 1), D(2025, 3, 10)): (1, 1)})
    res = robo.exportar(D(2025, 1, 1), D(2025, 3, 10))
    assert [p.name for p in map(hse_robo.Path, res["arquivos"])] == ["202501.xlsx", "202503.xlsx"]
    assert res["linhas_tela"] == 3 and robo.fechou


def test_mes_com_excel_incompleto_aborta_a_rodada(tmp_path):
    robo = RoboFalso(tmp_path, {(D(2025, 1, 1), D(2025, 1, 31)): (5, 0)})
    with pytest.raises(ErroHSE, match="01/01/2025 a 31/01/2025"):
        robo.exportar(D(2025, 1, 1), D(2025, 1, 31))
    assert robo.fechou
