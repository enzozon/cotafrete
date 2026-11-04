from decimal import Decimal
from pathlib import Path

from orcamento.config import Config
from orcamento.planilha import Item
from orcamento.ia import Ajudantes
from orcamento.processador import (Cliente, Conferencia, ErroHse, HseIndisponivel, Produto, Resolucao, aviso_preco_acima, aviso_sem_preco_tabela,
                                   aviso_preenchido, conferir, conferir_desconto)
from tests.orcamento.hse_falso import HseFalso
from tests.orcamento.planilhas.gerar import VARIANTES, criar


def cfg(tmp_path: Path) -> Config:
    return Config(usuario="u", senha="s", client_id="ventura", dry_run=False, headless=True,
                  pasta_programa=tmp_path)


def _produto(preco=None):
    return Produto("13370", "DELL MOUSE OPTICO MS116", True, None if preco is None else Decimal(preco))


def _item(valor="145.00"):
    return Item(numero=1, linha=2, produto="X", quantidade=Decimal(1), custo=Decimal(100),
                valor_unit=Decimal(valor), codigo="13370", ncm=None, origem=0, icms=Decimal(17),
                descricao_cadastro="X", grupo=None, marca=None, descricao="")


def test_conferencia_ok_lista_cliente_endereco_e_itens(tmp_path):
    p = criar(tmp_path, {"B30": "CENTRO"}, "orc.xlsx")
    hse = HseFalso(produtos=[_produto("150")])
    hse.endereco = "CENTRO - RUA X"
    c = conferir(p, cfg(tmp_path), hse)
    assert c.estado == "ok" and c.erros == ()
    assert c.cliente.startswith("18373 - VENTURA")
    assert c.endereco == "CENTRO - RUA X"
    assert c.vendedor == "ELIZIANE AMORIM ROSA BARROS"
    i = c.itens[0]
    assert (i.codigo, i.preco_tabela, i.valor_unit, i.por) == ("13370", Decimal("150"), Decimal("145.00"), "codigo")


def test_desconto_acima_do_maximo_vira_erros(tmp_path):
    p = criar(tmp_path, None, "orc.xlsx")
    c = conferir(p, cfg(tmp_path), HseFalso(produtos=[_produto("200")]))
    esperado = conferir_desconto(Resolucao(_item(), _produto("200"), "codigo")).erro
    assert c.estado == "erros" and c.erros[0] == f"Item 1: {esperado}"
    assert c.itens[0].por == ""


def test_cliente_nao_encontrado_vira_erros(tmp_path):
    c = conferir(criar(tmp_path, {"B31": 99999}, "o.xlsx"), cfg(tmp_path), HseFalso())
    assert c.estado == "erros" and c.cliente == "" and c.erros


def test_vendedor_inexistente_vira_erros(tmp_path):
    c = conferir(criar(tmp_path, None, "o.xlsx"), cfg(tmp_path), HseFalso(vendedores=["OUTRA"]))
    assert c.estado == "erros" and "Vendedor" in c.erros[0]


def test_produto_novo_incompleto_vira_erros(tmp_path):
    c = conferir(criar(tmp_path, VARIANTES["novo_sem_ncm"], "o.xlsx"), cfg(tmp_path), HseFalso())
    assert c.estado == "erros" and any("produto novo" in e for e in c.erros)


def test_planilha_com_erro_vira_erros_sem_chamar_o_hse(tmp_path):
    hse = HseFalso()
    c = conferir(criar(tmp_path, VARIANTES["filial_invalida"], "o.xlsx"), cfg(tmp_path), hse)
    assert c.estado == "erros" and c.erros and hse.chamadas == []


def test_local_de_entrega_sem_endereco_vira_erros(tmp_path):
    class Recusa(HseFalso):
        def montar_orcamento(self, *a, **k):
            raise ErroHse("Local de entrega 'XYZ' não encontrado no HSE")
    c = conferir(criar(tmp_path, {"B30": "XYZ"}, "o.xlsx"), cfg(tmp_path), Recusa())
    assert c.estado == "erros" and c.erros == ("Local de entrega 'XYZ' não encontrado no HSE",)


def test_sem_local_de_entrega_mostra_cadastral(tmp_path):
    c = conferir(criar(tmp_path, None, "o.xlsx"), cfg(tmp_path), HseFalso())
    assert c.estado == "ok" and c.endereco == "Cadastral do cliente (B30 vazia)"


def test_preco_acima_de_2x_avisa_na_fronteira():
    prod = Produto("123", "PRODUTO X", True, Decimal("100"))
    assert aviso_preco_acima(Resolucao(_item("200.00"), prod, "codigo")) is None
    assert aviso_preco_acima(Resolucao(_item("200.01"), prod, "codigo")) == (
        "Item 1: R$ 200,01 está 2,0× acima da tabela (R$ 100,00) do código 123 – PRODUTO X; "
        "confira se o código está certo")
    assert aviso_preco_acima(Resolucao(_item("500"), _produto(), "codigo")) is None
    assert aviso_preco_acima(Resolucao(_item("500"), prod, "codigo", erro="x")) is None


def test_preco_acima_de_2x_vira_aviso_na_conferencia(tmp_path):
    c = conferir(criar(tmp_path, None, "o.xlsx"), cfg(tmp_path), HseFalso(produtos=[_produto("50")]))
    assert c.estado == "ok" and any("2,9× acima da tabela" in a for a in c.avisos)


def test_aviso_lista_o_que_foi_preenchido_automaticamente():
    # DAV 76 (03/11/2026): a IA preencheu GRUPO e NCM e o vendedor não via nada na conferência
    r = Resolucao(_item(), por="novo", notas=(
        "Item 1: marca encontrada na descrição: VONDER",
        "Item 1: grupo escolhido por IA: ILUMINAÇÃO",
        "Item 1: NCM sugerido por IA: 85131090 (confira antes de faturar)"))
    assert aviso_preenchido(r) == ("Item 1: preenchido automaticamente — MARCA VONDER (da descrição), "
                                   "GRUPO ILUMINAÇÃO (IA), NCM 85131090 (IA); confira antes de gerar")
    resumo = Resolucao(_item(), por="novo", notas=("Item 1: descrição de cadastro resumida por IA: LANTERNA X",))
    assert aviso_preenchido(resumo) == ("Item 1: preenchido automaticamente — DESCRIÇÃO P/ CADASTRO "
                                        "LANTERNA X (IA); confira antes de gerar")
    assert aviso_preenchido(Resolucao(_item(), por="novo")) is None
    assert aviso_preenchido(Resolucao(_item(), por="novo", erro="x", notas=r.notas)) is None


def test_ncm_da_ia_que_nao_existe_no_hse_nao_conta_como_preenchido():
    r = Resolucao(_item(), por="novo", notas=("Item 1: NCM sugerido por IA (12345678) não existe no HSE",))
    assert aviso_preenchido(r) is None


def test_conferencia_avisa_o_que_a_ia_preencheu(tmp_path, monkeypatch):
    monkeypatch.setattr("orcamento.processador.ajudantes",
                        lambda c: Ajudantes(ncm=lambda d, existe: "84716053"))
    c = conferir(criar(tmp_path, VARIANTES["novo_sem_ncm"], "o.xlsx"), cfg(tmp_path), HseFalso())
    assert c.estado == "ok"
    assert "Item 2: preenchido automaticamente — NCM 84716053 (IA); confira antes de gerar" in c.avisos


def test_produto_achado_pela_descricao_avisa(tmp_path):
    p = criar(tmp_path, {"K2": None, "A2": "DELL MOUSE OPTICO MS116"}, "o.xlsx")
    c = conferir(p, cfg(tmp_path), HseFalso())
    assert c.itens[0].por == "descricao"
    assert ("Item 1: produto achado pela descrição, não pelo código: 13370 – DELL MOUSE OPTICO MS116; "
            "confira se é o produto certo") in c.avisos


def test_avisos_do_hse_entram_nos_avisos(tmp_path):
    hse = HseFalso()
    hse.avisos_ao_montar = ["Cliente bloqueado."]
    c = conferir(criar(tmp_path, None, "o.xlsx"), cfg(tmp_path), hse)
    assert "O HSE avisou: Cliente bloqueado." in c.avisos


def test_hse_indisponivel_vira_nao_conferido(tmp_path):
    c = conferir(criar(tmp_path, None, "o.xlsx"), cfg(tmp_path), HseFalso(indisponivel_em={"buscar_cliente"}))
    assert c.estado == "nao_conferido" and c.erros == ()


def test_hse_indisponivel_depois_de_um_erro_fica_erros(tmp_path):
    hse = HseFalso(indisponivel_em={"buscar_produtos"})
    c = conferir(criar(tmp_path, {"B31": 99999}, "o.xlsx"), cfg(tmp_path), hse)
    assert "buscar_produtos" in hse.nomes()
    assert c.estado == "erros" and c.erros


def test_conferir_nunca_inclui_nem_salva(tmp_path):
    hse = HseFalso()
    conferir(criar(tmp_path, None, "o.xlsx"), cfg(tmp_path), hse)
    assert "salvar_orcamento" not in hse.nomes()
    montagens = [c for c in hse.chamadas if c[0] == "montar_orcamento"]
    assert montagens and all(c[-1] is False for c in montagens)


def test_conferencia_ida_e_volta_json(tmp_path):
    hse = HseFalso(produtos=[_produto("50")])
    c = conferir(criar(tmp_path, None, "o.xlsx"), cfg(tmp_path), hse)
    assert c.itens and c.avisos
    assert Conferencia.de_json(c.para_json()) == c


def test_log_da_conferencia_nao_vaza_senha(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HSE_SENHA", "s3gredo")

    class Quebra(HseFalso):
        def __init__(self, onde, **kw):
            super().__init__(**kw)
            self.onde = onde

        def montar_orcamento(self, *a, **kw):
            if self.onde == "tela":
                raise Exception("tela falhou com s3gredo")
            return super().montar_orcamento(*a, **kw)

        def buscar_produtos(self, termo):
            if self.onde == "busca":
                raise Exception("busca falhou com s3gredo")
            if self.onde == "fora":
                raise HseIndisponivel("login falhou com s3gredo")
            return super().buscar_produtos(termo)

    for onde in ("tela", "busca", "fora"):
        caplog.clear()
        p = criar(tmp_path, None, f"{onde}.xlsx")
        conferir(p, cfg(tmp_path), Quebra(onde, produtos=[_produto("150")]))
        assert "falhou" in caplog.text and "s3gredo" not in caplog.text
        assert "Traceback" not in caplog.text


SEM_PRECO = ("Item 1: sem preço de tabela no HSE para o código 13370; "
             "o desconto máximo de 15% não foi conferido")


def test_sem_preco_de_tabela_avisa_so_para_item_por_codigo():
    assert aviso_sem_preco_tabela(Resolucao(_item(), _produto(), "codigo")) == SEM_PRECO
    assert aviso_sem_preco_tabela(Resolucao(_item(), _produto("100"), "codigo")) is None
    assert aviso_sem_preco_tabela(Resolucao(_item(), _produto(), "codigo", erro="x")) is None


def test_conferencia_sem_preco_avisa_sem_bloquear(tmp_path):
    c = conferir(criar(tmp_path, None, "o.xlsx"), cfg(tmp_path), HseFalso(produtos=[_produto()]))
    assert c.estado == "ok" and SEM_PRECO in c.avisos


def test_conferencia_com_preco_nao_avisa_sem_preco(tmp_path):
    c = conferir(criar(tmp_path, None, "o.xlsx"), cfg(tmp_path), HseFalso(produtos=[_produto("150")]))
    assert c.estado == "ok" and not any("sem preço de tabela" in a for a in c.avisos)
