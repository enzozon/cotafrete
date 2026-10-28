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


def test_gerar_chama_ao_salvar_antes_de_baixar_dav(tmp_path):
    p = criar(tmp_path, None, "orc.xlsx")
    hse = HseFalso()
    r = gerar(p, cfg(tmp_path), hse, tmp_path / "pdfs", lambda n: hse.chamadas.append(("ao_salvar", n)))
    assert r.estado == "pronto"
    nomes = hse.nomes()
    assert nomes.index("ao_salvar") == nomes.index("salvar_orcamento") + 1 < nomes.index("baixar_dav")
    assert ("ao_salvar", "55555") in hse.chamadas


def test_gerar_salvo_incerto_chama_ao_salvar_com_o_numero(tmp_path):
    p = criar(tmp_path, None, "orc.xlsx")
    vistos = []
    gerar(p, cfg(tmp_path), HseFalso(falhar_em={"salvo_incerto"}), tmp_path / "pdfs", vistos.append)
    assert vistos == ["55555"]


def test_modo_pasta_marca_a_planilha_mesmo_se_o_download_for_interrompido(tmp_path):
    import json
    import pytest
    from orcamento.processador import processar_arquivo
    pasta = tmp_path / "ORC"
    pasta.mkdir()
    prog = tmp_path / "prog"
    prog.mkdir()
    c = Config(usuario="u", senha="s", client_id="ventura", pasta=pasta, dry_run=False, headless=True,
               pasta_programa=prog)
    p = criar(pasta, None, "orc.xlsx")

    class Interrompido(HseFalso):
        def baixar_dav(self, numero, destino):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        processar_arquivo(p, c, Interrompido())
    assert len(json.loads((prog / "processados_estado.json").read_text(encoding="utf-8"))) == 1


def test_gerar_usa_o_nome_de_exibicao_no_relatorio(tmp_path):
    p = criar(tmp_path, None, "7.xlsx")
    r = gerar(p, cfg(tmp_path), HseFalso(), tmp_path / "pdfs", nome="orcamento_ana.xlsx")
    assert "Arquivo: orcamento_ana.xlsx" in r.relatorio
    assert "7.xlsx" not in r.relatorio
