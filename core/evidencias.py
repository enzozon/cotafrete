"""Faxina das pastas de print (`teste_real/<transportadora>/<run>/`).

Cada tentativa de cotação cria uma pasta nova e nunca apaga nada — em
produção isso já passava de 250 MB. A tela da cotação (web/layout.py,
`print_embutido`) já tolera evidência que sumiu: uma cotação antiga sem
print continua abrindo normalmente, só sem a imagem. Por isso é seguro
apagar pastas velhas aqui — o histórico de texto (valor, prazo, protocolo)
continua no banco para sempre, só o print pesado expira.
"""

from __future__ import annotations

import io
import shutil
import time
import zipfile
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


def montar_zip_de_prints(resultados: list[dict]) -> bytes:
    """O print final de cada transportadora que respondeu, num .zip só —
    e o PDF da proposta, para quem responde por e-mail.

    Usado tanto pela tela do vendedor quanto pelo painel adm — mesma regra
    nos dois: só o print já mostrado na tela (não as etapas intermediárias,
    que não têm registro no banco). Evidência apagada pela retenção é
    ignorada, não erro: o zip sai só com o que ainda existe."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in resultados:
            caminho = r["evidencia"]
            if caminho and Path(caminho).exists():
                # A extensão do ARQUIVO, não .png fixo: a Della Volpe entra
                # com o PDF da proposta, e "dellavolpe.png" com PDF dentro
                # não abre em lugar nenhum.
                extensao = Path(caminho).suffix.lower() or ".png"
                zf.write(caminho,
                         arcname=f'{r["transportadora"]}{extensao}')
    return buffer.getvalue()


if __name__ == "__main__":
    print(f"{limpar_antigas()} pasta(s) de evidência apagada(s).")
