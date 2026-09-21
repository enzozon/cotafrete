"""Generoso — contra o DOM real do painel de agendar coleta.

tests/fixtures/generoso_agendar_painel.html foi capturado por
recon/recon_generoso_agendar.py em 21/09/2026, na conta real, com o painel
aberto e o "Local fecha para almoço" MARCADO — é o único estado em que tudo
existe ao mesmo tempo: data, hora, os dois selects do almoço e a observação.

Roda por file://, e toda requisição que não seja file:// é barrada. É a mesma
lição das outras fixtures deste projeto: a captura vem do site de verdade e
traz `<script>` e CSS externos junto, e sem barrar isso um teste "offline"
passa a depender de DNS e estoura o timeout sem motivo nenhum.

O que este arquivo TRAVA: se a Generoso renomear o `id` do checkbox, trocar o
botão do calendário por um `<input>`, ou tirar o `<select>` nativo de trás dos
horários do almoço, o teste falha AQUI — e não numa coleta real agendada para
o dia errado. Os seletores do adapter são medidos, nunca deduzidos de print.

⚠ A fixture é ESTÁTICA. Ela não reage a clique: o calendário não abre, o
checkbox não revela nada. O que dá para provar offline é que as peças que o
adapter procura continuam existindo, com o nome que ele espera.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from carriers.generoso.adapter import (BOTAO_CONTINUAR_AGENDAMENTO,
                                       MARCA_DIA_BLOQUEADO,
                                       SELETOR_ABRIR_CALENDARIO,
                                       SELETOR_ALMOCO, SELETOR_DIA,
                                       SELETOR_OBSERVACAO_COLETA,
                                       SELETOR_SELECT_NATIVO)
from carriers.generoso.mapping import HORARIOS_ALMOCO

FIXTURE = (Path(__file__).parent / "fixtures"
           / "generoso_agendar_painel.html").resolve()


# scope="module": todos os testes daqui só LEEM o DOM. Com escopo de função,
# cada um subiria um Chromium inteiro para fazer um `count()`.
@pytest.fixture(scope="module")
def page():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_context(locale="pt-BR").new_page()
        pg.route("**/*", lambda rota: (
            rota.continue_() if rota.request.url.startswith("file:")
            else rota.abort()))
        pg.set_default_timeout(4_000)
        pg.goto(FIXTURE.as_uri(), wait_until="domcontentloaded")
        yield pg
        browser.close()


def test_o_campo_de_data_continua_sendo_um_botao_de_popover(page):
    """Se um dia virar <input type="date">, o adapter para de funcionar em
    silêncio: ele CLICA para abrir o calendário, e clicar num input não abre
    calendário nenhum. Melhor falhar aqui."""
    assert page.locator(SELETOR_ABRIR_CALENDARIO).count() >= 1
    assert page.locator('input[type="date"]').count() == 0


def test_o_botao_do_calendario_mostra_a_data_escolhida(page):
    """É o rótulo dele que o adapter lê para CONFERIR qual data o site
    entendeu — a única confirmação visível que existe nesta tela."""
    rotulo = page.locator(SELETOR_ABRIR_CALENDARIO).first.inner_text()

    assert "às" in rotulo
    assert "/202" in rotulo


def test_o_checkbox_do_almoco_tem_id_fixo(page):
    """Raro nesta tela, onde quase todo id é gerado por render
    (radix-_R_6j9qnpfiv9fl97b_). É por isso que o adapter pode ancorar nele."""
    assert page.locator(SELETOR_ALMOCO).count() == 1


def test_os_horarios_do_almoco_tem_select_nativo(page):
    """A diferença de que o adapter DEPENDE: estes dois têm <select> nativo
    por trás (select_option resolve), enquanto o "Coletar até ás" não tem e só
    sai por clique. Se a Generoso padronizar tudo em Radix, o
    `_escolher_almoco` para de funcionar — e é aqui que isso aparece."""
    assert page.locator(SELETOR_SELECT_NATIVO).count() >= 2


def test_o_select_do_almoco_tem_a_grade_que_o_mapping_promete(page):
    """10:00 às 14:30. A tela de aceite oferece exatamente estas opções ao
    vendedor: se a Generoso mudar a grade, o site passaria a receber um
    horário que ele não tem."""
    opcoes = [o.strip() for o in page.locator(
        f"{SELETOR_SELECT_NATIVO} option").all_inner_texts()]

    for hora in HORARIOS_ALMOCO:
        assert hora in opcoes, f"{hora} sumiu do select do almoço"


def test_a_observacao_continua_sendo_um_textarea_com_o_mesmo_name(page):
    assert page.locator(SELETOR_OBSERVACAO_COLETA).count() == 1


def test_o_botao_final_tem_o_texto_que_o_adapter_procura(page):
    """O adapter acha por NOME. Texto trocado = botão não encontrado, e o
    dry-run passaria a falhar com um timeout sem explicação."""
    assert page.get_by_role(
        "button", name=BOTAO_CONTINUAR_AGENDAMENTO).count() >= 1


def test_o_botao_final_e_de_submit(page):
    """Medido: type="submit". Não muda o que o adapter faz, mas é o que
    confirma que ele é o fim do formulário e não mais uma etapa."""
    assert page.locator(
        f'button[type="submit"]:has-text("{BOTAO_CONTINUAR_AGENDAMENTO}")'
    ).count() >= 1


# ------------------------------------------------------------ o calendário
# A fixture foi capturada com o calendário FECHADO (o popover só existe no
# DOM depois do clique), então o que dá para conferir aqui é a forma do
# seletor — não a presença das células. A prova de que `data-day` funciona
# está no dry-run real, registrado no commit do adapter.
def test_o_seletor_de_dia_usa_a_data_em_iso():
    """Nunca por posição na grade: a grade muda de forma todo mês, e "a
    terceira célula da quarta linha" é uma data diferente em outubro."""
    montado = SELETOR_DIA.format(date(2026, 9, 23).isoformat())

    assert montado == 'td[role="gridcell"][data-day="2026-09-23"]'


def test_a_marca_de_dia_bloqueado_e_a_medida_no_site():
    assert MARCA_DIA_BLOQUEADO == "data-disabled"


def test_a_fixture_nao_depende_de_rede():
    """A promessa do topo deste arquivo, verificada em vez de prometida: a
    captura do site vinha com <script> e CSS externos, e eles foram tirados
    quando a fixture foi montada."""
    html = FIXTURE.read_text(encoding="utf-8").lower()

    assert "<script" not in html
    assert 'rel="stylesheet"' not in html
