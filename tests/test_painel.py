"""As contas do dashboard. Camada PURA: recebe conexão, devolve dicionário.

Nenhum HTML mora aqui, pelo mesmo motivo de carriers/*/mapping.py: o risco
está na conta, e conta se testa sem navegador.

Os números da tela são a razão de a tela existir. Um aproveitamento errado
manda o Enzo cobrar a transportadora errada."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from core.banco import Banco
from core import painel

CARGA = {"cep_origem": "29105770", "cep_destino": "01310100",
         "cidade_origem": "Vila Velha", "cidade_destino": "São Paulo",
         "peso_kg": "10", "quantidade": 1, "comprimento_cm": 30,
         "largura_cm": 30, "altura_cm": 30, "valor_nf": "1000",
         "material": "PLACA DE VIDEO"}


@pytest.fixture
def db(tmp_path):
    return Banco(tmp_path / "painel.db")


def test_classifica_cada_status_como_a_spec_manda():
    assert painel.categoria("cotado") == "sucesso"
    assert painel.categoria("aguardando_retorno") == "sucesso"
    assert painel.categoria("recusado") == "recusa"
    assert painel.categoria("erro") == "falha"
    assert painel.categoria("intervencao_necessaria") == "falha"
    assert painel.categoria("interrompido") == "nossa"
    assert painel.categoria("coisa_nova") == "inesperado"


def test_aguardando_retorno_e_sucesso_e_nao_falha():
    """A Della Volpe recebeu e o preço vem por e-mail. Contar como falha
    jogaria ela para o vermelho todo dia, sem nada de errado."""
    assert painel.categoria("aguardando_retorno") == "sucesso"


def test_interrompido_fica_fora_do_aproveitamento(db):
    """É o servidor reiniciando no meio — coisa nossa. Descontar isso da
    transportadora seria puni-la por um restart que ela não causou."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado")
    db.salvar_resultado(cid, "jadlog", status="interrompido")

    with db._conectar() as con:
        linhas = {l["transportadora"]: l
                  for l in painel.saude_das_transportadoras(con, dias=30)}

    assert linhas["camilo"]["aproveitamento"] == 1.0
    assert linhas["jadlog"]["nossa"] == 1
    assert linhas["jadlog"]["aproveitamento"] is None, \
        "sem nada no denominador, aproveitamento é desconhecido, não zero"


def test_desconhecido_vai_para_o_fim_da_ordenacao(db):
    """None (sem dados) não pode ordenar como "pior que 0%": senão uma
    transportadora sem nenhuma cotação no período aparece no topo da lista
    dos piores, à frente até de quem errou todas."""
    sempre_erra = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(sempre_erra, "camilo", status="erro")
    sempre_acerta = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(sempre_acerta, "jadlog", status="cotado")
    sem_dados = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(sem_dados, "generoso", status="interrompido")

    with db._conectar() as con:
        ordem = [l["transportadora"]
                 for l in painel.saude_das_transportadoras(con, dias=30)]

    assert ordem == ["camilo", "jadlog", "generoso"]


def test_aguardando_retorno_conta_como_sucesso_na_coluna(db):
    """A regra "aguardando_retorno é sucesso" só estava presa dentro de
    categoria(). Esta prova leva ela até a coluna que a tela lê de verdade,
    num banco de verdade."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "dellavolpe", status="aguardando_retorno")

    with db._conectar() as con:
        linha = painel.saude_das_transportadoras(con, dias=30)[0]

    assert linha["sucesso"] == 1
    assert linha["aproveitamento"] == 1.0


def test_aproveitamento_conta_recusa_no_denominador(db):
    """Recusa não é defeito, mas também não é preço: entra na conta."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado")
    cid2 = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid2, "camilo", status="recusado")

    with db._conectar() as con:
        linha = painel.saude_das_transportadoras(con, dias=30)[0]

    assert linha["sucesso"] == 1 and linha["recusa"] == 1
    assert linha["aproveitamento"] == 0.5


def test_resumo_conta_cotacao_que_ficou_sem_nenhum_preco(db):
    """A métrica que mais importa: o vendedor ficou na mão."""
    boa = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(boa, "camilo", status="cotado")
    ruim = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(ruim, "camilo", status="erro")
    db.salvar_resultado(ruim, "jadlog", status="recusado")

    with db._conectar() as con:
        r = painel.resumo_do_dia(con)

    assert r["cotacoes"] == 2
    assert r["com_preco"] == 1
    assert r["sem_nenhum_preco"] == 1


def test_banco_vazio_nao_quebra(db):
    """Pasta nova, primeiro dia. A tela precisa abrir mesmo assim."""
    with db._conectar() as con:
        assert painel.saude_das_transportadoras(con, dias=30) == []
        assert painel.resumo_do_dia(con)["cotacoes"] == 0


def test_historico_traz_cotacao_de_todos_os_usuarios(db):
    """É a diferença central em relação ao histórico do vendedor, que só
    mostra as dele. Aqui o adm vê a empresa inteira."""
    a = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(a, "camilo", status="cotado", valor=Decimal("100.00"))
    b = db.salvar_cotacao("leandro", CARGA)
    db.salvar_resultado(b, "camilo", status="cotado", valor=Decimal("90.00"))

    with db._conectar() as con:
        linhas = painel.historico(con)

    assert {l["usuario"] for l in linhas} == {"enzo", "leandro"}


def test_historico_mostra_o_melhor_preco_de_cada_cotacao(db):
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado", valor=Decimal("150.00"))
    db.salvar_resultado(cid, "generoso", status="cotado", valor=Decimal("90.50"))

    with db._conectar() as con:
        assert painel.historico(con)[0]["melhor_preco"] == Decimal("90.50")


def test_historico_sem_preco_nenhum_devolve_none_e_nao_zero(db):
    """Zero seria um preço. None é "não teve preço" — coisas diferentes."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="erro", erro="deu ruim")

    with db._conectar() as con:
        assert painel.historico(con)[0]["melhor_preco"] is None


def test_historico_filtra_por_usuario(db):
    db.salvar_cotacao("enzo", CARGA)
    db.salvar_cotacao("leandro", CARGA)

    with db._conectar() as con:
        linhas = painel.historico(con, usuario="leandro")

    assert [l["usuario"] for l in linhas] == ["leandro"]


def test_historico_filtra_so_as_que_tiveram_falha(db):
    """O filtro que o Enzo vai usar mais: mostra só o que deu problema."""
    boa = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(boa, "camilo", status="cotado", valor=Decimal("10.00"))
    ruim = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(ruim, "jadlog", status="erro", erro="timeout")

    with db._conectar() as con:
        linhas = painel.historico(con, so_com_falha=True)

    assert [l["id"] for l in linhas] == [ruim]


def test_historico_vem_do_mais_novo_para_o_mais_velho(db):
    primeiro = db.salvar_cotacao("enzo", CARGA)
    segundo = db.salvar_cotacao("enzo", CARGA)

    with db._conectar() as con:
        assert [l["id"] for l in painel.historico(con)] == [segundo, primeiro]


def test_historico_so_com_falha_nao_perde_falha_antiga_pro_limite(db):
    """O filtro tem que entrar ANTES do LIMIT. Aplicado depois, em Python, o
    SQL corta nas `limite` mais recentes e só então descarta as sem falha —
    com `limite=2` e 3 cotações, a mais antiga (a única com falha) seria
    cortada antes de chegar a ser considerada."""
    antiga_com_falha = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(antiga_com_falha, "jadlog", status="erro", erro="timeout")
    db.salvar_cotacao("enzo", CARGA)
    db.salvar_cotacao("enzo", CARGA)

    with db._conectar() as con:
        linhas = painel.historico(con, so_com_falha=True, limite=2)

    assert [l["id"] for l in linhas] == [antiga_com_falha]


# ------------------------------- o que o gráfico do painel consome --------

def _backdatar(db, cotacao_id: int, quando: datetime) -> None:
    """`salvar_cotacao` sempre carimba agora. Para testar janela de tempo, a
    data precisa ser empurrada na marra."""
    with db._conectar() as con:
        con.execute("UPDATE cotacao SET criado_em = ? WHERE id = ?",
                    (quando.isoformat(timespec="seconds"), cotacao_id))


def test_unidade_muda_com_o_tamanho_da_janela():
    """Não é escolha estética: 3650 dias em barras de um dia dariam 3650
    barras de meio pixel, e 24 horas numa barra só não é gráfico nenhum."""
    assert painel.unidade_do_periodo(1) == "hora"
    assert painel.unidade_do_periodo(7) == "dia"
    assert painel.unidade_do_periodo(30) == "dia"
    assert painel.unidade_do_periodo(3650) == "mes"


def test_serie_de_sete_dias_traz_sete_baldes(db):
    with db._conectar() as con:
        serie = painel.serie_por_periodo(con, dias=7)

    assert serie["unidade"] == "dia"
    assert len(serie["pontos"]) == 7


def test_serie_de_vinte_e_quatro_horas_traz_vinte_e_quatro_baldes(db):
    with db._conectar() as con:
        serie = painel.serie_por_periodo(con, dias=1)

    assert serie["unidade"] == "hora"
    assert len(serie["pontos"]) == 24


def test_dia_sem_cotacao_aparece_zerado_e_nao_some(db):
    """Balde vazio é DADO: um dia sem nenhuma cotação é notícia. Sem ele, dois
    dias distantes ficariam colados e o gráfico mostraria um movimento
    contínuo que nunca existiu."""
    antiga = db.salvar_cotacao("enzo", CARGA)
    _backdatar(db, antiga, datetime.now() - timedelta(days=3))
    db.salvar_cotacao("enzo", CARGA)

    with db._conectar() as con:
        pontos = painel.serie_por_periodo(con, dias=7)["pontos"]

    assert [p["cotacoes"] for p in pontos] == [0, 0, 0, 1, 0, 0, 1]


def test_a_janela_de_dias_comeca_na_meia_noite(db):
    """Alinhar o primeiro balde não é detalhe: começando as 14h37, ele
    cobriria 23 minutos e apareceria como uma queda que nunca aconteceu."""
    with db._conectar() as con:
        pontos = painel.serie_por_periodo(con, dias=7)["pontos"]

    esperado = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    assert pontos[0]["chave"] == esperado
    assert pontos[-1]["chave"] == datetime.now().strftime("%Y-%m-%d")


def test_com_preco_conta_so_quem_virou_valor(db):
    """Mesmo critério de `resumo_do_dia`: status "cotado". Se o gráfico
    contasse `aguardando_retorno` também, ele e o cartão do topo discordariam
    na mesma tela."""
    com = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(com, "camilo", status="cotado", valor=Decimal("10"))
    sem = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(sem, "jadlog", status="recusado", erro="peso")
    esperando = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(esperando, "dellavolpe", status="aguardando_retorno")

    with db._conectar() as con:
        hoje = painel.serie_por_periodo(con, dias=7)["pontos"][-1]

    assert hoje["cotacoes"] == 3
    assert hoje["com_preco"] == 1


def test_duas_transportadoras_com_preco_contam_uma_cotacao_so(db):
    """A linha do gráfico é "cotações que viraram preço", não "preços". Sem
    o DISTINCT ela passaria por cima da barra de cotações."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado", valor=Decimal("10"))
    db.salvar_resultado(cid, "jadlog", status="cotado", valor=Decimal("20"))

    with db._conectar() as con:
        hoje = painel.serie_por_periodo(con, dias=7)["pontos"][-1]

    assert hoje["cotacoes"] == 1
    assert hoje["com_preco"] == 1


def test_periodo_tudo_comeca_na_cotacao_mais_antiga_e_nao_em_dez_anos(db):
    """3650 dias em baldes de mês dariam 120 barras, quase todas vazias, numa
    empresa que começou a usar o sistema mês passado."""
    antiga = db.salvar_cotacao("enzo", CARGA)
    _backdatar(db, antiga, datetime.now() - timedelta(days=70))

    with db._conectar() as con:
        serie = painel.serie_por_periodo(con, dias=3650)

    assert serie["unidade"] == "mes"
    assert len(serie["pontos"]) <= 4


def test_banco_vazio_ainda_desenha_a_janela(db):
    """Pasta nova, primeiro dia. O gráfico mostra a semana zerada, e não um
    vazio que pareceria defeito."""
    with db._conectar() as con:
        pontos = painel.serie_por_periodo(con, dias=7)["pontos"]

    assert len(pontos) == 7
    assert all(p["cotacoes"] == 0 for p in pontos)


def test_por_usuario_vem_do_mais_ativo_para_o_menos(db):
    for _ in range(3):
        db.salvar_cotacao("leandro", CARGA)
    db.salvar_cotacao("enzo", CARGA)

    with db._conectar() as con:
        linhas = painel.por_usuario(con, dias=30)

    assert linhas == [{"usuario": "leandro", "cotacoes": 3},
                      {"usuario": "enzo", "cotacoes": 1}]


def test_por_usuario_desempata_por_nome(db):
    """Sem desempate, dois vendedores com a mesma contagem trocam de lugar
    entre dois carregamentos e a lista parece estar mexendo sozinha."""
    db.salvar_cotacao("zeca", CARGA)
    db.salvar_cotacao("ana", CARGA)

    with db._conectar() as con:
        nomes = [l["usuario"] for l in painel.por_usuario(con, dias=30)]

    assert nomes == ["ana", "zeca"]


def test_por_usuario_respeita_a_janela(db):
    velha = db.salvar_cotacao("sumida", CARGA)
    _backdatar(db, velha, datetime.now() - timedelta(days=40))
    db.salvar_cotacao("atual", CARGA)

    with db._conectar() as con:
        nomes = [l["usuario"] for l in painel.por_usuario(con, dias=30)]

    assert nomes == ["atual"]


# ------------------------------- a cotação de qualquer vendedor -----------

def test_cotacao_abre_a_de_outro_usuario(db):
    """A porta do adm. `banco.buscar_cotacao` exige o dono e continua
    exigindo — esta é a OUTRA porta, e é a razão de a tela de detalhe do
    painel existir."""
    cid = db.salvar_cotacao("leandro", CARGA)
    db.salvar_resultado(cid, "camilo", status="cotado",
                        valor=Decimal("123.45"), prazo="3 dias")

    with db._conectar() as con:
        c = painel.cotacao(con, cid)

    assert c["usuario"] == "leandro"
    assert c["resultados"][0]["valor"] == Decimal("123.45")


def test_o_isolamento_do_vendedor_continua_de_pe(db):
    """A porta nova não pode ter afrouxado a antiga: trocar o número na URL
    da tela do VENDEDOR continua não abrindo a cotação alheia."""
    cid = db.salvar_cotacao("leandro", CARGA)

    assert db.buscar_cotacao(cid, "enzo") is None
    assert db.buscar_cotacao(cid, "leandro") is not None


def test_cotacao_que_nao_existe_devolve_none(db):
    with db._conectar() as con:
        assert painel.cotacao(con, 4242) is None


def test_cotacao_devolve_dinheiro_como_decimal(db):
    """`peso_kg` e `valor_nf` são TEXTO no banco, e `moeda()` recebendo texto
    levanta ValueError no meio do render — a tela inteira cairia por causa da
    formatação de um número."""
    cid = db.salvar_cotacao("enzo", CARGA)

    with db._conectar() as con:
        c = painel.cotacao(con, cid)

    assert c["valor_nf"] == Decimal("1000")
    assert c["peso_kg"] == Decimal("10")


def test_cotacao_traz_os_whatsapps_abertos(db):
    """Metade da explicação de uma cotação sem preço é se o vendedor chegou a
    acionar as manuais."""
    cid = db.salvar_cotacao("enzo", CARGA)
    db.marcar_whatsapp_aberto(cid, "movvi", "enzo")

    with db._conectar() as con:
        c = painel.cotacao(con, cid)

    assert [w["transportadora"] for w in c["whatsapp"]] == ["movvi"]


# ------------------------------------------- alerta de falha seguida ------

def _falhas(db, quantas: int, slug: str = "jadlog") -> list[int]:
    return [_com(db, slug, "erro") for _ in range(quantas)]


def _com(db, slug: str, status: str, erro: str = "timeout") -> int:
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, slug, status=status, erro=erro)
    return cid


def test_tres_falhas_seguidas_viram_alerta(db):
    """Duas acontecem por acaso; três seguidas, na série medida até aqui,
    sempre foram problema de verdade."""
    _falhas(db, 3)

    with db._conectar() as con:
        alertas = painel.falhas_seguidas(con, dias=30)

    assert [a["transportadora"] for a in alertas] == ["jadlog"]
    assert alertas[0]["quantas"] == 3


def test_duas_falhas_seguidas_nao_alertam(db):
    _falhas(db, 2)

    with db._conectar() as con:
        assert painel.falhas_seguidas(con, dias=30) == []


def test_sucesso_depois_das_falhas_zera_a_contagem(db):
    """O alerta é sobre AGORA. Se a última tentativa deu certo, a
    transportadora voltou — e um alerta que não some deixa de ser lido."""
    _falhas(db, 4)
    _com(db, "jadlog", "cotado")

    with db._conectar() as con:
        assert painel.falhas_seguidas(con, dias=30) == []


def test_recusa_tambem_zera_a_contagem(db):
    """Recusa é a transportadora respondendo com o motivo dela: o site está
    de pé, que é o que este alerta pergunta."""
    _falhas(db, 3)
    _com(db, "jadlog", "recusado", "peso acima de 120 kg")

    with db._conectar() as con:
        assert painel.falhas_seguidas(con, dias=30) == []


def test_interrompida_no_meio_nao_zera_nem_conta(db):
    """`interrompido` é o servidor reiniciando: não acusa a transportadora
    nem prova que ela voltou. Sem pular, um restart nosso apagaria o alerta
    de uma Jadlog que continua fora do ar."""
    _falhas(db, 2)
    _com(db, "jadlog", "interrompido")
    _falhas(db, 1)

    with db._conectar() as con:
        alertas = painel.falhas_seguidas(con, dias=30)

    assert alertas[0]["quantas"] == 3


def test_o_alerta_traz_os_numeros_das_cotacoes_e_o_ultimo_erro(db):
    """Sem os números, o alerta manda procurar — e procurar dá trabalho o
    bastante para ele virar decoração."""
    ids = _falhas(db, 3)
    ultima = _com(db, "jadlog", "erro", "senha recusada")

    with db._conectar() as con:
        alerta = painel.falhas_seguidas(con, dias=30)[0]

    assert alerta["ids"][0] == ultima
    assert set(alerta["ids"]) == {*ids, ultima}
    assert alerta["erro"] == "senha recusada"


def test_alertas_vem_do_pior_para_o_menos_pior(db):
    _falhas(db, 5, "jadlog")
    _falhas(db, 3, "generoso")

    with db._conectar() as con:
        alertas = painel.falhas_seguidas(con, dias=30)

    assert [a["transportadora"] for a in alertas] == ["jadlog", "generoso"]


def test_falha_fora_da_janela_nao_entra_na_contagem(db):
    """Recortar por período só pode DIMINUIR a contagem: o que fica de fora é
    mais velho que a falha mais antiga contada."""
    velhas = _falhas(db, 3)
    for cid in velhas:
        _backdatar(db, cid, datetime.now() - timedelta(days=40))
    _falhas(db, 3)

    with db._conectar() as con:
        assert painel.falhas_seguidas(con, dias=30)[0]["quantas"] == 3


# ------------------------------------------------------ rotas mais cotadas

def test_rotas_agrupa_pela_cidade_e_conta(db):
    for _ in range(3):
        db.salvar_cotacao("enzo", CARGA)
    db.salvar_cotacao("enzo", {**CARGA, "cidade_destino": "Curitiba"})

    with db._conectar() as con:
        linhas = painel.rotas(con, dias=30)

    assert linhas[0] == {"rota": "Vila Velha -> São Paulo", "cotacoes": 3}
    assert linhas[1]["cotacoes"] == 1


def test_rota_sem_cidade_cai_no_cep_e_nao_num_grupo_vazio(db):
    """Cidade em branco não é NULL para o SQLite: sem o NULLIF, as cotações
    anteriores à busca por CEP viravam um grupo " -> " sem nome nenhum."""
    db.salvar_cotacao("enzo", {**CARGA, "cidade_origem": "",
                               "cidade_destino": ""})

    with db._conectar() as con:
        assert painel.rotas(con, dias=30)[0]["rota"] == \
            "29105770 -> 01310100"


# ------------------------------------------------------ tempo de resposta

def test_duracao_conta_os_segundos_entre_os_dois_carimbos():
    assert painel.duracao_s("2026-09-02T14:00:00",
                            "2026-09-02T14:00:25") == 25


def test_duracao_sem_hora_de_resposta_e_desconhecida():
    """`respondido_em` é NULL nas linhas anteriores a 28/08/2026. Zero ali
    inventaria a transportadora mais rápida do sistema."""
    assert painel.duracao_s("2026-09-02T14:00:00", None) is None
    assert painel.duracao_s("data torta", "2026-09-02T14:00:25") is None


def test_duracao_negativa_tambem_e_desconhecida():
    """Relógio de máquina que andou para trás é dado ruim, e "-3 s" num
    quadro de instrumentos engana mais do que a lacuna."""
    assert painel.duracao_s("2026-09-02T14:00:25",
                            "2026-09-02T14:00:00") is None
