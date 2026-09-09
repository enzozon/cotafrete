"""O casco compartilhado das telas.

Existe como módulo próprio porque web/adm.py precisa dele e web/app.py
registra as rotas do adm — importar um do outro seria circular. De quebra
tira ~200 linhas de um arquivo que tinha 1753."""

import pathlib
import re

import pytest

from web import layout


def test_a_pagina_monta_o_casco_completo():
    html = layout.pagina("Teste", "<p>oi</p>")

    assert html.startswith("<!doctype html>")
    assert 'lang="pt-BR"' in html
    assert "Teste — Cotafrete" in html
    assert "<p>oi</p>" in html
    assert layout.CSS in html


def test_o_menu_so_aparece_com_usuario():
    """Sem cookie não há para onde navegar — e mostrar 'Sair' para quem não
    entrou confunde."""
    assert "/historico" not in layout.pagina("t", "c")
    assert "/historico" in layout.pagina("t", "c", usuario="enzo")


def test_escapa_html_do_usuario():
    """O nome vem de um formulário aberto. Sem escapar, vira XSS."""
    assert "<script>" not in layout.pagina("t", "c", usuario="<script>x</script>")
    assert layout.e("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"

# ------------------------------------------------------- contraste da marca
#
# As cores saem da logo da Ventura, mas "sai da logo" não é licença para ser
# ilegível. Estes limites são os do WCAG 2.2: 4.5:1 para texto, 3:1 para
# elemento de interface (1.4.11) — que é o caso do anel de foco.
#
# O teste lê os tokens do PRÓPRIO CSS em vez de repetir os valores aqui. Uma
# lista copiada envelheceria em silêncio: alguém escurece o índigo no CSS, o
# teste continua verde conferindo a cor antiga, e o contraste some sem aviso.
#
# Dois destes pares já falharam de verdade, na primeira versão do rebranding:
# --fraco dava 4.33:1 sobre --fundo (o subtítulo fica exatamente ali) e o
# ciano do foco dava 2.78:1 sobre o branco.

def _tokens() -> dict[str, str]:
    """Os tokens de cor declarados no :root do CSS, sempre com 6 dígitos.

    A forma curta existe no CSS (`--papel:#fff`) e a conta de luminância lê o
    hex em pares — sem expandir, o token mais usado da paleta ficava de fora
    da checagem inteira, e o teste passava sem conferir o branco."""
    bloco = re.search(r":root\{(.*?)\}", layout.CSS, re.S).group(1)
    achados = re.findall(r"(--[a-z-]+):(#(?:[0-9a-fA-F]{3}){1,2})", bloco)
    return {nome: cor if len(cor) == 7 else "#" + "".join(c * 2 for c in cor[1:])
            for nome, cor in achados}


def _luminancia(cor: str) -> float:
    canais = [int(cor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    canais = [c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
              for c in canais]
    return .2126 * canais[0] + .7152 * canais[1] + .0722 * canais[2]


def _contraste(frente: str, fundo: str) -> float:
    a, b = _luminancia(frente), _luminancia(fundo)
    return (max(a, b) + .05) / (min(a, b) + .05)


@pytest.mark.parametrize("frente,fundo,minimo,onde", [
    ("--fraco", "--papel", 4.5, "rótulo de campo dentro do cartão"),
    ("--fraco", "--fundo", 4.5, "subtítulo, que fica sobre o fundo da página"),
    ("--tinta", "--papel", 4.5, "texto comum"),
    ("--marca", "--papel", 4.5, "link"),
    ("--marca", "--lavagem", 4.5, "link sobre a lavagem da marca"),
    ("--ok", "--papel", 4.5, "preço"),
    ("--erro", "--papel", 4.5, "falha"),
    ("--ciano", "--papel", 3.0, "anel de foco (WCAG 1.4.11)"),
])
def test_a_paleta_da_marca_e_legivel(frente, fundo, minimo, onde):
    t = _tokens()
    razao = _contraste(t[frente], t[fundo])

    assert razao >= minimo, (
        f"{frente} ({t[frente]}) sobre {fundo} ({t[fundo]}) dá "
        f"{razao:.2f}:1, abaixo de {minimo}:1 — {onde}")


def test_o_botao_tem_contraste_com_o_branco_escrito_nele():
    """O botão é índigo cheio com texto branco. É o único lugar onde a cor da
    marca é FUNDO de texto, e por isso não entra na lista acima."""
    assert _contraste("#ffffff", _tokens()["--marca"]) >= 4.5


def test_o_ciano_da_logo_esta_na_paleta():
    """A logo é um gradiente ciano -> índigo, e a versão anterior do sistema
    usava só a metade escura. Se o ciano sumir dos tokens, o rebranding foi
    desfeito pela metade sem ninguém perceber — a tela continua funcionando,
    só volta a não parecer da Ventura."""
    t = _tokens()

    assert t["--ciano-claro"].lower() == "#70c8e0", \
        "é o ciano medido na ponta esquerda da elipse da logo"
    assert "70c8e0" in layout.CSS, "o gradiente da marca precisa dele"


def test_o_movimento_respeita_quem_pediu_para_parar():
    """Animação é enfeite até virar obstáculo. Sem esta regra, quem liga
    "reduzir movimento" no sistema operacional recebe o formulário entrando
    deslizando e os cartões subindo sob o cursor."""
    assert "prefers-reduced-motion" in layout.CSS
    assert "animation-duration:.01ms !important" in layout.CSS


def test_o_brilho_de_espera_casa_com_o_cartao_que_o_app_monta():
    """O brilho do cartao que ainda espera resposta e ligado por SELETOR, e nao
    por uma classe que alguem precisa lembrar de escrever no HTML.

    Isso so funciona enquanto o cartao pendente continuar sendo um `.res` com
    um `.cotando` dentro (web/app.py:1364-1366). Se aquela marcacao mudar, a
    regra para de casar em silencio - o cartao nao quebra, so volta a ficar
    parado, e ninguem descobre olhando a tela."""
    from web import app as modulo

    assert ".res:has(.cotando)" in layout.CSS
    assert 'class="cotando"' in pathlib.Path(
        modulo.__file__).read_text(encoding="utf-8")
