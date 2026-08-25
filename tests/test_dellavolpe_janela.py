"""A janela da Della Volpe: headed de verdade, mas fora da tela.

Por que headed: medido em 13/08/2026, cinco envios com Chromium headless
viraram "A submissao mencionou-se como spam" no Contact Form 7 e NENHUM
e-mail foi gerado. Com janela de verdade o mesmo envio passa. Headless nao
e preferencia ruim — ele simplesmente nao envia.

Por que fora da tela: headed abria uma janela no monitor do Enzo a cada
cotacao. O reCAPTCHA v3 pontua a IMPRESSAO DIGITAL do navegador, nao a
posicao da janela.

Medido em 25/08/2026, quatro configuracoes contra pagina em branco:

    sinal              headless_antigo    headed     headed_fora_da_tela
    ua_headless        True               False      False
    plugins            0                  5          5
    window.chrome      ausente            presente   presente
    webgl              Google, Vulkan     Intel real Intel real
    outerHeight        900                988        988
    hasFocus           True               True       True
    visibilityState    visible            visible    visible

A coluna de fora da tela e IDENTICA a da janela normal nos 14 sinais, e
`screenX` fica em -3000: a pagina se ve como janela normal e o Enzo nao ve
janela nenhuma.
"""

from __future__ import annotations

import pytest

from carriers.dellavolpe.adapter import (
    ARGS_FORA_DA_TELA, DellavolpeAdapter, argumentos_do_navegador,
)


def test_a_posicao_tira_a_janela_do_monitor():
    """-3000 e mais que a largura de qualquer monitor comum, entao a janela
    inteira fica fora mesmo em tela grande."""
    assert any("--window-position=-3000,-3000" in a for a in ARGS_FORA_DA_TELA)


def test_headed_sai_fora_da_tela():
    """O caso do envio real: headed obrigatorio, janela escondida."""
    assert argumentos_do_navegador(headless=False) == list(ARGS_FORA_DA_TELA)


def test_headless_nao_precisa_de_posicao():
    """Sem janela, posicionar nao significa nada — e o argumento a mais so
    atrapalharia quem for ler o log depois."""
    assert argumentos_do_navegador(headless=True) == []


def test_adapter_deixa_desligar_para_ver_o_que_esta_acontecendo():
    """Quando algo quebra no site, o operador PRECISA ver a janela. Sem esta
    saida, depurar a Della Volpe viraria adivinhacao."""
    assert DellavolpeAdapter(mostrar_janela=True).mostrar_janela is True
    assert argumentos_do_navegador(headless=False, mostrar_janela=True) == []


def test_por_padrao_a_janela_fica_escondida():
    assert DellavolpeAdapter().mostrar_janela is False


# ---------------- campo que o site recusou e deixou vazio
"""Medido em 25/08/2026, com um telefone malformado de proposito:

    campo whatsapp -> site mostrou "Telefone invalido" e ZEROU o campo
    adapter        -> status rascunho, erro/aviso: None

Num envio real isso viraria uma cotacao chegando na Della Volpe sem
telefone, ou um submit recusado em silencio — a mesma familia dos cinco
envios de 13/08 que "deram certo" sem existir.

A classe `wpcf7-not-valid` NAO serve de sinal: medida com telefone VALIDO,
ela continua grudada no campo, sobra de uma validacao anterior. O que
distingue os dois casos e o campo ter ficado VAZIO.
"""


def test_campo_que_ficou_vazio_e_denunciado():
    from carriers.dellavolpe.adapter import campos_que_o_site_recusou

    esperado = {"Nome completo": "Ventura", "WhatsApp": "(27) 99988-7766"}
    lido = {"Nome completo": "Ventura", "WhatsApp": ""}

    assert campos_que_o_site_recusou(esperado, lido) == ["WhatsApp"]


def test_mascara_do_site_nao_conta_como_recusa():
    """O site reescreve o que foi digitado — telefone ganha parenteses, CNPJ
    ganha pontos, dinheiro ganha virgula. Nada disso e recusa, e tratar como
    tal impediria todo envio."""
    from carriers.dellavolpe.adapter import campos_que_o_site_recusou

    esperado = {"WhatsApp": "27999887766", "Valor da NF": "1500"}
    lido = {"WhatsApp": "(27) 99988-7766", "Valor da NF": "1.500,00"}

    assert campos_que_o_site_recusou(esperado, lido) == []


def test_campo_que_nao_tentamos_preencher_e_ignorado():
    """`tipo-veiculo` fica marcado como invalido no formulario e nunca foi
    nosso. Reclamar dele bloquearia todo envio por um campo de outro
    servico."""
    from carriers.dellavolpe.adapter import campos_que_o_site_recusou

    assert campos_que_o_site_recusou({"Nome completo": "Ventura"},
                                     {"Nome completo": "Ventura"}) == []


def test_campo_que_ja_ia_vazio_nao_e_recusa():
    from carriers.dellavolpe.adapter import campos_que_o_site_recusou

    assert campos_que_o_site_recusou({"Mercadoria": ""},
                                     {"Mercadoria": ""}) == []
