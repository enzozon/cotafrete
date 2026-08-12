"""Testes da camada pura: verificam se o dado certo vai para o campo certo.
Nenhum destes testes toca a internet ou o site da Della Volpe."""

from __future__ import annotations

from decimal import Decimal

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from carriers.base import Severidade
from carriers.dellavolpe import mapping as dv
from carriers.dellavolpe.planilha import gerar_planilha_volumes
from core.models import (
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, StatusCotacao, Volume, cnpj_valido,
)

CNPJ_A = "11.222.333/0001-81"
CNPJ_B = "45.723.174/0001-10"
CNPJ_C = "61.139.432/0001-72"  # o da própria Della Volpe, público no site


def montar(**over) -> CotacaoRequest:
    base = dict(
        solicitante=Solicitante(nome="Teste da Silva", email="t@ex.com",
                                whatsapp="27999887766"),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf="es", cidade="Vitória"),
        destino=Local(uf="SP", cidade="São Paulo"),
        remetente=Parte(cnpj=CNPJ_A),
        destinatario=Parte(cnpj=CNPJ_B),
        pagador_frete=Parte(cnpj=CNPJ_C),
        volumes=[Volume(qtd=2, comprimento_cm=Decimal(100), largura_cm=Decimal(50),
                        altura_cm=Decimal(40), peso_kg=Decimal(10))],
        mercadoria=Mercadoria(tipo_material="Peças metálicas"),
        nota_fiscal=NotaFiscal(valor_total=Decimal(25_000)),
    )
    base.update(over)
    return CotacaoRequest(**base)


# ------------------------------------------------------------- fundamentos
def test_cnpj_mod11():
    assert cnpj_valido(CNPJ_A)
    assert cnpj_valido(CNPJ_C)
    assert not cnpj_valido("11.222.333/0001-80")
    assert not cnpj_valido("11111111111111")


def test_cnpj_invalido_rejeitado_no_modelo():
    with pytest.raises(ValidationError):
        montar(remetente=Parte(cnpj="00.000.000/0000-00"))


def test_uf_normalizada_para_maiuscula():
    assert montar().origem.uf == "ES"


# --------------------------------------------------------------- derivados
def test_peso_e_quantidade_multiplicam_pela_qtd():
    r = montar()
    assert r.peso_total_kg == Decimal(20)      # 10 kg x 2
    assert r.quantidade_volumes == 2


def test_cubagem_em_m3_nao_cm3():
    r = montar()
    # 100 x 50 x 40 = 200.000 cm³ x 2 = 400.000 cm³ = 0,4 m³
    assert r.cubagem_m3 == Decimal("0.4")


def test_cubagem_soma_volumes_heterogeneos():
    r = montar(volumes=[
        Volume(qtd=1, comprimento_cm=Decimal(100), largura_cm=Decimal(50),
               altura_cm=Decimal(40), peso_kg=Decimal(10)),
        Volume(qtd=1, comprimento_cm=Decimal(80), largura_cm=Decimal(40),
               altura_cm=Decimal(30), peso_kg=Decimal(8)),
    ])
    assert r.peso_total_kg == Decimal(18)
    assert r.quantidade_volumes == 2
    assert r.cubagem_m3 == Decimal("0.296")   # 0,2 + 0,096
    assert r.tem_medidas_distintas is True


def test_peso_cubado_usa_fator_da_transportadora():
    r = montar()
    assert r.peso_cubado_kg(dv.FATOR_CUBAGEM) == Decimal("120.0")  # 0,4 x 300


# -------------------------------------------------------------- formatação
@pytest.mark.parametrize("entrada,esperado", [
    (Decimal(25_000), "25.000,00"),
    (Decimal("1234.5"), "1.234,50"),
    (Decimal("999.99"), "999,99"),
    (Decimal(1_500_000), "1.500.000,00"),
])
def test_valor_em_formato_brasileiro(entrada, esperado):
    assert dv.num_br(entrada) == esperado


def test_peso_sem_separador_de_milhar():
    assert dv.peso_br(Decimal(1500)) == "1500"
    assert dv.peso_br(Decimal("1500.5")) == "1500,5"


def test_medidas_usam_uma_casa_decimal_por_causa_da_mascara():
    """Medido no site em produção: o campo de medida tem máscara que reserva
    UMA casa decimal. Digitar '100' vira '10,0' — a carga seria cotada 10x
    menor, em silêncio. O próprio placeholder declara o formato esperado:
    'Comprimento (ex. 12,5m = 1.250,0cm)'.

    peso_br() é formatador de PESO e não serve aqui: ele corta a casa decimal."""
    assert dv.medida_br(Decimal(100)) == "100,0"
    assert dv.medida_br(Decimal(40)) == "40,0"
    assert dv.medida_br(Decimal(1250)) == "1.250,0"
    assert dv.medida_br(Decimal("12.5")) == "12,5"


# ----------------------------------------------------------------- payload
def test_payload_mapeia_todos_os_campos_obrigatorios():
    campos = dv.campos_do_formulario(dv.preparar_payload(montar()))
    for spec in dv.campos_obrigatorios(montar()):
        assert spec.nome in campos, f"campo obrigatório ausente: {spec.nome}"


def test_payload_valores_exatos():
    p = dv.preparar_payload(montar())
    assert p["Nome completo"] == "Teste da Silva"
    assert p["WhatsApp"] == "(27) 99988-7766"
    assert p["Qual o serviço que você procura?"] == "Fracionado -LTL"
    assert p["CNPJ - Remetente"] == "11.222.333/0001-81"
    assert p["CNPJ - Destinatário"] == "45.723.174/0001-10"
    assert p["CNPJ da empresa que pagará o frete"] == "61.139.432/0001-72"
    assert p["Selecione o estado de origem"] == "ES"
    assert p["Peso total"] == "20"
    assert p["Quantidade de Volumes"] == "2"
    assert p["Comprimento"] == "100,0"    # máscara de 1 casa; ver medida_br()
    assert p["Largura"] == "50,0"
    assert p["Altura"] == "40,0"
    assert p["Valor total da nota fiscal"] == "25.000,00"


def test_cnpjs_nao_se_misturam():
    """Regressão: os três CNPJs são campos diferentes e não podem trocar."""
    p = dv.preparar_payload(montar())
    tres = {p["CNPJ - Remetente"], p["CNPJ - Destinatário"],
            p["CNPJ da empresa que pagará o frete"]}
    assert len(tres) == 3


def test_cubagem_nao_vai_para_o_formulario():
    """DV não tem campo de m³. Cubagem é interna e não pode vazar no envio."""
    p = dv.preparar_payload(montar())
    campos = dv.campos_do_formulario(p)
    assert "cubagem_m3" in p["_meta"]
    assert not any("cubagem" in k.lower() or "m³" in k for k in campos)


def test_medidas_distintas_usam_o_maior_volume():
    r = montar(volumes=[
        Volume(qtd=1, comprimento_cm=Decimal(80), largura_cm=Decimal(40),
               altura_cm=Decimal(30), peso_kg=Decimal(8)),
        Volume(qtd=1, comprimento_cm=Decimal(100), largura_cm=Decimal(50),
               altura_cm=Decimal(40), peso_kg=Decimal(10)),
    ])
    p = dv.preparar_payload(r)
    assert (p["Comprimento"], p["Largura"], p["Altura"]) == ("100,0", "50,0", "40,0")
    assert p["Anexar Planilha"] == ["__PLANILHA_VOLUMES__"]


def test_ftl_inclui_tipo_de_veiculo():
    p = dv.preparar_payload(montar(
        servico=Servico.LOTACAO_FTL,
        veiculo_desejado="Truck (até 12.500 kg)",
    ))
    assert p["Qual o serviço que você procura?"] == "Lotação/Dedicado-FTL"
    assert p["Escolha o tipo de veículo"] == "Truck (até 12.500 kg)"


def test_ltl_nao_inclui_tipo_de_veiculo():
    assert "Escolha o tipo de veículo" not in dv.preparar_payload(montar())


# ---------------------------------------------------------------- validação
def test_carga_valida_nao_tem_bloqueio():
    assert dv.bloqueantes(dv.validar(montar())) == []


def test_peso_acima_de_34t_bloqueia():
    r = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(100),
                               largura_cm=Decimal(100), altura_cm=Decimal(100),
                               peso_kg=Decimal(35_000))])
    erros = dv.bloqueantes(dv.validar(r))
    assert any(e.campo == "peso_total_kg" for e in erros)


def test_ftl_sem_veiculo_bloqueia():
    erros = dv.bloqueantes(dv.validar(montar(servico=Servico.LOTACAO_FTL)))
    assert any(e.campo == "veiculo_desejado" for e in erros)


def test_veiculo_pequeno_demais_bloqueia():
    r = montar(
        servico=Servico.LOTACAO_FTL,
        veiculo_desejado="Fiorino (até 500 kg)",
        volumes=[Volume(qtd=1, comprimento_cm=Decimal(100), largura_cm=Decimal(100),
                        altura_cm=Decimal(100), peso_kg=Decimal(2_000))],
    )
    erros = dv.bloqueantes(dv.validar(r))
    assert any("Fiorino" in e.mensagem for e in erros)


def test_quimico_sem_fispq_bloqueia():
    r = montar(mercadoria=Mercadoria(tipo_material="Soda cáustica", is_perigoso=True))
    assert any(e.campo == "mercadoria.fispq_path" for e in dv.bloqueantes(dv.validar(r)))


def test_medidas_distintas_e_aviso_nao_bloqueio():
    r = montar(volumes=[
        Volume(qtd=1, comprimento_cm=Decimal(100), largura_cm=Decimal(50),
               altura_cm=Decimal(40), peso_kg=Decimal(10)),
        Volume(qtd=1, comprimento_cm=Decimal(80), largura_cm=Decimal(40),
               altura_cm=Decimal(30), peso_kg=Decimal(8)),
    ])
    erros = dv.validar(r)
    assert dv.bloqueantes(erros) == []
    assert any(e.severidade is Severidade.AVISO for e in erros)


# ----------------------------------------------------------------- resposta
def test_envio_confirmado_vira_aguardando_retorno_sem_preco():
    res = dv.normalizar_resposta("Obrigado! Sua mensagem foi enviada com sucesso.")
    assert res.status is StatusCotacao.AGUARDANDO_RETORNO
    assert res.valor_frete is None   # não inventar preço


def test_resposta_inesperada_vira_erro():
    assert dv.normalizar_resposta("<html>502 Bad Gateway</html>").status is StatusCotacao.ERRO


# ----------------------------------------------------------------- planilha
def test_planilha_reflete_os_volumes(tmp_path):
    r = montar(volumes=[
        Volume(qtd=3, comprimento_cm=Decimal(100), largura_cm=Decimal(50),
               altura_cm=Decimal(40), peso_kg=Decimal(10), descricao="Caixas"),
        Volume(qtd=1, comprimento_cm=Decimal(80), largura_cm=Decimal(40),
               altura_cm=Decimal(30), peso_kg=Decimal(8), descricao="Pallet"),
    ])
    caminho = gerar_planilha_volumes(r, tmp_path / "volumes.xlsx")
    ws = load_workbook(caminho).active
    assert ws.cell(row=5, column=2).value == "Caixas"
    assert ws.cell(row=5, column=8).value == 30.0        # 10 x 3
    assert ws.cell(row=7, column=3).value == 4           # total de volumes
    assert ws.cell(row=7, column=8).value == 38.0        # 30 + 8


# ------------------------------------------------------------------ anexos
def test_anexos_nao_vao_junto_com_campos_de_texto():
    """Regressão: caminho de arquivo passado ao fill() quebra o envio.
    Só acontecia com produto químico — o caso em que o anexo é obrigatório."""
    r = montar(mercadoria=Mercadoria(tipo_material="Soda cáustica",
                                     is_perigoso=True,
                                     fispq_path="/tmp/fispq.pdf"))
    campos = dv.campos_do_formulario(dv.preparar_payload(r))
    texto, arquivos = dv.separar_anexos(campos)

    assert "Anexar FISPQ / Licença" not in texto
    assert arquivos["Anexar FISPQ / Licença"] == "/tmp/fispq.pdf"
    assert all(not str(v).startswith("/") for v in texto.values())


def test_separar_anexos_isola_planilha():
    r = montar(volumes=[
        Volume(qtd=1, comprimento_cm=Decimal(100), largura_cm=Decimal(50),
               altura_cm=Decimal(40), peso_kg=Decimal(10)),
        Volume(qtd=1, comprimento_cm=Decimal(80), largura_cm=Decimal(40),
               altura_cm=Decimal(30), peso_kg=Decimal(8)),
    ])
    texto, arquivos = dv.separar_anexos(
        dv.campos_do_formulario(dv.preparar_payload(r)))
    assert "Anexar Planilha" not in texto
    assert "Anexar Planilha" in arquivos


def test_carga_sem_anexo_nao_cria_chave_de_arquivo():
    texto, arquivos = dv.separar_anexos(
        dv.campos_do_formulario(dv.preparar_payload(montar())))
    assert arquivos == {}
    assert len(texto) == 18
