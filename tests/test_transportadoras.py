"""O cadastro das transportadoras de WhatsApp.

São erros de digitação que não dão exceção nenhuma: o nome do arquivo da logo
com uma letra trocada vira uma imagem quebrada na tela, e um telefone sem o 55
vira um link de WhatsApp que abre conversa com número errado. Os dois passam
despercebidos até um vendedor reclamar.
"""

from __future__ import annotations

import re

from web import transportadoras as t


def test_toda_logo_cadastrada_existe_no_disco():
    """O erro mais fácil de cometer ao acrescentar uma linha."""
    faltando = [reg.slug for reg in t.WHATSAPP
                if not (t.PASTA_LOGOS / reg.logo).is_file()]

    assert not faltando, f"logo não encontrada em web/logos/: {faltando}"


def test_nenhuma_logo_sobrando_na_pasta():
    """Arquivo em web/logos/ que ninguém usa é logo que alguém achou que
    cadastrou e não cadastrou."""
    no_disco = {a.name for a in t.PASTA_LOGOS.iterdir() if a.is_file()}
    cadastradas = {reg.logo for reg in t.WHATSAPP}

    assert no_disco == cadastradas, f"sobrando: {no_disco - cadastradas}"


def test_telefones_no_formato_do_wa_me():
    """Só dígitos, com 55 na frente. Máscara quebra a URL do wa.me."""
    for reg in t.com_whatsapp():
        assert re.fullmatch(r"55\d{10,11}", reg.telefone), (
            f"{reg.slug}: telefone {reg.telefone!r} não é 55+DDD+número")


def test_slugs_nao_se_repetem():
    slugs = [reg.slug for reg in t.WHATSAPP]

    assert len(slugs) == len(set(slugs))


def test_quem_nao_tem_numero_fica_fora_da_tela():
    """A regra que evita o botão que não abre conversa nenhuma."""
    assert all(reg.tem_numero for reg in t.com_whatsapp())
    assert not any(reg.tem_numero for reg in t.sem_numero())
    assert len(t.com_whatsapp()) + len(t.sem_numero()) == len(t.WHATSAPP)


def test_as_tres_que_ja_funcionavam_continuam_ativas():
    """Regressão: a reorganização não pode ter derrubado nenhuma das três
    que o Enzo já usava e conferiu em 14/08/2026."""
    ativas = {reg.slug: reg.telefone for reg in t.com_whatsapp()}

    assert ativas["movvi"] == "553194910111"
    assert ativas["translovato"] == "558181990635"
    assert ativas["continental"] == "5527988928840"
