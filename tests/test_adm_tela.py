"""O que a tela do painel mostra.

Os números são a razão de a tela existir: um aproveitamento errado manda o
Enzo cobrar a transportadora errada. Por isso o teste confere o CONTEÚDO, não
só o status 200.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core.banco import Banco
from web import adm, app as app_web

SENHA = "senha-de-teste-123"
CARGA = {"cep_origem": "29105770", "cep_destino": "01310100",
         "cidade_origem": "Vila Velha", "cidade_destino": "São Paulo",
         "peso_kg": "10", "quantidade": 1, "comprimento_cm": 30,
         "largura_cm": 30, "altura_cm": 30, "valor_nf": "1000",
         "material": "PLACA DE VIDEO"}


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))
    c = TestClient(app_web.app)
    c.cookies.set(adm.COOKIE_ADM, adm.token_de(SENHA))
    return c


def test_tela_mostra_cotacao_de_outro_usuario(cliente):
    """É o ponto do painel: o adm vê a empresa inteira, não só as dele."""
    cid = adm.banco.salvar_cotacao("leandro", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                                   valor=Decimal("123.45"))

    html = cliente.get("/adm").text

    assert "leandro" in html
    assert "123,45" in html


def test_tela_separa_falha_de_recusa(cliente):
    """Juntar as duas mandaria o Enzo cacar um problema que nao existe: as
    recusas da Jadlog por peso sao a transportadora funcionando.

    A versao antiga desta asserção só conferia "Recusas" e "Falhas" no HTML —
    e esses são os CABEÇALHOS ESTÁTICOS da tabela, presentes mesmo se as
    colunas viessem trocadas no render. Esta versão confere a LINHA montada de
    cada transportadora, coluna por coluna, com a mesma precisão do teste do
    travessão."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "jadlog", status="recusado",
                                   erro="peso acima de 120 kg")
    adm.banco.salvar_resultado(cid, "generoso", status="erro",
                                   erro="TimeoutError: nao abriu")

    html = cliente.get("/adm").text

    # Ordem das colunas em _saude: transportadora, sucesso, recusa, falha,
    # nossa, inesperado. O nome da primeira célula é o de TELA
    # (transportadoras.nome_de) desde 04/09/2026: o painel passou a mostrar
    # logo e nome de verdade nos cartões, e a tabela escrevendo "jadlog"
    # embaixo de um cartão escrito "Jadlog Entregas" parecia outra coisa.
    assert ('<td>Jadlog Entregas</td><td>0</td><td>1</td><td>0</td><td>0</td>'
            '<td>0</td>') in html
    assert ('<td>Transporte Generoso</td><td>0</td><td>0</td><td>1</td>'
            '<td>0</td><td>0</td>') in html


def test_tela_vazia_nao_quebra(cliente):
    """Pasta nova, primeiro dia, banco sem nada."""
    assert cliente.get("/adm").status_code == 200


def test_o_periodo_escolhido_fica_marcado(cliente):
    """Sem marcar, ninguém sabe qual recorte está vendo — e um número lido
    no período errado é pior que número nenhum."""
    html = cliente.get("/adm?dias=7").text

    assert 'class="periodo atual"' in html
    assert "?dias=7" in html


def test_ao_vivo_devolve_fragmentos_e_nao_a_pagina(cliente):
    """A tela troca a faixa e a tabela sozinha. Se a rota devolvesse a página
    inteira, o JavaScript recolocaria uma página dentro dela mesma."""
    dados = cliente.get("/adm/agora").json()

    assert set(dados) == {"v", "faixa", "tabela"}
    for pedaco in (dados["faixa"], dados["tabela"]):
        assert "<!doctype" not in pedaco.lower()
        assert "<html" not in pedaco.lower()


def test_faixa_ao_vivo_tambem_exige_cookie(monkeypatch, tmp_path):
    """O fragmento tem os mesmos dados da tela: não pode ser porta dos
    fundos."""
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))

    resposta = TestClient(app_web.app).get("/adm/agora",
                                           follow_redirects=False)

    assert resposta.status_code == 303


def test_transportadora_so_com_interrompido_mostra_sem_dados(cliente):
    """`aproveitamento` None é DESCONHECIDO, não zero. Se a tela confundir os
    dois, uma transportadora que só viu o servidor reiniciar aparece com
    "0%" — igual a quem nunca acerta uma cotação, o que é mentira."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "jadlog", status="interrompido")

    html = cliente.get("/adm").text

    assert "sem dados ainda" in html
    # Não "0%" cru: a CSS já tem "width:100%" espalhada, que contém "0%"
    # como substring. O que não pode aparecer é a barra de _barra() marcando
    # zero — o texto exato que ela escreve depois do </div>.
    assert "</div> 0%" not in html


def test_cotacao_sem_resultado_mostra_travessao(cliente):
    """`melhor_preco` None é "não teve preço", não "R$ 0,00" — zero seria um
    preço de verdade, e a diferença é a razão de a coluna existir.

    O travessão em si já está no `<title>` de toda página (o "—" de "Painel
    — Cotafrete"), então `assert "—" in html` passaria mesmo se a célula do
    preço saísse vazia. A asserção precisa do fragmento exato que
    `_historico` escreve para a célula: `<td>{moeda(...)}</td>`."""
    adm.banco.salvar_cotacao("enzo", CARGA)

    html = cliente.get("/adm").text

    assert "<td>—</td>" in html
    assert "R$ 0,00" not in html


def test_login_aceita_senha_acentuada(monkeypatch, tmp_path):
    """hmac.compare_digest com `str` só aceita ASCII: qualquer acento levanta
    TypeError (que vira 500). O time vai escrever COTAFRETE_ADM_SENHA no .env
    de produção — se usar acento ou cedilha, a senha CERTA também derrubaria
    o painel para sempre sem o .encode() dos dois lados."""
    senha = "señha-com-acentuação"
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", senha)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))
    c = TestClient(app_web.app)

    errada = c.post("/adm/entrar", data={"senha": "outra-señha-ã"})
    assert errada.status_code == 401

    certa = c.post("/adm/entrar", data={"senha": senha},
                   follow_redirects=False)
    assert certa.status_code == 303


def test_dias_fora_da_lista_cai_em_trinta(cliente):
    """?dias=999999999 estourava OverflowError no timedelta dentro de
    _desde(); ?dias=15 renderizava sem marcar período nenhum como atual; e
    ?dias=-5 buscava no futuro e devolvia tudo vazio. Os três precisam cair
    no mesmo lugar: 30, o padrão."""
    for bruto in ("999999999", "15", "-5"):
        r = cliente.get(f"/adm?dias={bruto}")
        assert r.status_code == 200
        assert '<a class="periodo atual" href="/adm?dias=30">30 dias</a>' \
            in r.text


# ------------------------------- o painel visual ---------------------------

def test_a_tela_desenha_o_grafico_do_periodo(cliente):
    """O gráfico é montado no servidor, em SVG. Se ele sumisse, a tela ainda
    responderia 200 com um buraco no lugar — status não é conferência."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("50"))

    html = cliente.get("/adm").text

    assert 'class="barra-g"' in html
    assert 'class="linha-g"' in html


def test_a_tela_nao_puxa_nada_da_internet(cliente):
    """O Servidor.bat sobe numa máquina da empresa. Um gráfico vindo de CDN
    viraria página em branco justamente no dia em que a internet cair — que é
    o dia em que alguém quer olhar o painel."""
    html = cliente.get("/adm").text

    assert "http://" not in html
    assert "https://" not in html


def test_o_historico_agrupa_por_dia(cliente):
    """A lista corrida obrigava a ler a data em toda linha para saber se
    ainda era hoje."""
    adm.banco.salvar_cotacao("enzo", CARGA)

    html = cliente.get("/adm").text

    assert 'class="dia"' in html
    assert "hoje · " in html


def test_o_historico_diz_o_que_aconteceu_em_cada_cotacao(cliente):
    """"1" na coluna falhas obrigava a abrir a cotação para saber se o resto
    deu certo. As pastilhas dizem as duas coisas de longe."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("50"))
    adm.banco.salvar_resultado(cid, "jadlog", status="erro", erro="timeout")

    html = cliente.get("/adm").text

    assert "1 sucesso" in html
    assert "1 falha" in html


def test_cotacao_sem_resposta_nenhuma_nao_parece_bem_sucedida(cliente):
    """Nenhuma resposta ainda não é "deu tudo certo"."""
    adm.banco.salvar_cotacao("enzo", CARGA)

    assert "ainda cotando" in cliente.get("/adm").text


def test_a_busca_do_historico_enxerga_material_e_vendedor(cliente):
    """O que a busca varre é montado no servidor, em minúsculas: procurar
    dentro do HTML visível acharia nome de classe CSS."""
    adm.banco.salvar_cotacao("leandro", CARGA)

    html = cliente.get("/adm").text

    assert "leandro" in html.lower()
    assert "placa de video" in html.lower()


def test_nome_de_vendedor_com_marcacao_nao_escapa_para_a_tela(cliente):
    """O login é placeholder: digitou um nome, entrou. Então `usuario` é
    texto de fora, e esta tela mostra o de TODO mundo — o nome de um vendedor
    não pode virar script na tela de quem administra.

    O nome passa por três lugares diferentes no render: a bolinha do avatar,
    o atributo data-busca da linha e o ranking de quem mais cotou."""
    veneno = "<script>alert(1)</script>"
    adm.banco.salvar_cotacao(veneno, CARGA)

    html = cliente.get("/adm").text

    assert veneno not in html
    assert "<script>alert" not in html


def test_transportadora_sem_dados_tambem_fica_sem_dados_na_rosca(cliente):
    """A rosca repete a regra da barra: None é DESCONHECIDO, não zero. Um
    anel vermelho vazio acusaria de "nunca acerta" quem só viu o servidor
    reiniciar."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "jadlog", status="interrompido")

    html = cliente.get("/adm").text

    assert 'class="arco"' not in html
    assert "sem dados ainda" in html


# ------------------------------- alertas e filtros do histórico ------------

def _falhou(quantas: int, slug: str = "jadlog") -> None:
    for _ in range(quantas):
        cid = adm.banco.salvar_cotacao("enzo", CARGA)
        adm.banco.salvar_resultado(cid, slug, status="erro",
                                   erro="Login recusado pelo painel.")


def test_falha_seguida_vira_alerta_no_topo(cliente):
    """A parte mais valiosa da tela, e a razão de o painel existir: a Jadlog
    falhou no login em 5 tentativas seguidas e ninguém notou até um vendedor
    reclamar, quase um dia depois."""
    _falhou(3)

    html = cliente.get("/adm").text

    assert "Precisa de atenção" in html
    assert "Jadlog Entregas falhou nas últimas 3 tentativas." in html


def test_transportadora_fora_da_automacao_nao_gera_alerta(cliente):
    """A Della Volpe saiu de AUTOMATICAS em 31/08/2026 (ver web/app.py) e
    nunca mais vai gravar um resultado novo — sem este filtro, as falhas de
    antes da saída ficariam presas na tela até sair da janela de `dias`, sem
    ninguém poder "resolver" o alerta."""
    _falhou(3, slug="dellavolpe")

    assert "Precisa de atenção" not in cliente.get("/adm").text


def test_sem_falha_seguida_o_cartao_de_alerta_nem_aparece(cliente):
    """Um cartão "nenhum alerta" fixo no topo treina o olho a pular a região
    — e aí ele pula também no dia em que o alerta está lá."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("50"))

    assert "Precisa de atenção" not in cliente.get("/adm").text


def test_o_filtro_por_vendedor_volta_ao_banco(cliente):
    """A busca do topo filtra o que está NA PÁGINA; o filtro volta ao banco,
    e por isso enxerga além das 200 linhas que a página carregou."""
    adm.banco.salvar_cotacao("leandro", {**CARGA, "material": "SO DO LEANDRO"})
    adm.banco.salvar_cotacao("enzo", {**CARGA, "material": "SO DO ENZO"})

    html = cliente.get("/adm?dias=30&quem=leandro").text

    assert "SO DO LEANDRO" in html
    assert "SO DO ENZO" not in html


def test_o_filtro_de_falhas_esconde_o_que_deu_certo(cliente):
    """O filtro que o Enzo vai usar mais: mostra só o que deu problema."""
    boa = adm.banco.salvar_cotacao("enzo", {**CARGA, "material": "DEU CERTO"})
    adm.banco.salvar_resultado(boa, "camilo", status="cotado",
                               valor=Decimal("10"))
    ruim = adm.banco.salvar_cotacao("enzo", {**CARGA, "material": "DEU RUIM"})
    adm.banco.salvar_resultado(ruim, "jadlog", status="erro", erro="timeout")

    html = cliente.get("/adm?dias=30&falhas=1").text

    assert "DEU RUIM" in html
    assert "DEU CERTO" not in html


def test_trocar_o_periodo_nao_joga_fora_o_filtro(cliente):
    """Montados em separado, clicar em "7 dias" jogava fora o vendedor
    escolhido sem avisar — e a tela passava a responder outra pergunta com a
    mesma cara."""
    adm.banco.salvar_cotacao("leandro", CARGA)

    html = cliente.get("/adm?dias=30&quem=leandro&falhas=1").text

    assert "/adm?dias=7&amp;quem=leandro&amp;falhas=1" in html


def test_vendedor_que_nao_existe_devolve_lista_vazia(cliente):
    """Resposta honesta. Cair em "todos" mostraria a empresa inteira para
    quem pediu uma pessoa."""
    adm.banco.salvar_cotacao("enzo", CARGA)

    html = cliente.get("/adm?dias=30&quem=ninguem").text

    assert "Nenhuma cotação no período." in html


def test_nome_de_vendedor_com_aspas_nao_escapa_no_link_do_filtro(cliente):
    """O login é placeholder: digitou um nome, entrou. Esse nome vira URL na
    pastilha do filtro."""
    adm.banco.salvar_cotacao('" onmouseover="alert(1)', CARGA)

    html = cliente.get("/adm").text

    assert 'onmouseover="alert' not in html


# ------------------------------------------------------- painel ao vivo
#
# O painel se atualiza sozinho quando entra cotação ou chega resposta. Duas
# metades, e as duas quebram feio sozinhas: não perceber a mudança deixa quem
# está olhando sem a resposta que já está no banco; perceber mudança onde não
# houve refaz a tabela debaixo do cursor de quem está lendo.

def test_ao_vivo_devolve_204_quando_nada_mudou(cliente):
    """O caso comum, e o que torna o pulso de 5s barato: o servidor nem monta
    HTML, e a tela não é tocada."""
    versao = cliente.get("/adm/agora").json()["v"]

    assert cliente.get(f"/adm/agora?v={versao}").status_code == 204


def test_ao_vivo_mostra_cotacao_que_entrou_depois(cliente):
    """É o pedido inteiro: a cotação nova aparece sem ninguém apertar F5."""
    versao = cliente.get("/adm/agora").json()["v"]
    cid = adm.banco.salvar_cotacao("leandro", CARGA)

    dados = cliente.get(f"/adm/agora?v={versao}").json()

    assert dados["v"] != versao
    assert "leandro" in dados["tabela"]
    assert f"#{cid}" in dados["tabela"] or str(cid) in dados["tabela"]


def test_ao_vivo_mostra_a_resposta_que_chegou(cliente):
    """A outra metade do pedido: a cotação já está na tela, e o preço da
    transportadora aparece nela conforme chega."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    versao = cliente.get("/adm/agora").json()["v"]

    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("321,00".replace(",", ".")))
    dados = cliente.get(f"/adm/agora?v={versao}").json()

    assert dados["v"] != versao
    assert "321,00" in dados["tabela"]


def test_ao_vivo_respeita_o_filtro_da_tela(cliente):
    """A tabela depende de dias/quem/falhas. Sem repassar o filtro, quem
    estivesse vendo só as do Leandro receberia a empresa inteira de volta na
    primeira cotação que entrasse."""
    adm.banco.salvar_cotacao("leandro", CARGA)
    adm.banco.salvar_cotacao("enzo", CARGA)

    tabela = cliente.get("/adm/agora?quem=leandro").json()["tabela"]

    assert "leandro" in tabela
    assert "enzo" not in tabela


def test_ao_vivo_tambem_exige_cookie(monkeypatch, tmp_path):
    """O fragmento tem os mesmos dados da tela: não pode ser porta dos
    fundos."""
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))

    resposta = TestClient(app_web.app).get("/adm/agora",
                                           follow_redirects=False)

    assert resposta.status_code == 303


def test_a_tela_leva_a_versao_para_o_navegador(cliente):
    """Sem a versão no HTML, o primeiro pulso viria com `v` vazio e a tela se
    redesenharia uma vez por nada, cinco segundos depois de abrir."""
    html = cliente.get("/adm").text
    versao = cliente.get("/adm/agora").json()["v"]

    assert f'data-versao="{versao}"' in html


# --------------------------------------------------- uma cotação ao vivo

def test_ao_vivo_da_cotacao_mostra_a_resposta_chegando(cliente):
    """A tela em que se fica olhando: a Della Volpe leva ~110s, e o preço
    dela tem que aparecer sem recarregar."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    versao = cliente.get(f"/adm/cotacao/{cid}/agora").json()["v"]

    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("456.78"))
    dados = cliente.get(f"/adm/cotacao/{cid}/agora?v={versao}").json()

    assert dados["v"] != versao
    assert "456,78" in dados["respostas"]
    assert dados["nota"] == "1 de 1 com preço"


def test_ao_vivo_da_cotacao_devolve_204_quando_nada_mudou(cliente):
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    versao = cliente.get(f"/adm/cotacao/{cid}/agora").json()["v"]

    assert cliente.get(
        f"/adm/cotacao/{cid}/agora?v={versao}").status_code == 204


def test_ao_vivo_da_cotacao_nao_reage_a_outra_cotacao(cliente):
    """Sem isso, a tela aberta numa cotação se redesenharia inteira toda vez
    que qualquer vendedor da empresa cotasse."""
    minha = adm.banco.salvar_cotacao("enzo", CARGA)
    outra = adm.banco.salvar_cotacao("leandro", CARGA)
    versao = cliente.get(f"/adm/cotacao/{minha}/agora").json()["v"]

    adm.banco.salvar_resultado(outra, "jadlog", status="cotado",
                               valor=Decimal("10.00"))

    assert cliente.get(
        f"/adm/cotacao/{minha}/agora?v={versao}").status_code == 204


def test_ao_vivo_da_cotacao_inexistente_e_404_seco(cliente):
    """Quem recebe isto é o JavaScript, não uma pessoa: 404 sem o casco do
    painel. A página inteira continua sendo devolvida por /adm/cotacao/{id},
    que é onde alguém chega por um link velho."""
    resposta = cliente.get("/adm/cotacao/9999/agora")

    assert resposta.status_code == 404
    assert "<html" not in resposta.text.lower()


def test_ao_vivo_da_cotacao_tambem_exige_cookie(monkeypatch, tmp_path):
    monkeypatch.setenv("COTAFRETE_ADM_SENHA", SENHA)
    monkeypatch.setattr(adm, "banco", Banco(tmp_path / "t.db"))

    resposta = TestClient(app_web.app).get("/adm/cotacao/1/agora",
                                           follow_redirects=False)

    assert resposta.status_code == 303


def test_a_tela_da_cotacao_leva_numero_e_versao(cliente):
    """O JavaScript lê os dois do DOM em vez de recebê-los interpolados: id de
    cotação dentro de f-string com chave de JavaScript é a receita do bug que
    o SCRIPT deste arquivo evita ficando fora do f-string."""
    cid = adm.banco.salvar_cotacao("enzo", CARGA)
    adm.banco.salvar_resultado(cid, "camilo", status="cotado",
                               valor=Decimal("99.90"))
    versao = cliente.get(f"/adm/cotacao/{cid}/agora").json()["v"]

    html = cliente.get(f"/adm/cotacao/{cid}").text

    assert f'data-cotacao="{cid}"' in html
    assert f'data-versao="{versao}"' in html


def test_o_alvo_da_troca_existe_mesmo_sem_cotacao_nenhuma(cliente):
    """O bug que o banco recém-criado revelou: com o `id` na tabela, ele sumia
    junto com ela no período vazio. A primeira cotação do dia não tinha onde
    entrar, e a tela ficava em "Nenhuma cotação no período" até alguém
    recarregar — justo no caso em que se está esperando a primeira."""
    vazio = cliente.get("/adm/agora").json()["tabela"]
    assert 'id="tabela"' in vazio

    adm.banco.salvar_cotacao("enzo", CARGA)

    assert 'id="tabela"' in cliente.get("/adm/agora").json()["tabela"]
    assert 'id="tabela"' in cliente.get("/adm").text


def test_a_contagem_filtrada_do_dia_sai_acentuada():
    """A busca reescreve a contagem do dia em JavaScript, fora do alcance de
    qualquer template. Uma reescrita do SCRIPT ja trocou "cotacoes" por
    "cotacoes" sem acento e ninguem viu ate a tela estar no ar: e texto que so
    aparece depois de alguem digitar na busca."""
    assert "' cotação'" in adm.SCRIPT
    assert "' cotações'" in adm.SCRIPT
