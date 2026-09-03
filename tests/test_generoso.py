"""Camada pura do Generoso.

O formulário é em etapas e quase tudo do endereço vem do CNPJ, então o que
sobra para a camada pura é pequeno — mas é onde mora o erro caro: a máscara
do peso e o formato do valor da nota.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from carriers.generoso.adapter import (
    TIPO_PAGADOR_REMETENTE, GenerosoAdapter, ler_resultado,
)
from core.models import StatusCotacao, Volume
from tests.test_jadlog import montar


@pytest.fixture
def adapter():
    return GenerosoAdapter()


# --------------------------------------------------------- máscara do peso
@pytest.mark.parametrize("kg, digitado", [
    (Decimal(1), "1,00"),
    (Decimal(12), "12,00"),
    (Decimal("0.5"), "0,50"),
    (Decimal(25), "25,00"),
    (Decimal("1.5"), "1,50"),
])
def test_peso_vai_com_duas_casas(adapter, kg, digitado):
    """Máscara medida no site em 13/08/2026, de 2 casas e da direita para a
    esquerda — o Enzo já tinha avisado e o recon confirmou:

        type("1")    -> 0.01
        type("100")  -> 1.00
        type("1200") -> 12.00

    Mandar "1" cotaria 10 gramas. A forma com vírgula e 2 casas produz o
    mesmo resultado que a de dígitos e é legível no código."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(30),
                                 largura_cm=Decimal(30), altura_cm=Decimal(30),
                                 peso_kg=kg)])
    assert adapter.preparar_payload(req)["peso"] == digitado


def test_medida_vai_inteira_em_cm(adapter):
    """As medidas não têm máscara: vão como inteiro, em centímetros."""
    req = montar(volumes=[Volume(qtd=1, comprimento_cm=Decimal(80),
                                 largura_cm=Decimal(60), altura_cm=Decimal(50),
                                 peso_kg=Decimal(4))])
    p = adapter.preparar_payload(req)

    assert p["altura"] == "50"
    assert p["largura"] == "60"
    assert p["comprimento"] == "80"


def test_peso_e_de_um_volume_e_quantidade_vai_separada(adapter):
    """O site tem 'Peso unitário' e 'Quantidade' e calcula o total sozinho.
    Mandar o peso do lote no campo unitário multiplicaria a carga."""
    req = montar(volumes=[Volume(qtd=3, comprimento_cm=Decimal(30),
                                 largura_cm=Decimal(30), altura_cm=Decimal(30),
                                 peso_kg=Decimal(12))])
    p = adapter.preparar_payload(req)

    assert p["peso"] == "12,00"        # unitário, não 36
    assert p["quantidade"] == "3"


def test_material_da_ficha_vai_para_a_observacao(adapter):
    """O formulário do Generoso não tem seletor de tipo de mercadoria — o
    site manda 1 fixo. Sem levar o material para a Observação, o vendedor
    recebe uma cotação sem saber o que vai transportar."""
    p = adapter.preparar_payload(montar())
    assert p["observacao"] == "Eletrônicos"


def test_embalagem_entra_no_payload(adapter):
    from carriers.generoso.adapter import EMBALAGEM_PADRAO
    assert adapter.preparar_payload(montar())["embalagem"] == EMBALAGEM_PADRAO


def test_embalagem_inexistente_e_recusada_na_criacao():
    """Escolher uma embalagem que não existe no site travaria a etapa da
    Carga com 'campo obrigatório' — melhor falhar aqui, com a lista."""
    with pytest.raises(ValueError, match="Engradado"):
        GenerosoAdapter(embalagem="Palete")


def test_valor_da_nota_em_formato_brasileiro(adapter):
    assert adapter.preparar_payload(montar())["valor_nf"] == "1500,00"


def test_documentos_vao_para_os_papeis_certos(adapter):
    """Três CNPJs, três papéis. Trocar remetente com destinatário inverteria
    a rota e o frete sairia de outra praça."""
    p = adapter.preparar_payload(montar())

    assert p["cnpj_remetente"] == "11.222.333/0001-81"
    # CIF: o pagador e o remetente (ver core.models.TipoFrete)
    assert p["cnpj_solicitante"] == "11.222.333/0001-81"


def test_cnpj_do_destinatario_entra_no_payload(adapter):
    """Logado, o site NAO deduz mais o destinatario: a etapa do destino vem
    com o CNPJ em branco e e dele que sai o endereco inteiro. Sem este campo
    a cotacao nao tem para onde ir.

    Medido em 20/08/2026: com CIF, digitar 60.042.686/0001-05 no destino
    trouxe Santo Andre/SP, Avenida dos Estados, CEP 09.220-570."""
    req = montar()
    p = adapter.preparar_payload(req)

    assert p["cnpj_destinatario"] == req.destinatario.cnpj_formatado


def test_o_padrao_e_CIF_porque_o_frete_sai_da_ventura(adapter):
    """Logado como Ventura, FOB quer dizer Ventura RECEBENDO: o site trava o
    destino no CNPJ da conta, e como a origem tambem e a Ventura ele recusa
    com "CEP de coleta nao pode ser o mesmo de destino".

    O Cotafrete cota frete SAINDO da Ventura. Isso e CIF."""
    assert adapter.preparar_payload(montar())["tipo_pagador"] == (
        TIPO_PAGADOR_REMETENTE)


# ------------------------------------------------------ leitura do resultado
def test_confirmacao_do_site_e_reconhecida(adapter):
    """Tela final medida: 'Recebemos seu pedido de cotação. Entraremos em
    contato em breve!' — não há preço nenhum, igual à Della Volpe."""
    res = adapter.normalizar_resposta(
        "Resultado\nRecebemos seu pedido de cotação. "
        "Entraremos em contato em breve!\nNova cotação")

    assert res.status is StatusCotacao.AGUARDANDO_RETORNO
    assert res.valor_frete is None
    assert res.erro is None


def test_tela_sem_confirmacao_vira_erro(adapter):
    """Sem a frase, não houve envio. Dar aguardando_retorno aqui repetiria o
    erro da Della Volpe, onde cinco cotações 'enviadas' nunca saíram."""
    res = adapter.normalizar_resposta("Carga\nPróximo\nConfirmar e ver resultado")
    assert res.status is StatusCotacao.ERRO


@pytest.mark.parametrize("texto, esperado", [
    ("Recebemos seu pedido de cotação", True),
    ("RECEBEMOS SEU PEDIDO DE COTAÇÃO. Entraremos em contato", True),
    ("Entraremos em contato em breve!", True),
    ("Preencha os campos para receber sua cotação", False),
    ("", False),
])
def test_frases_de_confirmacao(texto, esperado):
    assert ler_resultado(texto) is esperado


# ------------------------------------------------------------------ login
def test_sem_credenciais_recusa_sem_abrir_navegador(monkeypatch):
    """Logado, a Generoso mostra o preco na tela; deslogado ela so confirma o
    recebimento. Sem usuario e senha nao ha o que tentar — e abrir um Chromium
    inteiro para descobrir isso gastaria 45s de uma vaga de navegador que as
    outras transportadoras estao esperando."""
    monkeypatch.delenv("GENEROSO_USUARIO", raising=False)
    monkeypatch.delenv("GENEROSO_SENHA", raising=False)

    def estourar(*_a, **_k):
        raise AssertionError("abriu o navegador sem ter credenciais")

    monkeypatch.setattr("playwright.sync_api.sync_playwright", estourar)

    res = GenerosoAdapter().cotar(montar())

    assert res.status is StatusCotacao.ERRO
    assert "GENEROSO_USUARIO" in (res.erro or "")


# ------------------------------------------- tela de resultado, LOGADO
# Medida no envio real de 20/08/2026 (cotação 2651152). Rótulo numa linha,
# valor na seguinte — é assim que o inner_text sai desta página, e o R$ vem
# com espaço NÃO separável ( ), não com espaço comum.
TELA_COM_PRECO = """Resultado da cotação

Cotação: 2651152

Frete
R$ 421,94
Previsão de entrega
25/08/26
Cotado em
20/08/26
Cotação válida até
30/08/26

O valor de R$ 421,94 é válido para contratação até dia 30/08/26,
considerando os dados iguais ao da NFe

Detalhes desta cotação
Solicitante:
CNPJ
08.310.365/0001-24
"""


def test_le_o_valor_do_frete_da_tela_logada(adapter):
    """Logada, a Generoso deixa de ser assíncrona: o preço está na tela.
    Ler errado aqui é pior que não ler — vira número na mesa do cliente."""
    res = adapter.normalizar_resposta(TELA_COM_PRECO)

    assert res.status is StatusCotacao.COTADO
    assert res.valor_frete == Decimal("421.94")


def test_le_o_numero_da_cotacao_como_protocolo(adapter):
    """É por esse número que se fala com a Generoso sobre esta cotação."""
    assert adapter.normalizar_resposta(TELA_COM_PRECO).protocolo == "2651152"


def test_prazo_sai_da_diferenca_entre_as_duas_datas(adapter):
    """A tela dá datas, não dias: cotado em 20/08, entrega 25/08 = 5 dias.
    O resto do sistema compara prazo em dias."""
    assert adapter.normalizar_resposta(TELA_COM_PRECO).prazo_dias == 5


def test_valor_com_milhar_nao_vira_numero_menor(adapter):
    """R$ 1.421,94 tem ponto de milhar e vírgula decimal. Lido como float
    ingênuo viraria 1,42 — cem vezes menos, e ninguém veria."""
    res = adapter.normalizar_resposta(
        TELA_COM_PRECO.replace("421,94", "1.421,94"))

    assert res.valor_frete == Decimal("1421.94")


def test_tela_deslogada_ainda_e_reconhecida_como_recebida(adapter):
    """Se a sessão cair no meio, o site cai no formulário público e mostra
    "Recebemos seu pedido". Não é preço, mas também não é falha: a cotação
    foi enviada e a resposta vem por e-mail."""
    res = adapter.normalizar_resposta(
        "Recebemos seu pedido de cotação. Entraremos em contato.")

    assert res.status is StatusCotacao.AGUARDANDO_RETORNO
    assert res.valor_frete is None


# ------------------------------- a quarta tela: origem de unidade parceira
TELA_UNIDADE_PARCEIRA = """Resultado da cotação
Aguardando validação: 90ca36a0-9ca0-45be-a924-62f3356b62d5
Identificamos que o endereço de origem é atendido por uma de nossas
unidades parceiras.
Essa estrutura foi criada justamente para garantir mais agilidade e
proximidade no seu transporte.
Por isso, para obter valores e prazos personalizados, pedimos que realize
sua cotação diretamente com a unidade responsável. Fique tranquilo:
acompanhamos todo o padrão de qualidade de perto.
Consulte o contato da unidade aqui:
rodonaves.com.br/cidades-atendidas
Detalhes desta cotação"""


def test_origem_de_unidade_parceira_e_recusa_e_nao_erro(adapter):
    """A quarta tela, descoberta em 24/08/2026.

    Ela derrubou QUATRO cotacoes de producao seguidas (#6 a #9), todas com
    "A tela de resultado nao trouxe preco nem confirmacao de recebimento" —
    generico, com cara de defeito do programa, e ainda repetido tres vezes
    pela retentativa.

    Nao e falha nossa nem erro: a Generoso ATENDE aquela origem, so que por
    uma unidade parceira que cota por fora. Como recusa, o cartao explica e
    a retentativa nao insiste.
    """
    res = adapter.normalizar_resposta(TELA_UNIDADE_PARCEIRA)

    assert res.status is StatusCotacao.RECUSADO
    assert res.erro is None
    assert res.motivo_recusa
    assert "unidade" in res.motivo_recusa.lower()


def test_recusa_de_unidade_parceira_leva_o_link_do_site(adapter):
    """O vendedor precisa saber PARA ONDE ir. Sem o endereco, "fale com a
    unidade responsavel" e um beco sem saida."""
    res = adapter.normalizar_resposta(TELA_UNIDADE_PARCEIRA)

    assert "rodonaves.com.br/cidades-atendidas" in res.motivo_recusa


def test_tela_desconhecida_continua_sendo_erro(adapter):
    """A regra nova nao pode engolir tela que ninguem entendeu: erro de
    verdade continua erro, e continua sendo repetido."""
    res = adapter.normalizar_resposta("Erro 500 Internal Server Error")

    assert res.status is StatusCotacao.ERRO


# ---------------------------- a quinta tela: carga acima dos limites do site
TELA_LIMITE_EXCEDIDO = """Resultado da cotação
Aguardando validação: 2666464
A carga ultrapassou os limites permitidos para o site.
Confira os limites máximos abaixo:
Peso máximo: 5000
Cubagem máxima: 10
Peso máximo por volume: 80
Detalhes desta cotação"""


def test_carga_acima_do_limite_do_site_e_recusa_e_nao_erro(adapter):
    """Medida em duas cotacoes reais de 03/09/2026 (#120 e #122): a mesma
    tela generica de "sem preco nem confirmacao" que ja tinha acontecido com
    a unidade parceira — so que aqui a Generoso esta dizendo que a carga
    passa do peso/cubagem que o site aceita, nao que houve falha nossa."""
    res = adapter.normalizar_resposta(TELA_LIMITE_EXCEDIDO)

    assert res.status is StatusCotacao.RECUSADO
    assert res.erro is None
    assert res.motivo_recusa
    assert "limite" in res.motivo_recusa.lower()


def test_recusa_de_limite_leva_os_numeros_da_tela(adapter):
    """O vendedor precisa saber ATE QUANTO da para mandar, sem abrir a
    print."""
    res = adapter.normalizar_resposta(TELA_LIMITE_EXCEDIDO)

    assert "5000" in res.motivo_recusa
    assert "10" in res.motivo_recusa
    assert "80" in res.motivo_recusa


# ------------------- CIF/FOB trocado: recusa antes de abrir o navegador
def test_cif_fob_trocado_vira_recusa_e_nao_abre_navegador():
    """Cotacoes #5 e #20 de producao, #53 de desenvolvimento.

    Nao e defeito nosso nem carga invalida: o vendedor marcou CIF com uma
    empresa do grupo no destino. A Generoso trava o endereco dessa ponta no
    CNPJ cadastrado, as duas pontas viram a mesma casa, e o site recusa por
    um `aria-invalid` que ninguem le — 40 segundos de navegador para
    devolver "(nenhuma mensagem visivel)", tres vezes, por causa da
    retentativa.

    `validar` devolvendo Severidade.ERRO faz `cotar` sair por
    `recusa_por_validacao` ANTES do `sync_playwright`. RECUSADO tambem nao
    e repetido pela retentativa, que e o certo: repetir nao muda um engano
    de preenchimento.
    """
    from carriers.base import Severidade
    from carriers.generoso.adapter import GenerosoAdapter
    from core.models import Parte, TipoFrete
    from tests.test_jadlog import montar

    req = montar(tipo_frete=TipoFrete.CIF,
                 remetente=Parte(cnpj="60.042.686/0001-05"),      # Hercules
                 destinatario=Parte(cnpj="05.954.058/0001-98"))   # Alianca

    graves = [e for e in GenerosoAdapter().validar(req)
              if e.severidade is Severidade.ERRO]

    assert len(graves) == 1
    assert "FOB" in graves[0].mensagem
    assert "CEP" in graves[0].mensagem


def test_cotacao_com_cif_fob_coerente_continua_passando():
    """A trava nao pode pegar quem preencheu certo."""
    from carriers.base import Severidade
    from carriers.generoso.adapter import GenerosoAdapter
    from core.models import Parte, TipoFrete
    from tests.test_jadlog import montar

    req = montar(tipo_frete=TipoFrete.FOB,
                 remetente=Parte(cnpj="60.042.686/0001-05"),
                 destinatario=Parte(cnpj="05.954.058/0001-98"))

    graves = [e for e in GenerosoAdapter().validar(req)
              if e.severidade is Severidade.ERRO]

    assert graves == []
