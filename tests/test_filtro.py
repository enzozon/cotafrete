"""Escolher com quem cotar — e o cuidado de nao deixar isso passar calado.

O vendedor as vezes JA SABE que uma transportadora nao serve para aquela
carga ou aquele cliente. Tirar uma automatica economiza ~60s e uma vaga de
navegador; tirar uma de WhatsApp so limpa um botao da tela.

Sao TRES estados, e a diferenca entre os dois primeiros e o que faz as
cotacoes anteriores ao filtro continuarem certas sem migrar dado nenhum:

    None    ninguem mexeu no filtro   -> TODAS
    ""      mexeu e desmarcou tudo    -> nenhuma
    "a,b"   escolheu essas            -> so essas

Confundir `None` com `""` e o erro caro aqui: num sentido o sistema para de
cotar calado, no outro cota em quem o vendedor tinha tirado de proposito.
"""

from __future__ import annotations

from core import selecao


# ------------------------------------------- None quer dizer todas
def test_sem_escolha_cota_em_todas():
    """Cotacao anterior ao filtro: a coluna vem NULL e tem que valer tudo."""
    assert selecao.entra("camilo", None)
    assert selecao.entra("jadlog", None)
    assert selecao.entra("uma_que_nem_existia_na_epoca", None)


def test_escolha_explicita_limita():
    escolha = "camilo,generoso"

    assert selecao.entra("camilo", escolha)
    assert selecao.entra("generoso", escolha)
    assert not selecao.entra("jadlog", escolha)
    assert not selecao.entra("movvi", escolha)


def test_desmarcar_tudo_nao_vira_todas():
    """A armadilha. Se "" fosse lido como None, quem desmarcou as 17 veria o
    sistema cotar em todas assim mesmo — o contrario do que pediu."""
    assert not selecao.entra("camilo", "")


def test_nome_parecido_nao_cola():
    """'trans' nao pode entrar de carona em 'translovato'. Sem isto, um slug
    novo que fosse pedaco de outro passaria despercebido."""
    assert not selecao.entra("trans", "translovato")
    assert selecao.entra("translovato", "translovato")


# ------------------------------------------------------- guardar no banco
def test_todas_marcadas_guarda_none():
    """Guardar a lista inteira funcionaria hoje e quebraria amanha: no dia em
    que uma transportadora nova entrar, as cotacoes antigas passariam a
    exclui-la sem ninguem ter pedido. None = todas, inclusive as que ainda
    nao existem."""
    todas = ["camilo", "jadlog", "translovato"]

    assert selecao.para_guardar(todas, todas) is None


def test_escolha_parcial_guarda_os_slugs():
    todas = ["camilo", "jadlog", "translovato"]

    assert selecao.para_guardar(["camilo", "jadlog"], todas) == "camilo,jadlog"


def test_ordem_nao_importa_para_saber_se_e_tudo():
    todas = ["camilo", "jadlog", "translovato"]

    assert selecao.para_guardar(["translovato", "camilo", "jadlog"],
                                todas) is None


def test_nada_marcado_guarda_string_vazia():
    """Diferente de None de proposito: "" e uma escolha, None e a ausencia
    dela. O formulario ainda barra isso antes, mas a camada de dados nao
    pode depender do formulario para nao se contradizer."""
    todas = ["camilo", "jadlog"]

    assert selecao.para_guardar([], todas) == ""


def test_slug_desconhecido_e_ignorado():
    """Nao confia no que veio do formulario: alguem mexendo no HTML nao pode
    inventar transportadora."""
    todas = ["camilo", "jadlog"]

    assert selecao.para_guardar(["camilo", "inventada"], todas) == "camilo"
