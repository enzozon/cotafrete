from types import SimpleNamespace

import pytest
from playwright.sync_api import Error as PlaywrightError

from orcamento.hse import Hse, motivo_recusa
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
