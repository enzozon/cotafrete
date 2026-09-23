"""Atualização automática da pasta de produção.

Até 24/09/2026, cada merge pedia a mesma sequência à mão, dentro da VM:
fechar o Servidor.bat, `git checkout main`, `git pull`, `pip install -r
requirements.txt`, abrir de novo. Este script faz a mesma coisa sozinho. O
Agendador de Tarefas do Windows o roda a cada 5 minutos (ver `--instalar`),
e ele só age quando a `main` do GitHub tem commit que a pasta ainda não tem.

A ordem importa, e cada passo existe por um motivo:

1. SÓ NA PASTA DE PRODUÇÃO: a mesma trava do Servidor.bat. Rodado na
   pasta de desenvolvimento, derrubaria o servidor da empresa (que escuta
   na mesma porta 8000) para subir código em teste.
2. NADA DE ALTERAÇÃO LOCAL: um arquivo versionado mexido na mão é
   trabalho de alguém. O script avisa no log e não toca em nada.
3. ESPERA AS COTAÇÕES TERMINAREM: reiniciar no meio de uma cotação mata as
   threads das transportadoras. Com cotação rodando ele não faz nada, e
   tenta de novo na próxima volta, 5 minutos depois.
4. FECHA O SERVIDOR ANTES DO PIP: no Windows, pacote em uso pelo servidor
   não pode ser trocado ("acesso negado"). O pip só roda com o servidor
   fechado, e só quando o requirements.txt mudou.
5. CONFERE SE SUBIU: abre o Servidor.bat de novo e espera a tela de
   login responder. Se não responder, volta para a versão anterior e sobe
   de novo. Um merge com defeito não deixa a empresa fora do ar.

Tudo o que acontece vai para log\\atualizar.log. As voltas sem novidade não
escrevem nada, e o mesmo aviso repetido (sem internet, por exemplo) sai uma
vez só, não a cada 5 minutos.

Uso, dentro da VM, na pasta cotafrete-producao:

    .venv\\Scripts\\python.exe atualizar.py             # uma volta, agora
    .venv\\Scripts\\python.exe atualizar.py --instalar  # cria a tarefa
    .venv\\Scripts\\python.exe atualizar.py --remover   # apaga a tarefa
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PASTA = Path(__file__).resolve().parent
NOME_DA_PASTA_DE_PRODUCAO = "cotafrete-producao"
RAMO = "main"
PORTA = 8000
NOME_DA_TAREFA = "Cotafrete - atualizar sozinho"
INTERVALO_MIN = 5

# Quanto esperar a tela de login responder depois de abrir o Servidor.bat.
# A subida normal leva uns 5 segundos; 90 cobre uma VM lenta logo depois do
# pip.
ESPERA_SUBIR_S = 90
# Quanto esperar a porta ficar livre depois de fechar o servidor.
ESPERA_FECHAR_S = 30
# Um pip que baixa o Playwright inteiro passa de 5 minutos numa rede ruim.
TEMPO_DO_PIP_S = 1200
TEMPO_DO_GIT_S = 180

# Windows: sem janela preta piscando a cada comando.
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
JANELA_NOVA = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
FORA_DO_JOB = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)


class Falha(Exception):
    """Um passo que não deu certo. A mensagem vai para o log."""


# ------------------------------------------------------------------ log
def arquivo_de_log(pasta: Path = PASTA) -> Path:
    return pasta / "log" / "atualizar.log"


def _ultima_mensagem(log: Path) -> str | None:
    try:
        linhas = log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for linha in reversed(linhas):
        if linha.strip():
            # "2026-09-24 10:00:00  mensagem" -> "mensagem"
            return linha[21:] if re.match(r"\d{4}-\d\d-\d\d \d\d:", linha) \
                else linha
    return None


def registrar(pasta: Path, mensagem: str, *, repetida: bool = True) -> None:
    """Uma linha no log\\atualizar.log.

    `repetida=False` é para os avisos que voltariam a cada 5 minutos (sem
    internet, cotação em andamento): se a última linha do log já diz a mesma
    coisa, não escreve de novo."""
    log = arquivo_de_log(pasta)
    log.parent.mkdir(exist_ok=True)
    if not repetida and _ultima_mensagem(log) == mensagem:
        return
    quando = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log.open("a", encoding="utf-8") as f:
        f.write(f"{quando}  {mensagem}\n")
    # Quem roda à mão vê na tela também (pythonw não tem tela: ignora).
    if sys.stdout is not None:
        try:
            print(mensagem, flush=True)
        except (OSError, ValueError):
            pass


# ---------------------------------------------------------- comandos
def _ambiente() -> dict:
    amb = dict(os.environ)
    # Nunca perguntar nada: não há ninguém olhando. Sem isto, uma senha do
    # GitHub vencida abre uma janela de login que fica esperando para sempre
    # — e prende todas as voltas seguintes.
    amb["GIT_TERMINAL_PROMPT"] = "0"
    amb["GCM_INTERACTIVE"] = "never"
    return amb


def rodar(pasta: Path, *cmd: str, tempo: float = TEMPO_DO_GIT_S) -> str:
    try:
        r = subprocess.run(list(cmd), cwd=pasta, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=tempo, env=_ambiente(),
                           creationflags=SEM_JANELA)
    except FileNotFoundError:
        raise Falha(f"'{cmd[0]}' não encontrado nesta máquina") from None
    except subprocess.TimeoutExpired:
        raise Falha(f"'{' '.join(cmd[:3])}' passou de {int(tempo)} s "
                    f"e foi interrompido") from None
    if r.returncode != 0:
        saida = (r.stderr or r.stdout or "").strip().splitlines()
        raise Falha(f"'{' '.join(cmd[:3])}' falhou: "
                    f"{saida[-1] if saida else f'código {r.returncode}'}")
    return r.stdout.rstrip()


def git(pasta: Path, *args: str) -> str:
    return rodar(pasta, "git", *args)


def python_do_venv(pasta: Path) -> Path:
    if os.name == "nt":
        return pasta / ".venv" / "Scripts" / "python.exe"
    return pasta / ".venv" / "bin" / "python"


# ------------------------------------------------------ o servidor
def perguntar(caminho: str, porta: int = PORTA, tempo: float = 5):
    """GET no servidor local. None se ele não respondeu."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}{caminho}",
                                    timeout=tempo) as r:
            return r.status, r.read()
    except Exception:
        return None


def em_curso(porta: int = PORTA) -> int | None:
    """Quantas cotações o servidor está rodando. None: servidor fora do ar
    (ou de uma versão sem /_ocupado), e aí não há o que esperar."""
    resposta = perguntar("/_ocupado", porta)
    if resposta is None or resposta[0] != 200:
        return None
    try:
        return int(json.loads(resposta[1])["em_curso"])
    except (ValueError, KeyError, TypeError):
        return None


def no_ar(porta: int = PORTA) -> bool:
    resposta = perguntar("/login", porta)
    return resposta is not None and resposta[0] == 200


def pid_na_porta(porta: int = PORTA) -> int | None:
    try:
        saida = subprocess.run(["netstat", "-ano"], capture_output=True,
                               text=True, errors="replace", timeout=30,
                               creationflags=SEM_JANELA).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for linha in saida.splitlines():
        partes = linha.split()
        # O estado vem na língua do Windows ("ESCUTANDO" no português); o
        # endereço remoto zerado é o mesmo em qualquer língua.
        if (len(partes) >= 5 and partes[0].upper() == "TCP"
                and partes[1].endswith(f":{porta}")
                and (partes[3].upper() in ("LISTENING", "ESCUTANDO")
                     or partes[2] in ("0.0.0.0:0", "[::]:0"))
                and partes[4].isdigit()):
            return int(partes[4])
    return None


def _pai_e_nome(pid: int) -> tuple[int | None, str]:
    cmd = (f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}';"
           " if ($p) { \"$($p.ParentProcessId)|$($p.Name)\" }")
    try:
        saida = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, errors="replace", timeout=30,
            creationflags=SEM_JANELA).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    pai, _, nome = saida.partition("|")
    return (int(pai) if pai.isdigit() else None), nome.lower()


def janela_do_servidor(pid: int) -> int:
    """O cmd.exe do Servidor.bat que está por cima deste processo.

    Fechar só o python deixaria a janela velha aberta em "O servidor parou
    ... Pressione qualquer tecla", e a cada merge sobraria mais uma. O
    python do .venv ainda é um lançador que abre o python de verdade como
    filho, então a subida passa por um ou dois python.exe até achar o
    cmd.exe."""
    atual = pid
    for _ in range(4):
        pai, _ = _pai_e_nome(atual)
        if pai is None:
            break
        _, nome_do_pai = _pai_e_nome(pai)
        if nome_do_pai == "cmd.exe":
            return pai
        if nome_do_pai not in ("python.exe", "pythonw.exe"):
            break
        atual = pai
    return pid


def fechar_servidor(porta: int = PORTA) -> None:
    pid = pid_na_porta(porta)
    if pid is None:
        return
    raiz = janela_do_servidor(pid)
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(raiz)],
                   capture_output=True, timeout=30, creationflags=SEM_JANELA)
    fim = time.monotonic() + ESPERA_FECHAR_S
    while time.monotonic() < fim:
        if pid_na_porta(porta) is None:
            return
        time.sleep(1)
    raise Falha(f"o servidor (processo {pid}) não fechou em "
                f"{ESPERA_FECHAR_S} s")


def abrir_servidor(pasta: Path):
    """Abre o Servidor.bat numa janela nova, como o atalho do boot faz.

    Janela de verdade, e não escondida: a Generoso e a Della Volpe abrem
    navegador com janela, e o servidor precisa ficar na área de trabalho da
    conta logada — foi por isso que ele nunca virou serviço do Windows."""
    cmd = ["cmd.exe", "/c", str(pasta / "Servidor.bat"), "/auto"]
    # Fora do "job" do Agendador: se a tarefa for encerrada (tempo limite,
    # alguém clicando em Finalizar), o Windows fecha junto tudo o que está no
    # job dela — inclusive o servidor que ela abriu.
    try:
        return subprocess.Popen(cmd, cwd=pasta,
                                creationflags=JANELA_NOVA | FORA_DO_JOB)
    except OSError:
        # O job não permite sair dele: abre assim mesmo.
        return subprocess.Popen(cmd, cwd=pasta, creationflags=JANELA_NOVA)


def fechar_janela(processo) -> None:
    """A janela que este script abriu e que não subiu: está parada no
    "pause" do fim do Servidor.bat."""
    if processo is None or processo.poll() is not None:
        return
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(processo.pid)],
                   capture_output=True, timeout=30, creationflags=SEM_JANELA)


def esperar_no_ar(porta: int = PORTA, tempo: float = ESPERA_SUBIR_S) -> bool:
    fim = time.monotonic() + tempo
    while time.monotonic() < fim:
        if no_ar(porta):
            return True
        time.sleep(2)
    return False


def fim_do_log_do_servidor(pasta: Path, linhas: int = 8) -> str:
    try:
        texto = (pasta / "log" / "servidor.log").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return "(log\\servidor.log vazio)"
    return "\n".join("      " + l for l in texto.splitlines()[-linhas:])


def instalar_dependencias(pasta: Path) -> None:
    py = str(python_do_venv(pasta))
    rodar(pasta, py, "-m", "pip", "install", "-r", "requirements.txt",
          tempo=TEMPO_DO_PIP_S)
    # Só baixa se a versão do Playwright mudou; se não, volta na hora.
    rodar(pasta, py, "-m", "playwright", "install", "chromium",
          tempo=TEMPO_DO_PIP_S)


# ------------------------------------------------------- a atualização
def e_producao(pasta: Path) -> bool:
    return NOME_DA_PASTA_DE_PRODUCAO in (p.lower() for p in pasta.parts)


class Servidor:
    """O que o script faz com o servidor. Separado para o teste trocar por
    um de mentira: os testes rodam no Linux, sem Servidor.bat nem netstat."""

    def __init__(self, pasta: Path, porta: int = PORTA) -> None:
        self.pasta = pasta
        self.porta = porta

    def em_curso(self) -> int | None:
        return em_curso(self.porta)

    def fechar(self) -> None:
        fechar_servidor(self.porta)

    def abrir(self):
        return abrir_servidor(self.pasta)

    def fechar_janela(self, processo) -> None:
        fechar_janela(processo)

    def esperar_no_ar(self) -> bool:
        return esperar_no_ar(self.porta)

    def instalar_dependencias(self) -> None:
        instalar_dependencias(self.pasta)


def _resumo(pasta: Path, de: str, ate: str) -> str:
    try:
        titulos = git(pasta, "log", "--format=%s", f"{de}..{ate}")
    except Falha:
        return ""
    linhas = [t for t in titulos.splitlines() if t.strip()]
    return "".join(f"\n      - {t}" for t in linhas[:15])


def uma_volta(pasta: Path = PASTA, servidor: Servidor | None = None) -> str:
    """Uma passada. Devolve o que aconteceu, numa palavra (para o teste):
    fora_da_producao, sem_novidade, recusado, sem_rede, alteracao_local,
    nao_avanca, ocupado, nao_fechou, atualizado, voltou_atras ou
    fora_do_ar."""
    servidor = servidor or Servidor(pasta)
    if not e_producao(pasta):
        print(f"Esta não é a pasta {NOME_DA_PASTA_DE_PRODUCAO}: nada a "
              f"fazer. A atualização automática é só da produção.")
        return "fora_da_producao"

    try:
        git(pasta, "fetch", "--quiet", "origin", RAMO)
        ramo = git(pasta, "rev-parse", "--abbrev-ref", "HEAD")
        antes = git(pasta, "rev-parse", "HEAD")
        alvo = git(pasta, "rev-parse", f"origin/{RAMO}")
    except Falha as exc:
        registrar(pasta, f"Não consegui falar com o GitHub: {exc}",
                  repetida=False)
        return "sem_rede"

    if ramo == RAMO and antes == alvo:
        return "sem_novidade"
    if alvo == recusado(pasta):
        # Já falhou uma vez: tentar de novo derrubaria o servidor a cada 5
        # minutos. O próximo merge (outro commit) libera.
        return "recusado"

    mexidos = git(pasta, "status", "--porcelain", "--untracked-files=no")
    if mexidos:
        arquivos = ", ".join(l[3:] for l in mexidos.splitlines()[:5])
        registrar(pasta, f"Há versão nova, mas NÃO atualizei: arquivos "
                         f"alterados à mão nesta pasta ({arquivos}). Desfaça "
                         f"(git checkout -- .) ou me avise.", repetida=False)
        return "alteracao_local"

    if ramo == RAMO:
        try:
            git(pasta, "merge-base", "--is-ancestor", "HEAD", alvo)
        except Falha:
            registrar(pasta, f"Há versão nova, mas NÃO atualizei: esta "
                             f"pasta tem commit que o GitHub não tem, e o "
                             f"pull não é direto.", repetida=False)
            return "nao_avanca"

    ocupadas = servidor.em_curso()
    if ocupadas:
        registrar(pasta, f"Há versão nova; esperando as cotações em "
                         f"andamento ({ocupadas}) terminarem para reiniciar.",
                  repetida=False)
        return "ocupado"

    registrar(pasta, f"Atualizando {antes[:7]} -> {alvo[:7]}"
                     + (f" (estava no ramo {ramo})" if ramo != RAMO else "")
                     + _resumo(pasta, antes, alvo))
    mudou_dependencia = "requirements.txt" in git(
        pasta, "diff", "--name-only", antes, alvo).splitlines()

    try:
        servidor.fechar()
    except Falha as exc:
        # Nada foi trocado ainda: o código continua o de antes.
        registrar(pasta, f"NÃO atualizei: {exc}. Tento de novo na próxima "
                         f"volta.")
        if not servidor.esperar_no_ar():
            servidor.abrir()
        return "nao_fechou"

    try:
        if ramo != RAMO:
            git(pasta, "checkout", "--quiet", RAMO)
        git(pasta, "merge", "--ff-only", "--quiet", alvo)
        if mudou_dependencia:
            registrar(pasta, "requirements.txt mudou: pip install ...")
            servidor.instalar_dependencias()
        janela = servidor.abrir()
        if servidor.esperar_no_ar():
            registrar(pasta, f"Pronto: no ar com {alvo[:7]}.")
            return "atualizado"
        servidor.fechar_janela(janela)
        motivo = ("o servidor não respondeu depois de reiniciar. Fim do "
                  "log\\servidor.log:\n" + fim_do_log_do_servidor(pasta))
    except Falha as exc:
        motivo = str(exc)

    # Deu errado: a versão anterior de volta, e no ar.
    registrar(pasta, f"FALHOU ({motivo}). Voltando para {antes[:7]}.")
    try:
        servidor.fechar()
        if ramo != RAMO:
            git(pasta, "checkout", "--quiet", "--force", ramo)
        else:
            git(pasta, "reset", "--quiet", "--hard", antes)
        if mudou_dependencia:
            servidor.instalar_dependencias()
    except Falha as exc:
        registrar(pasta, f"Ao voltar: {exc}")
    servidor.abrir()
    if servidor.esperar_no_ar():
        registrar(pasta, f"No ar de novo com a versão anterior {antes[:7]}. "
                         f"A versão {alvo[:7]} fica de fora até o próximo "
                         f"merge.")
        # Sem isto, a próxima volta tentaria o mesmo commit de novo, a cada
        # 5 minutos, derrubando o servidor toda vez.
        _lembrar_recusado(pasta, alvo)
        return "voltou_atras"
    registrar(pasta, "ATENÇÃO: o servidor NÃO voltou. Abra a VM e rode o "
                     "Servidor.bat à mão.")
    return "fora_do_ar"


def _arquivo_recusado(pasta: Path) -> Path:
    return pasta / "log" / "atualizar-recusado.txt"


def _lembrar_recusado(pasta: Path, commit: str) -> None:
    _arquivo_recusado(pasta).write_text(commit, encoding="utf-8")


def recusado(pasta: Path) -> str | None:
    try:
        return _arquivo_recusado(pasta).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def volta_segura(pasta: Path = PASTA, servidor: Servidor | None = None) -> str:
    """`uma_volta` sem deixar exceção escapar sem ir para o log: o pythonw
    do Agendador não tem tela, e um erro não registrado some."""
    try:
        return uma_volta(pasta, servidor)
    except Exception as exc:
        registrar(pasta, f"Erro inesperado: {type(exc).__name__}: {exc}",
                  repetida=False)
        return "erro"


# ------------------------------------------------------ a tarefa agendada
def xml_da_tarefa(pasta: Path, usuario: str) -> str:
    """A tarefa do Agendador, em XML — é o único jeito de ligar tudo o que
    ela precisa. Pelo `schtasks /Create` simples ela nasce com "só na
    tomada" e "parar depois de 3 dias", e na VM isso pode querer dizer nunca
    rodar."""
    pythonw = python_do_venv(pasta).with_name("pythonw.exe")
    inicio = datetime.now().replace(microsecond=0).isoformat()

    def x(t) -> str:
        return (str(t).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Atualiza o Cotafrete de {x(pasta)} depois de cada merge na main: git pull, pip install e reinicio do servidor. Ver atualizar.py.</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{inicio}</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT{INTERVALO_MIN}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{x(usuario)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{x(pythonw)}</Command>
      <Arguments>"{x(pasta / 'atualizar.py')}"</Arguments>
      <WorkingDirectory>{x(pasta)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def instalar(pasta: Path = PASTA) -> int:
    if not e_producao(pasta):
        print(f"Recusado: esta não é a pasta {NOME_DA_PASTA_DE_PRODUCAO}.\n"
              f"Pasta: {pasta}\n"
              "Instalar aqui faria a pasta de desenvolvimento derrubar o "
              "servidor da empresa a cada merge.")
        return 1
    if not python_do_venv(pasta).with_name("pythonw.exe").exists():
        print("Falta .venv\\Scripts\\pythonw.exe nesta pasta. Instale o "
              "ambiente primeiro (docs\\DEPLOY_SERVIDOR.md, passo 4).")
        return 1
    usuario = f"{os.environ.get('USERDOMAIN', '')}\\" \
              f"{os.environ.get('USERNAME', '')}".lstrip("\\")
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False,
                                     encoding="utf-16") as f:
        f.write(xml_da_tarefa(pasta, usuario))
        caminho = f.name
    try:
        r = subprocess.run(["schtasks", "/Create", "/F", "/TN",
                            NOME_DA_TAREFA, "/XML", caminho],
                           capture_output=True, text=True, errors="replace")
    finally:
        os.unlink(caminho)
    print((r.stdout or r.stderr).strip())
    if r.returncode == 0:
        print(f"\nPronto. A cada {INTERVALO_MIN} minutos, enquanto a conta "
              f"{usuario} estiver logada, esta pasta se atualiza sozinha "
              f"depois de cada merge na main.\nO que acontecer fica em "
              f"log\\atualizar.log.")
    return r.returncode


def remover() -> int:
    r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", NOME_DA_TAREFA],
                       capture_output=True, text=True, errors="replace")
    print((r.stdout or r.stderr).strip())
    return r.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--instalar", action="store_true",
                    help="cria a tarefa no Agendador do Windows")
    ap.add_argument("--remover", action="store_true",
                    help="apaga a tarefa do Agendador")
    args = ap.parse_args(argv)
    if args.instalar:
        return instalar()
    if args.remover:
        return remover()
    resultado = volta_segura()
    if sys.stdout is not None:
        try:
            print(f"[{resultado}]")
        except (OSError, ValueError):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
