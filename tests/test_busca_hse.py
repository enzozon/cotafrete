"""Classificação e relatório da busca de NF no HSE (cruzar_nf/busca_hse.py).

A parte do navegador foi validada na tela real do HSE em 30/09/2026; aqui
fica o que decide o que cada NF achada quer dizer.
"""

from __future__ import annotations

import json

from cruzar_nf.busca_hse import (
    CANDIDATA, COINCIDENCIA, EXPLICADA, NAO_ACHOU, classificar, main, montar_md, uf_da_cidade,
)


def nota(numero, destinatario="CLIENTE X", uf="MG", empresa="VENTURA MATRIZ"):
    return {"empresa": empresa, "emissao": "12/08/2025", "modelo": "55", "nota": numero,
            "serie": "1", "origem": "VEN 1", "cfop": "5102", "destinatario": destinatario,
            "cnpj": "00000000000100", "valor": "100,00", "uf": uf, "status": "Autorizada"}


PEDIDO = {"oc": "4100000001", "nfs": "13653 / 13580", "cidade": "MARIANA - MG",
          "diferenca": "-28230.00"}


def test_uf_da_cidade():
    assert uf_da_cidade("MARIANA - MG") == "MG"
    assert uf_da_cidade("ANANINDEUA-PA") == "PA"
    assert uf_da_cidade("NOVA LIMA -MG") == "MG"
    assert uf_da_cidade(None) is None


def test_sem_nota_nao_achou():
    assert classificar(PEDIDO, [])[0] == NAO_ACHOU


def test_nf_que_ja_e_do_erp_explica_a_diferenca():
    # caso 1225000022: a busca achou justamente a 2a NF da OC
    conclusao, obs = classificar({**PEDIDO, "nfs": "15031 / 15130"}, [nota("15130")])
    assert conclusao == EXPLICADA
    assert "15130" in obs


def test_cliente_no_mesmo_estado_e_candidata():
    # caso 4500249590: NF 13768 para a Samarco, pedido de Mariana-MG
    conclusao, _ = classificar(PEDIDO, [nota("13768", "SAMARCO MINERACAO S.A.", "MG")])
    assert conclusao == CANDIDATA


def test_transferencia_do_grupo_e_coincidencia():
    # caso 4500272508: NF da Ventura para a União
    notas = [nota("15708", "UNIAO COMERCIO DE INFO", "MG")]
    assert classificar(PEDIDO, notas)[0] == COINCIDENCIA


def test_outro_estado_e_coincidencia():
    notas = [nota("14483", "CLIENTE Y", "ES")]
    assert classificar(PEDIDO, notas)[0] == COINCIDENCIA


def test_uma_candidata_entre_varias_notas_basta():
    notas = [nota("1", "VENTURA COMERCIO VAREJ", "MG"), nota("2", "CLIENTE Z", "MG")]
    conclusao, obs = classificar(PEDIDO, notas)
    assert conclusao == CANDIDATA
    assert "2 (CLIENTE Z)" in obs and "VAREJ" not in obs


def test_relatorio_tem_resumo_e_cada_pedido():
    res = [
        {**PEDIDO, "notas_hse": [nota("13768", "SAMARCO")], "conclusao": CANDIDATA, "observacao": "x"},
        {**PEDIDO, "oc": "4100000002", "notas_hse": [], "conclusao": NAO_ACHOU, "observacao": "y",
         "erro": "o HSE não respondeu a tempo"},
    ]
    md = montar_md({"gerado_em": "2026-09-30T12:00:00", "filtros": {"valor": "x"}, "resultados": res})
    assert "| ✅ candidata (conferir) | 1 |" in md
    assert "-R$ 28.230,00" in md
    assert "13768 (VENTURA, 12/08/2025, SAMARCO)" in md
    assert "## Buscas que falharam" in md and "4100000002" in md


def test_main_sem_entrada_da_erro(tmp_path, capsys):
    assert main(["--pasta", str(tmp_path)]) == 1
    assert "DIVERGENCIAS_VALOR.json" in capsys.readouterr().err


def test_rodar_com_navegador_falso(tmp_path, monkeypatch):
    from cruzar_nf import busca_hse
    (tmp_path / "DIVERGENCIAS_VALOR.json").write_text(json.dumps([PEDIDO]), encoding="utf-8")
    pedidos_ao_hse = []

    def falso(valores, desde, ate, perfil, ao_buscar=None):
        pedidos_ao_hse.extend(valores)
        return [{"valor": "28230.00", "notas": [nota("13768", "SAMARCO", "MG")]}]

    monkeypatch.setattr(busca_hse, "buscar_no_hse", falso)
    assert main(["--pasta", str(tmp_path), "--perfil", str(tmp_path / "p")]) == 0
    assert [str(v) for v in pedidos_ao_hse] == ["28230.00"]   # busca o valor absoluto
    dados = json.loads((tmp_path / "BUSCA_HSE_DIVERGENCIAS.json").read_text(encoding="utf-8"))
    assert dados["resultados"][0]["conclusao"] == CANDIDATA
    assert (tmp_path / "BUSCA_HSE_DIVERGENCIAS.md").is_file()
