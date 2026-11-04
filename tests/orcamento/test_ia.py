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
    assert ia.ajudantes(cfg(tmp_path, "api")).ncm("REFRIGERADOR MIDEA", lambda n: True) == "84181000"
    assert _uso(tmp_path)[0]["modo"] == "api:ncm"


def test_ncm_sem_formato_vira_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("não sei", 10, 10))
    assert ia.ajudantes(cfg(tmp_path, "api")).ncm("PRODUTO X", lambda n: True) is None


def test_ncm_tenta_sem_busca_na_internet_primeiro(tmp_path, monkeypatch):
    pedidos = []
    monkeypatch.setattr(ia, "_rodar_api", lambda prompt, modelo, instrucao, web: pedidos.append(web) or ("NCM=84181000", 1, 1))
    assert ia.ajudantes(cfg(tmp_path, "api")).ncm("REFRIGERADOR", lambda n: True) == "84181000"
    assert pedidos == [False]  # a busca custa US$ 0,01 cada; sem ela a pergunta sai por ~US$ 0,0001


def test_ncm_busca_na_internet_quando_o_de_memoria_nao_existe_no_hse(tmp_path, monkeypatch):
    pedidos = []

    def api(prompt, modelo, instrucao, web):
        pedidos.append(web)
        return ("NCM=84181000", 1, 1, 2) if web else ("NCM=12345678", 1, 1)
    monkeypatch.setattr(ia, "_rodar_api", api)
    ncm = ia.ajudantes(cfg(tmp_path, "api")).ncm
    assert ncm("REFRIGERADOR", lambda n: n == "84181000") == "84181000"
    assert pedidos == [False, True]
    assert [(u["modo"], u["ok"]) for u in _uso(tmp_path)] == [("api:ncm", "nao"), ("api:ncm_web", "sim")]
    assert "não existe no HSE" in _uso(tmp_path)[0]["detalhe"]
    # o NCM recusado não vai para o cache: reprocessar a planilha não traz o 12345678 de volta
    assert ncm("REFRIGERADOR", lambda n: n == "84181000") == "84181000" and len(pedidos) == 3


def test_busca_na_internet_entra_no_custo(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "_rodar_api", lambda prompt, modelo, instrucao, web:
                        ("NCM=84181000", 1000, 200, 2) if web else ("não sei", 10, 10))
    ia.ajudantes(cfg(tmp_path, "api")).ncm("REFRIGERADOR", lambda n: True)
    # tokens (US$ 0,0002) + 2 buscas a US$ 10 por mil
    assert _uso(tmp_path)[-1]["custo_usd"] == "0.020200"


def _gastou(tmp_path, data: str, custo: str) -> None:
    with open(tmp_path / "ia_uso.csv", "w", newline="", encoding="utf-8-sig") as f:
        f.write(";".join(ia.COLUNAS) + "\n")
        f.write(f"{data} 10:00:00;api:ncm_web;claude-haiku-5-5;1;1;{custo};sim;\n")


def test_freio_diario_para_a_ia_quando_o_gasto_do_dia_chega_ao_limite(tmp_path, monkeypatch):
    chamadas = []
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: chamadas.append(1) or ("CABO HDMI 2M", 10, 10))
    _gastou(tmp_path, ia.datetime.now().strftime("%Y-%m-%d"), "0.300000")
    assert ia.resumidor(cfg(tmp_path, "api"))("CABO HDMI 2M " * 15) is None
    assert chamadas == []
    assert "limite do dia" in _uso(tmp_path)[-1]["detalhe"]


def test_gasto_de_ontem_nao_conta_no_freio(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("CABO HDMI 2M", 10, 10))
    _gastou(tmp_path, "2020-01-01", "9.000000")
    assert ia.resumidor(cfg(tmp_path, "api"))("CABO HDMI 2M " * 15) == "CABO HDMI 2M"


def test_gasto_do_dia_e_do_mes(tmp_path):
    hoje = ia.datetime.now()
    _gastou(tmp_path, hoje.strftime("%Y-%m-%d"), "0.012345")
    assert ia.gasto(tmp_path / "ia_uso.csv", hoje) == (0.012345, 0.012345)
    with open(tmp_path / "ia_uso.csv", "a", encoding="utf-8-sig") as f:
        f.write(hoje.strftime("%Y-%m-%d") + " 11:00:00;api:ncm;claude-haiku-5-5;1;1;0.0\x00")  # linha cortada
    assert ia.gasto(tmp_path / "ia_uso.csv", hoje) == (0.012345, 0.012345)
    assert ia.gasto(tmp_path / "nao_existe.csv", hoje) == (0.0, 0.0)


def test_grupo_usa_o_guia_de_cadastro_da_empresa(tmp_path, monkeypatch):
    pedidos = []
    monkeypatch.setattr(ia, "_rodar_api", lambda prompt, modelo, instrucao, web=False:
                        pedidos.append(instrucao) or ("BEBEDOURO", 10, 10))
    assert ia.ajudantes(cfg(tmp_path, "api")).grupo("PURIFICADOR DE AGUA", ["BEBEDOURO", "ELETROPORTATEIS"]) == "BEBEDOURO"
    assert "PURIFICADOR/BEBEDOURO" in pedidos[0]  # D:\CADASTRO DE PRODUTO POR GRUPO.pdf


def test_grupo_so_aceita_nome_da_lista(tmp_path, monkeypatch):
    grupos = ["INFORMATICA", "ELETRODOMÉSTICOS"]
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("eletrodomesticos", 10, 10))
    assert ia.ajudantes(cfg(tmp_path, "api")).grupo("REFRIGERADOR", grupos) == "ELETRODOMÉSTICOS"
    monkeypatch.setattr(ia, "_rodar_api", lambda *a: ("LINHA BRANCA", 10, 10))
    assert ia.ajudantes(cfg(tmp_path, "api")).grupo("FOGAO", grupos) is None


def test_desligada_nao_tem_ajudantes(tmp_path):
    a = ia.ajudantes(cfg(tmp_path, "desligada"))
    assert a.resumir is None and a.grupo is None and a.ncm is None
