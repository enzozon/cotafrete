"""A trava que impede o servidor da rede de subir da pasta errada.

Em 25/08/2026 o `Servidor.bat` foi aberto pela pasta de desenvolvimento.
As duas pastas escutam na porta 8000 e nada distinguia uma da outra na
tela, entao a empresa passou a manha cotando contra o codigo de dev e
quatro cotacoes reais foram para o banco errado.

Apagar a copia da pasta de dev nao servia: o arquivo e versionado e as
duas pastas sao o mesmo repositorio, entao a exclusao chegaria em
producao no `git pull` seguinte. A trava mora dentro do proprio arquivo
e olha o caminho de onde ele foi chamado.

Os dois sentidos importam. Um teste que so verifica a recusa passaria
tambem com um `exit /b 1` no topo, que quebraria producao.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "Servidor.bat"

so_windows = pytest.mark.skipif(os.name != "nt", reason="lançador .bat é do Windows")


def rodar_de(pasta: Path) -> subprocess.CompletedProcess:
    """Copia o .bat para `pasta` e roda de la.

    stdin fechado por causa do `pause`: sem isso o teste ficaria esperando
    uma tecla que ninguem vai apertar.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    copia = pasta / "Servidor.bat"
    shutil.copy2(SERVIDOR, copia)
    return subprocess.run(
        ["cmd", "/c", str(copia)],
        capture_output=True, stdin=subprocess.DEVNULL, timeout=60)


def saida(proc: subprocess.CompletedProcess) -> str:
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


@so_windows
@pytest.mark.parametrize("nome", ["cotafrete-dev", "cotafrete", "outra-pasta"])
def test_recusa_subir_fora_de_producao(tmp_path, nome):
    proc = rodar_de(tmp_path / nome)

    assert proc.returncode == 1
    assert "ESTA NAO E A PASTA DE PRODUCAO" in saida(proc)
    assert "Cotafrete.bat" in saida(proc)     # diz o que usar no lugar


@so_windows
def test_de_producao_passa_da_trava(tmp_path):
    """O outro sentido: em cotafrete-producao ele PRECISA passar.

    Sem `.venv` na pasta temporaria ele para no aviso seguinte, o de
    ambiente nao instalado — que e justamente a prova de que passou da
    trava sem nunca chegar a abrir uma porta de rede.
    """
    proc = rodar_de(tmp_path / "cotafrete-producao")
    texto = saida(proc)

    assert "ESTA NAO E A PASTA DE PRODUCAO" not in texto
    assert "Ambiente nao instalado" in texto


@so_windows
def test_o_nome_da_pasta_nao_pega_maiuscula(tmp_path):
    """Windows nao liga para caixa em nome de pasta, e o `cmd` tambem nao.
    Se alguem criar COTAFRETE-PRODUCAO, tem que continuar subindo."""
    proc = rodar_de(tmp_path / "COTAFRETE-PRODUCAO")

    assert "ESTA NAO E A PASTA DE PRODUCAO" not in saida(proc)


# ------------------------------------------------- o congelamento por clique

def test_a_saida_do_servidor_nao_vai_para_a_tela():
    """A linha do uvicorn precisa redirecionar para arquivo.

    O console do Windows vem com QuickEdit ligado: um clique dentro da janela
    poe o console em modo de selecao, e enquanto ele estiver assim QUALQUER
    escrita na tela fica parada esperando um Enter. Nao para so a escrita —
    para o processo inteiro. O servidor continua vivo, a porta continua
    LISTENING, e nenhuma pagina abre.

    Era o "esta ligado porem nao esta funcionando" da empresa. Intermitente
    porque, com --log-level warning, o servidor quase nao escreve: o clique
    ARMA a armadilha e ela so dispara na escrita seguinte, que pode vir horas
    depois.

    Sem escrita na tela nao ha o que travar. Tirar este redirecionamento
    devolve o defeito, e ele nao aparece em teste nenhum que olhe para o
    HTML — por isso a guarda e aqui, no texto do lancador.
    """
    texto = SERVIDOR.read_text(encoding="utf-8", errors="replace")
    linha = next(l for l in texto.splitlines() if "-m uvicorn" in l)

    assert ">>" in linha and "2>&1" in linha, (
        f"a saida do uvicorn precisa ir para arquivo, nao para a tela:\n"
        f"  {linha.strip()}")


def test_o_erro_de_partida_nao_fica_so_no_arquivo():
    """Com a saida indo para o log, porta ocupada ou .env sem senha deixariam
    a janela mostrando apenas "O servidor parou", sem uma pista do porque.

    Quem liga o servidor de manha nao vai abrir um .log para descobrir que a
    porta estava ocupada."""
    texto = SERVIDOR.read_text(encoding="utf-8", errors="replace")

    assert "-Tail" in texto, (
        "o fim do log precisa aparecer na tela quando o servidor para")


def test_o_log_do_servidor_nao_vai_para_o_git():
    """O traceback de uma transportadora sai com o payload junto: CNPJ do
    cliente, valor da nota, endereco de entrega. Mesmo motivo de runs/ e
    backup/ ja estarem ignorados."""
    ignorados = (RAIZ / ".gitignore").read_text(encoding="utf-8").split()

    assert "log/" in ignorados
