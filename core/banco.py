"""Histórico de cotações em SQLite.

SQLite porque é da biblioteca padrão: um arquivo, zero servidor, zero
dependência nova. Para o volume disto — algumas dezenas de cotações por dia,
uma empresa — não há nada que um banco maior resolveria melhor.

Dinheiro e peso são guardados como TEXTO e devolvidos como Decimal. Float
acumula erro de arredondamento, e frete é dinheiro de cliente.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from core import sessao
from core.retentativa import ESPERA_MAXIMA_S

CAMINHO_PADRAO = Path("cotafrete.db")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cotacao (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario         TEXT NOT NULL,
    criado_em       TEXT NOT NULL,
    cep_origem      TEXT NOT NULL,
    cep_destino     TEXT NOT NULL,
    cidade_origem   TEXT,
    uf_origem       TEXT,
    cidade_destino  TEXT,
    uf_destino      TEXT,
    peso_kg         TEXT NOT NULL,
    quantidade      INTEGER NOT NULL,
    comprimento_cm  INTEGER NOT NULL,
    largura_cm      INTEGER NOT NULL,
    altura_cm       INTEGER NOT NULL,
    valor_nf        TEXT NOT NULL,
    material        TEXT,
    cnpj_remetente     TEXT,
    cnpj_destinatario  TEXT,
    cnpj_pagador       TEXT,
    nome_remetente     TEXT,
    nome_destinatario  TEXT,
    nome_pagador       TEXT,
    -- Onde a resposta da Generoso vai cair. Ela confirma o recebimento na
    -- tela e manda o preço por e-mail depois; sem guardar o endereço, a tela
    -- final não teria como dizer qual caixa o vendedor precisa abrir.
    email              TEXT,
    -- cif = paga o remetente, fob = paga o destinatario. Guardado para
    -- a mensagem do WhatsApp e para repetir a cotacao do mesmo jeito.
    tipo_frete         TEXT
);

CREATE TABLE IF NOT EXISTS resultado (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cotacao_id     INTEGER NOT NULL REFERENCES cotacao(id) ON DELETE CASCADE,
    transportadora TEXT NOT NULL,
    status         TEXT NOT NULL,
    valor          TEXT,
    protocolo      TEXT,
    prazo          TEXT,
    erro           TEXT,
    evidencia      TEXT,
    -- Até quando este preço ainda pode ser CONTRATADO, em ISO (2026-09-28).
    -- Não confundir com `prazo`, que é quanto tempo a entrega demora: um diz
    -- até quando dá para FECHAR, o outro quanto tempo leva para CHEGAR.
    --
    -- É o que decide se o botão "Aceitar" aparece na tela. Hoje só a Generoso
    -- informa (a tela final dela traz "Cotação válida até"); nas outras fica
    -- NULL, e NULL quer dizer "não sabemos", nunca "vence hoje".
    validade       TEXT,
    -- Quando a transportadora respondeu. NULL nas linhas anteriores a
    -- 28/08/2026, e a tela precisa dizer "sem dados ainda" em vez de zero.
    --
    -- Os adapters gravam datetime.now() só na tentativa BEM-SUCEDIDA (ver,
    -- por exemplo, carriers/camilo/adapter.py) — então respondido_em -
    -- criado_em inclui as esperas de QUALQUER retentativa que veio antes
    -- daquela. Quem for calcular "qual transportadora está lenta" na Fase 2
    -- vai culpar a transportadora pela nossa própria retentativa se não
    -- descontar isso.
    respondido_em  TEXT
);

-- Conversa de WhatsApp ABERTA. Nunca "enviada": o sistema abre a conversa
-- com o texto pronto, mas quem aperta enviar é a pessoa, do outro lado, e
-- disso aqui não chega notícia nenhuma. Registrar como "enviado" criaria a
-- pior cotação possível — a que todo mundo acha que saiu e não saiu.
--
-- UNIQUE porque reabrir é normal (fechou sem querer, voltou para conferir) e
-- não pode inflar a contagem. Com INSERT OR IGNORE, a hora guardada é a da
-- PRIMEIRA vez, que é a que diz quando a transportadora foi acionada.
CREATE TABLE IF NOT EXISTS whatsapp_aberto (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cotacao_id     INTEGER NOT NULL REFERENCES cotacao(id) ON DELETE CASCADE,
    transportadora TEXT NOT NULL,
    usuario        TEXT NOT NULL,
    aberto_em      TEXT NOT NULL,
    UNIQUE (cotacao_id, transportadora)
);

-- Cotação ACEITA: a coleta foi pedida à transportadora pelo site.
--
-- É a primeira coisa neste sistema que combina algo com o mundo de fora em
-- nome da Ventura. O WhatsApp aqui do lado só ABRE uma conversa e deixa a
-- pessoa apertar enviar; isto aqui é o robô falando pela empresa, e o que
-- sai do outro lado é caminhão na porta do cliente.
--
-- UNIQUE pelo mesmo motivo do whatsapp_aberto, mas com consequência maior:
-- lá, repetir inflava uma contagem; aqui, repetir agenda DUAS coletas para a
-- mesma carga. E o gesto que causa isso é o mais banal que existe numa tela
-- web — apertar o botão de novo porque a primeira vez pareceu não responder.
-- Esconder o botão não basta: um F5 traz de volta. A trava mora aqui.
--
-- `status`: agendando (o robô está no portal) / agendado (o site confirmou)
-- / erro (não chegou a acontecer — e aí dá para tentar de novo).
-- E-mail de proposta que o ingestor já leu (carriers/dellavolpe/ingestor.py).
--
-- É AQUI que mora o "já processei", e não na bandeira de lido do servidor de
-- e-mail: a caixa do suporte é lida por gente, e um e-mail aberto no Outlook
-- antes do robô passar seria pulado para sempre se o critério fosse "não
-- lido". Guarda também os que NÃO foram gravados (sem carimbo, rota que não
-- bate), para não reabrir o mesmo PDF a cada minuto e para o adm ver por que
-- uma proposta não apareceu.
--
-- `desfecho`: gravado / sem_pdf / sem_carimbo / sem_valor / sem_cotacao /
-- rota_diferente, com o motivo em `detalhe`. Todos são definitivos: nenhum
-- deles muda relendo o mesmo e-mail. Falha passageira (rede caiu no meio,
-- PDF que não abriu) NÃO entra aqui — e por isso é tentada de novo na
-- próxima volta.
CREATE TABLE IF NOT EXISTS email_processado (
    message_id     TEXT PRIMARY KEY,
    transportadora TEXT NOT NULL,
    cotacao_id     INTEGER,
    desfecho       TEXT NOT NULL,
    detalhe        TEXT,
    processado_em  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aceite (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cotacao_id     INTEGER NOT NULL REFERENCES cotacao(id) ON DELETE CASCADE,
    transportadora TEXT NOT NULL,
    usuario        TEXT NOT NULL,
    pedido_em      TEXT NOT NULL,
    -- ISO (2026-09-23). O site da Generoso mostra dd/mm/aaaa, mas guardar no
    -- formato da tela é como a validade: funciona até virar o ano.
    data_coleta    TEXT NOT NULL,
    hora_limite    TEXT NOT NULL,          -- "18:00", de 30 em 30 minutos
    -- NULL = o local NÃO fecha para almoço. Ausência, não "das 00:00 às
    -- 00:00": com o checkbox desmarcado os dois selects nem existem no DOM.
    almoco_inicio  TEXT,
    almoco_fim     TEXT,
    observacao     TEXT,
    status         TEXT NOT NULL,
    protocolo      TEXT,
    erro           TEXT,
    evidencia      TEXT,
    UNIQUE (cotacao_id, transportadora)
);

CREATE INDEX IF NOT EXISTS idx_cotacao_usuario ON cotacao(usuario, id DESC);
CREATE INDEX IF NOT EXISTS idx_resultado_cotacao ON resultado(cotacao_id);

-- Conta de vendedor. O admin cria a conta; a pessoa escolhe a senha no
-- primeiro acesso. Por isso senha_hash nasce NULL: NULL quer dizer "convite
-- aberto, ainda sem dono". Ver core/sessao.py.
CREATE TABLE IF NOT EXISTS conta (
    nome        TEXT PRIMARY KEY,
    senha_hash  TEXT,
    criado_em   TEXT NOT NULL,
    definida_em TEXT
);

-- Guarda-treco de uma linha só. Hoje serve para o segredo que assina os
-- cookies de sessão: ele precisa sobreviver a reinício do servidor, senão
-- toda subida derrubaria a equipe inteira.
CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
-- Mercado Eletrônico (ver docs/MERCADO_ELETRONICO.md). Uma linha por
-- cotação do ME por conta (VENTURA/UNIÃO): o número é do ME, não nosso, e o
-- mesmo número nunca aparece nas duas contas — mas a chave inclui a conta
-- para não depender disso. `status` é mercado_eletronico/painel.Status;
-- `status_resposta` é o `answerStatus` cru do ME. Os dois existem porque o
-- ME não marca rascunho: "Salva no ME" só o nosso banco sabe.
CREATE TABLE IF NOT EXISTS me_cotacao (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conta           TEXT NOT NULL,
    numero          INTEGER NOT NULL,
    empresa         TEXT,
    comprador       TEXT,
    codigo          TEXT,
    data_limite     TEXT,          -- ISO, hora de Brasília
    status          TEXT NOT NULL,
    status_resposta TEXT,
    na_lista        INTEGER NOT NULL DEFAULT 1,
    visto_em        TEXT,          -- primeira vez que a varredura achou
    atualizado_em   TEXT,          -- última varredura que passou por ela
    itens_lidos_em  TEXT,
    validade_dias   INTEGER,
    salvo_por       TEXT,
    salvo_em        TEXT,
    enviada_em      TEXT,
    erro            TEXT,
    evidencia       TEXT,
    obs_comprador   TEXT,          -- texto geral do comprador (ObsComp)
    revisao_ia      TEXT,          -- JSON de mercado_eletronico/revisao.Revisao
    revisao_em      TEXT,
    revisao_assinatura TEXT,       -- do preenchimento revisado: mudou = velha
    UNIQUE (conta, numero)
);

-- Um item da cotação. As colunas de cima vêm da página do ME (só leitura);
-- as de baixo são o que o usuário preencheu. Gravar de novo o que veio do
-- ME nunca apaga o que o usuário digitou.
CREATE TABLE IF NOT EXISTS me_item (
    cotacao_id        INTEGER NOT NULL REFERENCES me_cotacao(id) ON DELETE CASCADE,
    numero            INTEGER NOT NULL,    -- 10, 20, ... como o ME mostra
    pagina            INTEGER NOT NULL,
    indice            INTEGER NOT NULL,    -- N do Preco{N} naquela página
    produto_id        TEXT,
    descricao         TEXT,
    quantidade        TEXT,
    unidade           TEXT,
    obs_comprador     TEXT,
    campos_adicionais TEXT,
    uf_destino        TEXT,
    origem_pedida     INTEGER,
    data_remessa      TEXT,
    preco             TEXT,
    ncm               TEXT,
    prazo_dias        INTEGER,
    marca             TEXT,
    obs               TEXT,
    origem            INTEGER,
    PRIMARY KEY (cotacao_id, numero)
);

CREATE TABLE IF NOT EXISTS me_historico (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cotacao_id INTEGER NOT NULL REFERENCES me_cotacao(id) ON DELETE CASCADE,
    quando     TEXT NOT NULL,
    usuario    TEXT,                 -- NULL = o sistema (varredura, robô)
    evento     TEXT NOT NULL,
    detalhe    TEXT
);
CREATE INDEX IF NOT EXISTS idx_me_historico ON me_historico(cotacao_id, id);

-- Cada leitura da lista do ME (a varredura de 7 em 7 min e o "Atualizar
-- agora"), por conta. É o que deixa o /adm/me mostrar "a leitura da UNIÃO
-- está falhando desde as 14h" sem ninguém precisar abrir o ME. Antes ficava
-- só na memória do servidor e sumia a cada reinício.
CREATE TABLE IF NOT EXISTS me_varredura (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    quando     TEXT NOT NULL,
    conta      TEXT NOT NULL,
    ok         INTEGER NOT NULL,
    cotacoes   INTEGER,              -- quantas pendentes a lista trouxe
    duracao_s  REAL,
    erro       TEXT
);
CREATE INDEX IF NOT EXISTS idx_me_varredura ON me_varredura(conta, id);

-- Cada tentativa de chamada à IA (core/ia.py): qual modelo, para quê, se
-- respondeu. É o que diz ao administrador quem está respondendo e quando os
-- modelos grátis estão chegando no limite.
CREATE TABLE IF NOT EXISTS ia_chamada (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    quando     TEXT NOT NULL,
    funcao     TEXT NOT NULL,        -- "revisão ME", ...
    modelo     TEXT NOT NULL,        -- "groq:openai/gpt-oss-120b"
    ok         INTEGER NOT NULL,
    erro       TEXT,
    duracao_s  REAL
);
CREATE INDEX IF NOT EXISTS idx_ia_chamada ON ia_chamada(quando);

-- Memória por material: o NCM, a marca e a origem que alguém já digitou
-- para o mesmo código voltam sozinhos na próxima cotação.
CREATE TABLE IF NOT EXISTS me_material (
    chave         TEXT PRIMARY KEY,
    ncm           TEXT,
    marca         TEXT,
    origem        INTEGER,
    atualizado_em TEXT NOT NULL
);
"""

CAMPOS_CARGA = (
    "cep_origem", "cep_destino", "cidade_origem", "uf_origem",
    "cidade_destino", "uf_destino", "peso_kg", "quantidade",
    "comprimento_cm", "largura_cm", "altura_cm", "valor_nf", "material",
    "cnpj_remetente", "cnpj_destinatario", "cnpj_pagador",
    "nome_remetente", "nome_destinatario", "nome_pagador", "email",
    # Quem pediu a cotação, não quem envia/recebe a carga. Guardado por causa
    # do bookmarklet da Della Volpe: sem isto, "Nome completo" e "WhatsApp"
    # do formulário deles ficavam perdidos depois do /cotar terminar — só
    # existiam no POST original, igual o e-mail antes de 20/08/2026.
    "nome_solicitante", "whatsapp_solicitante",
    "tipo_frete",
    # Quem participa desta cotação. NULL = todas — ver core/selecao.py, que
    # explica por que ausência e escolha vazia precisam ser coisas distintas.
    "transportadoras",
)

# Colunas de `resultado` que nasceram depois do banco. Mesma razão de
# CAMPOS_CARGA: CREATE TABLE IF NOT EXISTS não altera tabela existente.
CAMPOS_RESULTADO = ("respondido_em", "validade")

# Colunas de `me_cotacao` que nasceram depois da tabela.
CAMPOS_ME_COTACAO_NOVOS = ("obs_comprador", "revisao_ia", "revisao_em",
                           "revisao_assinatura")


def _decimal(valor: str | None) -> Decimal | None:
    return Decimal(valor) if valor not in (None, "") else None


def _data(valor: str | None) -> date | None:
    """ISO -> date. Texto estragado vira None, nunca exceção.

    Uma data ilegível não pode derrubar a tela da cotação inteira: o pior que
    pode acontecer é o botão "Aceitar" não aparecer, e isso é reparável — a
    tela quebrar, no meio do vendedor comparando preços, não é."""
    try:
        return date.fromisoformat(valor) if valor else None
    except (TypeError, ValueError):
        return None


class Banco:
    def __init__(self, caminho: Path | str = CAMINHO_PADRAO) -> None:
        self.caminho = Path(caminho)
        if self.caminho.parent != Path(""):
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conectar()) as con, con:
            con.executescript(ESQUEMA)
            self._migrar(con)

    @staticmethod
    def _migrar(con: sqlite3.Connection) -> None:
        """Acrescenta colunas que passaram a existir depois do banco.

        CREATE TABLE IF NOT EXISTS não altera tabela existente: sem isto,
        quem já tinha cotafrete.db recebia "table cotacao has no column named
        cnpj_remetente" no primeiro INSERT. Acontece toda vez que o esquema
        cresce, então a checagem fica permanente."""
        existentes = {r["name"] for r in con.execute("PRAGMA table_info(cotacao)")}
        for coluna in CAMPOS_CARGA:
            if coluna not in existentes:
                con.execute(f"ALTER TABLE cotacao ADD COLUMN {coluna} TEXT")

        existentes = {r["name"] for r in con.execute("PRAGMA table_info(resultado)")}
        for coluna in CAMPOS_RESULTADO:
            if coluna not in existentes:
                con.execute(f"ALTER TABLE resultado ADD COLUMN {coluna} TEXT")

        existentes = {r["name"] for r in con.execute("PRAGMA table_info(me_cotacao)")}
        for coluna in CAMPOS_ME_COTACAO_NOVOS:
            if coluna not in existentes:
                con.execute(f"ALTER TABLE me_cotacao ADD COLUMN {coluna} TEXT")

        # UMA linha por transportadora por cotação. Sem esta regra o banco
        # aceitava duas, e a tela desenhava as duas: foi assim que a #50
        # (24/08/2026) mostrou "O sistema foi fechado durante a cotação" ao
        # lado do resultado real da mesma Translovato, que tinha cotado
        # R$ 338,40. O mesmo já tinha acontecido na #17.
        #
        # Fica no _migrar e não no ESQUEMA porque o índice não nasce num
        # banco que já tem duplicata: primeiro apaga, depois cria. Mantém o
        # MAIOR id de cada par — quem escreveu por último sabia mais.
        con.execute(
            "DELETE FROM resultado WHERE id NOT IN ("
            " SELECT MAX(id) FROM resultado GROUP BY cotacao_id, transportadora)")
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS resultado_unico"
            " ON resultado (cotacao_id, transportadora)")

    def _conectar(self) -> sqlite3.Connection:
        """Sempre use com `closing(...)`: o `with` do sqlite3 faz commit e
        rollback, mas NÃO fecha a conexão. Cada cotação abre cinco delas."""
        con = sqlite3.connect(self.caminho)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        # WAL: leitor e escritor deixam de brigar pelo arquivo. Sem isso o
        # monitor (monitorar.py), que lê o banco enquanto as cotações gravam,
        # leva "database is locked" na hora de maior movimento — justo quando
        # olhar o monitor importa. Fica gravado no arquivo, basta uma vez.
        con.execute("PRAGMA journal_mode = WAL")
        return con

    # ------------------------------------------------------------ escrita
    def salvar_cotacao(self, usuario: str, carga: dict[str, Any]) -> int:
        """Grava a carga e devolve o id. Os resultados vêm depois, um por
        transportadora, conforme cada uma responde."""
        valores = [usuario, datetime.now().isoformat(timespec="seconds")]
        valores += [str(carga.get(c)) if carga.get(c) is not None else None
                    for c in CAMPOS_CARGA]
        colunas = "usuario, criado_em, " + ", ".join(CAMPOS_CARGA)
        marcas = ", ".join("?" * (len(CAMPOS_CARGA) + 2))
        with closing(self._conectar()) as con, con:
            cur = con.execute(
                f"INSERT INTO cotacao ({colunas}) VALUES ({marcas})", valores)
            return int(cur.lastrowid)

    def salvar_resultado(self, cotacao_id: int, transportadora: str, *,
                         status: str, valor: Decimal | None = None,
                         protocolo: str | None = None,
                         prazo: str | None = None,
                         erro: str | None = None,
                         evidencia: str | None = None,
                         respondido_em: str | None = None,
                         validade: date | None = None) -> None:
        # Sobrescreve em vez de acrescentar: a transportadora que responde
        # depois de ter sido dada como interrompida precisa APAGAR o aviso,
        # não conviver com ele. Ver o índice resultado_unico em _migrar.
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT INTO resultado (cotacao_id, transportadora, status,"
                " valor, protocolo, prazo, erro, evidencia, respondido_em,"
                " validade) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (cotacao_id, transportadora) DO UPDATE SET"
                " status = excluded.status, valor = excluded.valor,"
                " protocolo = excluded.protocolo, prazo = excluded.prazo,"
                " erro = excluded.erro, evidencia = excluded.evidencia,"
                " respondido_em = excluded.respondido_em,"
                " validade = excluded.validade",
                (cotacao_id, transportadora, status,
                 str(valor) if valor is not None else None,
                 protocolo, prazo, erro, evidencia, respondido_em,
                 validade.isoformat() if validade else None))

    # ------------------------------------------------ e-mail de proposta
    def carga_da_cotacao(self, cotacao_id: int) -> dict | None:
        """A cotação SEM filtro de dono — só para o ingestor.

        `buscar_cotacao` exige o usuário porque é a porta da TELA, e lá
        trocar o número na URL não pode abrir a cotação alheia. O ingestor
        não é ninguém: ele recebe um número de dentro de um PDF e precisa
        saber se a cotação existe e para onde ela vai. Não devolve os
        resultados — ele não precisa deles."""
        with closing(self._conectar()) as con, con:
            linha = con.execute("SELECT * FROM cotacao WHERE id = ?",
                                (cotacao_id,)).fetchone()
            return dict(linha) if linha else None

    def email_ja_processado(self, message_id: str) -> bool:
        with closing(self._conectar()) as con, con:
            return con.execute(
                "SELECT 1 FROM email_processado WHERE message_id = ?",
                (message_id,)).fetchone() is not None

    def registrar_email(self, message_id: str, transportadora: str, *,
                        desfecho: str, cotacao_id: int | None = None,
                        detalhe: str | None = None) -> None:
        """Sobrescreve: uma segunda passada que DEU CERTO (a cotação foi
        criada depois do e-mail, por exemplo) troca o desfecho velho."""
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT INTO email_processado (message_id, transportadora,"
                " cotacao_id, desfecho, detalhe, processado_em)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (message_id) DO UPDATE SET"
                " cotacao_id = excluded.cotacao_id,"
                " desfecho = excluded.desfecho, detalhe = excluded.detalhe,"
                " processado_em = excluded.processado_em",
                (message_id, transportadora, cotacao_id, desfecho, detalhe,
                 datetime.now().isoformat(timespec="seconds")))

    def emails_processados(self, limite: int = 50) -> list[dict]:
        with closing(self._conectar()) as con, con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM email_processado"
                " ORDER BY processado_em DESC LIMIT ?", (limite,))]

    def marcar_whatsapp_aberto(self, cotacao_id: int, transportadora: str,
                               usuario: str) -> None:
        """Registra que a conversa foi ABERTA com o texto pronto.

        OR IGNORE, não REPLACE: reabrir não pode reescrever a hora da
        primeira vez nem duplicar a linha."""
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT OR IGNORE INTO whatsapp_aberto"
                " (cotacao_id, transportadora, usuario, aberto_em)"
                " VALUES (?, ?, ?, ?)",
                (cotacao_id, transportadora, usuario,
                 datetime.now().isoformat(timespec="seconds")))

    def whatsapp_abertos(self, cotacao_id: int) -> set[str]:
        """Só os slugs — é o que a tela precisa para marcar cada linha."""
        with closing(self._conectar()) as con, con:
            return {r["transportadora"] for r in con.execute(
                "SELECT transportadora FROM whatsapp_aberto"
                " WHERE cotacao_id = ?", (cotacao_id,))}

    def whatsapp_detalhado(self, cotacao_id: int) -> list[dict]:
        """Com hora e usuário, para o monitor e para conferir depois."""
        with closing(self._conectar()) as con, con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM whatsapp_aberto WHERE cotacao_id = ?"
                " ORDER BY id", (cotacao_id,))]

    # ------------------------------------------------------------- aceite
    def registrar_aceite(self, cotacao_id: int, transportadora: str,
                         usuario: str, *, data_coleta: str,
                         hora_limite: str,
                         almoco_inicio: str | None = None,
                         almoco_fim: str | None = None,
                         observacao: str | None = None) -> bool:
        """Reserva o direito de agendar. True se reservou, False se já era.

        Chamado ANTES de abrir o navegador, e é isso que o torna a trava: o
        segundo clique perde a corrida aqui e nunca chega ao portal. Se a
        checagem ficasse por conta de quem chama, dois cliques quase
        simultâneos passariam os dois — e o cliente receberia dois caminhões.

        O aceite que FALHOU não tranca: `status='erro'` quer dizer que a
        coleta não chegou a ser pedida, e o vendedor precisa poder tentar de
        novo. Só `agendando` e `agendado` seguram a vaga."""
        with closing(self._conectar()) as con, con:
            cur = con.execute(
                "INSERT INTO aceite (cotacao_id, transportadora, usuario,"
                " pedido_em, data_coleta, hora_limite, almoco_inicio,"
                " almoco_fim, observacao, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'agendando')"
                " ON CONFLICT (cotacao_id, transportadora) DO UPDATE SET"
                " usuario = excluded.usuario, pedido_em = excluded.pedido_em,"
                " data_coleta = excluded.data_coleta,"
                " hora_limite = excluded.hora_limite,"
                " almoco_inicio = excluded.almoco_inicio,"
                " almoco_fim = excluded.almoco_fim,"
                " observacao = excluded.observacao, status = 'agendando',"
                " protocolo = NULL, erro = NULL, evidencia = NULL"
                " WHERE aceite.status = 'erro'",
                (cotacao_id, transportadora, usuario,
                 datetime.now().isoformat(timespec="seconds"), data_coleta,
                 hora_limite, almoco_inicio, almoco_fim, observacao))
            return cur.rowcount == 1

    def concluir_aceite(self, cotacao_id: int, transportadora: str, *,
                        status: str, protocolo: str | None = None,
                        erro: str | None = None,
                        evidencia: str | None = None) -> None:
        """O que o portal respondeu. Nunca cria linha: só fecha a que o
        `registrar_aceite` abriu — concluir um aceite que ninguém pediu seria
        registrar uma coleta que não existe."""
        with closing(self._conectar()) as con, con:
            con.execute(
                "UPDATE aceite SET status = ?, protocolo = ?, erro = ?,"
                " evidencia = ? WHERE cotacao_id = ? AND transportadora = ?",
                (status, protocolo, erro, evidencia, cotacao_id,
                 transportadora))

    def aceites(self, cotacao_id: int) -> dict[str, dict]:
        """slug -> aceite. A tela pergunta "esta já foi aceita?" por
        transportadora, e um dicionário responde isso sem varrer lista."""
        with closing(self._conectar()) as con, con:
            return {r["transportadora"]: dict(r) for r in con.execute(
                "SELECT * FROM aceite WHERE cotacao_id = ?", (cotacao_id,))}

    # ------------------------------------------------------------ leitura
    def listar_cotacoes(self, usuario: str, limite: int = 100) -> list[dict]:
        """Mais recentes primeiro, já com o melhor preço de cada uma.

        O melhor preço vem na listagem para não obrigar a abrir uma por uma
        só para lembrar qual saiu mais barata."""
        with closing(self._conectar()) as con, con:
            linhas = con.execute(
                "SELECT * FROM cotacao WHERE usuario = ?"
                " ORDER BY id DESC LIMIT ?", (usuario, limite)).fetchall()
            saida = []
            for linha in linhas:
                c = dict(linha)
                precos = con.execute(
                    "SELECT valor FROM resultado"
                    " WHERE cotacao_id = ? AND valor IS NOT NULL",
                    (c["id"],)).fetchall()
                valores = [Decimal(p["valor"]) for p in precos]
                c["melhor_preco"] = min(valores) if valores else None
                c["peso_kg"] = _decimal(c["peso_kg"])
                c["valor_nf"] = _decimal(c["valor_nf"])
                saida.append(c)
            return saida

    def buscar_cotacao(self, cotacao_id: int, usuario: str) -> dict | None:
        """Devolve None se a cotação for de OUTRO usuário.

        O usuário entra na consulta de propósito: sem isso, trocar o número
        na URL daria acesso à cotação alheia."""
        with closing(self._conectar()) as con, con:
            linha = con.execute(
                "SELECT * FROM cotacao WHERE id = ? AND usuario = ?",
                (cotacao_id, usuario)).fetchone()
            if linha is None:
                return None
            c = dict(linha)
            c["peso_kg"] = _decimal(c["peso_kg"])
            c["valor_nf"] = _decimal(c["valor_nf"])
            c["resultados"] = [
                {**dict(r), "valor": _decimal(r["valor"]),
                 "validade": _data(r["validade"])}
                for r in con.execute(
                    "SELECT * FROM resultado WHERE cotacao_id = ? ORDER BY id",
                    (cotacao_id,)).fetchall()
            ]
            return c

    def marcar_interrompidas(self, esperadas: dict[str, str]) -> int:
        """Fecha cotações que ficaram sem resposta porque o sistema caiu.

        As transportadoras rodam em threads DENTRO do processo: fechar a
        janela mata as threads no meio do caminho. Sem isto o cartão fica
        "cotando..." para sempre e a página recarrega esperando um resultado
        que ninguém mais vai gravar.

        SÓ mexe no que já passou do teto de espera. A versão anterior mexia
        em tudo, apoiada na ideia de que "roda na subida do servidor, quando
        por definição nada está em andamento" — e essa premissa é falsa:
        `web/app.py` executa isto no IMPORT, então qualquer segundo processo
        na mesma pasta (pytest, um script solto, um segundo servidor) mata as
        cotações vivas do primeiro. Foi o que matou a #50 em 24/08/2026.

        `esperadas` mapeia slug -> desde quando essa automática existe (ISO
        8601), não só a lista de slugs. Cotação criada ANTES disso nunca teve
        chance de ser cotada por ela — sem essa data, toda vez que uma
        automática nova entra em produção esta varredura volta a TODO o
        histórico e carimba "sistema fechado no meio" numa transportadora que
        nunca chegou a ser chamada. Foi o que aconteceu com a Braspress em
        02-03/09/2026: 118 linhas fantasma, corrigidas na mão por não existir
        esta trava ainda.

        Passado o teto, a cotação está morta de qualquer jeito — a tela já
        parou de esperar por ela — e aí a linha só explica o porquê."""
        limite = (datetime.now() - timedelta(seconds=ESPERA_MAXIMA_S)
                  ).isoformat(timespec="seconds")
        marcadas = 0
        with closing(self._conectar()) as con, con:
            for linha in con.execute(
                    "SELECT id, criado_em FROM cotacao WHERE criado_em < ?",
                    (limite,)).fetchall():
                jah = {r["transportadora"] for r in con.execute(
                    "SELECT transportadora FROM resultado WHERE cotacao_id = ?",
                    (linha["id"],))}
                for slug, desde in esperadas.items():
                    if slug in jah or linha["criado_em"] < desde:
                        continue
                    con.execute(
                        "INSERT INTO resultado (cotacao_id, transportadora,"
                        " status, erro) VALUES (?, ?, 'interrompido', ?)",
                        (linha["id"], slug,
                         "O sistema foi fechado durante a cotação."))
                    marcadas += 1
        return marcadas

    def usuarios(self) -> list[str]:
        with closing(self._conectar()) as con, con:
            return [r[0] for r in con.execute(
                "SELECT DISTINCT usuario FROM cotacao ORDER BY usuario")]

    # ------------------------------------------------------------- contas
    # Quem pode entrar. Não confundir com usuarios() acima, que lista quem já
    # cotou — um nome pode aparecer lá sem ter conta (cotações anteriores ao
    # login) e uma conta pode existir sem nunca ter cotado.

    def segredo_sessao(self) -> str:
        """O segredo que assina os cookies. Cria na primeira chamada.

        Fica no banco, e não no .env, porque precisa sobreviver a reinício:
        gerar um novo a cada subida do servidor derrubaria a equipe toda a
        cada deploy. Para expulsar todo mundo de propósito, apague esta linha.
        """
        with closing(self._conectar()) as con, con:
            linha = con.execute(
                "SELECT valor FROM config WHERE chave = 'segredo_sessao'"
            ).fetchone()
            if linha:
                return linha["valor"]
            # INSERT OR IGNORE + releitura: dois trabalhadores subindo juntos
            # não podem acabar com segredos diferentes, cada um invalidando o
            # cookie do outro.
            con.execute("INSERT OR IGNORE INTO config (chave, valor)"
                        " VALUES ('segredo_sessao', ?)", (sessao.novo_segredo(),))
            return con.execute(
                "SELECT valor FROM config WHERE chave = 'segredo_sessao'"
            ).fetchone()["valor"]

    def criar_conta(self, nome: str) -> bool:
        """Abre o convite. Devolve False se o nome já existe.

        A senha fica NULL: quem escolhe é a própria pessoa, no primeiro
        acesso."""
        with closing(self._conectar()) as con, con:
            cur = con.execute(
                "INSERT OR IGNORE INTO conta (nome, criado_em) VALUES (?, ?)",
                (nome, datetime.now().isoformat(timespec="seconds")))
            return cur.rowcount == 1

    def conta(self, nome: str) -> dict | None:
        with closing(self._conectar()) as con, con:
            linha = con.execute(
                "SELECT * FROM conta WHERE nome = ?", (nome,)).fetchone()
            return dict(linha) if linha else None

    def contas(self) -> list[dict]:
        with closing(self._conectar()) as con, con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM conta ORDER BY nome")]

    def definir_senha(self, nome: str, senha_hash: str) -> bool:
        """Fecha o convite. Só funciona enquanto a senha ainda é NULL.

        O `AND senha_hash IS NULL` é a trava de segurança, e ela mora AQUI de
        propósito: se dependesse de quem chama conferir antes, bastaria um
        caminho esquecer a conferência para qualquer pessoa reescrever a senha
        de um vendedor que já usa o sistema. Para redefinir de verdade, o
        admin chama esquecer_senha() primeiro."""
        with closing(self._conectar()) as con, con:
            cur = con.execute(
                "UPDATE conta SET senha_hash = ?, definida_em = ?"
                " WHERE nome = ? AND senha_hash IS NULL",
                (senha_hash, datetime.now().isoformat(timespec="seconds"),
                 nome))
            return cur.rowcount == 1

    def esquecer_senha(self, nome: str) -> bool:
        """Reabre o convite: a pessoa escolhe outra senha no próximo acesso.
        É o que o admin usa quando alguém esquece a dela."""
        with closing(self._conectar()) as con, con:
            cur = con.execute(
                "UPDATE conta SET senha_hash = NULL, definida_em = NULL"
                " WHERE nome = ?", (nome,))
            return cur.rowcount == 1

    def remover_conta(self, nome: str) -> bool:
        """Tira o acesso. As cotações que a pessoa já fez ficam — são
        histórico da empresa, não dela."""
        with closing(self._conectar()) as con, con:
            cur = con.execute("DELETE FROM conta WHERE nome = ?", (nome,))
            return cur.rowcount == 1


    # ------------------------------------------------ Mercado Eletrônico
    # CRUD só. Quem decide status é mercado_eletronico/painel.py e quem
    # orquestra é web/me_ui.py — mesma divisão das cotações de frete.
    CAMPOS_ME_COTACAO = ("empresa", "comprador", "codigo", "data_limite",
                         "status", "status_resposta", "na_lista", "visto_em",
                         "atualizado_em", "itens_lidos_em", "validade_dias",
                         "salvo_por", "salvo_em", "enviada_em", "erro",
                         "evidencia", "obs_comprador", "revisao_ia",
                         "revisao_em", "revisao_assinatura")
    CAMPOS_ME_ENTRADA = ("preco", "ncm", "prazo_dias", "marca", "obs", "origem")

    def me_cotacao_id(self, conta: str, numero: int) -> int | None:
        with closing(self._conectar()) as con, con:
            r = con.execute("SELECT id FROM me_cotacao WHERE conta = ? AND numero = ?",
                            (conta, numero)).fetchone()
            return int(r["id"]) if r else None

    def me_criar(self, conta: str, numero: int, **campos) -> int:
        """Cria se não existe; devolve o id de qualquer jeito."""
        campos.setdefault("status", "pendente")
        self._me_conferir(campos, self.CAMPOS_ME_COTACAO)
        colunas = ["conta", "numero", *campos]
        with closing(self._conectar()) as con, con:
            con.execute(
                f"INSERT OR IGNORE INTO me_cotacao ({', '.join(colunas)})"
                f" VALUES ({', '.join('?' * len(colunas))})",
                (conta, numero, *campos.values()))
            return int(con.execute(
                "SELECT id FROM me_cotacao WHERE conta = ? AND numero = ?",
                (conta, numero)).fetchone()["id"])

    def me_atualizar(self, cotacao_id: int, **campos) -> None:
        if not campos:
            return
        self._me_conferir(campos, self.CAMPOS_ME_COTACAO)
        with closing(self._conectar()) as con, con:
            con.execute(
                f"UPDATE me_cotacao SET {', '.join(f'{c} = ?' for c in campos)}"
                " WHERE id = ?", (*campos.values(), cotacao_id))

    def me_trocar_status(self, cotacao_id: int, de: tuple[str, ...], para: str,
                         **campos) -> bool:
        """Troca o status só se ele ainda for um dos `de`. É o que impede dois
        cliques em "Salvar no ME" de soltar dois robôs na mesma cotação."""
        self._me_conferir(campos, self.CAMPOS_ME_COTACAO)
        sets = ["status = ?", *(f"{c} = ?" for c in campos)]
        with closing(self._conectar()) as con, con:
            cur = con.execute(
                f"UPDATE me_cotacao SET {', '.join(sets)} WHERE id = ?"
                f" AND status IN ({', '.join('?' * len(de))})",
                (para, *campos.values(), cotacao_id, *de))
            return cur.rowcount == 1

    def me_cotacao(self, cotacao_id: int) -> dict | None:
        with closing(self._conectar()) as con, con:
            r = con.execute("SELECT * FROM me_cotacao WHERE id = ?",
                            (cotacao_id,)).fetchone()
            if not r:
                return None
            c = dict(r)
            c["itens"] = [dict(i) for i in con.execute(
                "SELECT * FROM me_item WHERE cotacao_id = ?"
                " ORDER BY pagina, indice", (cotacao_id,))]
            return c

    def me_cotacoes(self, conta: str | None = None,
                    status: str | None = None) -> list[dict]:
        """Para a lista: abertas primeiro, pelo prazo mais curto."""
        sql = ("SELECT c.*, (SELECT COUNT(*) FROM me_item i WHERE i.cotacao_id = c.id)"
               " AS n_itens, (SELECT COUNT(*) FROM me_item i WHERE i.cotacao_id = c.id"
               " AND COALESCE(i.preco, '') <> '') AS n_com_preco FROM me_cotacao c")
        filtros, args = [], []
        if conta:
            filtros.append("c.conta = ?")
            args.append(conta)
        if status:
            filtros.append("c.status = ?")
            args.append(status)
        if filtros:
            sql += " WHERE " + " AND ".join(filtros)
        sql += (" ORDER BY c.status IN ('enviada', 'recusada', 'vencida'),"
                " c.data_limite IS NULL, c.data_limite, c.numero")
        with closing(self._conectar()) as con, con:
            return [dict(r) for r in con.execute(sql, args)]

    def me_gravar_itens_do_me(self, cotacao_id: int, itens: list[dict]) -> None:
        """O que veio da página do ME. Não toca no que o usuário preencheu."""
        colunas = ("numero", "pagina", "indice", "produto_id", "descricao",
                   "quantidade", "unidade", "obs_comprador", "campos_adicionais",
                   "uf_destino", "origem_pedida", "data_remessa")
        atualiza = ", ".join(f"{c} = excluded.{c}" for c in colunas[1:])
        with closing(self._conectar()) as con, con:
            for item in itens:
                con.execute(
                    f"INSERT INTO me_item (cotacao_id, {', '.join(colunas)})"
                    f" VALUES (?, {', '.join('?' * len(colunas))})"
                    f" ON CONFLICT (cotacao_id, numero) DO UPDATE SET {atualiza}",
                    (cotacao_id, *(item.get(c) for c in colunas)))

    def me_gravar_entrada(self, cotacao_id: int, numero: int, **campos) -> None:
        """O que o usuário digitou num item."""
        self._me_conferir(campos, self.CAMPOS_ME_ENTRADA)
        if not campos:
            return
        with closing(self._conectar()) as con, con:
            con.execute(
                f"UPDATE me_item SET {', '.join(f'{c} = ?' for c in campos)}"
                " WHERE cotacao_id = ? AND numero = ?",
                (*campos.values(), cotacao_id, numero))

    def me_registrar(self, cotacao_id: int, evento: str, detalhe: str = "",
                     usuario: str | None = None) -> None:
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT INTO me_historico (cotacao_id, quando, usuario, evento,"
                " detalhe) VALUES (?, ?, ?, ?, ?)",
                (cotacao_id, datetime.now().isoformat(timespec="seconds"),
                 usuario, evento, detalhe or None))

    def me_historico(self, cotacao_id: int) -> list[dict]:
        with closing(self._conectar()) as con, con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM me_historico WHERE cotacao_id = ? ORDER BY id",
                (cotacao_id,))]

    def me_registrar_varredura(self, conta: str, *, ok: bool, cotacoes: int | None = None,
                               duracao_s: float | None = None, erro: str | None = None) -> None:
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT INTO me_varredura (quando, conta, ok, cotacoes, duracao_s, erro)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), conta, int(ok),
                 cotacoes, duracao_s, erro))
            # Leitura boa não interessa depois de 90 dias; a falha fica.
            corte = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
            con.execute("DELETE FROM me_varredura WHERE ok = 1 AND quando < ?", (corte,))

    # ------------------------------------------------------------------ IA
    def ia_registrar(self, *, funcao: str, modelo: str, ok: bool, erro: str | None = None,
                     duracao_s: float | None = None) -> None:
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT INTO ia_chamada (quando, funcao, modelo, ok, erro, duracao_s)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), funcao, modelo, int(ok),
                 erro, duracao_s))
            corte = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
            con.execute("DELETE FROM ia_chamada WHERE quando < ?", (corte,))

    def me_material(self, chave: str) -> dict | None:
        with closing(self._conectar()) as con, con:
            r = con.execute("SELECT * FROM me_material WHERE chave = ?",
                            (chave,)).fetchone()
            return dict(r) if r else None

    def me_lembrar_material(self, chave: str, *, ncm: str | None,
                            marca: str | None, origem: int | None) -> None:
        if not chave:
            return
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT INTO me_material (chave, ncm, marca, origem, atualizado_em)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT (chave) DO UPDATE SET"
                " ncm = excluded.ncm, marca = excluded.marca,"
                " origem = excluded.origem, atualizado_em = excluded.atualizado_em",
                (chave, ncm, marca, origem, datetime.now().isoformat(timespec="seconds")))

    @staticmethod
    def _me_conferir(campos: dict, validos: tuple[str, ...]) -> None:
        # Os nomes de coluna entram no SQL por f-string: só os da lista.
        estranhos = set(campos) - set(validos)
        if estranhos:
            raise ValueError(f"Campo desconhecido: {sorted(estranhos)}")
