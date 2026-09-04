"""O desenho do painel: gráfico, rosca, pastilha.

Camada PURA, igual a core/painel.py: entra número, sai string. Testa sem
navegador porque o risco mora na CONTA — uma barra desenhada com a altura
errada mente com a mesma confiança de um número errado, e ninguém confere
pixel batendo o olho.

O outro risco é ESCAPE: o nome do vendedor vem do formulário de login
("digitou um nome, entrou") e desemboca aqui dentro de atributo HTML e de
<text> de SVG.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from web import painel_ui as ui


# ------------------------------------------------------------ eixo do gráfico

@pytest.mark.parametrize("maior", [0, 1, 2, 3, 7, 10, 12, 37, 99, 150, 1234])
def test_teto_cabe_o_maior_valor_e_e_sempre_par(maior):
    """Par porque o eixo tem um risco no MEIO: com topo ímpar, o rótulo do
    meio sairia "7,5 cotações", que não existe. E nunca menor que o maior
    valor, senão a barra mais alta sai para fora do desenho."""
    alto = ui.teto(maior)

    assert alto >= maior
    assert alto % 2 == 0


def test_teto_arredonda_para_numero_redondo():
    assert ui.teto(37) == 40
    assert ui.teto(7) == 8
    assert ui.teto(150) == 200


def test_rotulo_do_balde_por_unidade():
    assert ui.rotulo_do_balde("2026-09-02T14", "hora") == "14h"
    assert ui.rotulo_do_balde("2026-09-02", "dia") == "02/09"
    assert ui.rotulo_do_balde("2026-09", "mes") == "set/26"


# ---------------------------------------------------------------- o gráfico

def _alturas(svg: str) -> list[float]:
    """As alturas das barras desenhadas, na ordem em que saíram."""
    return [float(h) for h in re.findall(
        r'class="barra-g"[^>]*height="([\d.]+)"', svg)]


def _serie(*valores: int) -> list[dict]:
    return [{"chave": f"2026-09-{i + 1:02d}", "cotacoes": v, "com_preco": 0}
            for i, v in enumerate(valores)]


def test_barra_de_zero_nao_tem_altura():
    """Um dia sem cotação precisa ficar VAZIO. Com qualquer altura mínima
    "para aparecer", o gráfico inventaria movimento num dia parado."""
    assert _alturas(ui.grafico_periodo(_serie(0, 4), "dia"))[0] == 0


def test_altura_das_barras_e_proporcional_ao_valor():
    """A barra de 10 tem que ter o dobro da de 5. É a única coisa que um
    gráfico de barras promete."""
    baixa, alta = _alturas(ui.grafico_periodo(_serie(5, 10), "dia"))

    assert alta == pytest.approx(baixa * 2)


def test_a_maior_barra_encosta_no_topo_quando_bate_o_teto():
    """teto(10) é 10, então a barra de 10 usa a altura inteira do desenho. Se
    sobrasse folga, o gráfico estaria desperdiçando a altura que tem."""
    assert _alturas(ui.grafico_periodo(_serie(10), "dia"))[0] == \
        pytest.approx(ui.G_ALT)


def test_linha_tem_um_ponto_por_balde():
    svg = ui.grafico_periodo(_serie(1, 2, 3, 4), "dia")
    caminho = re.search(r'class="linha-g" d="M([^"]+)"', svg).group(1)

    assert len(caminho.split(" L")) == 4


def test_o_traco_da_linha_usa_o_comprimento_real():
    """A animação desenha a linha escondendo-a num tracejado do tamanho dela.
    Com um número chutado grande, o traço termina no primeiro quarto do tempo
    e o resto da animação não acontece — nem quebra, nem funciona."""
    svg = ui.grafico_periodo(_serie(1, 2, 3), "dia")
    comprimento = float(re.search(r"stroke-dasharray:([\d.]+)", svg).group(1))

    # Três pontos ao longo de ~700 unidades de viewBox: a linha não pode ter
    # nem uns poucos pixels nem alguns milhares.
    assert 100 < comprimento < ui.G_L


def test_grafico_sem_ponto_nenhum_nao_quebra():
    """Pasta nova, primeiro dia, banco sem nada."""
    assert "Nenhuma cotação" in ui.grafico_periodo([], "dia")


def test_o_ultimo_balde_sempre_ganha_rotulo():
    """O último é "agora". Sem ele rotulado, quem lê conta as barras de trás
    para frente para descobrir onde o gráfico termina."""
    svg = ui.grafico_periodo(_serie(*range(1, 31)), "dia")

    assert ">30/09<" in svg


def test_grafico_grande_nao_desenha_bolinha_em_cada_ponto():
    """Com 120 meses as bolinhas viram sujeira em cima da própria linha."""
    muitos = [{"chave": f"2026-{m % 12 + 1:02d}", "cotacoes": 1,
               "com_preco": 1} for m in range(ui.MAX_PONTOS_COM_BOLINHA + 5)]

    assert 'class="ponto-g"' not in ui.grafico_periodo(muitos, "mes")


# ------------------------------------------------------------------ roscas

def test_rosca_sem_dados_nao_finge_zero():
    """`aproveitamento` None é DESCONHECIDO. Um anel vazio pintado de
    vermelho acusa de "nunca acerta" quem só viu o servidor reiniciar."""
    html = ui.rosca(None, "jadlog")

    assert "sem dados ainda" in html
    assert "0%" not in html


def test_rosca_de_zero_mostra_zero():
    """Zero de verdade é outra coisa: aí o anel É vermelho e escreve 0%."""
    html = ui.rosca(0.0, "jadlog", "0 de 3 respostas")

    assert ">0%<" in html
    assert "#bf2600" in html


def test_rosca_cheia_nao_deixa_arco_faltando():
    """100% precisa fechar a volta: stroke-dashoffset zero."""
    assert "--cheio:0.0" in ui.rosca(1.0, "camilo")


def test_rosca_so_fica_verde_quando_e_bom_de_verdade():
    """Anel verde em 40% tranquiliza justamente quem deveria estar ligando
    para a transportadora."""
    assert "#00875a" in ui.rosca(0.9, "x")
    assert "#00875a" not in ui.rosca(0.6, "x")
    assert "#00875a" not in ui.rosca(0.4, "x")


def test_nome_de_transportadora_e_escapado_na_rosca():
    assert "<script>" not in ui.rosca(0.5, "<script>alert(1)</script>")


# --------------------------------------------------------- pizza de status

def _linha_saude(**contagens) -> dict:
    base = {"transportadora": "x", "sucesso": 0, "recusa": 0, "falha": 0,
            "nossa": 0, "inesperado": 0, "aproveitamento": None}
    return {**base, **contagens}


def test_pizza_soma_todas_as_respostas():
    html = ui.pizza_de_status([_linha_saude(sucesso=7, falha=3)])

    assert ">10</text>" in html


def test_categoria_com_uma_ocorrencia_nao_some_da_pizza():
    """A folga entre fatias é descontada do tamanho da fatia. Sem o limite,
    numa categoria com 1 de 201 a folga fica maior que a fatia e ela some — a
    única falha do mês desapareceria justamente do desenho que existe para
    mostrá-la."""
    html = ui.pizza_de_status([_linha_saude(sucesso=200, falha=1)])

    assert ui.CORES["falha"] in html
    riscos = [float(t) for t in re.findall(
        r'class="fatia"[^>]*stroke-dasharray="([\d.]+)', html)]
    assert min(riscos) > 0


def test_pizza_sem_resposta_nenhuma_nao_quebra():
    assert "Nenhuma resposta" in ui.pizza_de_status([])


# --------------------------------------------------------------- ranking

def test_ranking_compara_com_o_lider_e_nao_com_o_total():
    """Contra o total, dez vendedores viram dez barras de 10% e ninguém
    compara ninguém. O líder tem que encher a barra."""
    html = ui.ranking([{"usuario": "ana", "cotacoes": 8},
                       {"usuario": "bia", "cotacoes": 4}],
                      "usuario", "cotacoes")

    assert "width:100.0%" in html
    assert "width:50.0%" in html


def test_ranking_escapa_o_nome_do_vendedor():
    """O nome vem do formulário de login, que aceita qualquer coisa."""
    html = ui.ranking([{"usuario": '"><script>x</script>', "cotacoes": 1}],
                      "usuario", "cotacoes")

    assert "<script>" not in html


def test_ranking_vazio_nao_quebra():
    assert "Nenhuma cotação" in ui.ranking([], "usuario", "cotacoes")


# -------------------------------------------------------- linha e pastilha

def test_pilulas_mostram_cada_categoria_que_aconteceu():
    html = ui.pilulas({"sucesso": 3, "falha": 1})

    assert "3 sucessos" in html
    assert "recusa" not in html


def test_uma_ocorrencia_sai_no_singular():
    """"1 sucessos" numa tela que a empresa inteira lê passa de descuido a
    assinatura."""
    assert "1 falha" in ui.pilulas({"falha": 1})
    assert "1 falhas" not in ui.pilulas({"falha": 1})
    assert "1 interrompida" in ui.pilulas({"nossa": 1})
    assert "2 falhas" in ui.pilulas({"falha": 2})


def test_cotacao_sem_nenhuma_resposta_diz_que_ainda_esta_cotando():
    """Contagem vazia não é "deu tudo certo": é que ninguém respondeu
    ainda."""
    assert "ainda cotando" in ui.pilulas({})


def test_avatar_escapa_o_nome():
    assert "<script>" not in ui.avatar("<script>alert(1)</script>")


def test_avatar_da_a_mesma_cor_para_o_mesmo_nome():
    """Cor derivada do nome, sem tabela de cor por pessoa para manter."""
    assert ui.avatar("leandro") == ui.avatar("leandro")
    assert ui.avatar("leandro") != ui.avatar("enzo")


def test_avatar_de_nome_vazio_nao_quebra():
    assert "?" in ui.avatar("")


# ------------------------------------------------------------- dia do grupo

def test_hoje_e_ontem_ganham_nome():
    hoje = date.today().isoformat()
    ontem = (date.today() - timedelta(days=1)).isoformat()

    assert ui.dia_por_extenso(hoje).startswith("hoje · ")
    assert ui.dia_por_extenso(ontem).startswith("ontem · ")


def test_dia_antigo_sai_com_o_dia_da_semana():
    """Data FIXA e antiga de propósito: com uma data de hoje, o teste passaria
    a exercitar o ramo do "hoje ·" no dia em que foi escrito e só quebraria no
    dia seguinte."""
    # 04/03/2020 caiu numa quarta-feira.
    assert ui.dia_por_extenso("2020-03-04T14:33:07") == "quarta, 04/03"


def test_data_torta_nao_derruba_a_tela():
    """`criado_em` é TEXTO no banco. Uma linha torta some do agrupamento, não
    leva o painel inteiro junto."""
    assert ui.dia_por_extenso("sem-data") == "sem-data"


# ---------------------------------------------------------------- o casco

def test_a_pagina_do_painel_nao_puxa_nada_da_internet():
    """O Servidor.bat sobe numa máquina da empresa e a tela precisa abrir com
    a internet caída. Um <script src> de CDN viraria página em branco
    justamente no dia em que alguém quer olhar o painel."""
    html = ui.pagina_painel("Painel", "<p>oi</p>")

    assert "http://" not in html
    assert "https://" not in html
    assert "src=" not in html.replace('src="data:image', "")


def test_todo_item_do_menu_aponta_para_uma_secao_que_existe():
    """O id É o destino do link e o valor de data-secao. Dois nomes para a
    mesma seção deixariam a marcação do menu nunca acender."""
    html = ui.pagina_painel("Painel", "")

    for _, _, alvo in ui.MENU:
        assert f'href="#{alvo}" data-secao="{alvo}"' in html


def test_fora_do_painel_o_menu_volta_para_o_painel():
    """Na tela de UMA cotação as seções não existem. Um href="#movimento" que
    não sai do lugar deixa o menu inteiro parecendo quebrado."""
    html = ui.pagina_painel("Cotação", "", base="/adm")

    assert 'href="/adm#movimento"' in html
    assert 'href="#movimento"' not in html


# ------------------------------------------------------------- alertas

def _alerta(**campos) -> dict:
    base = {"transportadora": "jadlog", "quantas": 5,
            "ids": [56, 55, 54, 53, 52], "ultima": "2026-08-28T09:22:00",
            "desde": "2026-08-27T16:13:00", "erro": "login recusado"}
    return {**base, **campos}


def test_sem_alerta_nao_desenha_cartao_nenhum():
    """Um cartão "nenhum alerta" fixo no topo treina o olho a pular a região
    — e aí ele pula também no dia em que o alerta está lá."""
    assert ui.alertas([], str) == ""


def test_o_alerta_diz_quem_quantas_e_desde_quando():
    html = ui.alertas([_alerta()], lambda s: "Jadlog Entregas")

    assert "Jadlog Entregas falhou nas últimas 5 tentativas." in html
    assert "27/08 às 16:13" in html
    assert "login recusado" in html


def test_o_alerta_linka_cada_cotacao_afetada():
    """Sem os números, o alerta manda procurar."""
    html = ui.alertas([_alerta()], str)

    assert 'href="/adm/cotacao/56"' in html


def test_alerta_comprido_nao_despeja_a_lista_inteira():
    """Numa transportadora quebrada há duas semanas, a lista inteira cobriria
    o alerta seguinte."""
    html = ui.alertas([_alerta(quantas=12, ids=list(range(12)))], str)

    assert html.count("/adm/cotacao/") == 5
    assert ">+7</a>" in html


def test_o_alerta_escapa_o_texto_do_erro():
    """O erro vem do site da transportadora, não de nós."""
    html = ui.alertas([_alerta(erro="<script>alert(1)</script>")], str)

    assert "<script>" not in html


# ------------------------------------------- cartão de uma resposta

def test_cartao_de_resposta_mostra_preco_e_status():
    html = ui.cartao_resposta(nome="Braspress", logo="braspress.png",
                              status="cotado", valor="R$ 94,57")

    assert "R$ 94,57" in html
    assert "Cotou" in html


def test_so_o_mais_barato_leva_o_selo():
    com = ui.cartao_resposta(nome="x", logo="", status="cotado",
                             valor="R$ 10,00", melhor=True)
    sem = ui.cartao_resposta(nome="x", logo="", status="cotado",
                             valor="R$ 20,00")

    assert "MAIS BARATO" in com
    assert "MAIS BARATO" not in sem


def test_sem_preco_nunca_vira_zero():
    """Zero seria um preço. Não ter preço é outra coisa — e a frase diz o que
    aconteceu, em vez de deixar o cartão vazio."""
    html = ui.cartao_resposta(nome="x", logo="", status="erro")

    assert "R$ 0,00" not in html
    assert "não retornou preço" in html


def test_enviada_por_email_nao_e_apresentada_como_falha():
    """A Della Volpe e a Generoso recebem e respondem por e-mail. "sem preço"
    embaixo de "Enviada" contradiz a própria pastilha."""
    html = ui.cartao_resposta(nome="x", logo="", status="aguardando_retorno")

    assert "o preço vem por e-mail" in html
    assert "sem preço" not in html


def test_status_desconhecido_aparece_cru_em_vez_de_sumir():
    """Esconder o desconhecido foi como "(nenhuma mensagem visível)"
    nasceu."""
    html = ui.cartao_resposta(nome="x", logo="", status="coisa_nova")

    assert "coisa_nova" in html


def test_o_erro_tecnico_vai_inteiro_na_tela_do_adm():
    """A tela do vendedor corta em 400 caracteres; esta é onde se investiga,
    e cortar esconderia justamente a linha que explica."""
    enorme = "Timeout " + "x" * 900
    html = ui.cartao_resposta(nome="x", logo="", status="erro",
                              erro_cru=enorme)

    assert enorme in html


def test_transportadora_sem_logo_cadastrada_nao_vira_imagem_quebrada():
    """Na tela do adm, o ícone de imagem quebrada parece defeito do sistema —
    e não cadastro faltando."""
    html = ui.cartao_resposta(nome="Acme", logo="", status="cotado")

    assert "<img" not in html
    assert 'class="bola"' in html


def test_cartao_de_resposta_escapa_tudo_que_vem_de_fora():
    html = ui.cartao_resposta(nome="<script>a</script>", logo="",
                              status="erro", erro_cru="<script>b</script>",
                              avisos=("<script>c</script>",),
                              miudos=("<script>d</script>",))

    assert "<script>" not in html


# ------------------------------------------------------ tempo de resposta

def test_a_barra_do_tempo_e_proporcional_a_mais_lenta():
    """O que a tela responde é "quem segurou a cotação", e isso é comparação
    entre elas."""
    html = ui.tempos_de_resposta([
        {"nome": "a", "segundos": 120, "cor": "#000"},
        {"nome": "b", "segundos": 60, "cor": "#000"}])

    assert "width:100.0%" in html
    assert "width:50.0%" in html


def test_quem_nao_tem_hora_registrada_continua_na_lista():
    """Sumir da lista faria a transportadora parecer não ter sido chamada."""
    html = ui.tempos_de_resposta([
        {"nome": "antiga", "segundos": None, "cor": "#000"}])

    assert "antiga" in html
    assert "sem dados ainda" in html


def test_tempo_por_extenso():
    assert ui.segundos_por_extenso(25.4) == "25 s"
    assert ui.segundos_por_extenso(125) == "2 min 05 s"
    assert ui.segundos_por_extenso(None) == "sem dados ainda"


# ------------------------------------------------------ whatsapp aberto

def test_whatsapp_aberto_lista_quem_e_quando():
    html = ui.abertas_no_whatsapp(
        [{"transportadora": "movvi", "aberto_em": "2026-09-02T14:33:07"}],
        lambda s: "Movvi Logística")

    assert "Movvi Logística" in html
    assert "02/09 às 14:33" in html


def test_sem_whatsapp_aberto_diz_isso_em_vez_de_sumir():
    """Nenhuma conversa aberta é DADO: explica metade de uma cotação que
    ficou sem preço."""
    assert "Nenhuma conversa" in ui.abertas_no_whatsapp([], str)


def test_data_torta_no_alerta_nao_derruba_a_tela():
    """`criado_em` é TEXTO no banco."""
    assert ui.dia_e_hora("sem-data") == "sem-data"
