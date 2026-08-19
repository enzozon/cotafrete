"""Camada PURA da Translovato — o formato que o formulário deles exige.

Tudo aqui é armadilha silenciosa: o site aceita o valor errado sem reclamar e
devolve um preço plausível. Foram todas medidas contra o site real em
18/08/2026, com 5 dry-runs e 5 cotações reais.

A pior delas: as medidas do formulário são em METROS, e as da ficha do Enzo
(e de todas as outras transportadoras) são em CENTÍMETROS. Mandar "30" num
campo que espera "0,3" cotaria uma caixa de 30 metros de altura.
"""

from __future__ import annotations

from decimal import Decimal

from carriers.translovato import mapping as t
from core.models import (
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico, Solicitante,
    StatusCotacao, Volume,
)

CNPJ_A = "60.042.686/0001-05"
CNPJ_B = "05.954.058/0001-98"


def montar(*, cep_ori="29105770", cep_des="09895003", volumes=None, **over):
    base = dict(
        solicitante=Solicitante(nome="Enzo", email="e@ex.com",
                                whatsapp="27999887766"),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf="ES", cidade="Vila Velha", cep=cep_ori),
        destino=Local(uf="SP", cidade="São Bernardo do Campo", cep=cep_des),
        remetente=Parte(cnpj=CNPJ_B),
        destinatario=Parte(cnpj=CNPJ_A),
        pagador_frete=Parte(cnpj=CNPJ_B),
        volumes=volumes or [Volume(qtd=1, comprimento_cm=Decimal(30),
                                   largura_cm=Decimal(30),
                                   altura_cm=Decimal(30),
                                   peso_kg=Decimal(1))],
        mercadoria=Mercadoria(tipo_material="LUVA DE BOMBEIRO"),
        nota_fiscal=NotaFiscal(valor_total=Decimal("568.77")),
    )
    base.update(over)
    return CotacaoRequest(**base)


# ----------------------------------------------------- centímetros -> metros
def test_medidas_vao_em_metros_com_virgula():
    """A ficha fala em cm; o formulário deles, em metros.

    30 cm tem que virar "0,3". Mandar "30" cotaria 30 METROS de altura — e o
    site aceitaria calado, porque 30 é um número válido para o campo."""
    p = t.preparar_payload(montar())

    assert p["cubing_height[]"] == "0,3"
    assert p["cubing_length[]"] == "0,3"
    assert p["cubing_depth[]"] == "0,3"


def test_metro_inteiro_nao_vira_notacao_cientifica():
    """Decimal.normalize() transforma 100 em '1E+2'. Num campo de texto isso
    entra como lixo e a cotação sai de uma carga que não existe."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(100),
                                 largura_cm=Decimal(100),
                                 altura_cm=Decimal(100), peso_kg=Decimal(3))])
    p = t.preparar_payload(req)

    assert p["cubing_height[]"] == "1"
    assert "E" not in p["cubing_height[]"]


def test_medida_quebrada_mantem_as_casas():
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal("25"),
                                 largura_cm=Decimal("12.5"),
                                 altura_cm=Decimal(30), peso_kg=Decimal(2))])
    p = t.preparar_payload(req)

    assert p["cubing_length[]"] == "0,125"
    assert p["cubing_depth[]"] == "0,25"


# ------------------------------------------------------------- máscaras
def test_cep_vai_sem_mascara_e_cnpj_vai_com():
    """Medido: o campo de CEP tem maxlength 8 (só dígitos) e o de CNPJ tem
    maxlength 18 (com ponto, barra e traço). Trocar os dois formatos faz o
    site recusar ou, pior, truncar."""
    p = t.preparar_payload(montar())

    assert p["value[sender_zipcode]"] == "29105770"
    assert p["value[receiver_zipcode]"] == "09895003"
    assert p["value[sender_cpnj]"] == "05.954.058/0001-98"
    assert p["value[receiver_cnpj_cpf]"] == "60.042.686/0001-05"


def test_remetente_e_destinatario_nao_se_invertem():
    """A regra do Enzo: a carga sai SEMPRE da Ventura. Inverter os dois cotaria
    a rota ao contrário — e o preço volta parecendo normal."""
    p = t.preparar_payload(montar())

    assert p["value[sender_cpnj]"] == "05.954.058/0001-98"   # remetente
    assert p["value[receiver_cnpj_cpf]"] == "60.042.686/0001-05"


# ------------------------------------------------------------- produto
def test_produto_e_sempre_supr_informatica():
    """Enzo confirmou: toda cotação usa este produto, seja qual for a carga.

    Não é detalhe cosmético — o FATOR DE CUBAGEM vem do produto. Sem ele o
    site usa fator 1 e o peso cubado sai 270x menor."""
    p = t.preparar_payload(montar(
        mercadoria=Mercadoria(tipo_material="Parafusos")))

    assert p["value[volume_product]"] == "SUPR.INFORMATICA"
    assert t.FATOR_CUBAGEM == Decimal(300)


# ------------------------------------------------------------- dinheiro/peso
def test_valor_da_nf_com_virgula_e_duas_casas():
    p = t.preparar_payload(montar())
    assert p["value[volume_nf]"] == "568,77"


def test_peso_e_o_TOTAL_da_carga_nao_o_unitario():
    """3 caixas de 12 kg são 36 kg no formulário. Mandar 12 subcota."""
    req = montar(volumes=[Volume(qtd=3, comprimento_cm=Decimal(30),
                                 largura_cm=Decimal(30), altura_cm=Decimal(30),
                                 peso_kg=Decimal(12))])
    p = t.preparar_payload(req)

    assert p["value[volume_weigth]"] == "36"
    assert p["cubing_qnt[]"] == "3"


# ------------------------------------------------------------- cubagem
def test_cubagem_esperada_reproduz_a_cotacao_real():
    """Âncora: esta carga é a cotação de 17/08/2026 que voltou R$ 116,36.

    Se este teste quebrar, a fórmula do site mudou — e o preço junto."""
    esperado = t.cubagem_esperada(montar())

    assert esperado["cubagem"] == "0,0270"
    assert esperado["peso_cubado"] == "8,10"


def test_cubagem_de_carga_volumosa():
    """3 volumes de 1 x 0,8 x 0,6 m = 1,44 m³ -> 432 kg cubados."""
    req = montar(volumes=[Volume(qtd=3, comprimento_cm=Decimal(80),
                                 largura_cm=Decimal(60),
                                 altura_cm=Decimal(100), peso_kg=Decimal(5))])
    esperado = t.cubagem_esperada(req)

    assert esperado["cubagem"] == "1,4400"
    assert esperado["peso_cubado"] == "432,00"


# ------------------------------------------------------------- validação
def test_cep_incompleto_bloqueia():
    erros = t.bloqueantes(t.validar(montar(cep_ori="2910")))
    assert any("cep" in e.campo for e in erros)


def test_medidas_distintas_bloqueiam_com_explicacao():
    """O formulário tem UMA linha de cubagem por vez (existe "adicionar
    linha", que ainda não automatizamos). Cotar só o primeiro volume e ignorar
    o resto devolveria um preço menor do que a carga real."""
    req = montar(volumes=[
        Volume(qtd=1, comprimento_cm=Decimal(30), largura_cm=Decimal(30),
               altura_cm=Decimal(30), peso_kg=Decimal(1)),
        Volume(qtd=1, comprimento_cm=Decimal(50), largura_cm=Decimal(40),
               altura_cm=Decimal(20), peso_kg=Decimal(2)),
    ])
    erros = t.bloqueantes(t.validar(req))

    assert erros
    assert any("medida" in e.mensagem.lower() for e in erros)


def test_carga_normal_nao_tem_erro():
    assert t.bloqueantes(t.validar(montar())) == []


# ------------------------------------------------------------- resposta
def test_faixa_de_resultado_vira_cotacao():
    """Texto real da faixa, medido em 18/08/2026."""
    texto = ("Consulta de Valor de Cotação\nPRAZO DE ENTREGA\n3 dias\n"
             "VALIDADE DA COTAÇÃO\n09/09/2026 17:09:00\nVALOR\nR$116,36")
    res = t.normalizar_resposta(texto)

    assert res.status is StatusCotacao.COTADO
    assert res.valor_frete == Decimal("116.36")
    assert res.prazo_dias == 3


def test_valor_com_milhar_e_lido_certo():
    texto = ("Consulta de Valor de Cotação PRAZO DE ENTREGA 4 dias "
             "VALIDADE DA COTAÇÃO 09/09/2026 VALOR R$1.234,56")
    res = t.normalizar_resposta(texto)

    assert res.valor_frete == Decimal("1234.56")


def test_valor_da_nf_nao_e_confundido_com_o_frete():
    """A NF aparece na MESMA tela, acima da faixa. Sem cortar no lugar certo,
    a leitura pegava R$ 568,77 (a mercadoria) como se fosse o frete."""
    texto = ("VALOR DA NF 15000,00 PESO TOTAL 80\n"
             "Consulta de Valor de Cotação PRAZO DE ENTREGA 4 dias "
             "VALIDADE 09/09/2026 VALOR R$399,78")
    res = t.normalizar_resposta(texto)

    assert res.valor_frete == Decimal("399.78")


def test_praca_nao_atendida_vira_recusa_nao_erro():
    """Não é falha do robô: é resposta legítima da transportadora, e o
    vendedor precisa ver isso escrito, não um stack trace."""
    res = t.normalizar_resposta(
        "Desculpe, o CEP informado não está em nossa região")

    assert res.status is StatusCotacao.RECUSADO
    assert "não atende" in (res.motivo_recusa or "").lower()


def test_tela_sem_valor_vira_erro():
    res = t.normalizar_resposta("Cotação de Frete\nPreencha os campos")

    assert res.status is StatusCotacao.ERRO
    assert res.valor_frete is None


# --------------------------------------------- CNPJ sem tabela na Translovato
def test_cnpj_sem_tabela_explica_o_que_fazer():
    """Medido em 18/08/2026: get-products devolve `null` quando o CNPJ do
    REMETENTE não é cliente da Translovato. Não é erro do robô nem carga
    inválida — é a regra comercial deles: só cotam carga SAINDO da Ventura.

    Acontece com o valor que já vem preenchido no aplicativo (HERCULES, um
    fornecedor). A frase (redigida com o Enzo em 19/08/2026) tem que deixar o
    vendedor resolver sozinho: o que ela aceita, quais CNPJs servem, qual ele
    usou, e para onde ir quando o frete é no sentido contrário."""
    frase = t.recusa_sem_tabela("60.042.686/0001-05")

    assert "60.042.686/0001-05" in frase          # o que ele usou
    assert "remetente" in frase.lower()
    for aceito in t.CNPJS_REMETENTE_ACEITOS:      # os que serviriam
        assert aceito in frase
    assert "whatsapp" in frase.lower()            # a saída para o outro sentido


def test_o_cnpj_errado_nao_entra_na_lista_de_aceitos():
    """A frase mostra o CNPJ usado E os aceitos. Se o usado aparecesse na
    lista, o vendedor tentaria de novo com o mesmo número."""
    assert "60.042.686/0001-05" not in t.CNPJS_REMETENTE_ACEITOS


def test_recusa_de_cep_diz_qual_cep_e_para_onde_ir():
    """"Não atende esse CEP" sozinho não resolve nada: o vendedor precisa
    saber QUAL dos dois CEPs, e o que fazer em seguida."""
    frase = t.recusa_cep_nao_atendido("69900000", "destino")

    assert "69900-000" in frase, "o CEP tem que aparecer legível, com traço"
    assert "destino" in frase.lower()
    assert "whatsapp" in frase.lower()
