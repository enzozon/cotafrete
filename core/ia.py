"""IA do sistema: uma lista de modelos grátis, do melhor para o pior, percorrida
sozinha. Nenhuma tela chama provedor direto — pede aqui e recebe JSON.

Decisão do usuário (24/09/2026): usar os modelos GRÁTIS do Groq e do
OpenRouter, trocando de modelo quando um estoura o limite e voltando aos
melhores quando o limite reseta. Os dados das cotações podem ir para esses
provedores (o usuário aceitou que alguns guardam o que recebem).

Como funciona:
- `CADEIA`: "provedor:modelo" em ordem de preferência (IA_MODELOS no .env
  troca a ordem sem mexer no código).
- Todo pedido COMEÇA DO TOPO. É isso que "volta para os melhores": não há
  estado de "estamos no modelo 3" — há só a lista de quem está de castigo.
- Castigo: o modelo que respondeu 429 (limite) fica fora até o provedor
  liberar (`Retry-After`; "por dia" = até a meia-noite UTC, quando OpenRouter
  e Groq zeram a cota diária). Chave errada, modelo que sumiu e servidor fora
  também ficam fora por um tempo — cada um o seu.
- Resposta que não é o JSON pedido conta como falha e passa ao próximo:
  modelo grátis às vezes responde texto solto.
- Tudo falhou → `IAIndisponivel` com o motivo de cada tentativa. Quem chama
  decide o que fazer (a revisão do ME mostra "indisponível" e segue).

Os dois provedores falam o formato da OpenAI (`/chat/completions`), então é
um cliente só, mudando endereço e chave. `httpx` já é dependência do projeto.

Para usar em outro projeto: copie este arquivo; ele não importa nada do
cotafrete. `REGISTRO` é opcional (aqui grava cada chamada no banco).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

PROVEDORES = {
    # nome: (endereço base, variável da chave no .env)
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}

# A ordem é a escolha. Sem os US$ 10 no OpenRouter (50 pedidos/dia na conta
# toda) o Groq vai na frente: 1.000 pedidos/dia POR MODELO. Conferido nas
# listas oficiais em 24/09/2026 — modelo grátis entra e sai; o que sumir cai
# no castigo de "modelo não existe" e a fila anda.
CADEIA_PADRAO = (
    "groq:openai/gpt-oss-120b",
    "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
    "groq:qwen/qwen3.8-27b",
    "openrouter:nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter:qwen/qwen3.8-27b:free",
    "openrouter:google/gemma-4-31b-it:free",
    "groq:openai/gpt-oss-20b",
)

# Quem aceita `response_format: json_schema` estrito (docs do Groq e o
# `supported_parameters` do OpenRouter, 24/09/2026). Os outros recebem o
# esquema no texto e a resposta é validada do mesmo jeito.
COM_ESQUEMA = {
    "groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b", "groq:qwen/qwen3.8-27b",
    "openrouter:nvidia/nemotron-3-super-120b-a12b:free", "openrouter:qwen/qwen3.8-27b:free",
    "openrouter:google/gemma-4-31b-it:free", "openrouter:google/gemma-4-26b-a4b-it:free",
}

TIMEOUT_S = 90
# Quanto tempo cada tipo de falha deixa o modelo de fora.
CASTIGO_LIMITE_S = 60          # 429 sem dizer quanto esperar
CASTIGO_FORA_DO_AR_S = 120     # 5xx, timeout, rede
CASTIGO_CHAVE_S = 30 * 60      # 401/403: chave errada ou sem permissão
CASTIGO_SUMIU_S = 6 * 3600     # 404/400 de modelo: saiu da lista grátis
CASTIGO_JSON_S = 0             # respondeu fora do formato: tenta o próximo, sem castigo


class IAIndisponivel(RuntimeError):
    """Nenhum modelo da cadeia respondeu. A mensagem diz o porquê de cada um."""


@dataclass
class Resposta:
    dados: Any
    modelo: str                    # "provedor:modelo" que respondeu
    tentativas: list[str] = field(default_factory=list)  # quem falhou antes, e por quê
    duracao_s: float = 0.0


# ------------------------------------------------------------ configuração
def cadeia() -> list[str]:
    """A lista em vigor: IA_MODELOS no .env (separada por vírgula) ou a padrão."""
    texto = os.getenv("IA_MODELOS", "").strip()
    itens = [m.strip() for m in texto.split(",") if m.strip()] if texto else list(CADEIA_PADRAO)
    return [m for m in itens if m.split(":", 1)[0] in PROVEDORES]


def configurada() -> bool:
    """Existe ao menos uma chave para algum modelo da cadeia?"""
    return any(os.getenv(PROVEDORES[m.split(":", 1)[0]][1]) for m in cadeia())


# ------------------------------------------------------------------ castigo
_castigo: dict[str, tuple[float, str]] = {}   # modelo → (até quando, motivo)
_trava = threading.Lock()
agora: Callable[[], float] = time.time        # os testes trocam


def castigados() -> dict[str, tuple[float, str]]:
    with _trava:
        return {m: v for m, v in _castigo.items() if v[0] > agora()}


def _castigar(modelo: str, segundos: float, motivo: str) -> None:
    if segundos > 0:
        with _trava:
            _castigo[modelo] = (agora() + segundos, motivo)


def _ate_meia_noite_utc() -> float:
    d = datetime.fromtimestamp(agora(), tz=timezone.utc)
    amanha = (d + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
    return (amanha - d).total_seconds()


# ------------------------------------------------------------------ chamada
def _post(url: str, chave: str, corpo: dict, provedor: str):
    import httpx
    cab = {"Authorization": f"Bearer {chave}", "Content-Type": "application/json"}
    if provedor == "openrouter":   # identificação opcional pedida pelo OpenRouter
        cab |= {"HTTP-Referer": "https://cotafrete.local", "X-Title": "Cotafrete"}
    return httpx.post(url, headers=cab, json=corpo, timeout=TIMEOUT_S)


POST: Callable[..., Any] = _post              # os testes trocam por um falso
REGISTRO: Callable[..., None] | None = None   # web/app.py liga no banco


def _corpo(modelo_id: str, sistema: str, pedido: str, esquema: dict | None,
           estrito: bool, max_tokens: int) -> dict:
    mensagens = [{"role": "system", "content": sistema}, {"role": "user", "content": pedido}]
    corpo: dict[str, Any] = {"model": modelo_id, "messages": mensagens,
                             "temperature": 0.2, "max_tokens": max_tokens}
    if esquema and estrito:
        corpo["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "resposta", "strict": True, "schema": esquema}}
    elif esquema:
        mensagens[0] = {"role": "system", "content": sistema + (
            "\n\nResponda SOMENTE com um JSON válido, sem texto antes ou depois, "
            "neste esquema:\n" + json.dumps(esquema, ensure_ascii=False))}
    return corpo


def extrair_json(texto: str) -> Any:
    """O JSON da resposta, mesmo cercado de ```json ... ``` ou de uma frase."""
    t = (texto or "").strip()
    cerca = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if cerca:
        t = cerca.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        ini, fim = t.find("{"), t.rfind("}")
        if ini >= 0 and fim > ini:
            return json.loads(t[ini:fim + 1])
        raise


def _motivo_http(r) -> tuple[float, str]:
    """(castigo em segundos, motivo legível) para uma resposta de erro."""
    try:
        corpo = r.text[:400]
    except Exception:
        corpo = ""
    baixo = corpo.lower()
    if r.status_code == 429:
        espera = r.headers.get("retry-after")
        if espera and espera.replace(".", "", 1).isdigit():
            segundos = float(espera)
        elif re.search(r"per[ -]?day|daily|rpd|tpd|free-models-per-day", baixo):
            segundos = _ate_meia_noite_utc()
        else:
            segundos = CASTIGO_LIMITE_S
        diario = segundos > 3600
        return segundos, "limite diário atingido" if diario else "limite por minuto atingido"
    if r.status_code in (401, 403):
        return CASTIGO_CHAVE_S, f"chave recusada ({r.status_code})"
    if r.status_code == 402:
        return _ate_meia_noite_utc(), "sem crédito (402)"
    if r.status_code in (400, 404) and ("model" in baixo or "not found" in baixo):
        return CASTIGO_SUMIU_S, f"modelo indisponível ({r.status_code})"
    if r.status_code >= 500:
        return CASTIGO_FORA_DO_AR_S, f"provedor fora do ar ({r.status_code})"
    return CASTIGO_FORA_DO_AR_S, f"erro {r.status_code}: {corpo[:120]}"


def completar_json(sistema: str, pedido: str, esquema: dict | None = None, *,
                   funcao: str = "", validar: Callable[[Any], Any] | None = None,
                   max_tokens: int = 4000) -> Resposta:
    """Pede um JSON ao primeiro modelo livre da cadeia; falhou, o próximo.

    `validar(dados)` confere o formato e pode devolver os dados já limpos;
    levantar ali = resposta ruim = próximo modelo. `funcao` é só o rótulo do
    registro ("revisão ME", ...)."""
    tentativas: list[str] = []
    inicio = agora()
    for modelo in cadeia():
        provedor, modelo_id = modelo.split(":", 1)
        base, var = PROVEDORES[provedor]
        chave = os.getenv(var)
        if not chave:
            tentativas.append(f"{modelo}: sem {var} no .env")
            continue
        fora = castigados().get(modelo)
        if fora:
            tentativas.append(f"{modelo}: {fora[1]} (volta em {int(fora[0] - agora())} s)")
            continue
        estrito = bool(esquema) and modelo in COM_ESQUEMA
        t0 = agora()
        try:
            r = POST(f"{base}/chat/completions", chave,
                     _corpo(modelo_id, sistema, pedido, esquema, estrito, max_tokens), provedor)
            if r.status_code == 400 and estrito:
                # O provedor recusou o esquema estrito (regra dele mudou, ou o
                # esquema tem algo que ele não aceita): mesma pergunta com o
                # esquema no texto, antes de desistir do modelo.
                r = POST(f"{base}/chat/completions", chave,
                         _corpo(modelo_id, sistema, pedido, esquema, False, max_tokens), provedor)
        except Exception as exc:          # rede, timeout
            _castigar(modelo, CASTIGO_FORA_DO_AR_S, f"sem resposta ({type(exc).__name__})")
            tentativas.append(f"{modelo}: sem resposta ({type(exc).__name__})")
            _registrar(funcao, modelo, False, f"sem resposta ({type(exc).__name__})", agora() - t0)
            continue
        if r.status_code != 200:
            segundos, motivo = _motivo_http(r)
            # Chave recusada é do PROVEDOR, não do modelo: castiga todos os
            # dele, senão a mesma chave errada é testada modelo a modelo.
            for m in ([x for x in cadeia() if x.split(":", 1)[0] == provedor]
                      if r.status_code in (401, 403) else [modelo]):
                _castigar(m, segundos, motivo)
            tentativas.append(f"{modelo}: {motivo}")
            _registrar(funcao, modelo, False, motivo, agora() - t0)
            continue
        try:
            j = r.json()
            if j.get("error"):   # OpenRouter pode devolver 200 com erro do provedor de baixo
                raise ValueError(str(j["error"].get("message", j["error"]))[:120])
            escolha = j["choices"][0]
            if escolha.get("finish_reason") == "length":
                raise ValueError("resposta cortada (max_tokens)")
            dados = extrair_json(escolha["message"].get("content") or "")
            if validar:
                dados = validar(dados)
        except Exception as exc:
            motivo = f"resposta fora do formato ({type(exc).__name__}: {str(exc)[:80]})"
            _castigar(modelo, CASTIGO_JSON_S, motivo)
            tentativas.append(f"{modelo}: {motivo}")
            _registrar(funcao, modelo, False, motivo, agora() - t0)
            continue
        _registrar(funcao, modelo, True, None, agora() - t0)
        return Resposta(dados, modelo, tentativas, agora() - inicio)
    raise IAIndisponivel("nenhum modelo respondeu — " + "; ".join(tentativas or ["cadeia vazia"]))


def _registrar(funcao: str, modelo: str, ok: bool, erro: str | None, duracao: float) -> None:
    if REGISTRO:
        try:
            REGISTRO(funcao=funcao, modelo=modelo, ok=ok, erro=erro, duracao_s=round(duracao, 2))
        except Exception:
            pass   # registro nunca derruba a chamada


# ------------------------------------------------------------- teste manual
def _teste(todos: bool) -> None:
    """`python -m core.ia` (uma chamada pela cadeia) ou `--todos` (cada modelo).
    Gasta 1 pedido, ou 1 por modelo com --todos."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    esquema = {"type": "object", "properties": {"resposta": {"type": "string"}},
               "required": ["resposta"], "additionalProperties": False}
    sistema = "Você responde em português, curto."
    pedido = 'Quanto é 17% de 200? Responda no JSON {"resposta": "..."}'
    for var in {v for _, v in PROVEDORES.values()}:
        print(f"{var}: {'ok' if os.getenv(var) else 'FALTANDO'}")
    lista = cadeia() if todos else [None]
    original = os.environ.get("IA_MODELOS")
    for modelo in lista:
        if modelo:
            os.environ["IA_MODELOS"] = modelo
        try:
            r = completar_json(sistema, pedido, esquema, funcao="teste manual")
            print(f"OK   {r.modelo:<55} {r.duracao_s:5.1f} s  {r.dados}")
            for t in r.tentativas:
                print(f"     antes falhou: {t}")
        except IAIndisponivel as exc:
            print(f"FALHOU {modelo or 'cadeia'}: {exc}")
    if original is None:
        os.environ.pop("IA_MODELOS", None)


if __name__ == "__main__":
    import sys
    _teste("--todos" in sys.argv)
