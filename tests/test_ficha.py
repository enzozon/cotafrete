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
from core.ficha import CamposFaltando, ler_ficha, ler_modalidade
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


def test_peso_e_de_UM_volume_e_multiplica_pela_quantidade():
    """Regra do Enzo, 13/08/2026: o peso é o de UM produto.

    "3 de 12kg voce coloca 12kg e 3 volumes". Dividir pela quantidade — que
    era o que este código fazia — cotaria 4kg por volume, 12kg no total: um
    terço da carga real, e o frete sai barato demais sem nenhum aviso."""
    texto = (FICHA.replace("Peso Total (kg): 1", "Peso Total (kg): 12")
                  .replace("Quantidade de Volumes: 1", "Quantidade de Volumes: 3"))
    req = ler_ficha(texto)

    assert req.volumes[0].peso_kg == Decimal(12)
    assert req.peso_total_kg == Decimal(36)


# ------------------------------------------- cidade e UF vêm do CEP, não da mão
def test_cidade_e_uf_saem_do_cep_quando_nao_estao_na_ficha():
    """Regra 1: o CEP manda. Digitar cidade à mão foi o que gerou o erro de
    13/08/2026 — a ficha dizia "São José dos Campos" e o CEP 09895-003 é São
    Bernardo do Campo. A Jadlog cota por CEP e a Della Volpe por cidade, então
    a mesma ficha cotava DUAS rotas diferentes."""
    texto = "\n".join(l for l in FICHA.splitlines()
                      if not l.lower().startswith(("uf ", "cidade ")))

    def busca_falsa(cep: str):
        return {"09895003": ("São Bernardo do Campo", "SP", "3548708"),
                "29105770": ("Vila Velha", "ES", "3205200")}[cep]

    req = ler_ficha(texto, buscar_cep=busca_falsa)

    assert (req.origem.cidade, req.origem.uf) == ("São Bernardo do Campo", "SP")
    assert (req.destino.cidade, req.destino.uf) == ("Vila Velha", "ES")
    assert req.origem.codigo_ibge == "3548708"


def test_cep_na_ficha_vence_a_cidade_digitada():
    """Se os dois vierem, o CEP ganha — é ele que a transportadora usa para
    calcular. Cidade digitada é lembrete humano, não fonte de verdade."""
    def busca_falsa(cep: str):
        return ("São Bernardo do Campo", "SP", "3548708")

    req = ler_ficha(FICHA, buscar_cep=busca_falsa)
    assert req.origem.cidade == "São Bernardo do Campo"    # não "São José dos Campos"


def test_sem_busca_de_cep_a_cidade_da_ficha_e_usada():
    """Camada pura continua pura: sem callable injetado, não há rede."""
    assert ler_ficha(FICHA).origem.cidade == "São José dos Campos"


# ------------------------------------------------------------------ modalidade
# Fora do CotacaoRequest de propósito: modalidade é vocabulário da Jadlog, e o
# modelo central não conhece transportadora. Por isso é função à parte.
def test_modalidade_da_ficha_e_normalizada():
    assert ler_modalidade(FICHA + "modalidade: Expresso\n") == "expresso"
    assert ler_modalidade(FICHA + "Modalidade: RODOVIARIO\n") == "rodoviario"


def test_modalidade_ausente_cai_no_padrao():
    assert ler_modalidade(FICHA) == "expresso"


def test_modalidade_desconhecida_e_erro_e_lista_as_validas():
    with pytest.raises(ValueError, match="package"):
        ler_modalidade(FICHA + "modalidade: turbo a jato\n")


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


@pytest.mark.parametrize("escrito", [
    "+55 (27) 3063-1564",
    "+5527306315 64",
    "5527306 31564",
    "55 27 3063-1564",
])
def test_codigo_do_pais_e_removido_do_whatsapp(escrito):
    """Medido no formulário da Della Volpe em 13/08/2026.

    Mandamos '+55 (27) 3063-1564' e o campo, que tem máscara de telefone
    brasileiro, mostrou '(55) 2730-631': o +55 virou DDD e o número inteiro
    escorregou. O vendedor ligaria para um telefone que não existe, e nada
    no envio acusa isso."""
    texto = FICHA.replace("WhatsApp: 27999887766", f"WhatsApp: {escrito}")
    req = ler_ficha(texto)

    assert req.solicitante.whatsapp_formatado == "(27) 3063-1564"


def test_numero_sem_codigo_do_pais_continua_igual():
    """Não pode sair cortando '55' de quem tem DDD 55 (RS, Santa Maria)."""
    texto = FICHA.replace("WhatsApp: 27999887766", "WhatsApp: (55) 99988-7766")
    assert ler_ficha(texto).solicitante.whatsapp_formatado == "(55) 99988-7766"


def test_valor_da_nota_vai_em_formato_brasileiro_nos_dois(req):
    assert JadlogSimuladorAdapter().preparar_payload(req)["valor_mercadoria"] == "568,77"
    assert dv.preparar_payload(req)["Valor total da nota fiscal"] == "568,77"
