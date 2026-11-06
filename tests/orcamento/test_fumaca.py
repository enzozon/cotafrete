"""Teste de fumaça do DAV (P2 #14), com o HSE em memória."""
from pathlib import Path

from orcamento import fumaca
from orcamento.config import Config
from orcamento.planilha import ler_planilha
from tests.orcamento.hse_falso import CLIENTE_VENTURA, MOUSE, HseFalso

VENDEDOR = "ELIZIANE AMORIM ROSA BARROS"
ENV = {"HSE_USUARIO": "u", "HSE_SENHA": "s3gredo", "FUMACA_CLIENTE": CLIENTE_VENTURA.codigo,
       "FUMACA_VENDEDOR": VENDEDOR, "FUMACA_CODIGO": MOUSE.codigo}


def _cfg(tmp_path: Path) -> Config:
    return Config(usuario="u", senha="s3gredo", client_id="ventura", dry_run=False, headless=True,
                  ia="api", pasta_programa=tmp_path)


class HseLeitura(HseFalso):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.cfg, self.bloqueados = None, []


def _rodar(tmp_path, hse: HseLeitura) -> list[str]:
    def criar(cfg):
        hse.cfg = cfg
        return hse
    return fumaca.rodar(_cfg(tmp_path), ENV, criar)


def test_planilha_de_mentira_passa_na_leitura_sem_produto_novo(tmp_path):
    orc = ler_planilha(fumaca.montar_planilha(tmp_path / "f.xlsx", ENV))

    assert (orc.cliente, orc.vendedor) == (CLIENTE_VENTURA.codigo, VENDEDOR)
    assert [i.codigo for i in orc.itens] == [MOUSE.codigo]   # código pronto: IA nunca é chamada
    assert orc.frete == "CIF"


def test_tudo_certo_nao_tem_falha_e_nao_grava_nem_usa_ia(tmp_path):
    hse = HseLeitura()

    assert _rodar(tmp_path, hse) == []
    assert hse.cfg.dry_run is True and hse.cfg.ia == "desligada"
    assert "montar_orcamento" in hse.nomes()
    assert not {"salvar_orcamento", "cadastrar_produto"} & set(hse.nomes())


def test_robo_que_quebra_na_tela_vira_falha(tmp_path):
    falhas = _rodar(tmp_path, HseLeitura(falhar_em=("montar_orcamento",)))

    assert falhas


def test_hse_fora_do_ar_vira_falha(tmp_path):
    falhas = _rodar(tmp_path, HseLeitura(indisponivel_em=("buscar_cliente",)))

    assert falhas and "HSE" in falhas[0]


def test_cliente_que_sumiu_vira_falha(tmp_path):
    assert _rodar(tmp_path, HseLeitura(clientes=[]))


def test_login_que_cai_vira_falha_sem_senha(tmp_path, monkeypatch):
    monkeypatch.setenv("HSE_SENHA", "s3gredo")

    def criar(cfg):
        raise RuntimeError("login recusado para u/s3gredo")

    falhas = fumaca.rodar(_cfg(tmp_path), ENV, criar)

    assert "login recusado" in falhas[0] and "s3gredo" not in falhas[0]


def test_gravacao_bloqueada_vira_falha(tmp_path):
    hse = HseLeitura()
    hse.bloqueados = ["vendaAlt.php acao=salvar"]

    assert any("gravar" in f for f in _rodar(tmp_path, hse))


def _main(monkeypatch, falhas, env=ENV):
    enviados = []
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    monkeypatch.setattr(fumaca, "rodar", lambda *a, **k: falhas)
    monkeypatch.setattr(fumaca, "enviar", lambda assunto, corpo: enviados.append((assunto, corpo)))
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return fumaca.main(), enviados


def test_passou_nao_manda_email(monkeypatch, capsys):
    codigo, enviados = _main(monkeypatch, [])

    assert codigo == 0 and enviados == [] and "OK" in capsys.readouterr().out


def test_falhou_manda_um_email_com_o_motivo(monkeypatch):
    codigo, enviados = _main(monkeypatch, ["HSE fora do ar"])

    assert codigo == 1 and len(enviados) == 1
    assert "fumaça" in enviados[0][0] and "HSE fora do ar" in enviados[0][1]


def test_email_que_falha_aparece_no_log(monkeypatch, capsys):
    def cai(assunto, corpo):
        raise RuntimeError("faltam SMTP_USER e SMTP_PASSWORD no .env")
    _main(monkeypatch, ["x"])
    monkeypatch.setattr(fumaca, "enviar", cai)

    assert fumaca.main() == 1
    assert "SMTP_USER" in capsys.readouterr().out


def test_sem_configuracao_nao_abre_hse_nem_manda_email(monkeypatch, capsys):
    env = {k: v for k, v in ENV.items() if k != "FUMACA_CODIGO"}

    codigo, enviados = _main(monkeypatch, ["não devia rodar"], env)

    assert codigo == 1 and enviados == []
    assert "FUMACA_CODIGO" in capsys.readouterr().out
