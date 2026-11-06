"""Teste de fumaça do DAV (P2 #14): uma vez por dia, pouco depois das 8h, pelo
`atualizar.py`: `python -m orcamento.fumaca`.

Confere um DAV de mentira no HSE com `HseSoLeitura`, o mesmo caminho da tela de
conferência: nunca inclui nem salva. Código pronto na planilha e IA desligada,
então não gasta crédito. Falhou, avisa por e-mail; passou, fica só no log.

Cliente, vendedor e produto vêm do .env (`FUMACA_CLIENTE`, `FUMACA_VENDEDOR`,
`FUMACA_CODIGO`) porque o repositório é público. Têm de existir no HSE: um
vendedor que saiu da empresa vira aviso aqui até trocar o valor.
"""
from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

import openpyxl

from core.resumo_email import enviar
from orcamento.config import Config, config_do_ambiente
from orcamento.processador import _sem_segredo, conferir

VARIAVEIS = ("FUMACA_CLIENTE", "FUMACA_VENDEDOR", "FUMACA_CODIGO")
ASSUNTO = "Teste de fumaça do DAV falhou"
AJUDA = ("Teste diário das 8h, só leitura: um DAV de mentira conferido no HSE. "
         "Nada foi gravado.\nSe o vendedor do teste saiu da empresa ou o produto "
         "mudou, troque FUMACA_* no .env da VM.")


def montar_planilha(destino: Path, env: Mapping[str, str]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ORÇAMENTO"
    # Valor alto para o limite de desconto nunca barrar o teste.
    ws["A2"], ws["B2"], ws["J2"], ws["K2"] = "TESTE DE FUMACA", 1, 99999, env["FUMACA_CODIGO"]
    ws["B31"], ws["B33"] = env["FUMACA_CLIENTE"], env["FUMACA_VENDEDOR"]
    ws["B32"], ws["B34"], ws["B35"] = 30, "Deposito", "60 DIAS"
    ws["A38"], ws["B38"] = "Frete", "CIF"
    wb.save(destino)
    return destino


def _criar_hse(cfg: Config):
    from orcamento.hse import HseSoLeitura   # só carrega o playwright quando roda de verdade
    return HseSoLeitura(cfg)


def rodar(cfg: Config, env: Mapping[str, str],
          criar_hse: Callable[[Config], object] = _criar_hse) -> list[str]:
    """O que está errado; lista vazia = passou."""
    cfg = replace(cfg, dry_run=True, ia="desligada", pasta_programa=Path("davs"))
    try:
        with tempfile.TemporaryDirectory() as pasta:
            with criar_hse(cfg) as hse:
                conf = conferir(montar_planilha(Path(pasta) / "fumaca.xlsx", env), cfg, hse)
                bloqueados = list(hse.bloqueados)
    except Exception as e:  # noqa: BLE001 — login, navegador: é o que este teste existe para avisar
        return [f"{type(e).__name__}: {_sem_segredo(str(e))}"]
    falhas = [f"O robô tentou gravar no HSE (bloqueado): {_sem_segredo(b)}" for b in bloqueados]
    if conf.estado == "nao_conferido":
        falhas.append("HSE indisponível: a conferência não terminou.")
    return falhas + [_sem_segredo(e) for e in conf.erros]


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    faltam = [k for k in VARIAVEIS if not os.environ.get(k)]
    if faltam:   # é configuração, não HSE quebrado: fica no log, sem e-mail diário
        print(f"Teste de fumaça não rodou: faltam {', '.join(faltam)} no .env")
        return 1
    try:
        cfg = config_do_ambiente()
    except ValueError as e:
        print(f"Teste de fumaça não rodou: {e}")
        return 1
    falhas = rodar(cfg, os.environ)
    if not falhas:
        print("Teste de fumaça: OK")
        return 0
    print("Teste de fumaça FALHOU: " + " | ".join(falhas))
    try:
        enviar(ASSUNTO, "\n".join([*falhas, "", AJUDA]))
    except Exception as e:  # noqa: BLE001 — sem e-mail, ao menos o log diz
        print(f"E-mail do teste de fumaça falhou: {type(e).__name__}: {str(e)[:200]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
