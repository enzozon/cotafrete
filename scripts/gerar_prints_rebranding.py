"""Grava os prints das telas em docs/rebranding/ (390px e 1440px).

Era o test_grava_os_prints_da_documentacao de tests/test_rebranding_visual.py.
Saiu da suíte e da CI: não conferia nada que os outros testes daquele arquivo
não confiram, e levava ~1 min por rodada. Rode à mão depois de mexer no CSS:

    python scripts/gerar_prints_rebranding.py

Usa o mesmo servidor de dado sintético dos testes (banco descartável, nenhuma
cotação real). docs/rebranding/ está no .gitignore.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_rebranding_visual import (  # noqa: E402
    LARGURAS, PRINTS, _abrir, _telas, subir_servidor)


def main() -> None:
    PRINTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as pasta, \
            subir_servidor(Path(pasta)) as (base, cid), \
            sync_playwright() as pw:
        navegador = pw.chromium.launch()
        for perfil, largura, altura in LARGURAS:
            for nome, url in _telas(base, cid):
                ctx = _abrir(navegador, url, largura, altura,
                             adm=nome.startswith(("painel", "login-adm")))
                pagina = ctx.new_page()
                pagina.goto(url, wait_until="networkidle")
                if pagina.url != url:
                    sys.exit(f"Tela {nome} redirecionou para {pagina.url}")
                # A entrada em cascata dos cartões é `both`: sem esperar, o
                # print sai com metade da tela ainda transparente.
                pagina.wait_for_timeout(900)
                destino = PRINTS / f"{nome}-{perfil}.png"
                pagina.screenshot(path=str(destino), full_page=True)
                ctx.close()
                print(destino)
        navegador.close()


if __name__ == "__main__":
    main()
