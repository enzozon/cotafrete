"""Histórico de cotações, separado por usuário.

O que precisa ser verdade: a cotação de um usuário não aparece para outro, e
uma cotação guarda TODOS os resultados (uma linha por transportadora), para
dar para reabrir e comparar depois.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core import banco


@pytest.fixture
def db(tmp_path):
    return banco.Banco(tmp_path / "teste.db")


def _carga(**over):
    base = dict(
        cep_origem="09895-003", cep_destino="29105-770",
        cidade_origem="São Bernardo do Campo", uf_origem="SP",
        cidade_destino="Vila Velha", uf_destino="ES",
        peso_kg=Decimal("1"), quantidade=1,
        comprimento_cm=30, largura_cm=30, altura_cm=30,
        valor_nf=Decimal("568.77"), material="LUVA DE BOMBEIRO",
    )
    base.update(over)
    return base


# ------------------------------------------------------- separação por usuário
def test_cotacao_de_um_usuario_nao_aparece_para_outro(db):
    """A regra que o Enzo pediu: cada um vê as suas."""
    db.salvar_cotacao("enzo", _carga())
    db.salvar_cotacao("maria", _carga(material="Parafusos"))

    do_enzo = db.listar_cotacoes("enzo")
    da_maria = db.listar_cotacoes("maria")

    assert len(do_enzo) == 1
    assert len(da_maria) == 1
    assert do_enzo[0]["material"] == "LUVA DE BOMBEIRO"
    assert da_maria[0]["material"] == "Parafusos"


def test_usuario_sem_cotacao_ve_lista_vazia(db):
    assert db.listar_cotacoes("ninguem") == []


def test_cotacao_de_outro_usuario_nao_abre_pelo_id(db):
    """Sem isto, trocar o número na URL daria acesso à cotação alheia."""
    id_enzo = db.salvar_cotacao("enzo", _carga())

    assert db.buscar_cotacao(id_enzo, "enzo") is not None
    assert db.buscar_cotacao(id_enzo, "maria") is None


# ------------------------------------------------------ resultados por carrier
def test_uma_cotacao_guarda_varios_resultados(db):
    """É o ponto do histórico: reabrir e ver o preço de cada transportadora
    lado a lado, sem precisar cotar de novo."""
    cid = db.salvar_cotacao("enzo", _carga())
    db.salvar_resultado(cid, "camilo", status="cotado",
                        valor=Decimal("69.91"), protocolo="2799505")
    db.salvar_resultado(cid, "jadlog", status="cotado",
                        valor=Decimal("33.35"))

    achado = db.buscar_cotacao(cid, "enzo")
    por_nome = {r["transportadora"]: r for r in achado["resultados"]}

    assert por_nome["camilo"]["valor"] == Decimal("69.91")
    assert por_nome["camilo"]["protocolo"] == "2799505"
    assert por_nome["jadlog"]["valor"] == Decimal("33.35")


def test_resultado_com_erro_e_guardado_tambem(db):
    """Sumir com quem falhou esconde informação: o histórico tem que mostrar
    que a transportadora foi tentada e não respondeu."""
    cid = db.salvar_cotacao("enzo", _carga())
    db.salvar_resultado(cid, "generoso", status="erro",
                        erro="Timeout ao abrir a etapa 3")

    r = db.buscar_cotacao(cid, "enzo")["resultados"][0]
    assert r["status"] == "erro"
    assert r["valor"] is None
    assert "Timeout" in r["erro"]


def test_valor_volta_como_decimal_nao_float(db):
    """Dinheiro em float acumula erro de arredondamento. O banco guarda
    string e devolve Decimal."""
    cid = db.salvar_cotacao("enzo", _carga())
    db.salvar_resultado(cid, "camilo", status="cotado",
                        valor=Decimal("1234.56"))

    valor = db.buscar_cotacao(cid, "enzo")["resultados"][0]["valor"]
    assert isinstance(valor, Decimal)
    assert valor == Decimal("1234.56")


# --------------------------------------------------------------- listagem
def test_mais_recente_primeiro(db):
    """Quem abre o histórico quer a última cotação, não a primeira."""
    primeira = db.salvar_cotacao("enzo", _carga(material="Antiga"))
    segunda = db.salvar_cotacao("enzo", _carga(material="Nova"))

    ids = [c["id"] for c in db.listar_cotacoes("enzo")]
    assert ids == [segunda, primeira]


def test_listagem_traz_o_menor_preco(db):
    """A lista mostra o melhor preço de cada cotação sem abrir uma por uma."""
    cid = db.salvar_cotacao("enzo", _carga())
    db.salvar_resultado(cid, "camilo", status="cotado", valor=Decimal("69.91"))
    db.salvar_resultado(cid, "jadlog", status="cotado", valor=Decimal("33.35"))
    db.salvar_resultado(cid, "generoso", status="erro", erro="falhou")

    assert db.listar_cotacoes("enzo")[0]["melhor_preco"] == Decimal("33.35")


def test_cotacao_sem_resultado_nao_inventa_preco(db):
    db.salvar_cotacao("enzo", _carga())
    assert db.listar_cotacoes("enzo")[0]["melhor_preco"] is None


def test_banco_antigo_ganha_as_colunas_novas(tmp_path):
    """Banco criado antes de uma coluna existir precisa continuar servindo.

    CREATE TABLE IF NOT EXISTS não altera tabela que já existe: sem migração,
    quem já tinha cotafrete.db recebia "table cotacao has no column named
    cnpj_remetente" e o app parava de salvar. Aconteceu com o Enzo em
    14/08/2026, e só não apareceu nos meus testes porque eu apagava o banco
    entre eles."""
    import sqlite3
    caminho = tmp_path / "antigo.db"
    # esquema velho: sem os campos de CNPJ e razão social
    with sqlite3.connect(caminho) as con:
        con.execute("""CREATE TABLE cotacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT NOT NULL,
            criado_em TEXT NOT NULL, cep_origem TEXT NOT NULL,
            cep_destino TEXT NOT NULL, cidade_origem TEXT, uf_origem TEXT,
            cidade_destino TEXT, uf_destino TEXT, peso_kg TEXT NOT NULL,
            quantidade INTEGER NOT NULL, comprimento_cm INTEGER NOT NULL,
            largura_cm INTEGER NOT NULL, altura_cm INTEGER NOT NULL,
            valor_nf TEXT NOT NULL, material TEXT)""")
        con.execute("INSERT INTO cotacao (usuario, criado_em, cep_origem,"
                    " cep_destino, peso_kg, quantidade, comprimento_cm,"
                    " largura_cm, altura_cm, valor_nf, material)"
                    " VALUES ('enzo','2026-08-01T10:00','09895-003',"
                    "'29105-770','1',1,30,30,30,'100','Antiga')")

    b = banco.Banco(caminho)          # tem que migrar sozinho
    cid = b.salvar_cotacao("enzo", _carga(cnpj_remetente="60.042.686/0001-05",
                                          nome_remetente="HERCULES"))

    achado = b.buscar_cotacao(cid, "enzo")
    assert achado["nome_remetente"] == "HERCULES"
    # e a cotação antiga continua lá
    assert len(b.listar_cotacoes("enzo")) == 2


def test_email_do_solicitante_e_guardado(db):
    """A Generoso não devolve preço na tela: responde por e-mail. Sem guardar
    o endereço, a tela final não tem como dizer qual caixa conferir — e o
    vendedor fica esperando uma resposta que já chegou em outro lugar."""
    cid = db.salvar_cotacao("enzo", _carga(email="joao@ventura.com.br"))

    assert db.buscar_cotacao(cid, "enzo")["email"] == "joao@ventura.com.br"


def _envelhecer(db, cotacao_id: int) -> None:
    """Joga a cotação para antes do teto de espera.

    Desde 24/08/2026 `marcar_interrompidas` só mexe no que já passou do
    prazo — antes disso a cotação pode estar viva em outro processo. Quem
    quer testar a marcação precisa, portanto, de uma cotação velha."""
    from datetime import datetime, timedelta

    from core.retentativa import ESPERA_MAXIMA_S

    velha = (datetime.now() - timedelta(seconds=ESPERA_MAXIMA_S + 60)
             ).isoformat(timespec="seconds")
    with db._conectar() as con:
        con.execute("UPDATE cotacao SET criado_em = ? WHERE id = ?",
                    (velha, cotacao_id))


def test_cotacao_pendente_vira_interrompida(db):
    """Fechar a janela mata as threads no meio: sem isto o cartao fica
    'cotando...' para sempre, esperando quem ja morreu."""
    cid = db.salvar_cotacao("enzo", _carga())
    db.salvar_resultado(cid, "jadlog", status="cotado", valor=Decimal("33.35"))
    _envelhecer(db, cid)

    assert db.marcar_interrompidas(("camilo", "jadlog")) == 1

    por_nome = {r["transportadora"]: r
                for r in db.buscar_cotacao(cid, "enzo")["resultados"]}
    assert por_nome["camilo"]["status"] == "interrompido"
    assert "fechado" in por_nome["camilo"]["erro"]
    assert por_nome["jadlog"]["valor"] == Decimal("33.35")   # intacto


def test_cotacao_completa_nao_e_mexida(db):
    """Rodar duas vezes nao pode duplicar resultado nem apagar preco."""
    cid = db.salvar_cotacao("enzo", _carga())
    for slug in ("camilo", "jadlog"):
        db.salvar_resultado(cid, slug, status="cotado", valor=Decimal("10"))

    assert db.marcar_interrompidas(("camilo", "jadlog")) == 0
    assert len(db.buscar_cotacao(cid, "enzo")["resultados"]) == 2


def test_banco_e_criado_sozinho(tmp_path):
    """Primeira execução não pode exigir passo manual de instalação."""
    caminho = tmp_path / "sub" / "novo.db"
    b = banco.Banco(caminho)
    b.salvar_cotacao("enzo", _carga())

    assert caminho.exists()
    assert len(b.listar_cotacoes("enzo")) == 1


def test_conexoes_sao_fechadas(tmp_path):
    """O `with` do sqlite3 faz commit, mas NÃO fecha a conexão.

    Cada cotação abre 5 conexões (uma por gravação/leitura). Sem fechar, elas
    ficam penduradas esperando o coletor de lixo — com o servidor aberto o dia
    inteiro isso vira arquivo aberto acumulado. Não derrubou nada até hoje, e é
    justamente por isso que passaria despercebido até derrubar."""
    import sqlite3

    abertas = []
    original = sqlite3.connect

    def espiao(*a, **k):
        con = original(*a, **k)
        abertas.append(con)
        return con

    sqlite3.connect = espiao
    try:
        b = banco.Banco(tmp_path / "conexoes.db")
        cid = b.salvar_cotacao("enzo", _carga())
        b.salvar_resultado(cid, "camilo", status="cotado")
        b.buscar_cotacao(cid, "enzo")
        b.listar_cotacoes("enzo")
    finally:
        sqlite3.connect = original

    penduradas = []
    for con in abertas:
        try:
            con.execute("SELECT 1")
            penduradas.append(con)
        except sqlite3.ProgrammingError:
            pass

    assert not penduradas, f"{len(penduradas)} de {len(abertas)} ficaram abertas"


# ------------------------------------------------- WhatsApp: o que foi ABERTO
# Nunca "enviado". O sistema sabe que a conversa abriu; se o vendedor apertou
# enviar do outro lado, ninguém aqui tem como saber. Prometer "enviado" criaria
# a pior das cotações: a que todo mundo acha que saiu e não saiu.
def test_registra_abertura_de_whatsapp(db):
    cid = db.salvar_cotacao("enzo", _carga())

    db.marcar_whatsapp_aberto(cid, "movvi", "enzo")

    assert db.whatsapp_abertos(cid) == {"movvi"}


def test_abrir_de_novo_nao_duplica_nem_reescreve_a_hora(db):
    """Reabrir a mesma conversa é comum: o vendedor fecha sem querer, ou volta
    para conferir. A contagem não pode inflar, e a hora que interessa é a da
    PRIMEIRA vez — é ela que diz quando a transportadora foi acionada."""
    cid = db.salvar_cotacao("enzo", _carga())

    db.marcar_whatsapp_aberto(cid, "movvi", "enzo")
    primeira = db.whatsapp_detalhado(cid)[0]["aberto_em"]
    db.marcar_whatsapp_aberto(cid, "movvi", "enzo")

    assert db.whatsapp_abertos(cid) == {"movvi"}
    assert db.whatsapp_detalhado(cid)[0]["aberto_em"] == primeira
    assert len(db.whatsapp_detalhado(cid)) == 1


def test_aberturas_nao_vazam_de_uma_cotacao_para_outra(db):
    uma = db.salvar_cotacao("enzo", _carga())
    outra = db.salvar_cotacao("enzo", _carga())

    db.marcar_whatsapp_aberto(uma, "movvi", "enzo")

    assert db.whatsapp_abertos(outra) == set()


# ------------------------------- uma linha por transportadora, sempre a última
def test_resultado_que_chega_depois_substitui_o_anterior(db):
    """A #50 (24/08/2026) mostrou "O sistema foi fechado durante a cotação"
    para uma Translovato que tinha cotado R$ 338,40.

    As duas linhas existiam: `interrompido` gravada primeiro, `cotado`
    gravada depois, e a tela desenhava as duas — a errada primeiro. Uma
    transportadora tem UM resultado por cotação, e o mais recente é o que
    vale: quem escreve depois sabe mais."""
    cotacao_id = db.salvar_cotacao("enzo", _carga())

    db.salvar_resultado(cotacao_id, "translovato", status="interrompido",
                        erro="O sistema foi fechado durante a cotação.")
    db.salvar_resultado(cotacao_id, "translovato", status="cotado",
                        valor=Decimal("338.40"))

    resultados = db.buscar_cotacao(cotacao_id, "enzo")["resultados"]
    assert len(resultados) == 1
    assert resultados[0]["status"] == "cotado"
    assert resultados[0]["valor"] == Decimal("338.40")


def test_transportadoras_diferentes_nao_disputam_a_mesma_linha(db):
    cotacao_id = db.salvar_cotacao("enzo", _carga())

    db.salvar_resultado(cotacao_id, "camilo", status="cotado",
                        valor=Decimal("10"))
    db.salvar_resultado(cotacao_id, "generoso", status="cotado",
                        valor=Decimal("20"))

    resultados = db.buscar_cotacao(cotacao_id, "enzo")["resultados"]
    assert {r["transportadora"] for r in resultados} == {"camilo", "generoso"}


# --------------------------------- marcar interrompidas sem matar quem vive
def test_nao_marca_cotacao_recente_que_ainda_pode_estar_rodando(db):
    """`marcar_interrompidas` roda no import de `web/app.py`, e o comentário
    dela dizia "na subida do servidor, quando por definição nada está em
    andamento". A premissa é falsa: QUALQUER segundo processo que importe o
    módulo — pytest, um script solto, um segundo servidor — executa isso e
    mata as cotações vivas do primeiro.

    Foi assim que a #50 do Enzo morreu: uma rodada de testes minha, na mesma
    pasta, enquanto as transportadoras dele ainda estavam no ar.
    """
    cotacao_id = db.salvar_cotacao("enzo", _carga())   # criada agora

    assert db.marcar_interrompidas(("camilo", "generoso")) == 0
    assert db.buscar_cotacao(cotacao_id, "enzo")["resultados"] == []


def test_marca_cotacao_velha_que_ja_passou_do_prazo(db):
    """Passado o teto de espera, nada mais vai chegar: aí a linha explica ao
    vendedor por que o cartão parou, em vez de girar para sempre."""
    cotacao_id = db.salvar_cotacao("enzo", _carga())
    _envelhecer(db, cotacao_id)

    assert db.marcar_interrompidas(("camilo", "generoso")) == 2
    resultados = db.buscar_cotacao(cotacao_id, "enzo")["resultados"]
    assert {r["status"] for r in resultados} == {"interrompido"}
