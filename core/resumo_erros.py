"""Resumo do dia no /adm: o que deu errado hoje, em português simples.

Pedido do usuário (24/09/2026): em vez de ler "TimeoutError: Locator.click"
no histórico, o administrador lê "a Generoso falhou 5 vezes por CEP fora de
área; a leitura do ME caiu 2 vezes às 14h" — e o que fazer.

Três camadas, e só a do meio é IA:
1. `fatos_do_dia` (código, SQL): junta os problemas do dia de todas as
   fontes — resultado das transportadoras, leitura do ME (`me_varredura`),
   eventos de problema do ME (`painel_me.EVENTOS_PROBLEMA`), e-mails da Della
   Volpe que não viraram preço, chamadas de IA que falharam — agrupados por
   mensagem de erro, com quantas vezes e em que horas.
2. `pedir_resumo` (IA, core/ia.py): transforma os fatos em manchete + itens
   com gravidade e "o que fazer".
3. `_validador` (código): todo número que a IA escrever tem de existir nos
   fatos. "Falhou 7 vezes" quando foram 5 é resposta ruim — vai para o
   próximo modelo da cadeia, como JSON fora do formato.

`resumo_sem_ia` sai direto dos fatos e aparece SEMPRE: sem chave, com a IA
fora do ar, ou antes de alguém pedir o resumo, o administrador não fica sem
nada. O resumo da IA fica guardado por dia (tabela `resumo_ia`, criada aqui
mesmo) com a assinatura dos fatos — mudou alguma coisa desde então, a tela
diz "desatualizado" e oferece gerar de novo. Nada chama a IA ao abrir a
página: só o botão.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime

from core import ia

FUNCAO = "resumo de erros"
FALHA = ("erro", "intervencao_necessaria")          # core/painel.FALHA
MAX_GRUPOS = 6       # mensagens distintas por fonte que vão para a IA
MAX_ITENS = 8
GRAVIDADES = ("critico", "atencao", "info")
CONTAS_ME = {"ventura": "VENTURA", "uniao": "UNIÃO"}

ESQUEMA = {
    "type": "object",
    "properties": {
        "manchete": {"type": "string"},
        "itens": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "gravidade": {"type": "string", "enum": list(GRAVIDADES)},
                "texto": {"type": "string"},
                "o_que_fazer": {"type": "string"},
            },
            "required": ["gravidade", "texto", "o_que_fazer"],
            "additionalProperties": False,
        }},
    },
    "required": ["manchete", "itens"],
    "additionalProperties": False,
}

SISTEMA = """Você escreve o resumo do dia de um sistema de cotação de frete para o
ADMINISTRADOR da empresa (Ventura, distribuidora no Espírito Santo). Ele não é
programador. Você recebe em JSON os problemas de hoje: falhas das
transportadoras (robôs que cotam nos sites delas), leitura do Mercado
Eletrônico (portal de compras onde clientes pedem cotação), e-mails de
proposta da Della Volpe que não viraram preço, e chamadas de IA que falharam.

Escreva em português simples, sem jargão técnico: troque "timeout" por
"demorou demais para responder", "selector" por "a página não mostrou o que
o robô esperava", "429" por "limite de uso atingido", e assim por diante.

- manchete: uma frase com o mais importante do dia.
- itens: um por problema, do mais grave para o menos grave, no máximo 8.
  - gravidade: "critico" (vendedores estão sem cotar ou algo parou de vez),
    "atencao" (falhas repetidas, vale olhar hoje), "info" (pontual).
  - texto: o que aconteceu, com quantas vezes e em que horário, se os fatos
    trouxerem ("a Generoso falhou 5 vezes entre 14h e 16h porque...").
  - o_que_fazer: uma ação concreta e curta para o administrador.

O que NÃO bloqueia ninguém (nunca "critico"): "revisão IA indisponível" (a
resposta do ME segue sem a revisão), falha de UM modelo de IA, e-mail da Della
Volpe sem PDF (costuma ser outro e-mail da conversa, não a proposta).

Contexto do sistema de hoje: a IA usa as chaves GROQ_API_KEY e
OPENROUTER_API_KEY (modelos grátis). Mensagem antiga que cite ANTHROPIC_API_KEY
é de uma versão anterior — não mande configurar essa chave.

REGRA: use SOMENTE números que estão no JSON. Não some, não arredonde, não
invente quantidades, horários ou percentuais. Se não souber a causa, diga
que a causa não está clara e cite a mensagem de erro resumida."""


# -------------------------------------------------------------- os fatos
def _chave(erro: str | None) -> str:
    """Agrupa mensagens iguais a menos de números (CEP, CNPJ, id, tempo)."""
    t = " ".join(str(erro or "sem mensagem").split())[:160]
    return re.sub(r"\d+", "#", t)


def _hora(iso: str | None) -> str | None:
    m = re.search(r"[T ](\d{2}):", iso or "")
    return f"{int(m.group(1))}h" if m else None


def _agrupar(linhas: list[tuple[str | None, str | None]]) -> list[dict]:
    """[(mensagem, quando)] → [{erro, vezes, horas}], do mais comum ao menos."""
    grupos: dict[str, dict] = {}
    for erro, quando in linhas:
        g = grupos.setdefault(_chave(erro), {"erro": " ".join(str(erro or "sem mensagem").split())[:200],
                                             "vezes": 0, "horas": []})
        g["vezes"] += 1
        h = _hora(quando)
        if h and h not in g["horas"]:
            g["horas"].append(h)
    return sorted(grupos.values(), key=lambda g: -g["vezes"])[:MAX_GRUPOS]


def _legivel(texto: str | None) -> str | None:
    """Assunto de e-mail gravado ainda em MIME ("=?utf-8?b?Q290YcOnw6Nv?=")
    → "Cotação". O ingestor guarda o `Subject` cru no desfecho `sem_pdf`."""
    from carriers.dellavolpe.ingestor import texto_do_cabecalho
    return texto_do_cabecalho(texto) if texto else texto


def _tabela_existe(con: sqlite3.Connection, nome: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (nome,)).fetchone() is not None


def _transportadoras(con, dia: str, nome_de) -> list[dict]:
    por: dict[str, dict] = {}
    for r in con.execute(
            "SELECT r.transportadora, r.status, r.erro,"
            " COALESCE(r.respondido_em, c.criado_em) AS quando"
            " FROM resultado r JOIN cotacao c ON c.id = r.cotacao_id"
            " WHERE c.criado_em LIKE ?", (f"{dia}%",)):
        t = por.setdefault(r["transportadora"], {"cotacoes": 0, "recusas": 0, "falhas": []})
        t["cotacoes"] += 1
        if r["status"] in FALHA:
            t["falhas"].append((r["erro"], r["quando"]))
        elif r["status"] == "recusado":
            t["recusas"] += 1
    return [{"transportadora": nome_de(slug), "cotacoes": t["cotacoes"],
             "falhas": len(t["falhas"]), "recusas": t["recusas"],
             "erros": _agrupar(t["falhas"])}
            for slug, t in sorted(por.items(), key=lambda kv: -len(kv[1]["falhas"]))
            if t["falhas"]]


def _leitura_me(con, dia: str) -> list[dict]:
    if not _tabela_existe(con, "me_varredura"):
        return []
    por: dict[str, dict] = defaultdict(lambda: {"leituras": 0, "falhas": []})
    for r in con.execute("SELECT conta, ok, erro, quando FROM me_varredura WHERE quando LIKE ?",
                         (f"{dia}%",)):
        c = por[r["conta"]]
        c["leituras"] += 1
        if not r["ok"]:
            c["falhas"].append((r["erro"], r["quando"]))
    return [{"conta": CONTAS_ME.get(conta, conta), "leituras": c["leituras"],
             "falhas": len(c["falhas"]), "erros": _agrupar(c["falhas"])}
            for conta, c in sorted(por.items()) if c["falhas"]]


def _problemas_me(con, dia: str) -> list[dict]:
    if not _tabela_existe(con, "me_historico"):
        return []
    from core.painel_me import EVENTOS_PROBLEMA
    marcas = ", ".join("?" * len(EVENTOS_PROBLEMA))
    linhas = con.execute(
        f"SELECT h.evento, h.detalhe, h.quando, c.numero FROM me_historico h"
        f" LEFT JOIN me_cotacao c ON c.id = h.cotacao_id"
        f" WHERE h.quando LIKE ? AND h.evento IN ({marcas})",
        (f"{dia}%", *EVENTOS_PROBLEMA)).fetchall()
    saida = []
    for evento in EVENTOS_PROBLEMA:
        deste = [r for r in linhas if r["evento"] == evento]
        if deste:
            saida.append({"evento": evento, "vezes": len(deste),
                          "cotacoes_me": sorted({r["numero"] for r in deste if r["numero"]})[:5],
                          "detalhes": _agrupar([(r["detalhe"], r["quando"]) for r in deste])})
    return saida


def _emails_della_volpe(con, dia: str) -> list[dict]:
    if not _tabela_existe(con, "email_processado"):
        return []
    linhas = con.execute(
        "SELECT desfecho, detalhe, processado_em FROM email_processado"
        " WHERE processado_em LIKE ? AND desfecho != 'gravado'", (f"{dia}%",)).fetchall()
    por: dict[str, list] = defaultdict(list)
    for r in linhas:
        por[r["desfecho"]].append((_legivel(r["detalhe"]), r["processado_em"]))
    return [{"desfecho": d, "vezes": len(v), "detalhes": _agrupar(v)} for d, v in sorted(por.items())]


def _ia(con, dia: str) -> list[dict]:
    if not _tabela_existe(con, "ia_chamada"):
        return []
    por: dict[str, dict] = defaultdict(lambda: {"chamadas": 0, "falhas": []})
    for r in con.execute("SELECT funcao, ok, erro, quando FROM ia_chamada WHERE quando LIKE ?",
                         (f"{dia}%",)):
        f = por[r["funcao"]]
        f["chamadas"] += 1
        if not r["ok"]:
            f["falhas"].append((r["erro"], r["quando"]))
    # falha de UM modelo que o próximo cobriu é o normal da cadeia grátis;
    # só entra no resumo quando falhou mais do que respondeu
    return [{"funcao": fn, "tentativas": f["chamadas"], "falhas": len(f["falhas"]),
             "motivos": _agrupar(f["falhas"])}
            for fn, f in sorted(por.items()) if len(f["falhas"]) * 2 > f["chamadas"]]


def fatos_do_dia(con: sqlite3.Connection, dia: date, nome_de=lambda s: s) -> dict:
    """Todos os problemas de `dia`, agrupados. Só leitura. `nome_de`: slug → nome."""
    d = dia.isoformat()
    return {
        "dia": dia.strftime("%d/%m/%Y"),
        "transportadoras": _transportadoras(con, d, nome_de),
        "leitura_mercado_eletronico": _leitura_me(con, d),
        "problemas_mercado_eletronico": _problemas_me(con, d),
        "emails_della_volpe_sem_preco": _emails_della_volpe(con, d),
        "ia_com_falhas": _ia(con, d),
    }


def tem_problema(fatos: dict) -> bool:
    return any(v for k, v in fatos.items() if k != "dia")


def assinatura(fatos: dict) -> str:
    return hashlib.sha256(json.dumps(fatos, sort_keys=True, ensure_ascii=False)
                          .encode()).hexdigest()[:16]


# ---------------------------------------------------- resumo sem IA (sempre)
def _horas(*grupos: dict) -> str:
    """As horas de TODOS os grupos: "sem carimbo 2×" com um às 10h e outro às
    13h não pode sair só "(10h)"."""
    h = sorted({x for g in grupos for x in g["horas"]}, key=lambda s: int(s[:-1]))
    return "" if not h else f" ({h[0]})" if len(h) == 1 else f" ({h[0]} a {h[-1]})"


def resumo_sem_ia(fatos: dict) -> list[str]:
    """Uma linha por problema, direto dos fatos. Nunca falha, nunca inventa."""
    linhas = []
    for t in fatos["transportadoras"]:
        principal = t["erros"][0]
        linhas.append(f"{t['transportadora']}: {t['falhas']} falha(s) em {t['cotacoes']} "
                      f"resultado(s) — mais comum: “{principal['erro'][:90]}” "
                      f"{principal['vezes']}×{_horas(principal)}.")
    for c in fatos["leitura_mercado_eletronico"]:
        g = c["erros"][0]
        linhas.append(f"Leitura do ME ({c['conta']}): {c['falhas']} de {c['leituras']} falharam"
                      f"{_horas(*c['erros'])} — “{g['erro'][:90]}”.")
    for p in fatos["problemas_mercado_eletronico"]:
        linhas.append(f"Mercado Eletrônico — {p['evento']}: {p['vezes']}×"
                      f"{_horas(*p['detalhes'])}.")
    for e in fatos["emails_della_volpe_sem_preco"]:
        linhas.append(f"Della Volpe — e-mail sem preço ({e['desfecho']}): {e['vezes']}×"
                      f"{_horas(*e['detalhes'])}.")
    for f in fatos["ia_com_falhas"]:
        linhas.append(f"IA — {f['funcao']}: {f['falhas']} de {f['tentativas']} tentativas falharam.")
    return linhas


# ------------------------------------------------------------------ IA
def _numeros(texto: str) -> set[str]:
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+", texto)}


def _validador(fatos: dict):
    permitidos = _numeros(json.dumps(fatos, ensure_ascii=False))

    def validar(dados) -> dict:
        if not isinstance(dados, dict) or not isinstance(dados.get("itens"), list):
            raise ValueError("sem manchete/itens")
        manchete = " ".join(str(dados.get("manchete") or "").split())[:300]
        itens = []
        for it in dados["itens"][:MAX_ITENS]:
            if not isinstance(it, dict) or it.get("gravidade") not in GRAVIDADES:
                raise ValueError("item fora do formato")
            itens.append({"gravidade": it["gravidade"],
                          "texto": " ".join(str(it.get("texto") or "").split())[:500],
                          "o_que_fazer": " ".join(str(it.get("o_que_fazer") or "").split())[:300]})
        if not manchete or not itens:
            raise ValueError("resumo vazio")
        inventados = _numeros(manchete + " " + " ".join(i["texto"] + " " + i["o_que_fazer"]
                                                        for i in itens)) - permitidos
        if inventados:
            raise ValueError(f"números que não estão nos fatos: {sorted(inventados)[:5]}")
        itens.sort(key=lambda i: GRAVIDADES.index(i["gravidade"]))
        return {"manchete": manchete, "itens": itens}
    return validar


def pedir_resumo(fatos: dict) -> ia.Resposta:
    """Levanta ia.IAIndisponivel se nenhum modelo der um resumo que passe."""
    return ia.completar_json(SISTEMA, "Problemas de hoje:\n" + json.dumps(fatos, ensure_ascii=False,
                                                                          indent=1),
                             ESQUEMA, funcao=FUNCAO, validar=_validador(fatos), max_tokens=2500)


# --------------------------------------------------------------- cache
def _criar_tabela(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS resumo_ia ("
                " dia TEXT PRIMARY KEY, gerado_em TEXT NOT NULL, assinatura TEXT NOT NULL,"
                " modelo TEXT, dados TEXT NOT NULL)")


def guardado(con: sqlite3.Connection, dia: date) -> dict | None:
    """O último resumo da IA de `dia`, ou None. {manchete, itens, modelo, gerado_em, assinatura}."""
    _criar_tabela(con)
    r = con.execute("SELECT * FROM resumo_ia WHERE dia = ?", (dia.isoformat(),)).fetchone()
    if r is None:
        return None
    return json.loads(r["dados"]) | {"modelo": r["modelo"], "gerado_em": r["gerado_em"],
                                     "assinatura": r["assinatura"]}


def gerar(con: sqlite3.Connection, dia: date, nome_de=lambda s: s,
          agora: datetime | None = None) -> dict:
    """Pede o resumo à IA e guarda. Sem problema no dia: guarda sem chamar a IA."""
    fatos = fatos_do_dia(con, dia, nome_de)
    if tem_problema(fatos):
        r = pedir_resumo(fatos)
        dados, modelo = r.dados, r.modelo
    else:
        dados, modelo = {"manchete": "Nenhum erro registrado hoje.", "itens": []}, None
    _criar_tabela(con)
    con.execute("INSERT OR REPLACE INTO resumo_ia (dia, gerado_em, assinatura, modelo, dados)"
                " VALUES (?, ?, ?, ?, ?)",
                (dia.isoformat(), (agora or datetime.now()).isoformat(timespec="seconds"),
                 assinatura(fatos), modelo, json.dumps(dados, ensure_ascii=False)))
    con.commit()
    return guardado(con, dia)
