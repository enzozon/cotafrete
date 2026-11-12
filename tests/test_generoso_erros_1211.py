"""Seis defeitos da Generoso e da Favorita medidos em produção, 05 a 12/11/2026.

Cada um com o caso real que o derrubou:

1. #632, #633, #665, #666 (Generoso): "CEP deve ser da mesma UF do cadastro
   (SP)" embaixo do CEP virava o genérico "a etapa do destino não avançou.
   O site diz: (nenhuma mensagem visível)".
2. #665, #666 (Favorita): a recusa saiu "cadastrado na Favorita em
   Guarulhos/RS" — a cidade do cadastro com a UF do CEP da cotação.
3. #613 (Generoso): cadastro sem número com o mesmo CEP da cotação; ninguém
   marcava "Sem número" e o site respondia "Número é obrigatório quando não
   marcado "Sem número"".
4. #654, #655 (Favorita): "Ainda não realizamos transporte entre as cidades
   informadas" na tela de resultado caía em ERRO.
5. #610 (Favorita): o CNPJ não trouxe endereço, o site não disse nada e os
   campos ficaram abertos; saía RuntimeError em vez de digitar o endereço.
6. #670, #671, #672 (as duas, 12/11): com a internet da VM lenta, "campo não
   encontrado" e um falso "a Generoso não aceitou o login".

Nenhum teste aqui toca a rede nem abre navegador: as páginas são de mentira.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from carriers.base import CredencialRecusada
from carriers.favorita.adapter import FavoritaAdapter
from carriers.generoso import adapter as modulo
from carriers.generoso import mapping as m
from carriers.generoso.adapter import ForaDeArea, GenerosoAdapter
from core.models import Parte, StatusCotacao
from core.retentativa import vale_repetir
from tests.test_jadlog import montar

CAPTURA = json.loads(
    (Path(__file__).parent / "fixtures" / "generoso_busca_cnpj.json")
    .read_text(encoding="utf-8"))

VENTURA = Parte(cnpj="08.310.365/0001-24")
CADASTRO_SP = {"cep": "07.190-100", "city": "Guarulhos", "state": "SP",
               "neighborhood": "Cumbica", "address": "Rodovia Helio Smidt"}


class _Texto:
    """`page.locator("body").inner_text()`, e mais nada."""
    def __init__(self, texto: str) -> None:
        self._texto = texto

    def locator(self, _seletor: str) -> "_Texto":
        return self

    def inner_text(self) -> str:
        return self._texto


class _Campo:
    def __init__(self, valor: str = "", ligado: bool = True) -> None:
        self.valor, self.ligado = valor, ligado

    def is_enabled(self) -> bool:
        return self.ligado

    def input_value(self) -> str:
        return self.valor

    def blur(self) -> None:
        pass


# ------------------- 1. "CEP deve ser da mesma UF do cadastro (SP)"
AVISO_MESMA_UF_REAL = "CEP deve ser da mesma UF do cadastro (SP)"


def _cep_recusado_pela_uf(adapter):
    """O site mantém a cidade do cadastro e mostra o aviso embaixo do CEP."""
    adapter._campo = lambda page, seletor: _Campo()
    adapter._endereco_a_mao = lambda page, req, lado, cnpj: {
        **CADASTRO_SP, "cep": "90.010-000", "state": "RS"}
    page = _Texto("Dados da origem\nCEP\n90.010-000\n" + AVISO_MESMA_UF_REAL)
    with pytest.raises(ForaDeArea) as excinfo:
        adapter._usar_cep_da_cotacao(
            page, montar(cep_des="90010000"), "destino",
            "11.222.333/0001-81", dict(CADASTRO_SP))
    return str(excinfo.value)


def test_a_frase_da_mesma_uf_esta_reconhecida_no_mapping():
    assert m.AVISO_MESMA_UF in AVISO_MESMA_UF_REAL.lower()


def test_cep_de_outra_uf_vira_recusa_e_nao_erro_generico():
    frase = _cep_recusado_pela_uf(GenerosoAdapter())
    assert "11.222.333/0001-81" in frase and "90010000" in frase
    assert "cadastrado na Generoso em Guarulhos/SP" in frase


def test_sem_o_aviso_o_cep_digitado_segue():
    novo = {"cep": "01.310-100", "city": "São Paulo", "state": "SP",
            "address": "Avenida Paulista"}
    a = GenerosoAdapter()
    a._campo = lambda page, seletor: _Campo()
    a._endereco_a_mao = lambda page, req, lado, cnpj: novo
    assert a._usar_cep_da_cotacao(_Texto("Dados do destino"), montar(),
                                  "destino", "x", dict(CADASTRO_SP)) == novo


# ----------------------- 2. cidade do cadastro com a UF do cadastro
def test_a_recusa_da_favorita_nao_mistura_a_uf_do_cep_digitado():
    """Como saiu nas #665/#666: "Guarulhos/RS"."""
    frase = _cep_recusado_pela_uf(FavoritaAdapter())
    assert "cadastrado na Favorita em Guarulhos/SP" in frase
    assert "Guarulhos/RS" not in frase


def test_a_uf_do_cadastro_sai_da_resposta_da_busca():
    assert m.uf_do_cadastro(CAPTURA["conhecido"]["corpo"]) == "ES"
    assert m.uf_do_cadastro(CAPTURA["desconhecido"]["corpo"]) is None
    assert m.uf_do_cadastro("") is None


class _PaginaDaBusca:
    """Entrega a resposta da busca de CNPJ enquanto a ponta é preenchida."""
    def __init__(self, corpo: str) -> None:
        self.corpo = corpo
        self.ouvinte = None

    def on(self, _evento, ouvinte) -> None:
        self.ouvinte = ouvinte

    def remove_listener(self, _evento, _ouvinte) -> None:
        self.ouvinte = None

    def wait_for_timeout(self, _ms) -> None:
        if self.ouvinte:
            resposta = MagicMock()
            resposta.request.method = "POST"
            resposta.url = "https://cliente.favorita.com.br/cotacao"
            resposta.text.return_value = self.corpo
            self.ouvinte(resposta)


def test_ponta_preenchida_traz_a_uf_do_cadastro_e_nao_a_do_campo():
    """O campo `state` da tela pode não ser o do cadastro; a busca é."""
    a = FavoritaAdapter()
    a._digitar = lambda page, seletor, valor: None
    a._campo = lambda page, seletor: _Campo()
    a._esperar_endereco = lambda page, tentativas=12: {
        **CADASTRO_SP, "state": "RS"}
    corpo = CAPTURA["conhecido"]["corpo"].replace(
        '"cidade":"VILA VELHA","uf":"ES"', '"cidade":"GUARULHOS","uf":"SP"')
    assert '"uf":"SP"' in corpo, "a captura mudou de forma"

    achado, resposta = a._preencher_ponta(_PaginaDaBusca(corpo),
                                          "11.222.333/0001-81")

    assert (achado["city"], achado["state"]) == ("Guarulhos", "SP")
    assert resposta == corpo


def test_sem_resposta_da_busca_fica_a_uf_da_tela():
    a = GenerosoAdapter()
    a._digitar = lambda page, seletor, valor: None
    a._campo = lambda page, seletor: _Campo()
    a._esperar_endereco = lambda page, tentativas=12: dict(CADASTRO_SP)
    achado, _ = a._preencher_ponta(_PaginaDaBusca(""), "11.222.333/0001-81")
    assert achado["state"] == "SP"


# ---------------------- 3 e 5: o laço das pontas, com o site de mentira
def _cotar(monkeypatch, tmp_path, adapter, *, numero: _Campo | None = None,
           destino: dict | None = None, cep: _Campo | None = None):
    """Roda o `cotar` de verdade até a etapa do destino, sem navegador.

    Só as pontas são de verdade; login, empresa e a leitura dos endereços
    são trocados. `_chegou_na_carga` devolve False para o `cotar` parar ali
    (vira ERRO "a etapa do destino não avançou")."""
    passos: list[str] = []
    page = MagicMock()
    vazio = MagicMock()
    vazio.count.return_value = 0
    casa = MagicMock()
    casa.count.return_value = 1 if numero else 0
    casa.last = numero
    page.locator.side_effect = lambda seletor: (
        casa if seletor == 'input[name="number"]:visible' else vazio)
    page.get_by_text.return_value.click.side_effect = (
        lambda: passos.append("sem número"))

    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.launch.return_value \
        .new_context.return_value.new_page.return_value = page
    monkeypatch.setattr("playwright.sync_api.sync_playwright",
                        lambda: playwright)
    monkeypatch.setattr(modulo, "print_seguro", lambda page, caminho: [])

    cadastro = {"cep": "01.310-100", "city": "São Paulo", "state": "SP",
                "neighborhood": "Bela Vista", "address": "Avenida Paulista"}
    adapter.workdir = tmp_path
    adapter.usuario = adapter.senha = "teste"
    adapter._entrar = lambda page: None
    adapter._escolher_empresa = lambda page, empresa: None
    adapter._preencher_ponta = lambda page, cnpj: (
        (dict(cadastro), "") if cnpj is None
        else (dict(cadastro if destino is None else destino), ""))
    adapter._conferir_cobertura = lambda page, lado, req: None
    adapter._campo = lambda page, seletor: (
        cep if cep and "cep" in seletor else _Campo("Bela Vista"))
    adapter._avancar = lambda page: passos.append("próximo")
    adapter._chegou_na_carga = lambda page: False
    adapter._erros_da_tela = lambda page: "(nenhuma mensagem visível)"

    def a_mao(page, req, lado, cnpj):
        passos.append("endereço à mão")
        return dict(cadastro)
    adapter._endereco_a_mao = a_mao

    res = adapter.cotar(montar(remetente=VENTURA), confirmar_envio=False)
    return res, passos, page


def test_cadastro_sem_numero_marca_sem_numero_antes_do_proximo(
        monkeypatch, tmp_path):
    """#613: mesmo CEP da cotação, `_usar_cep_da_cotacao` volta cedo e o
    campo do número ficava vazio."""
    _, passos, page = _cotar(monkeypatch, tmp_path, GenerosoAdapter(),
                             numero=_Campo(""))
    page.get_by_text.assert_called_with("Sem número", exact=True)
    # etapa 1, e depois as duas pontas: marca e só então avança
    assert passos == ["próximo", "sem número", "próximo",
                      "sem número", "próximo"]


@pytest.mark.parametrize("numero", [
    _Campo("492"),                 # cadastro com número
    _Campo("", ligado=False),      # já marcado, ou travado pelo site
    None,                          # etapa sem o campo
])
def test_sem_numero_nao_e_marcado_quando_nao_precisa(
        monkeypatch, tmp_path, numero):
    _, passos, _ = _cotar(monkeypatch, tmp_path, GenerosoAdapter(),
                          numero=numero)
    assert passos == ["próximo"] * 3


def test_o_sem_numero_e_marcado_num_lugar_so():
    import inspect
    assert inspect.getsource(GenerosoAdapter).count(
        'get_by_text("Sem número"') == 1


SEM_ENDERECO = {"cep": "", "city": "", "state": "", "neighborhood": "",
                "address": ""}


def test_favorita_digita_o_endereco_quando_o_cnpj_nao_trouxe_nada(
        monkeypatch, tmp_path):
    """#610: a busca não respondeu "nao cadastrado", a cidade veio vazia e o
    CEP ficou editável."""
    res, passos, _ = _cotar(monkeypatch, tmp_path, FavoritaAdapter(),
                            destino=SEM_ENDERECO)
    assert "endereço à mão" in passos
    assert "nao trouxe o endereco" not in (res.erro or "")


def test_favorita_com_o_cep_travado_continua_no_erro(monkeypatch, tmp_path):
    res, passos, _ = _cotar(monkeypatch, tmp_path, FavoritaAdapter(),
                            destino=SEM_ENDERECO,
                            cep=_Campo("", ligado=False))
    assert "endereço à mão" not in passos
    assert res.status is StatusCotacao.ERRO
    assert "nao trouxe o endereco de destino" in res.erro


def test_generoso_nao_muda_o_cnpj_sem_endereco_continua_erro(
        monkeypatch, tmp_path):
    res, passos, _ = _cotar(monkeypatch, tmp_path, GenerosoAdapter(),
                            destino=SEM_ENDERECO)
    assert "endereço à mão" not in passos
    assert res.status is StatusCotacao.ERRO
    assert "nao trouxe o endereco de destino" in res.erro
    assert vale_repetir(res)


# ---------- 4. "Ainda não realizamos transporte entre as cidades informadas"
# Texto da tela das #654/#655, como o inner_text devolve.
RESULTADO_SEM_TRANSPORTE = (
    "Resultado da cotação\nNova cotação\nLista de cotações\n"
    "Aguardando validação: 5f0c2a1e-9b7d-4c3a-8e21-0d4b6a7c9f12\n"
    "Ainda não realizamos transporte entre as cidades informadas. Confira "
    "as cidades atendidas clicando aqui: Cidades Atendidas.\n"
    "Detalhes desta cotação\nAlterar\n"
    "Solicitante:\nCNPJ\t08.310.365/0001-24\n"
    "Endereço Coleta:\nCNPJ\t08.310.365/0001-24\nCEP\t29.105-770\n"
    "Cidade\tVila Velha\nEstado\tES\n"
    "Endereço destino:\nCNPJ\t33.000.167/0001-01\nCEP\t69.005-070\n"
    "Cidade\tManaus\nEstado\tAM\nEndereço\tAvenida Eduardo Ribeiro\n"
    "Carga:\nValor total da nota fiscal\tR$ 4.233,00\n")


def test_sem_transporte_entre_as_cidades_vira_recusa():
    res = FavoritaAdapter().normalizar_resposta(RESULTADO_SEM_TRANSPORTE)
    assert res.status is StatusCotacao.RECUSADO
    assert res.erro is None
    assert res.motivo_recusa == (
        "A Favorita não faz transporte entre Vila Velha/ES e Manaus/AM. "
        "Cote com outra transportadora, ou fale com a Favorita pelo "
        "WhatsApp, no botão aqui embaixo.")
    assert not vale_repetir(res)


def test_sem_transporte_sem_resumo_nao_inventa_cidade():
    assert m.sem_transporte_entre(
        "Ainda não realizamos transporte entre as cidades informadas."
    ) == ("", "")
    assert "entre as cidades informadas" in m.recusa_sem_transporte_entre(
        "", "", "Favorita")
    assert m.sem_transporte_entre("Cotação: 371121\nFrete\nR$ 260,42") is None


# -------------------- 6a. campo que aparece atrasado (site lento, 12/11)
class _Atrasado:
    """`page.locator(...)` de uma etapa que ainda não desenhou."""
    def __init__(self, aparece: bool) -> None:
        self.aparece = aparece
        self.total = 0
        self.esperou_ms = None
        self.last = self

    def locator(self, _seletor: str) -> "_Atrasado":
        return self

    def count(self) -> int:
        return self.total

    def wait_for(self, state: str, timeout: int) -> None:
        self.esperou_ms = timeout
        if not self.aparece:
            raise TimeoutError("Timeout 50ms exceeded")
        self.total = 1

    def nth(self, indice: int) -> str:
        return f"campo {indice}"


def test_campo_que_aparece_atrasado_e_achado(monkeypatch):
    """#670 a #672: `campo não encontrado: input[name="cep"]` com a etapa
    ainda desenhando."""
    monkeypatch.setattr(modulo, "ESPERA_CAMPO_MS", 50)
    page = _Atrasado(aparece=True)
    assert GenerosoAdapter._campo(page, 'input[name="cep"]') == "campo 0"
    assert page.esperou_ms == 50


def test_campo_que_nunca_aparece_continua_o_mesmo_erro(monkeypatch):
    monkeypatch.setattr(modulo, "ESPERA_CAMPO_MS", 50)
    page = _Atrasado(aparece=False)
    with pytest.raises(RuntimeError) as excinfo:
        GenerosoAdapter._campo(page, 'input[name="cep"]')
    assert str(excinfo.value) == 'campo não encontrado: input[name="cep"]'


def test_campo_que_ja_esta_na_tela_nao_espera():
    page = _Atrasado(aparece=True)
    page.total = 2
    assert GenerosoAdapter._campo(page, 'input[name="cep"]') == "campo 1"
    assert page.esperou_ms is None, "caminho normal não pode ficar mais lento"


# ----------------- 6b. login lento não é credencial recusada (#670, 12/11)
class _Login:
    """A tela de /login que não sai do lugar: senha preenchida, e o site
    respondendo ou não ao "Entrar"."""
    def __init__(self, status: int | None) -> None:
        self.status = status
        self.ouvinte = None
        self.cliques = 0

    def goto(self, *a, **k) -> None:
        pass

    def wait_for_selector(self, *a, **k) -> None:
        pass

    def on(self, _evento, ouvinte) -> None:
        self.ouvinte = ouvinte

    def remove_listener(self, _evento, _ouvinte) -> None:
        self.ouvinte = None

    def get_by_role(self, *a, **k) -> "_Login":
        return self

    def click(self) -> None:
        self.cliques += 1
        if self.status is not None:
            resposta = MagicMock()
            resposta.request.method = "POST"
            resposta.status = self.status
            self.ouvinte(resposta)

    def wait_for_url(self, *a, **k) -> None:
        raise TimeoutError("Timeout 30000ms exceeded")

    def locator(self, _seletor: str) -> "_Login":
        return self

    first = property(lambda self: self)

    def input_value(self) -> str:
        return "senha-de-teste"


def _entrar(status: int | None):
    a = GenerosoAdapter(usuario="conta@ventura.com.br", senha="senha-de-teste")
    a._preencher_login = lambda page: None
    page = _Login(status)
    with pytest.raises(RuntimeError) as excinfo:
        a._entrar(page)
    assert page.cliques == 1, "nunca clicar em Entrar duas vezes"
    assert page.ouvinte is None, "o ouvinte tem que sair no fim"
    return excinfo.value


def test_login_sem_resposta_do_site_nao_vira_credencial_recusada():
    erro = _entrar(None)
    assert not isinstance(erro, CredencialRecusada)
    assert "não respondeu" in str(erro)
    assert "senha-de-teste" not in str(erro)


def test_login_que_o_site_respondeu_e_nao_entrou_continua_recusado():
    """O que protege a conta: senha enviada, site respondeu, não entrou."""
    assert isinstance(_entrar(200), CredencialRecusada)
    assert isinstance(_entrar(401), CredencialRecusada)


# --------------------------------------------------------------------------
# 7. #670 a #675 (12/11, as duas): pop-up "Atenção" depois do Próximo.
#    Texto copiado do diálogo real (recon de 12/11/2026).
POPUP = ("Atenção\n\nPara ativar a cotação de frete no site, entre em contato "
         "com o nosso time comercial. CNPJ: 08.310.365/0001-24.\n\nFechar\n"
         "Falar com suporte\nClose")


class _ComPopup:
    """Página depois do Próximo: `aberto` diz se há um diálogo na tela."""
    def __init__(self, aberto: bool) -> None:
        self.aberto = aberto

    def get_by_role(self, *_a, **_k):
        return MagicMock()

    def wait_for_timeout(self, _ms) -> None:
        pass

    def wait_for_function(self, *_a, **_k) -> None:
        pass

    def locator(self, seletor: str):
        assert seletor == '[role="dialog"]:visible'
        loc = MagicMock()
        loc.count.return_value = 1 if self.aberto else 0
        loc.first.inner_text.return_value = POPUP
        return loc


def test_popup_depois_do_proximo_vira_aviso_com_as_palavras_do_site():
    with pytest.raises(modulo.AvisoDoPortal) as erro:
        FavoritaAdapter()._avancar(_ComPopup(aberto=True))
    frase = str(erro.value)
    assert "A Favorita não deixou cotar pelo site" in frase
    assert ("Para ativar a cotação de frete no site, entre em contato com o "
            "nosso time comercial. CNPJ: 08.310.365/0001-24.") in frase
    assert "Fechar" not in frase and "Close" not in frase


def test_sem_popup_o_proximo_segue():
    GenerosoAdapter()._avancar(_ComPopup(aberto=False))


def test_aviso_do_portal_sai_recusado_e_nao_repete():
    """Mesmo `except` do ForaDeArea: RECUSADO, sem retentativa."""
    import inspect
    fonte = inspect.getsource(GenerosoAdapter.cotar)
    assert "except (ForaDeArea, AvisoDoPortal) as fora:" in fonte
