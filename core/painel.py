"""As contas do dashboard administrativo.

Camada PURA: recebe uma conexão sqlite3, devolve list[dict] ou dict. Nenhum
HTML — pelo mesmo motivo de carriers/*/mapping.py, o risco mora na conta, e
conta se testa sem navegador.

Só LEITURA. Nada aqui escreve no banco.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

# Como cada status conta. Definição única: sem ela, cada bloco da tela
# poderia contar diferente e os números não fechariam entre si.
#
# `aguardando_retorno` é SUCESSO: a Della Volpe recebeu e o preço vem por
# e-mail. Contar como falha a jogaria para o vermelho todo dia, sem nada de
# errado.
#
# `interrompido` é NOSSO: o servidor reiniciou no meio. Fica fora do
# aproveitamento — punir a transportadora por um restart nosso faria o número
# mentir.
SUCESSO = frozenset({"cotado", "aguardando_retorno"})
RECUSA = frozenset({"recusado"})
FALHA = frozenset({"erro", "intervencao_necessaria"})
NOSSA = frozenset({"interrompido"})


def categoria(status: str) -> str:
    """Status do banco -> categoria da tela. FUNÇÃO PURA."""
    if status in SUCESSO:
        return "sucesso"
    if status in RECUSA:
        return "recusa"
    if status in FALHA:
        return "falha"
    if status in NOSSA:
        return "nossa"
    # Status que ninguém previu aparece como "inesperado" em vez de sumir:
    # esconder o desconhecido foi como "(nenhuma mensagem visível)" nasceu.
    return "inesperado"


def _desde(dias: int) -> str:
    return (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")


def resumo_do_dia(con: sqlite3.Connection) -> dict:
    """Os números de hoje, para a faixa do topo."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    ids = [r["id"] for r in con.execute(
        "SELECT id FROM cotacao WHERE criado_em LIKE ?", (f"{hoje}%",))]
    if not ids:
        return {"cotacoes": 0, "com_preco": 0, "sem_nenhum_preco": 0,
                "em_andamento": 0}

    marcas = ", ".join("?" * len(ids))
    com_preco = {r["cotacao_id"] for r in con.execute(
        f"SELECT DISTINCT cotacao_id FROM resultado"
        f" WHERE cotacao_id IN ({marcas}) AND status = 'cotado'", ids)}
    respondidas = {r["cotacao_id"] for r in con.execute(
        f"SELECT DISTINCT cotacao_id FROM resultado"
        f" WHERE cotacao_id IN ({marcas})", ids)}

    return {
        "cotacoes": len(ids),
        "com_preco": len(com_preco),
        # Sem NENHUM preço: respondeu alguma coisa e nada virou valor. É a
        # métrica que diz "o vendedor ficou na mão".
        "sem_nenhum_preco": len(respondidas - com_preco),
        "em_andamento": len(set(ids) - respondidas),
    }


def saude_das_transportadoras(con: sqlite3.Connection,
                               dias: int) -> list[dict]:
    """Uma linha por transportadora, da pior para a melhor."""
    linhas: dict[str, dict] = {}
    for r in con.execute(
            "SELECT r.transportadora, r.status FROM resultado r"
            " JOIN cotacao c ON c.id = r.cotacao_id"
            " WHERE c.criado_em >= ?", (_desde(dias),)):
        alvo = linhas.setdefault(r["transportadora"], {
            "transportadora": r["transportadora"], "sucesso": 0,
            "recusa": 0, "falha": 0, "nossa": 0, "inesperado": 0})
        alvo[categoria(r["status"])] += 1

    for alvo in linhas.values():
        base = alvo["sucesso"] + alvo["recusa"] + alvo["falha"]
        # None, não 0: sem nada no denominador o aproveitamento é
        # DESCONHECIDO. Zero diria "nunca acertou", que é outra coisa.
        alvo["aproveitamento"] = alvo["sucesso"] / base if base else None

    # None (sem dados) vai para o FIM da lista, depois até de quem tem a
    # melhor nota. A chave antiga ("is not None") fazia o contrário: None
    # virava (False, 0), que ordena ANTES de qualquer aproveitamento real —
    # "desconhecido" aparecia como pior do que "0% conhecido", e uma
    # transportadora sem nenhuma cotação no período ia parar no topo da
    # lista dos piores, à frente de quem de fato errou todas.
    return sorted(linhas.values(),
                  key=lambda a: (a["aproveitamento"] is None,
                                 a["aproveitamento"] or 0))


def _preco(bruto: str | None) -> Decimal | None:
    """`resultado.valor` é TEXTO no banco (ver core/banco.py) e pode estar
    ausente ou, em tese, corrompido — daqui não vira exceção, vira None."""
    if bruto is None:
        return None
    try:
        return Decimal(bruto)
    except InvalidOperation:
        return None


def cotacao(con: sqlite3.Connection, cotacao_id: int) -> dict | None:
    """UMA cotação, de QUALQUER usuário, com os resultados e os WhatsApps.

    A porta do adm para a tela de detalhe, e a irmã de
    `banco.buscar_cotacao` — que continua exigindo o dono e NÃO muda: a
    garantia da tela do vendedor (coberta por
    `test_cotacao_de_outro_usuario_nao_abre`) é dela. Duas portas separadas,
    em vez de uma porta com um `if adm` no meio.

    `peso_kg`, `valor_nf` e cada `valor` saem daqui como Decimal, do mesmo
    jeito que `banco.buscar_cotacao` os devolve: são TEXTO no banco, e
    `moeda()` recebendo texto levanta ValueError no meio do render.
    """
    linha = con.execute("SELECT * FROM cotacao WHERE id = ?",
                        (cotacao_id,)).fetchone()
    if linha is None:
        return None

    c = dict(linha)
    c["peso_kg"] = _preco(c["peso_kg"])
    c["valor_nf"] = _preco(c["valor_nf"])
    c["resultados"] = [{**dict(r), "valor": _preco(r["valor"])}
                       for r in con.execute(
                           "SELECT * FROM resultado WHERE cotacao_id = ?"
                           " ORDER BY id", (cotacao_id,))]
    # Quais conversas foram ABERTAS com o texto pronto. Nunca "enviadas" —
    # ver o comentário da tabela em core/banco.py. Na tela do adm isto
    # responde "o vendedor chegou a acionar as manuais?", que é metade da
    # explicação de uma cotação que ficou sem preço.
    c["whatsapp"] = [dict(r) for r in con.execute(
        "SELECT * FROM whatsapp_aberto WHERE cotacao_id = ? ORDER BY id",
        (cotacao_id,))]
    return c


def duracao_s(inicio: str | None, fim: str | None) -> float | None:
    """Segundos entre dois carimbos ISO do banco, ou None. FUNÇÃO PURA.

    None quando falta um dos dois — `respondido_em` é NULL nas linhas
    anteriores a 28/08/2026 — ou quando o texto não é data. A tela escreve
    "sem dados ainda" em vez de fingir zero.

    Negativo também vira None: relógio de máquina que andou para trás é dado
    ruim, e "-3 s" num quadro de instrumentos engana mais do que a lacuna.
    """
    try:
        segundos = (datetime.fromisoformat(fim)
                    - datetime.fromisoformat(inicio)).total_seconds()
    except (TypeError, ValueError):
        return None
    return segundos if segundos >= 0 else None


def falhas_seguidas(con: sqlite3.Connection, *, dias: int = 30,
                    minimo: int = 3) -> list[dict]:
    """Quem está falhando SEGUIDO, da pior para a menos pior.

    É o alerta que motivou o painel inteiro: a Jadlog falhou no login em 5
    tentativas seguidas, da cotação #49 (27/08 16:13) à #56 (28/08 09:22), e
    o problema só foi notado quando um vendedor reclamou — quase um dia
    depois.

    A contagem anda da cotação MAIS NOVA para trás e para na primeira
    resposta que não é falha:

    - `sucesso` e `recusa` PARAM. Recusa é a transportadora respondendo com o
      motivo dela: o site está de pé, que é o que este alerta pergunta.
    - `nossa` (interrompido) é PULADO: foi o servidor reiniciando no meio.
      Não acusa a transportadora nem prova que ela voltou.
    - `inesperado` é pulado pelo mesmo motivo — um status que este módulo
      ainda não conhece não pode nem acusar nem inocentar ninguém.

    `minimo` é 3 porque duas falhas acontecem por acaso; três seguidas, na
    série medida até aqui, sempre foram problema de verdade.

    A janela é a MESMA do resto da tela, e recortá-la nunca INVENTA alerta: o
    que fica de fora é sempre mais velho que a falha mais antiga contada, então
    a contagem só pode sair menor do que a real.
    """
    por_transportadora: dict[str, list] = {}
    for r in con.execute(
            "SELECT r.transportadora, r.status, r.erro, r.cotacao_id,"
            " c.criado_em FROM resultado r"
            " JOIN cotacao c ON c.id = r.cotacao_id"
            " WHERE c.criado_em >= ? ORDER BY r.cotacao_id DESC",
            (_desde(dias),)):
        por_transportadora.setdefault(r["transportadora"], []).append(r)

    alertas = []
    for transportadora, respostas in por_transportadora.items():
        seguidas = []
        for r in respostas:
            classe = categoria(r["status"])
            if classe == "falha":
                seguidas.append(r)
            elif classe in ("nossa", "inesperado"):
                continue
            else:
                break
        if len(seguidas) < minimo:
            continue
        alertas.append({
            "transportadora": transportadora,
            "quantas": len(seguidas),
            # Da mais nova para a mais velha, como vieram do SQL. A tela
            # linka cada uma: sem os números, o alerta manda procurar.
            "ids": [r["cotacao_id"] for r in seguidas],
            "ultima": seguidas[0]["criado_em"],
            "desde": seguidas[-1]["criado_em"],
            # O erro da tentativa mais recente. É o que se leva para a
            # conversa com a transportadora — ou para o .env, quando é senha.
            "erro": seguidas[0]["erro"],
        })

    return sorted(alertas, key=lambda a: (-a["quantas"], a["transportadora"]))


def rotas(con: sqlite3.Connection, dias: int, limite: int = 8) -> list[dict]:
    """As rotas mais cotadas no período, da mais para a menos cotada.

    Agrupa pela CIDADE quando ela existe e pelo CEP quando não — a mesma
    regra que `historico` usa para escrever a rota na linha. Sem ela,
    "Vila Velha -> São Paulo" e "29105770 -> 01310100" contariam separado
    sendo a mesma rota, e as duas apareceriam pela metade do tamanho.

    NULLIF junto do COALESCE porque cidade em branco ("") não é NULL para o
    SQLite: sem ele, as cotações anteriores à busca por CEP viravam um grupo
    " -> " sem nome nenhum no topo da lista.
    """
    return [{"rota": f"{r['origem']} -> {r['destino']}", "cotacoes": r["n"]}
            for r in con.execute(
                "SELECT COALESCE(NULLIF(cidade_origem, ''), cep_origem)"
                " AS origem,"
                " COALESCE(NULLIF(cidade_destino, ''), cep_destino)"
                " AS destino, COUNT(*) AS n FROM cotacao"
                " WHERE criado_em >= ? GROUP BY origem, destino"
                " ORDER BY n DESC, origem, destino LIMIT ?",
                (_desde(dias), limite))]


def historico(con: sqlite3.Connection, *, dias: int = 30,
              usuario: str | None = None, so_com_falha: bool = False,
              limite: int = 200) -> list[dict]:
    """As cotações de TODA a empresa, da mais nova para a mais velha.

    É a diferença central em relação a `banco.listar_cotacoes`, que mostra só
    as do próprio vendedor. Aquela função NÃO muda: a garantia dela é da tela
    do vendedor. Esta é outra porta, para outro público — em vez de um
    `if adm` no meio da que já existe."""
    condicoes = ["criado_em >= ?"]
    valores: list = [_desde(dias)]
    if usuario:
        condicoes.append("usuario = ?")
        valores.append(usuario)
    if so_com_falha:
        # Filtro precisa entrar ANTES do LIMIT: aplicá-lo depois, em Python,
        # deixava o SQL cortar nas `limite` cotações mais recentes e só então
        # descartar as sem falha — se a janela de `dias` tivesse mais que
        # `limite` cotações, falha antiga sumia sem aviso. `sorted()` porque
        # frozenset não garante ordem, e a quantidade de "?" tem que bater
        # com a de valores.
        falhas = sorted(FALHA)
        condicoes.append(
            "id IN (SELECT cotacao_id FROM resultado"
            f" WHERE status IN ({', '.join('?' * len(falhas))}))")
        valores.extend(falhas)

    cotacoes = con.execute(
        f"SELECT * FROM cotacao WHERE {' AND '.join(condicoes)}"
        f" ORDER BY id DESC LIMIT ?", [*valores, limite]).fetchall()
    if not cotacoes:
        return []

    ids = [c["id"] for c in cotacoes]
    marcas = ", ".join("?" * len(ids))
    por_cotacao: dict[int, list] = {i: [] for i in ids}
    for r in con.execute(
            f"SELECT cotacao_id, status, valor FROM resultado"
            f" WHERE cotacao_id IN ({marcas})", ids):
        por_cotacao[r["cotacao_id"]].append(r)

    linhas = []
    for c in cotacoes:
        resultados = por_cotacao[c["id"]]
        contagem: dict[str, int] = {}
        for r in resultados:
            chave = categoria(r["status"])
            contagem[chave] = contagem.get(chave, 0) + 1

        precos = [p for p in (_preco(r["valor"]) for r in resultados)
                  if p is not None]
        linhas.append({
            "id": c["id"],
            "criado_em": c["criado_em"],
            "usuario": c["usuario"],
            "rota": f"{c['cidade_origem'] or c['cep_origem']} -> "
                    f"{c['cidade_destino'] or c['cep_destino']}",
            "material": c["material"],
            # None, não 0: zero seria um preço. Não ter preço é outra coisa.
            "melhor_preco": min(precos) if precos else None,
            "contagem": contagem,
        })
    return linhas


# Quantas horas/dias/meses o gráfico do período mostra. A escolha não é
# estética: 3650 dias em barras de um dia dariam 3650 barras de meio pixel, e
# 24 horas numa barra só não é gráfico nenhum.
def unidade_do_periodo(dias: int) -> str:
    """FUNÇÃO PURA: o tamanho do balde para uma janela de `dias`."""
    if dias <= 2:
        return "hora"
    if dias <= 92:
        return "dia"
    return "mes"


# Quantos caracteres do `criado_em` ISO identificam o balde:
# "2026-09-02T14:33:07" -> 13 é a hora, 10 é o dia, 7 é o mês.
_TAMANHO = {"hora": 13, "dia": 10, "mes": 7}


def _inicio_do_balde(agora: datetime, dias: int, unidade: str) -> datetime:
    """O começo da janela, ALINHADO ao balde.

    Alinhar não é detalhe: com a janela começando às 14h37, o primeiro balde
    cobriria 23 minutos e apareceria como uma queda no gráfico que nunca
    aconteceu."""
    if unidade == "hora":
        return (agora - timedelta(hours=23)).replace(
            minute=0, second=0, microsecond=0)
    if unidade == "dia":
        return (agora - timedelta(days=dias - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
    return agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _chaves(inicio: datetime, fim: datetime, unidade: str) -> list[str]:
    """Todos os baldes da janela, INCLUSIVE os vazios.

    Balde vazio é dado: um dia sem nenhuma cotação é notícia. Sem ele, dois
    dias distantes ficariam colados e o gráfico mostraria um movimento
    contínuo que não existiu."""
    if unidade == "mes":
        chaves, ano, mes = [], inicio.year, inicio.month
        while (ano, mes) <= (fim.year, fim.month):
            chaves.append(f"{ano:04d}-{mes:02d}")
            ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
        return chaves

    passo = timedelta(hours=1) if unidade == "hora" else timedelta(days=1)
    molde = "%Y-%m-%dT%H" if unidade == "hora" else "%Y-%m-%d"
    chaves, quando = [], inicio
    while quando <= fim:
        chaves.append(quando.strftime(molde))
        quando += passo
    return chaves


def serie_por_periodo(con: sqlite3.Connection, dias: int) -> dict:
    """Cotações e cotações-com-preço por balde de tempo, para o gráfico.

    "com preço" usa `status = 'cotado'` — o MESMO critério de
    `resumo_do_dia`. Se aqui contasse `aguardando_retorno` também, o número
    do gráfico e o do cartão do topo discordariam na mesma tela."""
    unidade = unidade_do_periodo(dias)
    agora = datetime.now()
    inicio = _inicio_do_balde(agora, dias, unidade)

    if unidade == "mes":
        # Em meses a janela é longa demais para desenhar inteira: começa no
        # mês da cotação mais antiga que existe, e não em dez anos atrás.
        primeiro = con.execute(
            "SELECT MIN(criado_em) AS m FROM cotacao WHERE criado_em >= ?",
            (_desde(dias),)).fetchone()["m"]
        # Fatiar em vez de fromisoformat: `criado_em` é TEXTO, e uma linha
        # torta derrubaria a tela inteira em vez de sumir de um gráfico.
        if primeiro and len(primeiro) >= 7:
            try:
                inicio = min(inicio, datetime(int(primeiro[:4]),
                                              int(primeiro[5:7]), 1))
            except ValueError:
                pass

    corte = inicio.isoformat(timespec="seconds")
    # O `{tamanho}` no SQL vem de _TAMANHO[unidade], e `unidade` só pode ser
    # uma das três de unidade_do_periodo(). Nada de fora entra nesta string.
    tamanho = _TAMANHO[unidade]
    totais = {r["chave"]: r["n"] for r in con.execute(
        f"SELECT substr(criado_em, 1, {tamanho}) AS chave, COUNT(*) AS n"
        " FROM cotacao WHERE criado_em >= ? GROUP BY chave", (corte,))}
    com_preco = {r["chave"]: r["n"] for r in con.execute(
        f"SELECT substr(c.criado_em, 1, {tamanho}) AS chave,"
        " COUNT(DISTINCT c.id) AS n FROM cotacao c"
        " JOIN resultado r ON r.cotacao_id = c.id"
        " WHERE c.criado_em >= ? AND r.status = 'cotado' GROUP BY chave",
        (corte,))}

    return {"unidade": unidade, "pontos": [
        {"chave": chave, "cotacoes": totais.get(chave, 0),
         "com_preco": com_preco.get(chave, 0)}
        for chave in _chaves(inicio, agora, unidade)]}


def por_usuario(con: sqlite3.Connection, dias: int,
                limite: int = 8) -> list[dict]:
    """Quem cotou quanto no período, do mais ativo para o menos.

    Desempate por nome: sem ele, dois vendedores com a mesma contagem trocam
    de lugar entre dois carregamentos e a lista parece estar mexendo
    sozinha."""
    return [{"usuario": r["usuario"], "cotacoes": r["n"]}
            for r in con.execute(
                "SELECT usuario, COUNT(*) AS n FROM cotacao"
                " WHERE criado_em >= ? GROUP BY usuario"
                " ORDER BY n DESC, usuario LIMIT ?", (_desde(dias), limite))]


# ------------------------------------------------------------------ ao vivo
#
# O painel se atualiza sozinho. Estas duas funcoes existem para ele so se
# REDESENHAR quando algo mudou de verdade: a tela e lida, e refazer a tabela
# debaixo do cursor de quem esta lendo, a cada poucos segundos, para nada, e
# pior do que nao atualizar.

def _assinatura(*partes: object) -> str:
    """Encolhe as partes num rotulo curto o bastante para caber numa URL.

    Nao e seguranca: e um detector de mudanca. blake2s e o hash rapido da
    stdlib, e 8 bytes dao 16 caracteres - colisao aqui atrasaria uma
    atualizacao da tela, nao corromperia nada."""
    cru = "|".join(str(p) for p in partes).encode()
    return hashlib.blake2s(cru, digest_size=8).hexdigest()


def versao_do_painel(con: sqlite3.Connection) -> str:
    """Muda quando entra cotacao nova ou quando alguma transportadora responde.

    Contagens e maiores ids, nao o conteudo das linhas: a consulta roda a cada
    poucos segundos para cada pessoa com o painel aberto, entao precisa ser
    barata.

    `respondido_em` entra por causa do upsert em `banco.salvar_resultado`: a
    resposta que chega depois de a cotacao ter sido dada como `interrompido`
    SOBRESCREVE a linha em vez de criar outra. Sem ela a contagem nao mexe, e
    a tela nunca perceberia essa resposta."""
    return _assinatura(*con.execute(
        "SELECT (SELECT COUNT(*) FROM cotacao),"
        "       (SELECT COALESCE(MAX(id), 0) FROM cotacao),"
        "       (SELECT COUNT(*) FROM resultado),"
        "       (SELECT COALESCE(MAX(id), 0) FROM resultado),"
        "       (SELECT COALESCE(MAX(respondido_em), '') FROM resultado)"
    ).fetchone())


def versao_da_cotacao(con: sqlite3.Connection, cotacao_id: int) -> str:
    """Muda a qualquer mudanca nas respostas DESTA cotacao.

    Aqui a assinatura e EXATA, e nao contagem como no painel: sao no maximo
    seis linhas, e esta e a tela em que se fica olhando a resposta chegar. Uma
    transportadora que sai de `erro` para `cotado` na retentativa nao mexe em
    contagem nenhuma, e precisa aparecer mesmo assim.

    ORDER BY dentro da subconsulta porque a ordem do GROUP_CONCAT nao e
    garantida pelo SQLite: sem ele, a mesma cotacao geraria versoes diferentes
    entre duas leituras e a tela se redesenharia para sempre."""
    (linhas,) = con.execute(
        "SELECT COALESCE(GROUP_CONCAT(assinatura, ';'), '') FROM ("
        "  SELECT transportadora || '/' || status"
        "         || '/' || COALESCE(valor, '')"
        "         || '/' || COALESCE(respondido_em, '') AS assinatura"
        "  FROM resultado WHERE cotacao_id = ? ORDER BY transportadora)",
        (cotacao_id,)).fetchone()
    return _assinatura(linhas)
