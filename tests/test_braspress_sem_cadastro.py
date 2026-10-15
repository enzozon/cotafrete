"""Braspress com CNPJ sem cadastro: digitar o CEP e seguir, não desistir.

Cinco cotações reais (#213, #248, #321, #342, #380 — 23/09 a 09/10/2026)
falharam com "A Braspress não trouxe endereço para o CNPJ ...". O print da
#380 mostra o que o site pedia embaixo do campo:

    CNPJ/CPF não cadastrado, para prosseguir informe o CEP de Destino.

A página falsa abaixo imita só isso: o endereço chega depois que o CEP
certo é digitado no campo certo.
"""

from __future__ import annotations

from carriers.braspress.adapter import AVISO_NAO_CADASTRADO, BraspressAdapter
from core.models import TipoFrete
from tests.test_jadlog import montar

FRASE_REAL = ("CNPJ/CPF não cadastrado, para prosseguir informe o CEP de "
              "Destino.")


class _Campo:
    def __init__(self, pagina: "_Pagina", seletor: str) -> None:
        self.p, self.s = pagina, seletor

    def inner_text(self) -> str:
        return self.p.texto

    def input_value(self) -> str:
        return self.p.valores.get(self.s, "")

    def click(self) -> None: ...

    def fill(self, valor: str) -> None:
        self.p.valores[self.s] = valor

    def type(self, valor: str, delay: int = 0) -> None:
        self.p.valores[self.s] = self.p.valores.get(self.s, "") + valor

    def blur(self) -> None:
        if self.p.valores.get(self.p.cep_que_resolve[0]) == \
                self.p.cep_que_resolve[1]:
            self.p.valores["#endereco"] = "RUA DO CLIENTE, 10"


class _Pagina:
    def __init__(self, texto: str, cep_que_resolve: tuple[str, str]) -> None:
        self.texto, self.cep_que_resolve = texto, cep_que_resolve
        self.valores: dict[str, str] = {}

    def locator(self, seletor: str) -> _Campo:
        return _Campo(self, seletor)

    def wait_for_timeout(self, _ms: int) -> None: ...


def test_a_frase_do_print_esta_reconhecida():
    assert AVISO_NAO_CADASTRADO in FRASE_REAL.lower()


def test_cif_digita_o_cep_de_destino():
    page = _Pagina(FRASE_REAL, ("#cepDestino", "01310100"))
    req = montar(cep_des="01310-100", tipo_frete=TipoFrete.CIF)
    assert BraspressAdapter()._endereco_pelo_cep(req, page) == \
        "RUA DO CLIENTE, 10"


def test_fob_digita_o_cep_de_origem():
    page = _Pagina(FRASE_REAL, ("#cepOrigem", "29010000"))
    req = montar(tipo_frete=TipoFrete.FOB)
    assert BraspressAdapter()._endereco_pelo_cep(req, page)


def test_sem_o_aviso_nao_digita_nada():
    """Endereço vazio por outro motivo não é licença para inventar a ponta."""
    page = _Pagina("tela qualquer", ("#cepDestino", "01310100"))
    assert BraspressAdapter()._endereco_pelo_cep(montar(), page) == ""
    assert page.valores == {}


def test_cep_que_nao_resolve_continua_sem_endereco():
    page = _Pagina(FRASE_REAL, ("#cepDestino", "99999999"))
    assert BraspressAdapter()._endereco_pelo_cep(montar(), page) == ""
