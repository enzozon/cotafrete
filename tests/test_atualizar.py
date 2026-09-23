"""A atualização automática da produção (atualizar.py).

Git de verdade: um "GitHub" (repositório bare), uma pasta de onde se faz o
merge e a pasta cotafrete-producao, clonada dele. O que é do Windows (fechar
e abrir o Servidor.bat, pip) é trocado por um servidor de mentira, que anota
o que foi pedido e responde o que o teste mandar.

O que precisa continuar valendo:
- sem commit novo, NADA acontece (nem linha no log);
- com cotação rodando, não reinicia;
- arquivo mexido à mão na produção não é atropelado;
- o pip só roda quando o requirements.txt muda, e com o servidor FECHADO;
- se a versão nova não sobe, a anterior volta — e a quebrada não é tentada
  de novo a cada 5 minutos;
- nunca age fora da pasta cotafrete-producao.
"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import atualizar


def _git(pasta: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=pasta, check=True,
                          capture_output=True, text=True).stdout.strip()


def _commit(pasta: Path, arquivo: str, conteudo: str, msg: str) -> str:
    (pasta / arquivo).write_text(conteudo, encoding="utf-8")
    _git(pasta, "add", arquivo)
    _git(pasta, "commit", "-q", "-m", msg)
    _git(pasta, "push", "-q", "origin", "HEAD:main")
    return _git(pasta, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path):
    github = tmp_path / "github.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(github))

    dev = tmp_path / "cotafrete-dev"
    _git(tmp_path, "clone", "-q", str(github), str(dev))
    for chave, valor in (("user.email", "t@t"), ("user.name", "t")):
        _git(dev, "config", chave, valor)
    _git(dev, "checkout", "-q", "-b", "main")
    _commit(dev, "requirements.txt", "fastapi\n", "primeiro")
    (dev / ".gitignore").write_text("log/\n", encoding="utf-8")
    _commit(dev, ".gitignore", "log/\n", "ignora o log")

    producao = tmp_path / "C" / "cotafrete-producao"
    producao.parent.mkdir()
    _git(tmp_path, "clone", "-q", str(github), str(producao))
    return dev, producao


class ServidorFalso:
    def __init__(self, ocupadas=0, sobe=True, sobe_na_volta=True,
                 fecha=True):
        self.ocupadas = ocupadas
        self.sobe = sobe
        self.sobe_na_volta = sobe_na_volta
        self.fecha = fecha
        self.passos: list[str] = []
        self.pasta: Path | None = None

    def em_curso(self):
        return self.ocupadas

    def fechar(self):
        self.passos.append("fechar")
        if not self.fecha:
            raise atualizar.Falha("o servidor não fechou em 30 s")

    def abrir(self):
        self.passos.append("abrir")
        return object()

    def fechar_janela(self, processo):
        self.passos.append("fechar_janela")

    def esperar_no_ar(self):
        aberturas = self.passos.count("abrir")
        self.passos.append("esperar")
        return self.sobe if aberturas <= 1 else self.sobe_na_volta

    def instalar_dependencias(self):
        self.passos.append("pip")


def _log(producao: Path) -> str:
    log = atualizar.arquivo_de_log(producao)
    return log.read_text(encoding="utf-8") if log.exists() else ""


def _head(pasta: Path) -> str:
    return _git(pasta, "rev-parse", "HEAD")


# ---------------------------------------------------------- nada a fazer
def test_sem_commit_novo_nada_acontece(repos):
    _, producao = repos
    srv = ServidorFalso()

    assert atualizar.uma_volta(producao, srv) == "sem_novidade"
    assert srv.passos == []
    assert _log(producao) == ""


def test_fora_da_pasta_de_producao_nao_age(repos):
    dev, _ = repos
    srv = ServidorFalso()

    assert atualizar.uma_volta(dev, srv) == "fora_da_producao"
    assert srv.passos == []


def test_instalar_fora_da_producao_e_recusado(repos, capsys):
    dev, _ = repos

    assert atualizar.instalar(dev) == 1
    assert "não é a pasta cotafrete-producao" in capsys.readouterr().out


# ------------------------------------------------------------ o caminho feliz
def test_merge_novo_vira_pull_e_reinicio(repos):
    dev, producao = repos
    novo = _commit(dev, "app.py", "print(1)\n", "feat: tela nova")
    srv = ServidorFalso()

    assert atualizar.uma_volta(producao, srv) == "atualizado"
    assert _head(producao) == novo
    assert srv.passos == ["fechar", "abrir", "esperar"]
    log = _log(producao)
    assert "feat: tela nova" in log
    assert f"Pronto: no ar com {novo[:7]}" in log


def test_pip_so_quando_o_requirements_muda_e_com_servidor_fechado(repos):
    dev, producao = repos
    _commit(dev, "requirements.txt", "fastapi\npypdf\n", "dep nova")
    srv = ServidorFalso()

    assert atualizar.uma_volta(producao, srv) == "atualizado"
    assert srv.passos == ["fechar", "pip", "abrir", "esperar"]


def test_producao_em_outro_ramo_volta_para_a_main(repos):
    """O `git checkout main` que era feito à mão."""
    dev, producao = repos
    _git(producao, "checkout", "-q", "-b", "teste-antigo")
    novo = _commit(dev, "app.py", "x\n", "novo")

    assert atualizar.uma_volta(producao, ServidorFalso()) == "atualizado"
    assert _git(producao, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _head(producao) == novo


# ------------------------------------------------------------- as esperas
def test_com_cotacao_rodando_nao_reinicia(repos):
    dev, producao = repos
    antes = _head(producao)
    _commit(dev, "app.py", "x\n", "novo")
    srv = ServidorFalso(ocupadas=2)

    assert atualizar.uma_volta(producao, srv) == "ocupado"
    assert srv.passos == []
    assert _head(producao) == antes
    assert "esperando as cotações em andamento (2)" in _log(producao)


def test_aviso_repetido_sai_uma_vez_so(repos):
    """A cada 5 minutos com cotação rodando, a mesma linha: uma basta."""
    dev, producao = repos
    _commit(dev, "app.py", "x\n", "novo")
    for _ in range(3):
        atualizar.uma_volta(producao, ServidorFalso(ocupadas=1))

    assert _log(producao).count("esperando") == 1


def test_arquivo_mexido_a_mao_nao_e_atropelado(repos):
    dev, producao = repos
    (producao / "requirements.txt").write_text("mexido\n", encoding="utf-8")
    _commit(dev, "app.py", "x\n", "novo")
    srv = ServidorFalso()

    assert atualizar.uma_volta(producao, srv) == "alteracao_local"
    assert srv.passos == []
    assert (producao / "requirements.txt").read_text() == "mexido\n"
    assert "requirements.txt" in _log(producao)


def test_arquivo_novo_nao_versionado_nao_atrapalha(repos):
    """.env, cotafrete.db, log\\ — tudo fora do git — são normais."""
    dev, producao = repos
    (producao / ".env").write_text("SEGREDO=1\n", encoding="utf-8")
    _commit(dev, "app.py", "x\n", "novo")

    assert atualizar.uma_volta(producao, ServidorFalso()) == "atualizado"
    assert (producao / ".env").read_text() == "SEGREDO=1\n"


def test_commit_local_que_o_github_nao_tem_nao_e_forcado(repos):
    dev, producao = repos
    for chave, valor in (("user.email", "t@t"), ("user.name", "t")):
        _git(producao, "config", chave, valor)
    (producao / "local.txt").write_text("x", encoding="utf-8")
    _git(producao, "add", "local.txt")
    _git(producao, "commit", "-q", "-m", "commit feito na VM")
    _commit(dev, "app.py", "x\n", "novo")
    srv = ServidorFalso()

    assert atualizar.uma_volta(producao, srv) == "nao_avanca"
    assert srv.passos == []


def test_sem_github_registra_e_nao_mexe(repos):
    _, producao = repos
    _git(producao, "remote", "set-url", "origin", str(producao / "nao-existe"))
    srv = ServidorFalso()

    assert atualizar.uma_volta(producao, srv) == "sem_rede"
    assert srv.passos == []
    assert "Não consegui falar com o GitHub" in _log(producao)


def test_servidor_que_nao_fecha_nao_troca_o_codigo(repos):
    dev, producao = repos
    antes = _head(producao)
    _commit(dev, "app.py", "x\n", "novo")
    srv = ServidorFalso(fecha=False)

    assert atualizar.uma_volta(producao, srv) == "nao_fechou"
    assert _head(producao) == antes


# ----------------------------------------------------- a versão que não sobe
def test_versao_que_nao_sobe_volta_para_a_anterior(repos):
    dev, producao = repos
    antes = _head(producao)
    quebrado = _commit(dev, "app.py", "quebrado\n", "feat: com defeito")
    srv = ServidorFalso(sobe=False)

    assert atualizar.uma_volta(producao, srv) == "voltou_atras"
    assert _head(producao) == antes
    assert srv.passos == ["fechar", "abrir", "esperar", "fechar_janela",
                          "fechar", "abrir", "esperar"]
    log = _log(producao)
    assert "FALHOU" in log
    assert f"No ar de novo com a versão anterior {antes[:7]}" in log

    # E na próxima volta não tenta de novo o mesmo commit.
    srv2 = ServidorFalso()
    assert atualizar.uma_volta(producao, srv2) == "recusado"
    assert srv2.passos == []
    assert _head(producao) != quebrado


def test_o_merge_seguinte_libera_de_novo(repos):
    dev, producao = repos
    _commit(dev, "app.py", "quebrado\n", "com defeito")
    atualizar.uma_volta(producao, ServidorFalso(sobe=False))
    corrigido = _commit(dev, "app.py", "certo\n", "fix: corrige")

    assert atualizar.uma_volta(producao, ServidorFalso()) == "atualizado"
    assert _head(producao) == corrigido


def test_voltar_atras_com_dependencia_nova_reinstala_a_antiga(repos):
    dev, producao = repos
    _commit(dev, "requirements.txt", "fastapi\nquebra\n", "dep nova")
    srv = ServidorFalso(sobe=False)

    assert atualizar.uma_volta(producao, srv) == "voltou_atras"
    assert srv.passos.count("pip") == 2
    assert (producao / "requirements.txt").read_text() == "fastapi\n"


def test_se_nem_a_anterior_sobe_avisa_em_letras_grandes(repos):
    dev, producao = repos
    _commit(dev, "app.py", "x\n", "novo")
    srv = ServidorFalso(sobe=False, sobe_na_volta=False)

    assert atualizar.uma_volta(producao, srv) == "fora_do_ar"
    assert "ATENÇÃO: o servidor NÃO voltou" in _log(producao)


def test_erro_inesperado_vai_para_o_log(repos):
    """No Agendador roda o pythonw, sem tela: erro fora do log some."""
    dev, producao = repos
    _commit(dev, "app.py", "x\n", "novo")

    class Explode(ServidorFalso):
        def em_curso(self):
            raise RuntimeError("bum")

    assert atualizar.volta_segura(producao, Explode()) == "erro"
    assert "Erro inesperado: RuntimeError: bum" in _log(producao)


# ------------------------------------------------------------ peças soltas
def test_netstat_acha_quem_escuta_na_porta(monkeypatch):
    saida = """
  Proto  Endereço local          Endereço externo       Estado          PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       900
  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       4242
  TCP    192.168.1.250:8000     192.168.1.9:51000      ESTABLISHED     4242
  TCP    0.0.0.0:18000          0.0.0.0:0              LISTENING       77
"""
    monkeypatch.setattr(atualizar.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(
                            a, 0, stdout=saida))

    assert atualizar.pid_na_porta(8000) == 4242
    assert atualizar.pid_na_porta(9999) is None


def test_netstat_em_portugues(monkeypatch):
    saida = """
  Proto  Endereço local          Endereço externo       Estado          PID
  TCP    0.0.0.0:8000           0.0.0.0:0              ESCUTANDO       5151
"""
    monkeypatch.setattr(atualizar.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(
                            a, 0, stdout=saida))

    assert atualizar.pid_na_porta(8000) == 5151


def test_janela_do_servidor_sobe_ate_o_cmd(monkeypatch):
    """python real -> python lançador do .venv -> cmd do Servidor.bat."""
    arvore = {4242: (4100, "python.exe"), 4100: (4000, "python.exe"),
              4000: (1, "cmd.exe")}
    monkeypatch.setattr(atualizar, "_pai_e_nome",
                        lambda pid: arvore.get(pid, (None, "")))

    assert atualizar.janela_do_servidor(4242) == 4000


def test_janela_do_servidor_sem_cmd_fecha_so_o_processo(monkeypatch):
    arvore = {4242: (500, "explorer.exe"), 500: (None, "explorer.exe")}
    monkeypatch.setattr(atualizar, "_pai_e_nome",
                        lambda pid: arvore.get(pid, (None, "")))

    assert atualizar.janela_do_servidor(4242) == 4242


def test_xml_da_tarefa(tmp_path):
    pasta = tmp_path / "cotafrete-producao"
    xml = atualizar.xml_da_tarefa(pasta, r"VM\cotafrete")
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    raiz = ET.fromstring(xml.split("?>", 1)[1])

    assert raiz.find(".//t:Interval", ns).text == "PT5M"
    # Na conta logada: o Servidor.bat precisa da área de trabalho.
    assert raiz.find(".//t:LogonType", ns).text == "InteractiveToken"
    assert raiz.find(".//t:UserId", ns).text == r"VM\cotafrete"
    # Uma volta de cada vez, e nunca "só na tomada".
    assert raiz.find(".//t:MultipleInstancesPolicy", ns).text == "IgnoreNew"
    assert raiz.find(".//t:DisallowStartIfOnBatteries", ns).text == "false"
    assert raiz.find(".//t:Command", ns).text.endswith("pythonw.exe")
    assert "atualizar.py" in raiz.find(".//t:Arguments", ns).text


def test_ocupado_conta_o_que_esta_rodando():
    """O número que o atualizar.py consulta antes de reiniciar."""
    import threading

    from fastapi.testclient import TestClient

    import web.app as modulo

    cliente = TestClient(modulo.app)
    assert cliente.get("/_ocupado").json() == {"em_curso": 0}

    solta = threading.Event()
    futuro = modulo.EXECUTOR.submit(solta.wait, 10)
    try:
        assert cliente.get("/_ocupado").json() == {"em_curso": 1}
    finally:
        solta.set()
        futuro.result(timeout=10)
    assert cliente.get("/_ocupado").json() == {"em_curso": 0}


def test_ocupado_desconta_mesmo_quando_o_trabalho_quebra():
    import web.app as modulo

    def quebra():
        raise ValueError("x")

    futuro = modulo.EXECUTOR.submit(quebra)
    with pytest.raises(ValueError):
        futuro.result(timeout=10)
    assert modulo.EXECUTOR.em_curso == 0
