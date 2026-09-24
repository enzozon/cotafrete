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
    # `[a-z0-9-]`, e não `[a-z-]`: com a classe só de letras, TODO token com
    # dígito no nome ficava invisível para estes testes. `--tinta2` é texto
    # de verdade na tela e nunca tinha sido conferido — o teste passava
    # porque nem chegava a olhar para ele.
    achados = re.findall(r"(--[a-z0-9-]+):(#(?:[0-9a-fA-F]{3}){1,2})", bloco)
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
    ("--realce", "--papel", 3.0, "anel de foco (WCAG 1.4.11)"),
    ("--tinta2", "--papel", 4.5, "texto secundário"),
    ("--tom-marca", "--tom-marca-fraco", 3.0, "ícone do número, no painel"),
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


def test_o_botao_de_tema_nao_e_pintado_como_botao_de_marca():
    """O botão de tema é contorno, não preenchimento — e não pode herdar a
    tinta de quem tem preenchimento.

    A regra `[data-tema="escuro"] button{color:var(--sobre-marca)}` existe
    porque o botão comum é ciano cheio e o #fff nele dá 1.9:1. Mas ela é um
    seletor com atributo (0,1,1) e ganhava do `.tema` (0,1,0): o ícone do sol
    saía pintado de #0b0f1c, que é a cor do FUNDO da página. Ficava desenhado
    em preto sobre preto — presente na tela, com 17px de lado, e invisível
    para quem olha.

    Nenhum teste de HTML pega isso: o SVG está lá, o atributo está lá, a
    página responde 200. Só a cor computada denuncia.

    O `re.sub` do comentário não é detalhe: sem ele o teste lia o comentário
    que explica a regra — e como ele cita `:not(.tema)`, passava sozinho, sem
    nunca olhar para o seletor de verdade."""
    css = re.sub(r"/\*.*?\*/", "", layout.CSS, flags=re.S)
    # `button` no fim, com ou sem pseudo-classe atrás — é preciso casar as
    # duas formas: a certa (`button:not(.tema)`) e a errada (`button` puro),
    # senão o teste passa justamente quando o defeito volta.
    # Várias pseudo-classes em fila também (`button:not(.tema):not(.botao2)`).
    alvo = re.compile(r"\bbutton(:[a-z-]+(\([^)]*\))?)*$")
    achados = [s.strip()
               for regra in re.findall(r"([^{}]+)\{", css)
               for s in regra.split(",")
               if "data-tema" in s and alvo.search(s.strip())]

    assert achados, "a regra de tinta sobre preenchimento sumiu do CSS"
    for seletor in achados:
        assert ":not(.tema)" in seletor, (
            f"{seletor!r} alcança o botão de tema, que não tem preenchimento "
            f"da marca — o ícone do sol sumiria dentro dele")


def test_cada_peca_da_marca_vai_onde_cabe():
    """Tres pecas, tres trabalhos — e cada uma no lugar em que e legivel.

    O lockup inteiro tem tres niveis de texto e a assinatura ocupa 6px de
    120: num cabecalho de 36px isso vira 1.8px de mingau. Por isso o
    cabecalho usa a peca COMPACTA (sem assinatura) e o lockup inteiro fica na
    entrada e na faixa do inicio, onde ha altura para le-lo.

    A lateral do painel tem 236px de largura: so o SIMBOLO cabe ali."""
    from web import painel_ui

    do_vendedor = layout.pagina("t", "<b>x</b>", "enzo")
    entrada = layout.entrada("t", "<b>x</b>", chamada="c", apoio="a")
    painel = painel_ui.pagina_painel("t", "<b>x</b>")

    assert layout.MARCA_COMPACTA in do_vendedor, "cabecalho do vendedor"
    assert layout.MARCA_COMPACTA in entrada, "a entrada usa a mesma peca"
    assert layout.MARCA_SIMBOLO in painel, "a lateral so cabe o simbolo"
    # A pergunta e sobre a marca VISIVEL, entao a conferencia e no <img> e nao
    # na presenca do caminho: desde 17/09/2026 o simbolo tambem e o icone da
    # aba, e aparece no <head> de todas as telas. Conferir o caminho solto
    # daria alarme falso para uma imagem que ninguem ve dentro da pagina.
    assert f'<img src="{layout.MARCA_SIMBOLO}"' not in do_vendedor, \
        "no vendedor a marca vem por extenso, e nao so o simbolo"

    # A assinatura e TEXTO em toda parte: dentro do raster ela tem 6px de
    # 120, e so se le a partir de ~180px de altura da peca inteira — altura
    # que tela nenhuma do sistema tem.
    assert layout.ASSINATURA in entrada
    assert layout.ASSINATURA in do_vendedor


def test_a_marca_nao_vai_embutida_em_cada_pagina():
    """As pecas sao ARQUIVO, e nao base64 dentro do HTML.

    A logo antiga tinha 26 KB e cabia embutida. As tres pecas novas somam
    ~110 KB, e 110 KB em toda resposta e peso que o navegador ja sabe evitar
    sozinho: servidas por /marca, ele busca uma vez e guarda."""
    from web import painel_ui

    for nome, html in (("vendedor", layout.pagina("t", "<b>x</b>", "enzo")),
                       ("entrada", layout.entrada("t", "<b>x</b>",
                                                  chamada="c", apoio="a")),
                       ("painel", painel_ui.pagina_painel("t", "<b>x</b>"))):
        assert "base64," not in html, (
            f"a tela do {nome} voltou a embutir imagem no HTML")


def test_cada_tema_recebe_a_arte_feita_para_ele():
    """Duas artes da marca, e o tema escolhe. Nenhuma placa atras.

    As letras da marca sao PRATEADAS: sobre branco dao 1.1:1. A primeira
    solucao foi uma placa quase preta atras da logo — resolvia a
    legibilidade e cortava a pagina clara ao meio, que e remendo, nao
    desenho.

    Agora sao duas artes: a prateada para fundo escuro, e uma com o prateado
    virado tinta escura para fundo claro.

    A troca e por `background-image`, e nao por duas <img> com uma
    escondida: o navegador baixa <img> mesmo com display:none, e seriam
    90 KB que nunca aparecem na tela.
    """
    css = layout.CSS

    assert layout.MARCA_COMPACTA_CLARA in css, "falta a arte do tema claro"
    assert '[data-tema="escuro"] .marca-lockup{background-image:' in css, (
        "o escuro precisa trocar para a arte prateada")
    antes_da_faixa = css.split(".faixa-marca")[0]
    assert "background:#0a1020" not in antes_da_faixa, (
        "a placa escura atras da logo nao pode voltar")


def test_a_faixa_do_inicio_acompanha_o_tema():
    """Ela era um painel quase preto no alto de uma pagina branca.

    Cortava a tela ao meio e nao combinava com nada em volta — foi essa a
    queixa que gerou a mudanca. No claro ela passa a ser um cartao da casa;
    no escuro continua painel, porque la o cartao claro e que seria o corpo
    estranho.
    """
    css = layout.CSS

    assert "linear-gradient(110deg,var(--lavagem)" in css, (
        "no claro a faixa sai da lavagem da marca, e nao de um preto")
    assert '[data-tema="escuro"] .faixa-marca{background:#0a1020' in css, (
        "no escuro ela continua escura")
    assert ".faixa-marca .diz{color:var(--tinta2)" in css, (
        "o texto da faixa precisa seguir o tema, e nao ser fixo em claro")


def test_os_tokens_da_marca_estao_na_matiz_da_marca():
    """Todo token de marca nasce da MATIZ medida em web/marca/: 218 graus.

    Não confere o valor exato de cada um — a luminosidade de cada tom é
    escolhida pelo contraste que ele precisa ter, e os testes acima já
    guardam isso. O que se guarda aqui é a FAMÍLIA: um azul de outra matiz
    colado no meio da paleta não quebra contraste nenhum e mesmo assim faz a
    tela parar de parecer da Ventura, que é o defeito mais difícil de ver
    olhando um token por vez.

    A tolerância de 12 graus é a folga de arredondar hexadecimal: derivar
    #0042b5 da matiz 218 e ler de volta dá 217.6."""
    import colorsys

    for nome in ("--marca", "--marca-forte", "--marca-viva",
                 "--realce", "--realce-claro", "--tom-marca"):
        cor = _tokens()[nome]
        r, g, b = (int(cor[i:i + 2], 16) / 255 for i in (1, 3, 5))
        matiz = colorsys.rgb_to_hls(r, g, b)[0] * 360

        assert abs(matiz - 218) <= 12, (
            f"{nome} ({cor}) está na matiz {matiz:.0f}, e a marca é 218 — "
            f"medida pixel a pixel em web/marca/")


def test_a_paleta_nao_guarda_mais_o_ciano_da_logo_antiga():
    """O ciano #70c8e0 vinha da logo ANTERIOR e não existe no desenho atual.

    Ele sobreviveria calado: nenhum contraste quebra por causa dele, e a tela
    continua funcionando — só volta a não parecer da empresa. Um hexadecimal
    esquecido numa regra é exatamente como isso acontece."""
    codigo = layout.CSS
    from web import painel_ui

    for antigo in ("70c8e0", "384890", "2f3f88", "359fc0", "4058a0"):
        # No comentário que conta a história ele pode aparecer; em REGRA não.
        sem_comentario = re.sub(r"/\*.*?\*/", "", codigo + painel_ui.CSS,
                                flags=re.S)
        assert antigo not in sem_comentario, (
            f"#{antigo} é da marca anterior e sobrou numa regra")


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


def test_cada_casco_abre_no_tema_que_ja_era_o_dele():
    """Vendedor claro, painel escuro — para quem NUNCA mexeu no botao.

    O padrao nao e detalhe: e a promessa de que ninguem chega amanha numa
    tela diferente da de ontem so porque o sistema ganhou um botao."""
    from web import painel_ui

    assert "||'claro'" in layout.pagina("t", "<b>x</b>")
    assert "||'escuro'" in painel_ui.pagina_painel("t", "<b>x</b>")


def test_o_tema_e_decidido_antes_da_primeira_pintura():
    """O script do tema no <head> e ANTES do <style>, e sincrono.

    Solto no fim do <body> ele tambem funcionaria - e quem escolheu escuro
    veria a pagina inteira clara por um quadro antes de escurecer. Essa
    piscada branca na cara de quem pediu tela escura e pior do que nao ter
    o botao, e e o tipo de coisa que so aparece na maquina de quem usa."""
    from web import painel_ui

    for pagina in (layout.pagina("t", "<b>x</b>"),
                   painel_ui.pagina_painel("t", "<b>x</b>")):
        assert pagina.index("dataset.tema") < pagina.index("<style>")
        # `defer`/`async` aqui devolveriam a piscada de graca.
        assert "<script defer" not in pagina
        assert "<script async" not in pagina


def test_os_dois_conjuntos_de_token_cobrem_os_mesmos_nomes():
    """Todo token redefinido no escuro precisa existir no claro.

    Um nome so no escuro vira `var(--x)` sem valor no tema claro, e a
    propriedade inteira e descartada: o texto fica preto no meio de um
    cartao branco, ou o fundo some. E ninguem ve isso testando so o tema em
    que estava trabalhando."""
    def nomes(bloco: str) -> set[str]:
        sem_comentario = re.sub(r"/\*.*?\*/", "", bloco, flags=re.S)
        return set(re.findall(r"(--[a-z0-9-]+):", sem_comentario))

    css = layout.CSS
    claro = css[css.index(":root{"):css.index("*{box-sizing")]
    abre = 'html[data-tema="escuro"]{'
    escuro = css[css.index(abre):css.index("color-scheme:dark}")]
    so_no_escuro = nomes(escuro) - nomes(claro)

    assert not so_no_escuro, f"token sem par no claro: {sorted(so_no_escuro)}"


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

    # Conta o ELEMENTO, e nao o endereco do arquivo: desde que a marca virou
    # background-image, o endereco aparece tambem no CSS — que vai inteiro
    # dentro da pagina. Contar a string dava 3 e nao dizia nada sobre quantas
    # marcas a pessoa ve.
    assert html.count('class="logo marca-peca"') == 1, \
        "a marca tem que aparecer uma vez so"
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


def test_todas_as_telas_levam_o_icone_da_aba():
    """Sao TRES cascos diferentes - entrada(), pagina() e pagina_painel() - e
    cada um monta o proprio <head>. Conferir um so deixaria as outras duas com
    o globo cinza do navegador, que e como o site estava ate 17/09/2026.

    O mesmo descuido ja tinha acontecido com a barra lateral da tela de
    contas: o que vale para um casco nao vale sozinho para os outros."""
    from web import painel_ui

    cascos = {
        "entrada (login)": layout.entrada("t", "<div>x</div>", chamada="c",
                                          apoio="a", paradas=("um", "dois")),
        "pagina (vendedor)": layout.pagina("t", "<div>x</div>", "enzo"),
        "painel (adm)": painel_ui.pagina_painel("t", "<div>x</div>"),
    }

    for nome, html in cascos.items():
        assert 'rel="icon"' in html, f"{nome} sem icone na aba"
        assert layout.MARCA_SIMBOLO in html, f"{nome} aponta para outro arquivo"
