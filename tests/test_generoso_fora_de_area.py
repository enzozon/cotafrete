"""A Generoso recusando por praça fora da malha — e por que isso não era ERRO.

Seis cotações reais entre 24/08 e 31/08/2026 (#5, #20, #40, #43, #78, #79)
viraram:

    RuntimeError: a etapa do destino não avançou. O site diz:
    (nenhuma mensagem visível)

O print de cada uma mostra a mesma coisa: o CEP É resolvido (cidade e rua
vêm preenchidas, ex. "São Sebastião do Passé/BA", "Maceió/AL"), mas um aviso
vermelho aparece embaixo do campo — "Ainda não atendemos essa origem. Veja
nossas unidades e cidades atendidas." — e o botão Próximo trava sem avançar.

`_erros_da_tela` não pega esse aviso: o filtro lá só casa
"obrigat|inválid|erro", e "não atendemos" não tem nenhuma dessas palavras.
Por isso a tela virava "(nenhuma mensagem visível)" mesmo com o aviso
visível na tela — mesma classe de bug de test_generoso_cnpj.py, resolvida
do mesmo jeito: checar o texto real da tela ANTES do Próximo, e virar
RECUSADO com a frase certa em vez de ERRO genérico repetido pela retentativa.
"""

from __future__ import annotations

import pytest

from carriers.generoso import mapping as m
from carriers.generoso.adapter import ForaDeArea, GenerosoAdapter
from core.models import StatusCotacao
from core.retentativa import vale_repetir
from tests.test_jadlog import montar

# Frase real, capturada nos prints de teste_real/generoso/20260826-165411/ e
# .../20260831-102226/ (produção).
AVISO_REAL = ("Ainda não atendemos essa origem. Veja nossas unidades e "
              "cidades atendidas.")


def test_a_frase_do_site_esta_reconhecida_no_mapping():
    assert m.AVISO_CEP_NAO_ATENDIDO in AVISO_REAL.lower()


@pytest.mark.parametrize("lado", ["origem", "destino"])
def test_a_recusa_nomeia_o_lado_e_o_cep(lado):
    """Numa cotação existem DOIS CEPs. Não dizer qual deixa o vendedor
    procurando no escuro — mesma lição de recusa_cliente_nao_cadastrado."""
    frase = m.recusa_cep_nao_atendido("62670000", lado)

    assert "62670000" in frase
    assert lado in frase
    assert "WhatsApp" in frase


def test_a_recusa_nao_fala_em_erro_de_sistema():
    frase = m.recusa_cep_nao_atendido("62670000", "destino")

    for tecnique in ("RuntimeError", "Timeout", "None", "null"):
        assert tecnique not in frase


# ------------------------------------- o que faz a repetição inútil parar
def test_cep_fora_de_area_vira_recusa_e_nao_repete(tmp_path):
    """RECUSADO, não ERRO — o que impede a retentativa de repetir três vezes
    para ouvir o mesmo "não atendemos" que a Generoso já tinha dado na
    primeira. Mesma forma de test_cliente_nao_cadastrado_vira_recusa_e_nao_repete
    em test_generoso_cnpj.py: `_entrar` levanta a exceção no lugar de
    percorrer o site, então nenhuma rede é tocada."""
    def recusar(self, page):
        raise ForaDeArea(m.recusa_cep_nao_atendido("62670000", "destino"))

    adapter = GenerosoAdapter(workdir=str(tmp_path), usuario="teste",
                              senha="teste")
    adapter._entrar = recusar.__get__(adapter)

    res = adapter.cotar(montar())

    assert res.status is StatusCotacao.RECUSADO
    assert res.erro is None, "recusa não é erro; o cartão lê isso"
    assert "62670000" in (res.motivo_recusa or "")
    assert not vale_repetir(res), "repetir daria o mesmo não, custando uma vaga"


# --------------------------- a regressao real: NameError em producao (03/09)
class _PaginaFalsa:
    """Só o suficiente para `_conferir_cobertura`: um `page.locator(...)
    .inner_text()`. O bug de producao (`NameError: name 'm' is not
    defined`) NUNCA teria passado no teste acima — ele forjava a exceção
    pronta em vez de rodar a linha de verdade. Este teste chama o método
    real, com o texto real da tela, e por isso quebra se o código quebrar."""
    def __init__(self, texto: str) -> None:
        self._texto = texto

    def locator(self, _seletor: str) -> "_PaginaFalsa":
        return self

    def inner_text(self) -> str:
        return self._texto


def test_conferir_cobertura_roda_a_linha_de_verdade():
    """Cotações #130, #131 e #132 (03/09/2026, ~16:27-16:39): TODAS as
    tentativas da Generoso viraram 'NameError: name 'm' is not defined' —
    o fix da praça fora da malha usava `m.AVISO_CEP_NAO_ATENDIDO`, mas este
    adapter importa a mapping por nome (`from ... import X, Y`), não como
    `m`. Nenhum teste chamava o código de verdade para pegar isso."""
    page = _PaginaFalsa("cabeçalho\n" + AVISO_REAL + "\nrodapé")

    with pytest.raises(ForaDeArea) as excinfo:
        GenerosoAdapter._conferir_cobertura(page, "destino", montar())

    assert "01310100" in str(excinfo.value)  # o CEP do destino da ficha


def test_conferir_cobertura_no_caminho_feliz_nao_levanta_nada():
    page = _PaginaFalsa("Peso total 63,00 kg — tudo certo")

    GenerosoAdapter._conferir_cobertura(page, "origem", montar())  # não lança


# ------------------ a outra metade dos 6: origem e destino no mesmo CEP
# Frases reais, capturadas em teste_real/generoso/20260824-104757/erro.png
# (cotação #5) e .../20260825-113325/erro.png (cotação #20) — as duas com o
# CNPJ do lado livre batendo numa empresa do grupo Ventura já cadastrada no
# mesmo endereço da ponta travada.
AVISO_MESMO_CEP_REAL = "CEP de destino não pode ser o mesmo de coleta"
# A ordem invertida que o mapping.py já documentava desde a Translovato, sem
# nunca ter sido vista do lado da Generoso — a detecção tem que pegar as duas.
AVISO_MESMO_CEP_INVERTIDO = "CEP de coleta não pode ser o mesmo de destino"


def test_aviso_de_mesmo_cep_reconhecido_nas_duas_ordens():
    assert m.AVISO_MESMO_CEP in AVISO_MESMO_CEP_REAL.lower()
    assert m.AVISO_MESMO_CEP in AVISO_MESMO_CEP_INVERTIDO.lower()


def test_mesmo_cep_vira_recusa_e_nao_erro_generico():
    """Cotações #5 e #20 (24-25/08/2026): mesma classe de bug que
    AVISO_CEP_NAO_ATENDIDO — o aviso não bate com "obrigat|inválid|erro" e
    o Próximo trava calado, virando "etapa não avançou" genérico."""
    page = _PaginaFalsa("cabeçalho\n" + AVISO_MESMO_CEP_REAL + "\nrodapé")

    with pytest.raises(ForaDeArea) as excinfo:
        GenerosoAdapter._conferir_cobertura(page, "destino", montar())

    assert "CNPJ" in str(excinfo.value)


def test_mesmo_cep_nao_precisa_dizer_qual_lado():
    """Ao contrário de AVISO_CEP_NAO_ATENDIDO, aqui não dá para saber de
    qual lado o site está reclamando (ele usa as duas ordens) — a mensagem
    não pode fingir que sabe."""
    page = _PaginaFalsa(AVISO_MESMO_CEP_INVERTIDO)

    with pytest.raises(ForaDeArea) as excinfo:
        GenerosoAdapter._conferir_cobertura(page, "origem", montar())

    for lado in ("origem", "destino"):
        assert f"de {lado}" not in str(excinfo.value)


# ------------------------- a outra causa da #130: empresa da conta, nao da aba
def test_cotar_esta_protegido_pela_trava_da_conta():
    """A #130 (03/09/2026, 16:27) pediu a empresa Alianca e saiu com o CNPJ
    da Ventura (o padrão da conta) — rodando ao mesmo tempo que a #131.
    Repetida sozinha minutos depois (#132), saiu certa: a diferença foi só
    ter rodado concorrente. A "empresa ativa" é estado DA CONTA na Generoso,
    não da aba do navegador (o próprio `_escolher_empresa` já documentava
    isso: "a conta abre na empresa que cotou por último") — duas sessões
    concorrentes se pisam.

    Simular duas cotações reais concorrentes exigiria mockar o Playwright
    inteiro (`sync_playwright` é importado DENTRO de `cotar`, não dá para
    substituir de fora). Este é o teste de fumaça mais barato que ainda
    quebra se alguém tirar a trava do lugar certo: confere que `cotar`
    adquire `_TRAVA_CONTA` ANTES de abrir o navegador, não depois."""
    import inspect

    from carriers.generoso.adapter import GenerosoAdapter

    fonte = inspect.getsource(GenerosoAdapter.cotar)

    assert "_TRAVA_CONTA" in fonte, "a trava sumiu de cotar()"
    assert fonte.index("_TRAVA_CONTA") < fonte.index("sync_playwright() as p"), (
        "a trava tem que vir ANTES do navegador abrir, senão duas sessões "
        "ainda entram juntas na tela que troca a empresa")
