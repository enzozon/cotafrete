from pathlib import Path

from orcamento.config import Config
from orcamento.processador import gerar
from tests.orcamento.hse_falso import HseFalso
from tests.orcamento.planilhas.gerar import VARIANTES, criar


def cfg(tmp_path: Path, dry_run: bool = False) -> Config:
    return Config(usuario="u", senha="s", client_id="ventura", dry_run=dry_run, headless=True,
                  pasta_programa=tmp_path)


def test_gerar_pronto_devolve_numero_pdf_e_relatorio(tmp_path):
    p = criar(tmp_path, None, "orc.xlsx")
    pdfs = tmp_path / "pdfs"
    r = gerar(p, cfg(tmp_path), HseFalso(), pdfs)
    assert r.estado == "pronto" and r.numero == "55555"
    assert r.pdf.exists() and r.pdf.parent == pdfs
    assert "orçamento 55555 salvo" in r.relatorio
    assert r.cliente.startswith("18373 - VENTURA")
    assert p.exists()


def test_gerar_planilha_com_erro_nao_chama_o_hse(tmp_path):
    p = criar(tmp_path, VARIANTES["filial_invalida"], "ruim.xlsx")
    hse = HseFalso()
    r = gerar(p, cfg(tmp_path), hse, tmp_path / "pdfs")
    assert r.estado == "erro" and r.cliente == "" and hse.chamadas == []


def test_gerar_salvo_incerto_vira_incerto_com_numero(tmp_path):
    p = criar(tmp_path, None, "orc.xlsx")
    r = gerar(p, cfg(tmp_path), HseFalso(falhar_em={"salvo_incerto"}), tmp_path / "pdfs")
    assert r.estado == "incerto" and r.numero == "55555" and r.pdf is None
    assert "NÃO reenvie" in r.relatorio


def test_gerar_dav_que_falha_depois_do_salvar_vira_incerto(tmp_path):
    p = criar(tmp_path, None, "orc.xlsx")
    r = gerar(p, cfg(tmp_path), HseFalso(falhar_em={"baixar_dav"}), tmp_path / "pdfs")
    assert r.estado == "incerto" and r.numero == "55555"


def test_gerar_hse_fora_do_ar_vira_adiado(tmp_path):
    p = criar(tmp_path, None, "orc.xlsx")
    r = gerar(p, cfg(tmp_path), HseFalso(indisponivel_em={"buscar_cliente"}), tmp_path / "pdfs")
    assert r.estado == "adiado" and r.numero is None


def test_gerar_dry_run_vira_simulado_sem_pdf(tmp_path):
    p = criar(tmp_path, None, "orc.xlsx")
    r = gerar(p, cfg(tmp_path, dry_run=True), HseFalso(), tmp_path / "pdfs")
    assert r.estado == "simulado" and r.pdf is None
    assert not (tmp_path / "pdfs").exists()
