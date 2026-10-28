"""IA opcional para produto novo: resume a descrição, escolhe o GRUPO da lista do HSE e pesquisa o NCM.

Modos (IA no .env): desligada | api (ANTHROPIC_API_KEY).
Toda chamada vai para ia_uso.csv (modo:tarefa, tokens e custo); `python -m orcamento.ia` mostra o relatório.
Falhou (limite do plano, rede, resposta ruim)? Devolve None e o robô segue como se não houvesse IA.
"""
import csv
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from orcamento.config import Config
from orcamento.planilha import normalizar

log = logging.getLogger("robo")

MAX_DESCRICAO = 100
MIN_PALAVRAS_DO_TEXTO = 0.6  # fração das palavras do resumo que precisa existir no texto original
DIAS_UTEIS_MES = 22
MAX_BUSCAS_WEB = 3
# US$ por 1 milhão de tokens (entrada, saída) — tabela da Anthropic de out/2026
PRECOS = {"claude-haiku-5-5": (0.10, 0.50)}
COLUNAS = ["data", "modo", "modelo", "tokens_entrada", "tokens_saida", "custo_usd", "ok", "detalhe"]

INSTRUCAO_RESUMO = (
    "Você resume descrições de produtos para o cadastro de um ERP. Responda SOMENTE com a descrição, "
    "em uma linha, em MAIÚSCULAS, sem acentos e com no máximo 100 caracteres. Mantenha o tipo do produto, "
    "a marca, o modelo/referência e as características que o diferenciam (capacidade, cor, voltagem). "
    "Não invente nenhum dado que não esteja no texto."
)
INSTRUCAO_GRUPO = (
    "Você classifica produtos no cadastro de um ERP. Escolha, da lista de grupos enviada, o grupo que melhor "
    "classifica o produto. Responda SOMENTE com o nome do grupo, exatamente como está na lista."
)
INSTRUCAO_NCM = (
    "Você descobre o NCM (Nomenclatura Comum do Mercosul, 8 dígitos) de produtos vendidos no Brasil. "
    "Pesquise na internet o NCM usado em nota fiscal para o produto enviado (prefira o modelo exato, "
    "depois o tipo de produto). Responda SOMENTE em uma linha no formato NCM=XXXXXXXX."
)


@dataclass(frozen=True)
class Ajudantes:
    """O que a IA sabe fazer para o processador; None = desligado."""
    resumir: Callable[[str], str | None] | None = None
    grupo: Callable[[str, list[str]], str | None] | None = None
    ncm: Callable[[str], str | None] | None = None


# --- chamadas ------------------------------------------------------------------

def _rodar_api(prompt: str, modelo: str, instrucao: str, web: bool = False) -> tuple[str, int, int]:
    import anthropic  # só necessário no modo api

    extra = {"tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_BUSCAS_WEB}]} if web else {}
    resp = anthropic.Anthropic().messages.create(
        model=modelo, max_tokens=4096, system=instrucao,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}], **extra,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("modelo recusou o pedido")
    u = resp.usage
    entrada = u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
    return "".join(b.text for b in resp.content if b.type == "text"), entrada, u.output_tokens


def _custo(modelo: str, entrada: int, saida: int) -> float:
    p_in, p_out = PRECOS.get(modelo, (0.0, 0.0))
    return (entrada * p_in + saida * p_out) / 1_000_000


def _chamar(cfg: Config, prompt: str, instrucao: str, web: bool) -> tuple[str, int, int, float]:
    bruto, entrada, saida = _rodar_api(prompt, cfg.ia_modelo, instrucao, web)
    return bruto, entrada, saida, _custo(cfg.ia_modelo, entrada, saida)


def _registrar(caminho: Path, modo: str, modelo: str, entrada: int, saida: int, custo: float,
               ok: bool, detalhe: str) -> None:
    novo = not caminho.exists()
    with open(caminho, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if novo:
            w.writerow(COLUNAS)
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), modo, modelo, entrada, saida,
                    f"{custo:.6f}", "sim" if ok else "nao", detalhe])


def _ler_cache(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _perguntar(cfg: Config, tarefa: str, instrucao: str, prompt: str,
               validar: Callable[[str], tuple[str | None, str]], web: bool = False) -> str | None:
    """Pergunta com cache (mesma pergunta → mesma resposta), validação e registro de uso.
    `validar(bruto)` devolve (resposta aceita ou None, motivo da recusa)."""
    uso = cfg.pasta_programa / "ia_uso.csv"
    cache_path = cfg.pasta_programa / "ia_cache.json"
    chave = hashlib.sha256(f"{tarefa}\n{normalizar(prompt)}".encode("utf-8")).hexdigest()
    cache = _ler_cache(cache_path)
    if chave in cache:  # reprocessar a mesma planilha não muda o produto cadastrado
        return cache[chave]
    modo = f"{cfg.ia}:{tarefa}"
    try:
        bruto, entrada, saida, custo = _chamar(cfg, prompt, instrucao, web)
    except Exception as e:  # noqa: BLE001 — IA nunca derruba o robô
        log.warning("IA (%s) indisponível: %s", modo, (str(e).splitlines() or [repr(e)])[0][:200])
        _registrar(uso, modo, cfg.ia_modelo, 0, 0, 0.0, False, str(e)[:200])
        return None
    resposta, motivo = validar(bruto)
    _registrar(uso, modo, cfg.ia_modelo, entrada, saida, custo, resposta is not None, motivo)
    if resposta is None:
        return None
    cache_path.write_text(json.dumps({**cache, chave: resposta}, ensure_ascii=False, indent=1), encoding="utf-8")
    return resposta


# --- tarefas ---------------------------------------------------------------------

def _limpar(bruto: str) -> str:
    linhas = [l for l in (bruto or "").strip().splitlines() if l.strip()]
    return normalizar(linhas[0].strip().strip("\"'")) if linhas else ""


def _vem_do_texto(resumo: str, original: str) -> bool:
    """Trava contra resposta estranha: a maioria das palavras do resumo tem que estar no texto original."""
    fonte = normalizar(original)
    palavras = [p for p in re.findall(r"[A-Z0-9]+", resumo) if len(p) >= 3]
    return bool(palavras) and sum(p in fonte for p in palavras) / len(palavras) >= MIN_PALAVRAS_DO_TEXTO


def _resumir(cfg: Config, texto: str) -> str | None:
    def validar(bruto: str) -> tuple[str | None, str]:
        resumo = _limpar(bruto)
        if not resumo or len(resumo) > MAX_DESCRICAO:
            return None, f"resposta inválida: {bruto[:80]!r}"
        if not _vem_do_texto(resumo, texto):
            return None, f"resposta não vem do texto original: {resumo[:80]!r}"
        return resumo, ""
    return _perguntar(cfg, "resumo", INSTRUCAO_RESUMO, texto, validar)


def _grupo(cfg: Config, descricao: str, grupos: list[str]) -> str | None:
    por_nome = {normalizar(g): g for g in grupos}

    def validar(bruto: str) -> tuple[str | None, str]:
        g = por_nome.get(_limpar(bruto))
        return (g, "") if g else (None, f"grupo fora da lista: {bruto[:80]!r}")
    prompt = f"Produto: {descricao}\n\nGrupos:\n" + "\n".join(grupos)
    return _perguntar(cfg, "grupo", INSTRUCAO_GRUPO, prompt, validar)


def _ncm(cfg: Config, descricao: str) -> str | None:
    def validar(bruto: str) -> tuple[str | None, str]:
        m = re.search(r"NCM\s*[=:]?\s*(\d{4})\.?(\d{2})\.?(\d{2})", bruto or "", re.I)
        return ("".join(m.groups()), "") if m else (None, f"NCM não encontrado na resposta: {bruto[:80]!r}")
    return _perguntar(cfg, "ncm", INSTRUCAO_NCM, f"Produto: {descricao}", validar, web=True)


def ajudantes(cfg: Config) -> Ajudantes:
    if cfg.ia != "api":
        return Ajudantes()
    if cfg.ia == "api" and cfg.ia_chave:
        os.environ.setdefault("ANTHROPIC_API_KEY", cfg.ia_chave)
    return Ajudantes(resumir=lambda t: _resumir(cfg, t),
                     grupo=lambda d, gs: _grupo(cfg, d, gs),
                     ncm=lambda d: _ncm(cfg, d))


def resumidor(cfg: Config) -> Callable[[str], str | None] | None:
    return ajudantes(cfg).resumir


# --- relatório -------------------------------------------------------------------

def relatorio_uso(caminho: Path, por_dia: int = 40) -> str:
    """Resumo do ia_uso.csv por modo:tarefa e projeção: custo médio por chamada × chamadas por dia."""
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            linhas = [l for l in csv.DictReader(f, delimiter=";") if l["ok"] == "sim"]
    except FileNotFoundError:
        return "Nenhuma chamada de IA registrada ainda."
    partes = []
    for modo in sorted({l["modo"] for l in linhas}):
        do_modo = [l for l in linhas if l["modo"] == modo]
        media = sum(float(l["custo_usd"]) for l in do_modo) / len(do_modo)
        entrada = sum(int(l["tokens_entrada"]) for l in do_modo) / len(do_modo)
        saida = sum(int(l["tokens_saida"]) for l in do_modo) / len(do_modo)
        partes.append(
            f"{modo}: {len(do_modo)} chamada(s), média {entrada:.0f} tokens de entrada e {saida:.0f} de saída, "
            f"US$ {media:.6f} por chamada → {por_dia} por dia = US$ {media * por_dia:.4f} por dia, "
            f"US$ {media * por_dia * DIAS_UTEIS_MES:.2f} por mês ({DIAS_UTEIS_MES} dias úteis)")
    return "\n".join(partes) or "Nenhuma chamada de IA bem-sucedida registrada ainda."


if __name__ == "__main__":
    from orcamento.config import config_do_ambiente

    c = config_do_ambiente()
    sys.stdout.reconfigure(errors="replace")  # console cp1252
    print(relatorio_uso(c.pasta_programa / "ia_uso.csv", por_dia=40))
