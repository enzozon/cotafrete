from decimal import Decimal
from types import SimpleNamespace

import pytest
from playwright.sync_api import Error as PlaywrightError

from orcamento.hse import Hse, motivo_recusa, preco_de_tabela, recusa_do_incluir
from orcamento.processador import HseIndisponivel

# trecho real da resposta do Incluir recusado (mouse 13370 a 43,50 no orçamento 16354)
RECUSA = """<script>
    var percentDesconto = 0;
    var percentDescontoValor = 30.23;
    var percentDescMax = 15;
    var erroDescontoMsg = 'Desconto máximo 15%<br>desconto aplicado 30,23%';
    //console.log('vlOriginal', 62.35);
</script>"""


def test_motivo_da_recusa_por_desconto():
    assert motivo_recusa(RECUSA) == ("Desconto máximo 15% - desconto aplicado 30,23%; "
                                     "preço de tabela 62,35, menor preço aceito 53,00")


def test_recusa_sem_mensagem():
    assert motivo_recusa("<div>tabela</div>") == "o HSE não informou o motivo"


def test_recusa_do_primeiro_item_diz_o_motivo():
    # 6000162094 (29/10/2026): no 1º item a recusa nem cria o pedido; antes saía só
    # "Incluir não gerou nº de pedido", sem dizer o porquê
    assert recusa_do_incluir(1, "60333", Decimal("150"), RECUSA) == (
        "Item 1: o HSE recusou o produto 60333 a 150,00 (Desconto máximo 15% - desconto aplicado "
        "30,23%; preço de tabela 62,35, menor preço aceito 53,00)")


class _Loc:
    def __init__(self, pagina, falha):
        self.pagina, self.falha = pagina, falha

    def wait_for(self, **kw):
        if self.falha:
            raise PlaywrightError("Timeout 15000ms exceeded.\nCall log: fill(senha)")


class _Pagina:
    """Página falsa: o HSE fica em login2.php mostrando `corpo` (recusa ou nada)."""

    def __init__(self, corpo, empresa_aparece=False):
        self.corpo, self.empresa_aparece = corpo, empresa_aparece
        self.url = "https://app.hsesistemas.com.br/login2.php"

    def goto(self, *a, **kw): pass
    def fill(self, *a): pass
    def dispatch_event(self, *a): pass
    def click(self, *a): pass
    def select_option(self, *a): pass
    def locator(self, sel): return _Loc(self, not self.empresa_aparece)
    def inner_text(self, sel): return self.corpo
    def evaluate(self, *a): return "1"
    def wait_for_function(self, js, **kw):
        if "ACESSO NEGADO" not in self.corpo.upper() and "login2.php" in self.url:
            raise PlaywrightError("Timeout 30000ms exceeded.")


def _hse(pagina):
    hse = Hse.__new__(Hse)
    hse.cfg = SimpleNamespace(client_id="x", usuario="u", senha="SEGREDO")
    hse._ctx = None
    hse._browser = SimpleNamespace(new_context=lambda **kw: SimpleNamespace(
        set_default_timeout=lambda t: None, new_page=lambda: pagina))
    return hse


FORA = "Entrar\nACESSO NEGADO! Sem permissão para logar nesse horário\nOutra linha"


def test_login_recusado_depois_da_filial_mostra_o_motivo():
    with pytest.raises(HseIndisponivel) as e:
        _hse(_Pagina(FORA, empresa_aparece=True))._login(1)
    assert str(e.value) == "O HSE recusou o login do robô: Sem permissão para logar nesse horário"
    assert "SEGREDO" not in str(e.value) and "Call log" not in str(e.value)


def test_login_recusado_ja_no_primeiro_passo():
    with pytest.raises(HseIndisponivel) as e:
        _hse(_Pagina(FORA))._login(1)
    assert str(e.value).startswith("O HSE recusou o login do robô: Sem permissão")


def test_login_sem_recusa_no_primeiro_passo_mantem_a_mensagem_antiga():
    with pytest.raises(HseIndisponivel, match="confira HSE_USUARIO/HSE_SENHA"):
        _hse(_Pagina("Entrar"))._login(1)


class _Modal:
    def __init__(self, texto):
        self.texto, self.visivel, self.fechou = texto, texto is not None, False

    def locator(self, sel):
        assert sel == "#modalAlert"
        return SimpleNamespace(is_visible=lambda: self.visivel, inner_text=lambda: self.texto)

    def evaluate(self, js):
        assert "modalAlert" in js and "hide" in js
        self.visivel, self.fechou = False, True

    def wait_for_timeout(self, ms): pass


def test_aviso_do_hse_e_fechado_e_guardado_sem_o_ok():
    hse = Hse.__new__(Hse)
    hse.avisos = []
    pagina = _Modal("Pendência\nCliente bloqueado. Consultar o setor financeiro\nDE15648 Venc: 19/10/2026\nok")
    hse._fechar_aviso(pagina)
    hse._fechar_aviso(pagina)  # já fechado: não duplica
    assert pagina.fechou
    assert hse.avisos == ["Pendência Cliente bloqueado. Consultar o setor financeiro DE15648 Venc: 19/10/2026"]


def test_sem_aviso_nao_mexe_na_tela():
    hse = Hse.__new__(Hse)
    hse.avisos = []
    pagina = _Modal(None)
    hse._fechar_aviso(pagina)
    assert not pagina.fechou and hse.avisos == []


def test_preco_de_tabela_vem_do_autocomplete():
    onclick = ("itemSelected_dsProduto('13370', '13370 - 570-ABIE-DTO86_ES DELL MOUSE OPTICO MS116 PRETO', "
               "'62.3500', '43.0000', '43.0000', '.0000000000000000000');")
    assert preco_de_tabela(onclick) == Decimal("62.3500")
    assert preco_de_tabela("itemSelected_dsProduto('1', 'X')") is None


class _Linha:
    """Tela depois do Incluir: a linha nova trItem_901 com o botão + e a caixa dsObsItem_901."""

    def __init__(self, falhar_em=None, resposta_ok=True):
        self.falhar_em, self.resposta_ok = falhar_em, resposta_ok
        self.feito: list[tuple] = []
        self.div = ""

    def eval_on_selector_all(self, sel, js):
        assert sel == "tr[id^=trItem_]"
        return ["trItem_900", "trItem_901"]

    def _passo(self, nome, *args):
        if nome == self.falhar_em:
            raise PlaywrightError(f"{nome} falhou")
        self.feito.append((nome, *args))

    def click(self, sel):
        self._passo("click", sel)

    def fill(self, sel, valor):
        self._passo("fill", sel, valor)
        self.valor = valor

    def expect_response(self, pred):
        pagina = self
        req = SimpleNamespace(post_data="acao=salvarObsItem&cdPedidoItem=901", method="POST")
        resp = SimpleNamespace(url="https://x/vendaItem.php", request=req, ok=self.resposta_ok)
        assert pred(resp)

        class Ctx:
            value = resp

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                if not exc[0] and pagina.resposta_ok:
                    pagina.div = pagina.valor
                return False
        return Ctx()

    def locator(self, sel):
        return SimpleNamespace(blur=lambda: self._passo("blur", sel))

    def inner_text(self, sel):
        assert sel == "#divObsItem_901"
        return self.div


def _item(descricao="Cor preta"):
    return SimpleNamespace(numero=2, descricao=descricao)


def test_descricao_do_item_e_gravada_na_linha_nova():
    hse = Hse.__new__(Hse)
    hse.notas = []
    pagina = _Linha()
    hse._gravar_descricao(pagina, _item(), {"trItem_900"})
    assert ("fill", "#dsObsItem_901", "Cor preta") in pagina.feito
    assert ("blur", "#dsObsItem_901") in pagina.feito
    assert hse.notas == []


@pytest.mark.parametrize("pagina", [_Linha(falhar_em="click"), _Linha(resposta_ok=False)])
def test_descricao_que_falha_vira_nota_sem_derrubar(pagina):
    hse = Hse.__new__(Hse)
    hse.notas = []
    hse._gravar_descricao(pagina, _item(), {"trItem_900"})
    assert len(hse.notas) == 1
    assert hse.notas[0].startswith("Item 2: descrição não gravada no HSE (")
    assert hse.notas[0].endswith("confira no DAV")


def test_sem_linha_nova_tambem_vira_nota():
    hse = Hse.__new__(Hse)
    hse.notas = []
    hse._gravar_descricao(_Linha(), _item(), {"trItem_900", "trItem_901"})
    assert "Item 2: descrição não gravada no HSE" in hse.notas[0]
