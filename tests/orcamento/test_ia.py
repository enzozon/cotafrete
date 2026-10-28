import csv
import json
from pathlib import Path

from orcamento import ia
from orcamento.config import Config

LONGA = ("|| REFRIGERADOR;TIPO:FROST FREE;CAPACIDADE REFRIGERADOR:305L;CAPACIDADE CONGELADOR:120L;"
         "COR:INOX; FABRICANTE/REFERENCIA: MIDEA / MDRT572EVD013;" * 2)


def cfg(tmp_path: Path, modo: str) -> Config:
    return Config(usuario="u", senha="s", client_id="ventura", pasta=tmp_path, dry_run=True, headless=True,
                  intervalo_min=5, pasta_programa=tmp_path, ia=modo)


def _uso(tmp_path):
    with open(tmp_path / "ia_uso.csv", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def test_desligada_nao_resume(tmp_path):
    assert ia.resumidor(cfg(tmp_path, "desligada")) is None


def test_api_registra_custo_pelo_preco_do_modelo(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("CABO HDMI 2M", 1000, 200))
    assert ia.resumidor(cfg(tmp_path, "api"))("CABO HDMI 2M " * 15) == "CABO HDMI 2M"
    # Haiku 5.5: US$ 0,10 / 1M entrada e US$ 0,50 / 1M saída
    assert _uso(tmp_path)[0]["custo_usd"] == "0.000200"


def test_resposta_invalida_vira_none(tmp_path, monkeypatch):
    for ruim in ("", "X" * 101):
        monkeypatch.setattr(ia, "_rodar_api", lambda *a, r=ruim: (r, 10, 10))
        assert ia.resumidor(cfg(tmp_path, "api"))("y" * 150 + ruim[:1]) is None


def test_resposta_que_nao_vem_do_texto_e_recusada(tmp_path, monkeypatch):
    # visto no teste real: um hook do Claude Code fez a resposta virar um aviso do sistema
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("AVISO: O CLAUDE-MEM NAO CONSEGUE SALVAR", 10, 10))
    assert ia.resumidor(cfg(tmp_path, "api"))(LONGA) is None
    assert "não vem do texto" in _uso(tmp_path)[0]["detalhe"]


def test_cache_mantem_o_mesmo_resumo(tmp_path, monkeypatch):
    chamadas = []
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: (chamadas.append(1) or "CABO HDMI 2M", 10, 10))
    resumir = ia.resumidor(cfg(tmp_path, "api"))
    assert resumir("CABO HDMI 2M " * 15) == resumir("CABO HDMI 2M " * 15) == "CABO HDMI 2M"
    assert len(chamadas) == 1  # 2ª vez vem do ia_cache.json: reprocessar não gera produto diferente


def test_projecao_de_custo(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("CABO HDMI 2M", 1000, 200))
    resumir = ia.resumidor(cfg(tmp_path, "api"))
    resumir("CABO HDMI 2M A " * 12)
    resumir("CABO HDMI 2M B " * 12)
    texto = ia.relatorio_uso(tmp_path / "ia_uso.csv", por_dia=40)
    assert "2 chamada(s)" in texto and "US$ 0.000200 por chamada" in texto
    assert "US$ 0.0080 por dia" in texto


def test_ncm_extrai_8_digitos_e_registra_tarefa(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("Pesquisei. NCM=8418.10.00", 300, 40))
    assert ia.ajudantes(cfg(tmp_path, "api")).ncm("REFRIGERADOR MIDEA") == "84181000"
    assert _uso(tmp_path)[0]["modo"] == "api:ncm"


def test_ncm_sem_formato_vira_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("não sei", 10, 10))
    assert ia.ajudantes(cfg(tmp_path, "api")).ncm("PRODUTO X") is None


def test_ncm_pede_busca_na_internet(tmp_path, monkeypatch):
    pedidos = []
    monkeypatch.setattr(ia, "_rodar_api", lambda prompt, modelo, instrucao, web: pedidos.append(web) or ("NCM=84181000", 1, 1))
    ia.ajudantes(cfg(tmp_path, "api")).ncm("REFRIGERADOR")
    assert pedidos == [True]


def test_grupo_so_aceita_nome_da_lista(tmp_path, monkeypatch):
    grupos = ["INFORMATICA", "ELETRODOMÉSTICOS"]
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("eletrodomesticos", 10, 10))
    assert ia.ajudantes(cfg(tmp_path, "api")).grupo("REFRIGERADOR", grupos) == "ELETRODOMÉSTICOS"
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("LINHA BRANCA", 10, 10))
    assert ia.ajudantes(cfg(tmp_path, "api")).grupo("FOGAO", grupos) is None


def test_desligada_nao_tem_ajudantes(tmp_path):
    a = ia.ajudantes(cfg(tmp_path, "desligada"))
    assert a.resumir is None and a.grupo is None and a.ncm is None
