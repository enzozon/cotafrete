"""As chaves do .env da Della Volpe, e o carimbo que liga e-mail e cotação.

Tudo aqui é puro: `caixa`, `automatica` e companhia recebem o ambiente como
dicionário. É o que deixa o teste perguntar "e se o .env tivesse isto?" sem
depender do .env de quem roda os testes.
"""

from __future__ import annotations

import os

import pytest

from carriers.dellavolpe import bookmarklet, caixa, mapping
from carriers.dellavolpe.proposta import RE_CARIMBO
from core.models import Solicitante
from tests.test_dellavolpe_mapping import montar
from web import transportadoras

IMAP = {"DV_IMAP_HOST": "imap.exemplo.com.br",
        "DV_IMAP_USUARIO": "suporte@ventura.com.br",
        "DV_IMAP_SENHA": "segredo"}
LIGADA = {"DV_AUTOMATICA_DESDE": "2026-09-23T09:00:00",
          "DV_ENVIO_REAL_AUTORIZADO": "sim"}


# ------------------------------------------------------------ a caixa
def test_sem_nada_no_env_nao_ha_caixa():
    assert caixa.caixa({}) is None
    assert caixa.email_de_resposta({}) is None


def test_caixa_completa():
    cx = caixa.caixa(IMAP)

    assert cx.host == "imap.exemplo.com.br"
    assert cx.porta == 993
    assert cx.pasta == "INBOX"
    assert cx.remetente == "dellavolpe.com.br"
    assert cx.intervalo_s == 60
    assert caixa.email_de_resposta(IMAP) == "suporte@ventura.com.br"


@pytest.mark.parametrize("falta", ["DV_IMAP_HOST", "DV_IMAP_USUARIO",
                                   "DV_IMAP_SENHA"])
def test_caixa_pela_metade_nao_vale(falta):
    """Com a resposta indo para o suporte e sem senha para ler o suporte, a
    proposta ficaria parada numa caixa que ninguém lê — nem o robô."""
    amb = {k: v for k, v in IMAP.items() if k != falta}

    assert caixa.caixa(amb) is None
    assert caixa.email_de_resposta(amb) is None


def test_login_sem_arroba_precisa_do_endereco():
    amb = {**IMAP, "DV_IMAP_USUARIO": "suporte"}
    assert caixa.caixa(amb) is None

    amb["DV_EMAIL_RESPOSTA"] = "suporte@ventura.com.br"
    assert caixa.email_de_resposta(amb) == "suporte@ventura.com.br"


def test_numero_ruim_no_env_cai_no_padrao():
    cx = caixa.caixa({**IMAP, "DV_IMAP_INTERVALO_S": "dez",
                      "DV_IMAP_PORTA": "-1"})

    assert cx.intervalo_s == 60 and cx.porta == 993


# --------------------------------------------------- ligar a automática
def test_so_liga_com_as_duas_chaves():
    assert caixa.automatica(LIGADA) is True
    assert caixa.automatica({"DV_AUTOMATICA_DESDE": "2026-09-23"}) is False
    assert caixa.automatica({"DV_ENVIO_REAL_AUTORIZADO": "sim"}) is False
    assert caixa.automatica({}) is False


def test_data_que_nao_e_data_nao_liga():
    """Data errada é exatamente o que gera linha fantasma. Na dúvida, não."""
    amb = {**LIGADA, "DV_AUTOMATICA_DESDE": "amanhã"}

    assert caixa.automatica(amb) is False
    assert caixa.o_que_falta(amb)


def test_a_data_sai_em_iso():
    assert (caixa.automatica_desde({"DV_AUTOMATICA_DESDE": "2026-09-23"})
            == "2026-09-23T00:00:00")


def test_a_lista_de_automaticas_segue_o_env():
    assert "dellavolpe" not in transportadoras.automaticas({})
    assert transportadoras.automaticas(LIGADA)[-1] == "dellavolpe"
    assert (transportadoras.automaticas(LIGADA)[:-1]
            == transportadoras.AUTOMATICAS_FIXAS)


def test_a_lista_carregada_e_a_do_env_desta_maquina():
    assert transportadoras.AUTOMATICAS == transportadoras.automaticas(
        os.environ)


def test_env_normal_nao_gera_aviso():
    assert caixa.o_que_falta({}) == []
    assert caixa.o_que_falta({**LIGADA, **IMAP}) == []


def test_env_pela_metade_gera_aviso():
    faltas = caixa.o_que_falta({"DV_AUTOMATICA_DESDE": "2026-09-23",
                                "DV_IMAP_HOST": "imap.x"})

    assert any("DV_ENVIO_REAL_AUTORIZADO" in f for f in faltas)
    assert any("DV_IMAP" in f for f in faltas)


# ------------------------------------------------------------ o carimbo
def test_carimbo():
    assert mapping.carimbar("Enzo Zon", 208) == "Enzo Zon (cot. 208)"


def test_sem_id_o_nome_vai_como_esta():
    assert mapping.carimbar("Enzo Zon", None) == "Enzo Zon"


def test_carimbo_velho_e_trocado_e_nao_somado():
    """Repetir uma cotação reaproveita o nome. Dois carimbos fariam o
    ingestor ler o PRIMEIRO — o da cotação velha."""
    assert (mapping.carimbar("Enzo Zon (cot. 12)", 15)
            == "Enzo Zon (cot. 15)")


def test_o_carimbo_escrito_e_o_que_o_ingestor_le():
    """A Della Volpe devolve o nome em MAIÚSCULAS no A/C do PDF. Se o
    formato daqui e a leitura de lá divergirem, nenhum preço volta."""
    escrito = mapping.carimbar("Enzo Zon", 208).upper()

    assert int(RE_CARIMBO.search(escrito).group(1)) == 208


def test_o_payload_leva_carimbo_e_caixa_do_suporte():
    req = montar(solicitante=Solicitante(nome="Enzo Zon",
                                         email="vendedor@ventura.com.br",
                                         whatsapp="27999887766"))

    p = mapping.preparar_payload(req, cotacao_id=208,
                                 email_resposta="suporte@ventura.com.br")

    assert p["Nome completo"] == "Enzo Zon (cot. 208)"
    assert p["E-mail"] == "suporte@ventura.com.br"


def test_sem_caixa_o_email_continua_o_do_vendedor():
    """Sem ingestor, só uma pessoa lê a proposta — e ela precisa chegar a
    essa pessoa."""
    req = montar(solicitante=Solicitante(nome="Enzo Zon",
                                         email="vendedor@ventura.com.br",
                                         whatsapp="27999887766"))

    assert (mapping.preparar_payload(req, cotacao_id=208)["E-mail"]
            == "vendedor@ventura.com.br")


def test_o_formulario_assistido_leva_o_mesmo_carimbo_e_caixa():
    """A proposta de um envio feito À MÃO também precisa cair no ingestor —
    é o caminho de quando o automático não passa."""
    c = {"id": 208, "nome_solicitante": "Enzo Zon",
         "email": "vendedor@ventura.com.br"}

    campos = bookmarklet.campos_por_name(c, "suporte@ventura.com.br")

    assert campos["nome"] == "Enzo Zon (cot. 208)"
    assert campos["email"] == "suporte@ventura.com.br"
