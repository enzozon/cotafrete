"""O que o rebranding prometeu, conferido no NAVEGADOR de verdade.

Os outros testes de tela leem a string de HTML. Isso pega marcação e pega
texto, e não pega nada do que este trabalho mudou: um `.contexto` que estoura
a coluna, uma faixa grudada que tapa o conteúdo, um cabeçalho que quebra em
três linhas no celular. Tudo isso passa num teste de substring e aparece na
primeira vez que alguém abre a tela.

Aqui o Playwright abre as telas de verdade, em 390px (celular) e 1440px
(monitor da empresa), e confere três coisas que não dá para ver de outro
jeito:

1. **Nada rola de lado.** `scrollWidth > clientWidth` é o defeito que o CSS
   novo mais arriscava introduzir — pastilha de contexto, tabela de resultado,
   faixa de indicadores do painel. Um pixel a mais e a tela inteira ganha uma
   barra horizontal no celular.
2. **O console fica limpo.** Erro de JavaScript numa tela que "abriu" é o
   defeito mais fácil de não notar.
3. **O foco aparece.** Percorre a tela pelo Tab e exige contorno visível no
   que recebeu foco.

De quebra grava os prints em docs/rebranding/ — as mesmas telas, nas duas
larguras. É por isso que ele roda com dado SINTÉTICO montado aqui: nenhuma
cotação real, nenhum CNPJ de cliente, nenhum print de transportadora.

    pytest tests/test_rebranding_visual.py

Sem Playwright instalado o arquivo inteiro é pulado — ele não pode derrubar a
suíte de quem só quer rodar os testes de lógica.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api",
                    reason="Playwright não instalado neste ambiente")

from playwright.sync_api import sync_playwright  # noqa: E402

from core.banco import Banco  # noqa: E402

PRINTS = Path(__file__).resolve().parents[1] / "docs" / "rebranding"

# As duas larguras do enunciado. 390 é o iPhone que o vendedor leva para a
# rua; 1440 é o monitor da empresa.
LARGURAS = (("celular", 390, 844), ("desktop", 1440, 900))

# Carga de mentira, escrita aqui. Nenhum dado real entra num teste que grava
# imagem numa pasta versionada.
CARGA = {
    "cep_origem": "29010-000", "cep_destino": "01310-100",
    "cidade_origem": "Vitória", "uf_origem": "ES",
    "cidade_destino": "São Paulo", "uf_destino": "SP",
    "peso_kg": "12", "quantidade": 3,
    "comprimento_cm": 80, "largura_cm": 60, "altura_cm": 50,
    "valor_nf": "1500.00", "material": "Bomba centrífuga",
    "cnpj_remetente": "12.345.678/0001-90",
    "cnpj_destinatario": "98.765.432/0001-10",
    "cnpj_pagador": "12.345.678/0001-90",
    "nome_remetente": "Ventura", "nome_destinatario": "Cliente de teste",
    "nome_pagador": "Ventura", "email": "prova@exemplo.invalido",
}


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    """A aplicação de verdade, num banco descartável, numa porta livre.

    Uvicorn numa thread e não num processo: o banco é trocado por
    `monkeypatch` dentro do processo, e um subprocesso abriria o banco real.
    """
    import uvicorn
    from web import app as modulo

    pasta = tmp_path_factory.mktemp("visual")
    banco = Banco(pasta / "visual.db")
    modulo.banco = banco
    # Senha do painel só neste processo: sem ela /adm responde 404 de
    # propósito, e a tela do painel não entraria nos prints.
    import os
    os.environ["COTAFRETE_ADM_SENHA"] = "print-sintetico"

    config = uvicorn.Config(modulo.app, host="127.0.0.1", port=0,
                            log_level="error")
    servidor = uvicorn.Server(config)
    thread = threading.Thread(target=servidor.run, daemon=True)
    thread.start()
    while not servidor.started:
        if not thread.is_alive():        # pragma: no cover - falha de boot
            raise RuntimeError("o servidor de teste não subiu")
    porta = servidor.servers[0].sockets[0].getsockname()[1]

    # Duas cotações: uma com resultado (a tela de comparação precisa de linha
    # para desenhar) e uma crua, para o histórico ter mais de um item.
    cid = banco.salvar_cotacao("enzo", CARGA)
    banco.salvar_resultado(cid, "camilo", "concluido", valor="69.91",
                           prazo=3, protocolo="A-1001")
    banco.salvar_resultado(cid, "jadlog", "concluido", valor="133.29",
                           prazo=5)
    banco.salvar_resultado(cid, "generoso", "aguardando_retorno")
    banco.salvar_resultado(cid, "braspress", "erro",
                           erro="site fora do ar (sintético)")
    banco.salvar_cotacao("enzo", {**CARGA, "material": "Válvula"})

    yield f"http://127.0.0.1:{porta}", cid

    servidor.should_exit = True
    thread.join(timeout=5)


def _telas(base: str, cotacao_id: int) -> tuple[tuple[str, str], ...]:
    """(nome do arquivo, endereço). Cobre o escopo obrigatório do trabalho."""
    return (
        ("login-vendedor", f"{base}/login"),
        ("login-adm", f"{base}/adm/entrar"),
        ("formulario", f"{base}/"),
        ("resultado", f"{base}/cotacao/{cotacao_id}"),
        ("historico", f"{base}/historico"),
        ("documentacao", f"{base}/documentacao"),
        ("email-pronto", f"{base}/email/{cotacao_id}/dellavolpe"),
        ("dellavolpe", f"{base}/dellavolpe/{cotacao_id}"),
        ("painel", f"{base}/adm"),
        ("painel-cotacao", f"{base}/adm/cotacao/{cotacao_id}"),
    )


@pytest.fixture(scope="module")
def navegador():
    with sync_playwright() as pw:
        try:
            nav = pw.chromium.launch()
        except Exception as erro:              # pragma: no cover
            pytest.skip(f"Chromium do Playwright indisponível: {erro}")
        yield nav
        nav.close()


def _abrir(navegador, url: str, largura: int, altura: int, *,
           adm: bool = False):
    """Uma aba nova, com o cookie de sessão já posto.

    Cookie e não login pela tela: o objetivo aqui é a APARÊNCIA das telas de
    dentro, e passar por dois formulários a cada print só multiplica o que
    pode falhar por motivo que não é visual."""
    ctx = navegador.new_context(viewport={"width": largura, "height": altura},
                                device_scale_factor=2)
    dominio = url.split("//")[1].split("/")[0].split(":")[0]
    porta = url.split(":")[2].split("/")[0]
    biscoitos = [{"name": "cotafrete_usuario", "value": "enzo",
                  "domain": dominio, "path": "/"}]
    if adm:
        from web import adm as modulo_adm
        biscoitos.append({"name": modulo_adm.COOKIE_ADM,
                          "value": modulo_adm.token_de("print-sintetico"),
                          "domain": dominio, "path": "/"})
    del porta
    ctx.add_cookies(biscoitos)
    return ctx


@pytest.mark.parametrize("perfil,largura,altura", LARGURAS)
def test_nenhuma_tela_rola_de_lado(servidor, navegador, perfil, largura,
                                   altura):
    """Rolagem horizontal é o defeito clássico de rebranding.

    Ele não quebra teste nenhum, não aparece no HTML e some assim que a janela
    é larga o bastante — então quem mexe no CSS num monitor de 27" nunca o vê.
    A tolerância é de 1px: `scrollWidth` arredonda para cima, e um subpixel de
    borda não é uma barra de rolagem."""
    base, cid = servidor
    problemas = []
    for nome, url in _telas(base, cid):
        ctx = _abrir(navegador, url, largura, altura,
                     adm=nome.startswith(("painel", "login-adm")))
        pagina = ctx.new_page()
        pagina.goto(url, wait_until="networkidle")
        sobra = pagina.evaluate(
            "() => document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth")
        if sobra > 1:
            # Qual elemento estourou. Sem isto a falha diz "sobrou 40px" e
            # quem for consertar procura no CSS inteiro.
            culpado = pagina.evaluate(
                "(w) => { for (const el of document.querySelectorAll('*')) {"
                " const r = el.getBoundingClientRect();"
                " if (r.right > w + 1 || r.left < -1)"
                "  return el.tagName + '.' + (el.className || '?')"
                "         + ' [' + Math.round(r.left) + '..'"
                "         + Math.round(r.right) + ']'; } return '?'; }",
                largura)
            problemas.append(f"{nome} ({perfil}): sobra {sobra}px — {culpado}")
        ctx.close()

    assert not problemas, "rolagem lateral em:\n  " + "\n  ".join(problemas)


@pytest.mark.parametrize("perfil,largura,altura", LARGURAS)
def test_nenhuma_tela_reclama_no_console(servidor, navegador, perfil, largura,
                                         altura):
    """Erro de JavaScript numa tela que "abriu" passa despercebido para
    sempre: a página responde 200, o HTML está lá, e a única pista é um
    contador que parou de contar ou um filtro que parou de filtrar."""
    base, cid = servidor
    queixas = []
    for nome, url in _telas(base, cid):
        ctx = _abrir(navegador, url, largura, altura,
                     adm=nome.startswith(("painel", "login-adm")))
        pagina = ctx.new_page()
        pagina.on("console", lambda m, n=nome: queixas.append(f"{n}: {m.text}")
                  if m.type == "error" else None)
        pagina.on("pageerror",
                  lambda erro, n=nome: queixas.append(f"{n}: {erro}"))
        pagina.goto(url, wait_until="networkidle")
        ctx.close()

    assert not queixas, "console sujo:\n  " + "\n  ".join(queixas)


def test_o_foco_do_teclado_e_visivel_no_formulario(servidor, navegador):
    """Quem trabalha no teclado precisa VER onde está.

    O CSS novo trocou o anel de foco por um token e ampliou a regra para caixa
    de seleção e campo de busca. Um `outline:0` esquecido em qualquer lugar
    apaga tudo isso em silêncio — nada quebra, o Tab continua andando, e a
    pessoa é que passa a navegar às cegas.

    Confere os dez primeiros paradas do Tab: se nenhuma delas tiver contorno
    OU sombra, é porque o anel sumiu."""
    base, cid = servidor
    ctx = _abrir(navegador, f"{base}/", 1440, 900)
    pagina = ctx.new_page()
    pagina.goto(f"{base}/", wait_until="networkidle")

    sem_anel = []
    for _ in range(10):
        pagina.keyboard.press("Tab")
        info = pagina.evaluate("""() => {
          const el = document.activeElement;
          if (!el || el === document.body) return null;
          const s = getComputedStyle(el);
          return {quem: el.tagName + '.' + (el.className || ''),
                  contorno: s.outlineStyle !== 'none'
                            && parseFloat(s.outlineWidth) > 0,
                  sombra: s.boxShadow !== 'none'};
        }""")
        if info and not (info["contorno"] or info["sombra"]):
            sem_anel.append(info["quem"])
    ctx.close()

    assert not sem_anel, f"foco invisível em: {sem_anel}"


@pytest.mark.parametrize("perfil,largura,altura", LARGURAS)
def test_grava_os_prints_da_documentacao(servidor, navegador, perfil, largura,
                                         altura):
    """Os prints de docs/rebranding/. Não é bem um teste — é o artefato que o
    IMPLEMENTACAO.md referencia, e deixá-lo aqui garante que ele é sempre
    gerado a partir das telas que os testes acima acabaram de aprovar, e não
    de uma versão antiga que alguém esqueceu de regravar."""
    base, cid = servidor
    PRINTS.mkdir(parents=True, exist_ok=True)
    for nome, url in _telas(base, cid):
        ctx = _abrir(navegador, url, largura, altura,
                     adm=nome.startswith(("painel", "login-adm")))
        pagina = ctx.new_page()
        pagina.goto(url, wait_until="networkidle")
        # A entrada em cascata dos cartões é `both`: sem esperar, o print sai
        # com metade da tela ainda transparente.
        pagina.wait_for_timeout(900)
        destino = PRINTS / f"{nome}-{perfil}.png"
        pagina.screenshot(path=str(destino), full_page=True)
        ctx.close()
        assert destino.exists() and destino.stat().st_size > 0
