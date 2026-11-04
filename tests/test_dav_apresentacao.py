"""Aceite do modelo 02 e projeções de orientação por perfil."""
from datetime import datetime, timezone
from html import unescape
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from tests.test_dav_tela import app_web, cli  # noqa: F401


def test_barra_compacta_preserva_e_remove_filtros():
    from web.dav_ui import filtros_dav
    filtros = dict(dias=7, estado="erro", vendedor="Ana & Bia", busca='<cliente>', categoria="endereco", pagina=3)
    html = filtros_dav({"periodo": {"dias": 7}, "vendedores": ["Ana & Bia"]}, filtros,
                       administrador=True, base="/adm/dav/erros")
    s = BeautifulSoup(html, "html.parser")
    assert s.select_one('.dav-barra input[name="busca"]')["value"] == "<cliente>"
    assert not s.select("select")
    links = s.select('.dav-filtros-ativos a[aria-label="Remover filtro Resultado"]')
    assert len(links) == 1
    q = parse_qs(urlsplit(unescape(links[0]["href"])).query)
    assert "estado" not in q and q["dias"] == ["7"] and q["vendedor"] == ["Ana & Bia"]
    assert q["categoria"] == ["endereco"] and q["pagina"] == ["1"]
    assert "<cliente>" not in html


def test_vendedor_modelo_b_envio_no_banner_e_quadro(cli):
    s = BeautifulSoup(cli.get("/dav").text, "html.parser")
    assert "Novo orçamento DAV" in s.get_text()
    assert s.select_one('.dav-ola form input[name="planilha"][accept=".xlsx"]')
    assert s.select_one('.dav-ola a[href="/dav/modelo"]')
    assert [h.get_text(" ", strip=True).rsplit(" ", 1)[0] for h in s.select('#dav-quadro .dav-col h2')] == [
        "Precisa de você", "Em andamento", "Prontos"]
    assert s.select_one('#historico #dav-historico')
    assert not s.select('[name="vendedor"]')
    assert 'Sem surpresas' not in s.get_text() and 'com clareza' not in s.get_text()
    assert s.select_one('.dav-barra')


def test_tempo_dav_usa_datas_reais_sem_futuro():
    from web.dav_ui import tempo_dav
    agora = datetime(2026, 11, 3, 15, 10, tzinfo=timezone.utc)
    assert '10 min' in tempo_dav(dict(estado="fila", criado_em="2026-11-03T12:00:00"), instante=agora)
    assert tempo_dav(dict(estado="fila", criado_em="invalida"), instante=agora) == ""
    assert tempo_dav(dict(estado="fila", criado_em="2026-11-04T12:00:00"), instante=agora) == ""
    assert '2 min' in tempo_dav(dict(estado="pronto", iniciado_em="2026-11-03T12:00:00",
                                   terminado_em="2026-11-03T12:02:00"), instante=agora)


def test_detalhe_orienta_planilha_e_copia_tem_contexto(cli, app_web):
    i = app_web.banco.dav_rejeitar("ana", "a.xlsx", ["Item 3: quantidade deve ser maior que zero"])
    s = BeautifulSoup(cli.get(f"/dav/{i}").text, "html.parser")
    assert s.select_one('.dav-orientacao')
    assert 'B4' in s.select_one('.dav-orientacao').get_text()
    assert 'Quantidade do item 3' in s.select_one('.dav-orientacao').get_text()
    assert 'maior que zero' in s.select_one('.dav-orientacao').get_text()
    copia = s.select_one('#dav-diagnostico').get_text()
    assert f'Envio #{i}' in copia and 'Horário' in copia and 'Etapa' in copia


def test_falha_automacao_nao_pede_planilha_corrigida(cli, app_web):
    i = app_web.banco.dav_criar('ana', 'a.xlsx', 'x', 'Cliente A')
    app_web.banco.dav_atualizar(i, estado='erro', erro='Item 1: tela ficou com qtd/preço diferente do esperado')
    s = BeautifulSoup(cli.get(f'/dav/{i}').text, 'html.parser')
    assert 'Enzo, Allan ou Lucas' in s.get_text()
    assert not s.select(f'a[href="/dav?origem={i}"]')


def test_quadro_vendedor_separa_situacoes_e_atualiza(cli, app_web):
    b = app_web.banco
    falha = b.dav_criar('ana', 'a.xlsx', 'a', 'Cliente Falha')
    b.dav_atualizar(falha, estado='erro', erro='Local de entrega não encontrado')
    robo = b.dav_criar('ana', 'b.xlsx', 'b', 'Cliente Robo')
    b.dav_atualizar(robo, estado='erro', erro='Item 1: tela ficou com qtd/preço diferente do esperado')
    fila = b.dav_criar('ana', 'c.xlsx', 'c', 'Cliente Fila')
    b.dav_atualizar(fila, estado='fila')
    pronto = b.dav_criar('ana', 'd.xlsx', 'd', 'Cliente Pronto')
    b.dav_atualizar(pronto, estado='pronto', numero='777')
    b.dav_criar('bia', 'e.xlsx', 'e', 'Cliente da Bia')
    s = BeautifulSoup(cli.get('/dav').text, 'html.parser')
    precisa, andamento, prontos = s.select('#dav-quadro .dav-col')
    assert 'Cliente Falha' in precisa.get_text() and 'Cliente Robo' in precisa.get_text()
    assert precisa.select_one(f'a[href="/dav?origem={falha}"]')  # planilha × cadastro: o vendedor corrige
    assert not precisa.select(f'a[href="/dav?origem={robo}"]')  # falha do robô: não pede planilha nova
    assert 'Cliente Fila' in andamento.get_text() and '777' in prontos.get_text()
    assert 'Cliente da Bia' not in s.select_one('#dav-quadro').get_text()
    assert '2 precisam de você' in s.select_one('#dav-resumo-dia').get_text()
    fragmentos = cli.get('/dav/agora').json()['fragmentos']
    assert {'dav-quadro', 'dav-resumo-dia', 'dav-historico'} <= set(fragmentos)
