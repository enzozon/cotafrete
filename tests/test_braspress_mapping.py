"""Braspress — camada pura. Máscaras e leitura do resultado, sem navegador.

As máscaras (peso_para_campo, valor_nf_para_campo, medida_para_campo) foram
medidas digitando no site de verdade e lendo o campo de volta — não
deduzidas de print. Ver recon/recon_braspress.py e o cabeçalho de
carriers/braspress/mapping.py.

ler_sucesso/ler_recusa são testados contra tests/fixtures/braspress_resultado.html,
capturado de um envio real (cotação #373377732, 02/09/2026, Ventura -> Magazine
Luiza) — não escrito à mão.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from carriers.braspress import mapping as m
from core.models import TipoFrete
from tests.test_jadlog import montar

FIXTURE_RESULTADO = (Path(__file__).parent / "fixtures" /
                    "braspress_resultado.html").read_text(encoding="utf-8")


# --------------------------------------------------------------- máscaras
def test_peso_digita_centavos_do_kg():
    # medido: type("1250") -> "12,50" kg
    assert m.peso_para_campo(Decimal("12.5")) == "1250"


def test_valor_nf_digita_centavos_do_real():
    # medido: type("150000") -> "1.500,00"
    assert m.valor_nf_para_campo(Decimal("1500")) == "150000"


def test_medida_em_cm_vira_o_digito_certo_pro_campo_em_metros():
    # medido: type("120") no campo (mostrado em metros) -> "1,20" = 120 cm
    assert m.medida_para_campo(Decimal(120)) == "120"
    assert m.medida_para_campo(Decimal(80)) == "80"


def test_campo_cubagem_segue_o_padrao_medido_no_btnadd():
    assert m.campo_cubagem(0, "comprimento") == "cubagem0comprimento"
    assert m.campo_cubagem(2, "volumes") == "cubagem2volumes"


# ------------------------------------------------- lado livre (CIF/FOB)
def test_cif_trava_remetente_e_o_lado_livre_e_o_destinatario():
    req = montar(tipo_frete=TipoFrete.CIF)
    assert m.cnpj_lado_livre(req) == req.destinatario.cnpj


def test_fob_trava_destinatario_e_o_lado_livre_e_o_remetente():
    req = montar(tipo_frete=TipoFrete.FOB)
    assert m.cnpj_lado_livre(req) == req.remetente.cnpj


def test_valor_tipo_frete_casa_com_o_select_do_site():
    assert m.valor_tipo_frete(montar(tipo_frete=TipoFrete.CIF)) == "1"
    assert m.valor_tipo_frete(montar(tipo_frete=TipoFrete.FOB)) == "2"


# ------------------------------------------------- leitura do resultado
def test_le_o_sucesso_da_cotacao_real():
    r = m.ler_sucesso(FIXTURE_RESULTADO)

    assert r is not None
    assert r.valor_frete == Decimal("1295.87")
    assert r.protocolo == "373377732"
    assert r.prazo_dias == 3
    assert r.status == "OK"


def test_sem_alert_success_nao_e_sucesso():
    assert m.ler_sucesso("<html><body>nada aqui</body></html>") is None


def test_recusa_vazia_quando_nao_ha_alert_danger():
    """Nunca vimos uma recusa real — o padrão é um chute educado a partir da
    convenção Bootstrap. O que este teste trava é só o caminho feliz: uma
    tela SEM `.alert-danger` não pode inventar uma recusa."""
    assert m.ler_recusa(FIXTURE_RESULTADO) is None
