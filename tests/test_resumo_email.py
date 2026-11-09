from datetime import date, datetime
from pathlib import Path

import pytest

from core import resumo_email
from core.banco import Banco

DIA = date(2026, 11, 6)


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def logs(tmp_path):
    (tmp_path / "gerenciador.txt").write_text(
        "2026-11-06 09:15:01,747 [PID 1] [Thread-1] ValeApp INFO tudo bem\n"
        "2026-11-06 09:16:01,747 [PID 1] [Thread-1] ValeApp ERROR Falha ao abrir evento 123\n"
        "2026-11-06 09:17:01,747 [PID 1] [Thread-1] ValeApp ERROR Falha ao abrir evento 456\n"
        "2026-11-05 09:17:01,747 [PID 1] [Thread-1] ValeApp ERROR de ontem\n", encoding="utf-8")
    (tmp_path / "datasheet.txt").write_text(
        "[06/11/2026 16:35:33] [ERRO DO MODULO] [MÓDULO: API] Pedido falhou\n"
        "[06/11/2026 16:35:34] [INFO] [MÓDULO: API] normal\n", encoding="utf-8")
    return tmp_path


def test_junta_logs_do_dia_e_agrupa_sem_numeros(tmp_path):
    linhas = resumo_email.secao_logs(DIA, logs(tmp_path))
    assert "Gerenciador: 2 erro(s)." in linhas
    assert "   2× Falha ao abrir evento #" in linhas
    assert "Datasheet: 1 erro(s)." in linhas
    assert not any("de ontem" in l for l in linhas)
    assert "Coupa: log não pôde ser lido (log-coupa.txt)." in linhas


def test_resumo_traz_dav_com_erro_e_assunto(banco, tmp_path):
    i = banco.dav_criar("ana", "a.xlsx", "h", "VALE S.A.")
    banco.dav_atualizar(i, estado="erro", erro="falha no HSE")
    from contextlib import closing
    with closing(banco._conectar()) as con, con:
        con.execute("UPDATE dav SET criado_em='2026-11-06T10:00:00'")
    with closing(banco._conectar()) as con:
        assunto, corpo = resumo_email.montar(con, DIA, pasta_logs=logs(tmp_path))
    assert assunto.startswith("Resumo de erros 06/11: ")
    assert "ponto(s) para olhar" in assunto
    assert f"Envio #{i} (ana, erro): VALE S.A. - falha no HSE" in corpo


def test_sem_erro_o_email_vai_dizendo_que_esta_tudo_certo(banco, tmp_path):
    from contextlib import closing
    vazia = tmp_path / "logs"
    vazia.mkdir()
    for a in resumo_email.LOGS.values():
        (vazia / a).write_text("", encoding="utf-8")
    with closing(banco._conectar()) as con:
        assunto, corpo = resumo_email.montar(con, DIA, pasta_logs=vazia)
    assert assunto.endswith("tudo certo") and corpo.count("Nenhum erro.") == 3


def test_resumo_da_semana_usa_o_texto_do_adm(banco):
    from contextlib import closing
    with closing(banco._conectar()) as con:
        assunto, corpo = resumo_email.montar_semana(con, DIA)
    assert assunto == "Resumo da semana 06/11" and corpo.startswith("Resumo da semana até 06/11/2026")


def test_enviar_usa_o_destino_e_exige_credencial():
    enviados = []

    class Smtp:
        def __init__(self, host, porta, timeout): assert host == "email-ssl.com.br"
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, u, s): enviados.append(u)
        def send_message(self, m): enviados.append(m["To"])
    resumo_email.enviar("a", "b", {"SMTP_USER": "x@v.com", "SMTP_PASSWORD": "s"}, Smtp)
    assert enviados == ["x@v.com", "vendas2@venturainformatica.com.br"]
    with pytest.raises(RuntimeError, match="SMTP_USER"):
        resumo_email.enviar("a", "b", {}, Smtp)


def test_main_le_o_banco_com_linhas_por_nome(banco, monkeypatch, capsys):
    """Produção 06–08/11/2026: o main abria o banco sem row_factory e r["transportadora"]
    estourava "tuple indices must be integers" assim que o dia tinha uma cotação."""
    from contextlib import closing
    hoje = datetime.now().isoformat()
    with closing(banco._conectar()) as con, con:
        cid = con.execute(
            "INSERT INTO cotacao (usuario, criado_em, cep_origem, cep_destino, peso_kg, quantidade,"
            " comprimento_cm, largura_cm, altura_cm, valor_nf) VALUES ('ana', ?, '1', '2', '1', 1, 1, 1, 1, '1')",
            (hoje,)).lastrowid
        con.execute("INSERT INTO resultado (cotacao_id, transportadora, status, erro)"
                    " VALUES (?, 'jadlog', 'erro', 'caiu')", (cid,))
    monkeypatch.setattr("core.banco.CAMINHO_PADRAO", banco.caminho)
    enviados = []
    monkeypatch.setattr(resumo_email, "enviar", lambda a, c: enviados.append(c))
    monkeypatch.setattr("sys.argv", ["resumo_email"])
    assert resumo_email.main() == 0
    assert "caiu" in enviados[0]
