"""Faxina das pastas de print (`teste_real/<transportadora>/<run>/`).

Cada tentativa de cotação cria uma pasta nova e nunca apaga nada — em
produção isso já passava de 250 MB. A tela da cotação (web/layout.py,
`print_embutido`) já tolera evidência que sumiu: uma cotação antiga sem
print continua abrindo normalmente, só sem a imagem. Por isso é seguro
apagar pastas velhas aqui — o histórico de texto (valor, prazo, protocolo)
continua no banco para sempre, só o print pesado expira.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

RAIZ_EVIDENCIAS = Path("teste_real")
DIAS_RETENCAO = 30


def limpar_antigas(raiz: Path = RAIZ_EVIDENCIAS,
                    dias: int = DIAS_RETENCAO) -> int:
    """Apaga pastas de run mais velhas que `dias`. Devolve quantas apagou.

    "Velha" é pela data de modificação da pasta, que reflete o último print
    gravado nela — não a hora atual do sistema de arquivos."""
    if not raiz.exists():
        return 0
    corte = time.time() - dias * 86400
    apagadas = 0
    for pasta_transportadora in raiz.iterdir():
        if not pasta_transportadora.is_dir():
            continue
        for run in pasta_transportadora.iterdir():
            if run.is_dir() and run.stat().st_mtime < corte:
                shutil.rmtree(run, ignore_errors=True)
                apagadas += 1
    return apagadas


if __name__ == "__main__":
    print(f"{limpar_antigas()} pasta(s) de evidência apagada(s).")
