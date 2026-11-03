from datetime import datetime
from decimal import Decimal
from pathlib import Path

from orcamento.planilha import Item
from orcamento.relatorio import Relatorio, moeda

NOVO = Item(numero=5, linha=6, produto="CABO HDMI 2M", quantidade=Decimal(1), custo=Decimal(45),
            valor_unit=Decimal("65.25"), codigo=None, ncm="84716053", origem=0, icms=Decimal(17),
            descricao_cadastro="CABO HDMI 2M", grupo="INFORMATICA", marca="DELL")


def test_moeda():
    assert moeda(Decimal("45")) == "R$ 45,00"
    assert moeda(Decimal("1234.5")) == "R$ 1.234,50"


def test_frases_da_spec():
    r = Relatorio("orc.xlsx", dry_run=False)
    r.item_existente(3, "13370", "DELL MOUSE OPTICO MS116", por="codigo")
    r.item_existente(4, "22010", "TECLADO X", por="descricao")
    r.item_cadastrado(5, "56601", NOVO)
    r.item_cadastraria(6, NOVO)
    r.item_erro(7, "código 999 não encontrado")
    linhas = r.texto().splitlines()
    assert "Item 3: usou produto existente 13370 - DELL MOUSE OPTICO MS116 (pelo código informado)" in linhas
    assert "Item 4: usou produto existente 22010 - TECLADO X (encontrado pela descrição)" in linhas
    assert ("Item 5: CADASTROU produto novo 56601 - CABO HDMI 2M | NCM 84716053 | Origem 0 | "
            "ICMS 17% | custo R$ 45,00 | grupo INFORMATICA | marca DELL") in linhas
    assert ("Item 6: [DRY_RUN] cadastraria produto novo - CABO HDMI 2M | NCM 84716053 | Origem 0 | "
            "ICMS 17% | custo R$ 45,00 | grupo INFORMATICA | marca DELL") in linhas
    assert "Item 7: ERRO - código 999 não encontrado" in linhas


def test_cabecalho_e_gravar(tmp_path: Path):
    r = Relatorio("orc.xlsx", dry_run=True, agora=datetime(2026, 10, 27, 14, 5))
    r.resultado = "DRY_RUN - simulação concluída"
    r.info("Cliente: 18373 - VENTURA")
    r.erro("algo falhou")
    destino = r.gravar(tmp_path / "orc.txt")
    texto = destino.read_text(encoding="utf-8")
    assert "Arquivo: orc.xlsx" in texto
    assert "Data: 27/10/2026 14:05" in texto
    assert "Modo: DRY_RUN (simulação, nada foi salvo no HSE)" in texto
    assert "Resultado: DRY_RUN - simulação concluída" in texto
    assert "Cliente: 18373 - VENTURA" in texto
    assert "ERRO: algo falhou" in texto
    assert r.tem_erro


def test_novo_pendente():
    r = Relatorio("x", dry_run=False)
    r.item_novo_pendente(5, NOVO)
    assert "Item 5: produto novo NÃO cadastrado (planilha com erro) - CABO HDMI 2M | NCM 84716053" in r.texto()


def test_icms_fracionado():
    item = Item(**{**NOVO.__dict__, "icms": Decimal("12.5")})
    r = Relatorio("x", dry_run=True)
    r.item_cadastraria(1, item)
    assert "ICMS 12,5%" in r.texto()
