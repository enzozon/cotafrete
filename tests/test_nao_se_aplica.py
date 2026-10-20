"""'Não se aplica': a transportadora nem é consultada, e não conta no
aproveitamento.

Pedido do Enzo em 15/10/2026, depois do levantamento do /adm: recusas que se
sabem de antemão (Jadlog só CIF, Translovato só saindo da Ventura, Favorita
com a conta só da Ventura) derrubavam o aproveitamento delas sem ser defeito
de ninguém — a Favorita aparecia com 10%, metade disso por regra de conta.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from carriers.base import ErroValidacao, recusa_por_validacao
from carriers.favorita.adapter import FavoritaAdapter
from carriers.jadlog import mapping as jadlog
from carriers.translovato import mapping as translovato
from core import painel, resumo_semana
from core.banco import Banco
from core.models import Parte, StatusCotacao, TipoFrete, Volume
from core.retentativa import vale_repetir
from tests.test_jadlog import montar
from tests.test_painel import CARGA

FORNECEDOR = Parte(cnpj="35.120.753/0001-15")
ALIANCA = Parte(cnpj="05.954.058/0001-98")
VENTURA = Parte(cnpj="08.310.365/0001-24")


def test_so_regra_fixa_vira_nao_se_aplica():
    regra = ErroValidacao("tipo_frete", "só CIF", nao_se_aplica=True)
    carga = ErroValidacao("peso", "pesado demais")
    sozinha = recusa_por_validacao("jadlog", [regra])
    assert sozinha.status is StatusCotacao.NAO_SE_APLICA
    assert sozinha.motivo_recusa == "só CIF"
    assert not vale_repetir(sozinha)
    assert recusa_por_validacao("jadlog", [regra, carga]).status is \
        StatusCotacao.RECUSADO


def test_jadlog_fob_nao_se_aplica():
    erros = jadlog.validar(montar(tipo_frete=TipoFrete.FOB))
    assert recusa_por_validacao("jadlog", erros).status is \
        StatusCotacao.NAO_SE_APLICA


def test_translovato_com_remetente_fornecedor_nem_abre_o_site():
    erros = translovato.validar(montar(remetente=FORNECEDOR))
    assert [e.nao_se_aplica for e in erros] == [True]
    assert "SAINDO da Ventura" in erros[0].mensagem
    assert translovato.validar(montar(remetente=VENTURA)) == []


def test_translovato_cota_a_filial_que_ela_atende():
    """#407 e #408 (15/10/2026): a filial 0006-42 do fornecedor 07.500.596
    recebeu preço da Translovato, apesar de não ser CNPJ da Ventura. A matriz
    (0001-38) continua sem tabela (#146)."""
    filial = Parte(cnpj="07.500.596/0006-42")
    matriz = Parte(cnpj="07.500.596/0001-38")
    assert translovato.validar(montar(remetente=filial)) == []
    assert [e.nao_se_aplica for e in translovato.validar(montar(remetente=matriz))] == [True]


def test_favorita_com_alianca_nao_se_aplica():
    erros = FavoritaAdapter().validar(montar(remetente=ALIANCA))
    assert recusa_por_validacao("favorita", erros).status is \
        StatusCotacao.NAO_SE_APLICA


def test_fica_fora_do_aproveitamento_e_dos_alertas(tmp_path):
    db = Banco(tmp_path / "t.db")
    for _ in range(3):
        cid = db.salvar_cotacao("enzo", CARGA)
        db.salvar_resultado(cid, "favorita", status="nao_se_aplica")
    cid = db.salvar_cotacao("enzo", CARGA)
    db.salvar_resultado(cid, "favorita", status="cotado", valor=Decimal("10"))
    with db._conectar() as con:
        linha = painel.saude_das_transportadoras(con, dias=30)[0]
        semana = resumo_semana.fatos(con, date.today())
    assert painel.categoria("nao_se_aplica") == "nao_aplica"
    assert linha["nao_aplica"] == 3
    assert linha["aproveitamento"] == 1.0
    assert semana["transportadoras"][0]["aproveitamento"] == 100
    assert semana["transportadoras"][0]["pedidos"] == 1
