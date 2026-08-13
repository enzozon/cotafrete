"""O print de diagnóstico não pode derrubar quem está tratando o erro.

Bug visto em produção 13/08/2026: `page.screenshot(full_page=True)` dentro do
`except` do adapter estourou o timeout de 45s, a exceção escapou do `cotar()`
e matou o lote inteiro de cotações — levando junto o erro ORIGINAL, que era a
informação que importava.
"""

from __future__ import annotations

from pathlib import Path

from carriers.base import print_seguro


class PaginaFalsa:
    """Page do Playwright de mentira. `falhas` = quantas chamadas quebram."""

    def __init__(self, falhas: int = 0) -> None:
        self.chamadas: list[dict] = []
        self.falhas = falhas

    def screenshot(self, **kwargs) -> None:
        self.chamadas.append(kwargs)
        if len(self.chamadas) <= self.falhas:
            raise RuntimeError("Page.screenshot: Timeout 45000ms exceeded.")
        Path(kwargs["path"]).write_bytes(b"\x89PNG")


def test_print_que_falha_sempre_nao_propaga(tmp_path):
    """O caso que quebrou o lote: nada pode escapar daqui."""
    pagina = PaginaFalsa(falhas=99)
    assert print_seguro(pagina, tmp_path / "erro.png") == []


def test_evidencia_so_e_listada_se_o_arquivo_existir(tmp_path):
    """Listar um print que não foi gerado manda o operador procurar arquivo
    que não existe, no meio de um incidente."""
    assert print_seguro(PaginaFalsa(falhas=99), tmp_path / "erro.png") == []
    assert not (tmp_path / "erro.png").exists()


def test_cai_para_o_viewport_quando_full_page_trava(tmp_path):
    """full_page=True é o que trava em página longa. O viewport ainda serve
    de evidência — melhor um print parcial do que nenhum."""
    pagina = PaginaFalsa(falhas=1)
    destino = tmp_path / "erro.png"

    assert print_seguro(pagina, destino) == [str(destino)]
    assert len(pagina.chamadas) == 2
    assert pagina.chamadas[0]["full_page"] is True
    assert not pagina.chamadas[1].get("full_page")


def test_caminho_feliz_tira_um_print_so(tmp_path):
    pagina = PaginaFalsa()
    destino = tmp_path / "erro.png"

    assert print_seguro(pagina, destino) == [str(destino)]
    assert len(pagina.chamadas) == 1


def test_timeout_curto_para_nao_queimar_o_do_adapter(tmp_path):
    """45s é o timeout do adapter. O print de diagnóstico não pode gastar
    tudo isso de novo — em lote, são 45s perdidos por cotação."""
    pagina = PaginaFalsa()
    print_seguro(pagina, tmp_path / "erro.png")
    assert pagina.chamadas[0]["timeout"] <= 10_000
