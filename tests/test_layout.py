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
    """O nome vem de um formulário aberto. Sem escapar, vira XSS.

    A asserção mudou em 09/09/2026, e para MAIS estrita. Ela era "a página não
    contém <script>", o que só provava alguma coisa enquanto o casco não
    tivesse script nenhum — a lupa do comprovante trouxe um, e a asserção
    passou a falhar sem que nada de segurança tivesse mudado.

    Agora confere as duas metades do que importa, e não um efeito colateral
    delas: o que a pessoa digitou NÃO aparece cru, e aparece escapado. Isso
    continua valendo por mais scripts que o casco venha a ter."""
    html = layout.pagina("t", "c", usuario="<script>alert(1)</script>")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
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


def test_a_rota_da_entrada_nao_escapa_para_o_resto_do_sistema():
    """A rota e um COMPONENTE da tela de entrada, e precisa ficar la dentro.

    Solta no global, `.rota{display:flex}` alcancava o `<td class="rota">` do
    historico do painel - a coluna origem->destino. Um <td> em display:flex
    sai do modelo de colunas da tabela: a celula parava de alinhar com o
    proprio cabecalho, e nada quebrava o suficiente para alguem reparar.

    O teste guarda a REGRA (nome de classe generico so vale escopado), e nao
    o texto de um seletor: qualquer regra nova da rota que nasca fora de
    .entrada-marca cai aqui."""
    for regra in re.findall(r"[^{}]+\{", layout.CSS):
        for seletor in regra.split(","):
            seletor = seletor.strip()
            if re.match(r"^\.rota\b", seletor):
                pytest.fail(f"seletor .rota sem escopo de entrada: {seletor!r}")


def test_o_brilho_de_espera_casa_com_a_linha_que_o_app_monta():
    """O brilho da transportadora que ainda espera resposta e ligado por
    SELETOR, e nao por uma classe que alguem precisa lembrar de escrever.

    Era `.res:has(.cotando)`, do tempo dos cartoes; virou `tr.r:has(.cotando)`
    quando o resultado passou a ser tabela (10/09/2026). Se a marcacao mudar de
    novo, a regra para de casar EM SILENCIO - a tela nao quebra, so volta a
    ficar parada, e ninguem descobre olhando."""
    from web import app as modulo

    assert "tr.r:has(.cotando)" in layout.CSS
    assert 'class="cotando"' in pathlib.Path(
        modulo.__file__).read_text(encoding="utf-8")


# ------------------------------------------------------ lupa do comprovante
#
# O zoom do print ja quebrou duas vezes pelo mesmo motivo, e a segunda correcao
# so consertou uma das telas. A causa e sempre a mesma: `position:fixed` se
# ancora no ancestral mais proximo que tenha `transform`, e todo cartao carrega
# um transform identidade deixado pela animacao de entrada (`fill-mode:both`).
# Medido em 09/09/2026: o print abria dentro do cartao, no tamanho natural, por
# cima do texto da pagina.

def test_a_lupa_nao_usa_position_fixed():
    """`position:fixed` na imagem e a raiz do bug, nao um detalhe da
    implementacao. Qualquer volta a ele quebra de novo assim que a imagem
    estiver dentro de um cartao - que e sempre."""
    assert ".print.zoom" not in layout.CSS,         "o zoom por classe + position:fixed foi o que quebrou duas vezes"
    assert "position:fixed" not in layout.CSS.split(".lupa{")[1].split("}")[0]


def test_a_lupa_abre_na_camada_de_topo():
    """`showModal()` e o que poe o dialogo na camada de topo do navegador:
    acima de todo o documento, sem z-index, e imune a transform de ancestral.
    Um `<dialog>` aberto com `show()` (nao-modal) NAO ganha isso."""
    assert "showModal()" in layout.LUPA
    assert "<dialog" in layout.LUPA
    assert "::backdrop" in layout.CSS, "e o que escurece a pagina atras"


def test_a_lupa_existe_nas_duas_telas_que_mostram_print():
    """A correcao anterior consertou a tela do vendedor e deixou a do adm
    quebrada, porque cada uma tinha a sua copia do mesmo codigo. As duas
    montam o casco por funcoes diferentes - e as duas precisam da lupa."""
    from web import painel_ui

    assert "<dialog" in layout.pagina("t", "<p>x</p>")
    assert "<dialog" in painel_ui.pagina_painel("t", "<p>x</p>")


def test_existe_UMA_implementacao_da_lupa_e_nao_uma_por_tela():
    """Eram tres copias de `classList.toggle('zoom')`, em dois arquivos. Foi
    isso que deixou a correcao chegar numa tela so. Se voltar a haver copia,
    volta a haver tela consertada pela metade."""
    from web import adm, app as app_web

    for modulo in (app_web, adm):
        fonte = pathlib.Path(modulo.__file__).read_text(encoding="utf-8")
        assert "toggle('zoom')" not in fonte and 'toggle("zoom")' not in fonte,             f"{modulo.__name__} voltou a ter a sua propria copia do zoom"


def test_o_comprovante_abre_em_largura_de_leitura():
    """O print e para ser LIDO: o vendedor explica a composicao do frete ao
    cliente a partir dele. Encolher ate caber na altura da tela deixaria a
    letra menor que na miniatura - por isso largura cheia e rolagem dentro do
    dialogo, e nao `object-fit:contain`."""
    regra = layout.CSS.split(".lupa{")[1].split("}")[0]

    assert "overflow:auto" in regra
    assert "object-fit" not in regra


# --------------------------------------------------------- tela de entrada

def test_a_entrada_nao_repete_a_logo():
    """A tela de login usava `pagina()`, que traz a faixa do topo com a logo -
    e o cartao mostrava a MESMA logo logo abaixo, uma embaixo da outra. O
    casco proprio existe para isso: a faixa serve para navegar, e quem ainda
    nao entrou nao tem para onde ir."""
    html = layout.entrada("Entrar", "<div class='cartao'>x</div>",
                          chamada="c", apoio="a")

    assert html.count("base64,") == 1, "a logo tem que aparecer uma vez so"
    assert 'class="topo"' not in html


def test_a_entrada_escapa_o_que_vem_de_fora():
    """`cartao` entra cru de proposito (e HTML montado por quem chama), mas
    chamada, apoio, paradas e rodape sao texto e passam por e()."""
    html = layout.entrada("t", "<div>ok</div>", chamada="<script>a</script>",
                          apoio="<b>b</b>", paradas=("<i>1</i>", "<u>x</u>"),
                          rodape="<em>r</em>")

    for cru in ("<script>a</script>", "<b>b</b>", "<i>1</i>", "<u>x</u>",
                "<em>r</em>"):
        assert cru not in html
    assert "&lt;script&gt;a&lt;/script&gt;" in html


def test_o_texto_das_telas_de_entrada_sai_acentuado(monkeypatch):
    """Segunda vez que acento se perde em texto que a pessoa LE - a primeira
    foi a contagem do historico, que saiu "1 cotacao". Some quando o texto e
    escrito por script e o shell come o UTF-8, e ninguem percebe ate a tela
    estar no ar, porque o codigo ao redor continua funcionando."""
    from web import adm, app as app_web

    # Sem senha no ambiente o painel responde 404 de proposito (a Regra 1 do
    # modulo: a tela nao passa a existir "aberta por engano"). O teste e do
    # TEXTO, entao monta a senha para chegar na tela.
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", "so-para-o-teste")

    vendedor = app_web.tela_login()
    for palavra in ("formulário", "cotações", "automáticas", "histórico"):
        assert palavra in vendedor, f"a tela do vendedor perdeu: {palavra}"

    painel = adm.tela_de_entrada().body.decode("utf-8")
    for palavra in ("cotações", "Números", "histórico", "única"):
        assert palavra in painel, f"a tela do painel perdeu: {palavra}"


def test_a_rota_conta_as_transportadoras_de_verdade():
    """A parada do meio diz quantas cotam sozinhas, e o numero sai de
    len(AUTOMATICAS). Escrito a mao, a tela de entrada passaria a mentir sobre
    o tamanho do proprio sistema na primeira transportadora que entrasse ou
    saisse - e ninguem olha a tela de login para conferir isso."""
    from web import app as app_web

    html = app_web.tela_login()

    assert f"{len(app_web.AUTOMATICAS)} cotam sozinhas" in html


def test_a_rota_deixa_o_ultimo_ponto_em_aberto():
    """O ultimo trecho e pontilhado e o ultimo ponto e so contorno: e o preco
    que ainda nao chegou. Linha inteira solida diria que a cotacao acabou -
    numa tela onde ninguem nem entrou ainda."""
    html = layout.entrada("t", "<div>x</div>", chamada="c", apoio="a",
                          paradas=("um", "dois", "tres"))

    assert html.count('class="ponto"') == 3
    assert html.count('class="trecho"') == 1, "o do meio, percorrido"
    assert html.count('class="trecho falta"') == 1, "o ultimo, em aberto"
