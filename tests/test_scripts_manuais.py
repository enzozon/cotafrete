"""Os scripts que a gente roda a mao continuam importaveis de qualquer pasta.

Eles sairam da raiz em 18/08/2026 (recon/ e tests/manuais/) e passaram a
depender de um `sys.path.insert` ancorado no __file__ para achar carriers/,
core/ e web/. Quem escrever o proximo recon vai copiar um destes arquivos --
se esquecer o bloco, o script morre no primeiro import, e so descobre na hora
em que precisava dele.

Importa, nao executa: todos tem guarda `if __name__ == "__main__"`, entao
nenhuma cotacao e enviada aqui.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((RAIZ / "recon").glob("*.py")) + \
          sorted((RAIZ / "tests" / "manuais").glob("*.py"))


def test_existe_script_para_conferir():
    """Se a pasta mudar de nome, o teste abaixo passa vazio e nao avisa."""
    assert len(SCRIPTS) >= 10


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_importa_de_outra_pasta(script, tmp_path):
    """Roda com cwd em tmp_path: e ali que a falta do bootstrap aparece."""
    codigo = (
        "import importlib.util as u, sys;"
        f"s = u.spec_from_file_location('script_manual', r'{script}');"
        "m = u.module_from_spec(s); s.loader.exec_module(m)"
    )
    r = subprocess.run([sys.executable, "-c", codigo], cwd=tmp_path,
                       capture_output=True, text=True, timeout=120)

    assert r.returncode == 0, f"{script.name} nao importa:\n{r.stderr}"
