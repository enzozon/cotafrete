"""Leitura da ficha em texto -> modelo central -> formato de cada site.

A ficha é o formato que o Enzo digita à mão. Ela cobre quase todos os sites de
cotação, mas cada site quer os mesmos números escritos de um jeito: a medida
vai com UMA casa decimal na Della Volpe (o campo tem máscara) e SEM casa na
Jadlog. Errar isso não dá erro: cota a carga 10x menor, calado.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from carriers.dellavolpe import mapping as dv
from carriers.jadlog.simulador import JadlogSimuladorAdapter
from core.ficha import CamposFaltando, ler_ficha
from core.models import Servico

FICHA = """\
Nome Completo: Enzo Zon
UF Origem: SP
Cidade Origem: São José dos Campos
UF Destino: ES
Cidade Destino: Vitória
CNPJ Remetente: 60.042.686/0001-05
CNPJ Destinatario: 05.954.058/0001-98
CNPJ Pagador: 05.954.058/0001-98
Peso Total (kg): 1
Quantidade de Volumes: 1
Comprimento (cm): 30
Largura (cm): 30
Altura (cm): 30
Valor Total Nota Fiscal: 568.77
Material: LUVA DE BOMBEIRO
Tipo de Serviço: Fracionado -LTL
email: vendas2@venturainformatica.com.br
WhatsApp: 27999887766
CEP ORIGEM: 09895-003
CEP DESTINO: 29105-770
"""


@pytest.fixture
def req():
    return ler_ficha(FICHA)


# ------------------------------------------------------------------- leitura
def test_le_a_ficha_inteira(req):
    assert req.solicitante.nome == "Enzo Zon"
    assert req.solicitante.email == "vendas2@venturainformatica.com.br"
    assert req.origem.uf == "SP"
    assert req.origem.cidade == "São José dos Campos"
    assert req.origem.cep == "09895-003"
    assert req.destino.uf == "ES"
    assert req.destino.cidade == "Vitória"
    # o modelo guarda só os dígitos e formata na saída
    assert req.remetente.cnpj == "60042686000105"
    assert req.remetente.cnpj_formatado == "60.042.686/0001-05"
    assert req.mercadoria.tipo_material == "LUVA DE BOMBEIRO"
    assert req.servico is Servico.FRACIONADO_LTL
    assert req.nota_fiscal.valor_total == Decimal("568.77")


@pytest.mark.parametrize("chave", [
    "Tipo de Serviço", "TIPO DE SERVICO", "tipo de servico", "Tipo  de   Serviço",
])
def test_chave_sem_acento_e_com_caixa_trocada_ainda_acha(chave):
    """Ficha digitada à mão: acento e maiúscula variam a cada vez."""
    texto = FICHA.replace("Tipo de Serviço", chave)
    assert ler_ficha(texto).servico is Servico.FRACIONADO_LTL


@pytest.mark.parametrize("escrito, esperado", [
    ("568.77", Decimal("568.77")),      # ponto decimal, como veio na ficha
    ("568,77", Decimal("568.77")),      # vírgula decimal, jeito brasileiro
    ("1.568,77", Decimal("1568.77")),   # ponto de milhar + vírgula decimal
    ("1568", Decimal("1568")),
])
def test_valor_da_nota_aceita_os_dois_jeitos_de_escrever(escrito, esperado):
    """A ficha veio com '568.77', mas quem digita alterna sem avisar."""
    texto = FICHA.replace("Valor Total Nota Fiscal: 568.77",
                          f"Valor Total Nota Fiscal: {escrito}")
    assert ler_ficha(texto).nota_fiscal.valor_total == esperado


def test_peso_total_vira_peso_por_volume():
    """A ficha diz 'Peso TOTAL', o modelo guarda peso POR volume.

    Copiar o total para cada volume multiplica a carga pela quantidade —
    3 volumes de 12kg viravam 36kg cada, 108kg no total."""
    texto = (FICHA.replace("Peso Total (kg): 1", "Peso Total (kg): 36")
                  .replace("Quantidade de Volumes: 1", "Quantidade de Volumes: 3"))
    req = ler_ficha(texto)

    assert req.volumes[0].peso_kg == Decimal(12)
    assert req.peso_total_kg == Decimal(36)


def test_linha_desconhecida_nao_quebra():
    """Ficha real vem com linha extra, comentário, rodapé de e-mail."""
    req = ler_ficha(FICHA + "\nObs: entregar de manhã\n\n-- enviado do celular\n")
    assert req.solicitante.nome == "Enzo Zon"


def test_campo_faltando_diz_qual_e():
    """WhatsApp não está na ficha padrão e a Della Volpe exige. Falhar sem
    dizer o nome do campo faz a pessoa conferir 19 linhas na mão."""
    texto = FICHA.replace("WhatsApp: 27999887766\n", "")

    with pytest.raises(CamposFaltando) as exc:
        ler_ficha(texto)
    assert "WhatsApp" in str(exc.value)


# -------------------------------------------- a mesma medida, dois formatos
def test_medida_vai_com_uma_casa_na_dellavolpe_e_sem_casa_na_jadlog(req):
    """O ponto central do pedido: adaptar o mesmo dado para cada site.

    O campo da Della Volpe tem máscara de uma casa — digitar '30' vira '3,0'
    e a carga é cotada 10x menor, sem aviso. O da Jadlog não tem máscara."""
    payload_dv = dv.preparar_payload(req)
    payload_jad = JadlogSimuladorAdapter().preparar_payload(req)

    assert payload_dv["Comprimento"] == "30,0"
    assert payload_dv["Largura"] == "30,0"
    assert payload_dv["Altura"] == "30,0"

    assert payload_jad["valComprimento"] == "30"
    assert payload_jad["valLargura"] == "30"
    assert payload_jad["valAltura"] == "30"


def test_cep_vai_so_com_digitos_para_a_jadlog(req):
    """A Jadlog cota por CEP; a Della Volpe nem recebe CEP, cota por cidade."""
    payload_jad = JadlogSimuladorAdapter().preparar_payload(req)

    assert payload_jad["origem"] == "09895003"
    assert payload_jad["destino"] == "29105770"


def test_valor_da_nota_vai_em_formato_brasileiro_nos_dois(req):
    assert JadlogSimuladorAdapter().preparar_payload(req)["valor_mercadoria"] == "568,77"
    assert dv.preparar_payload(req)["Valor total da nota fiscal"] == "568,77"
