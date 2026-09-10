"""O login da Generoso contra a hidratação do SPA.

Três cotações de produção (#75, #76 e #77, 28-31/08/2026) morreram com a
mesma assinatura:

    RuntimeError: o login na Generoso não passou: a tela ficou em /login com
    o campo de senha vazio, ou seja, o formulário nem chegou a ser enviado.

O campo de senha VAZIO é a pista. O portal é um SPA: `fill()` escreve no DOM
e o React re-renderiza por cima com o estado dele, que ainda está vazio — o
campo volta a ficar em branco e o "Entrar" manda um formulário vazio.

O código antigo dormia 1,2s fixo e preenchia às cegas. Dormir mais não
conserta: só empurra o problema para a próxima máquina lenta — e desde
10/09/2026 o sistema roda numa VM, que é exatamente isso, e o erro passou a
aparecer muito mais. Conferir o valor conserta.

A Jadlog já tinha o mesmo bug e a mesma solução desde 17/08/2026
(carriers/jadlog/painel.py::_preencher_login). Este arquivo é a prova de que
a Generoso agora aguenta o mesmo maltrato.

Nenhum teste aqui toca a rede: a página é de mentira, servida por
`set_content`.
"""

from __future__ import annotations

import pytest

from carriers.generoso.adapter import GenerosoAdapter

USUARIO = "conta@ventura.com.br"
SENHA = "senha-de-teste"

# A hidratação chegando ATRASADA: apaga os dois campos uma vez, 500ms depois
# de a página abrir. É o que derrubou as #75/#76/#77.
FORMULARIO = """<!doctype html><meta charset="utf-8">
<form>
  <input name="email" type="email">
  <input name="password" type="password">
  <button type="button">Entrar</button>
</form>
<script>
  const limpar = () => {
    document.querySelector('[name=email]').value = '';
    document.querySelector('[name=password]').value = '';
  };
  __QUANDO__
</script>
"""

# Um susto só, tarde: é o que a hidratação faz na página real.
UMA_VEZ = "setTimeout(limpar, 500);"
# O caso perdido: o formulário apaga tudo o que se digita, sempre.
SEMPRE = """document.querySelectorAll('input').forEach(
  i => i.addEventListener('input', () => setTimeout(limpar, 50)));"""
NUNCA = ""


@pytest.fixture
def navegador():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def _pagina(navegador, quando: str):
    pg = navegador.new_context().new_page()
    pg.set_default_timeout(5_000)
    pg.set_content(FORMULARIO.replace("__QUANDO__", quando))
    return pg


def _valores(pg) -> tuple[str, str]:
    return (pg.locator('input[name="email"]').input_value(),
            pg.locator('input[name="password"]').input_value())


def test_o_campo_apagado_pela_hidratacao_e_preenchido_de_novo(navegador):
    """O bug das #75/#76/#77: quem preenche às cegas deixa os campos vazios
    e o "Entrar" manda nada."""
    pg = _pagina(navegador, UMA_VEZ)

    GenerosoAdapter(usuario=USUARIO, senha=SENHA)._preencher_login(pg)

    assert _valores(pg) == (USUARIO, SENHA), \
        "a hidratação apagou os campos e o login sairia vazio"


def test_a_pagina_de_mentira_reproduz_mesmo_o_bug(navegador):
    """Prova de que a fixture morde: preenchendo às cegas, como o código
    fazia antes, os campos ficam VAZIOS. Sem esta prova, o teste de cima
    passaria mesmo com o código antigo e não valeria nada."""
    pg = _pagina(navegador, UMA_VEZ)

    pg.fill('input[name="email"]', USUARIO)
    pg.fill('input[name="password"]', SENHA)
    pg.wait_for_timeout(900)          # a hidratação chega DEPOIS e apaga

    assert _valores(pg) == ("", ""), \
        "a fixture não reproduziu a hidratação — o teste acima não prova nada"


def test_sem_hidratacao_atrapalhando_sai_rapido(navegador):
    """Guarda contra o conserto virar lentidão: no caso comum ele confirma e
    devolve, sem gastar as quatro tentativas."""
    import time

    pg = _pagina(navegador, NUNCA)

    inicio = time.monotonic()
    GenerosoAdapter(usuario=USUARIO, senha=SENHA)._preencher_login(pg)
    gasto = time.monotonic() - inicio

    assert _valores(pg) == (USUARIO, SENHA)
    assert gasto < 4, f"levou {gasto:.1f}s no caminho feliz"


def test_formulario_que_nunca_segura_o_valor_falha_com_frase_clara(navegador):
    """Se a página estiver realmente quebrada, o adapter tem que dizer isso
    — e não clicar em Entrar com o formulário vazio para colher um
    "senha recusada" que não é verdade."""
    pg = _pagina(navegador, SEMPRE)

    with pytest.raises(RuntimeError) as erro:
        GenerosoAdapter(usuario=USUARIO, senha=SENHA)._preencher_login(pg)

    assert "não terminou de carregar" in str(erro.value)
    assert SENHA not in str(erro.value), "a senha nunca entra na mensagem"
