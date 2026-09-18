"""Senha e sessão do vendedor. Funções puras — quem grava é o `core/banco.py`.

O QUE ISTO CONSERTA

Até 16/09/2026 o cookie do vendedor guardava o nome digitado, puro:
`cotafrete_usuario=joao`. Trocar esse valor no inspetor do navegador era
virar outra pessoa e ver o histórico dela — CNPJ de cliente, endereço de
entrega, valor de nota. Na rede local isso era um incômodo; publicado na
internet, é vazamento.

Agora o cookie carrega uma assinatura que só quem tem o segredo do servidor
consegue produzir, e um prazo. Forjar exige o segredo; sem ele, o valor é
recusado.

POR QUE NÃO REAPROVEITEI O `token_de()` DO `web/adm.py`

Aquele HMAC deriva da senha única do painel e responde uma pergunta de
sim/não ("esta pessoa tem a senha do adm?"). Aqui a pergunta é outra: *qual*
vendedor é este, e até quando. Precisa de identidade e de prazo — o token do
adm não tem nem um nem outro.

SEM DEPENDÊNCIA NOVA

`hashlib.scrypt` é biblioteca padrão e é derivação de chave de verdade: cara
de propósito, para que testar senha em massa contra um banco roubado custe
caro. `hashlib.sha256` sozinho não serve para senha — é rápido demais.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime

# Parâmetros do scrypt. n é o custo; 2**14 leva ~100 ms nesta máquina, que é
# desprezível num login e caro em quem tenta milhões. Ficam GRAVADOS em cada
# hash: aumentar o custo no futuro não invalida as senhas já guardadas.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
TAMANHO_CHAVE = 32
TAMANHO_SAL = 16

MINIMO_DA_SENHA = 8
# Teto para o scrypt não virar negação de serviço: uma senha de 10 MB colada
# no formulário faria o servidor derreter calculando o hash dela.
MAXIMO_DA_SENHA = 256

DIAS_DE_SESSAO = 7
SEPARADOR = "|"


# -------------------------------------------------------------------- senha
def recusa_da_senha(senha: str) -> str | None:
    """A mensagem de recusa, ou None se a senha serve."""
    if len(senha) < MINIMO_DA_SENHA:
        return (f"A senha precisa de pelo menos {MINIMO_DA_SENHA} caracteres. "
                f"Uma frase curta que só você saiba serve bem.")
    if len(senha) > MAXIMO_DA_SENHA:
        return f"A senha passa de {MAXIMO_DA_SENHA} caracteres."
    return None


def hash_senha(senha: str) -> str:
    """O que vai para o banco. Nunca a senha."""
    sal = secrets.token_bytes(TAMANHO_SAL)
    chave = hashlib.scrypt(senha.encode(), salt=sal, n=SCRYPT_N, r=SCRYPT_R,
                           p=SCRYPT_P, dklen=TAMANHO_CHAVE)
    return (f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"
            f"{sal.hex()}${chave.hex()}")


def senha_confere(senha: str, guardado: str) -> bool:
    """Confere contra o que está no banco.

    Qualquer defeito no valor guardado vira `False`, nunca exceção: uma linha
    corrompida não pode derrubar a tela de login — nem, muito pior, passar."""
    try:
        marca, n, r, p, sal_hex, esperado_hex = guardado.split("$")
        if marca != "scrypt":
            return False
        chave = hashlib.scrypt(senha.encode(), salt=bytes.fromhex(sal_hex),
                               n=int(n), r=int(r), p=int(p),
                               dklen=len(esperado_hex) // 2)
    except (ValueError, TypeError, AttributeError, MemoryError):
        return False
    # compare_digest e não ==: comparação comum sai no primeiro byte
    # diferente, e o tempo da resposta entrega o quanto do hash já bateu.
    return hmac.compare_digest(chave.hex(), esperado_hex)


# ------------------------------------------------------------------- cookie
def _assinatura(corpo: str, segredo: str) -> str:
    return hmac.new(segredo.encode(), corpo.encode(), "sha256").hexdigest()


def assinar(nome: str, segredo: str, agora: datetime | None = None,
            dias: int = DIAS_DE_SESSAO) -> str:
    """O valor do cookie: nome, prazo e a assinatura dos dois.

    O nome vai em hexadecimal para não esbarrar no separador nem em acento,
    que não passa cru num cabeçalho HTTP."""
    prazo = int((agora or datetime.now()).timestamp()) + dias * 86400
    corpo = f"{nome.encode().hex()}{SEPARADOR}{prazo}"
    return f"{corpo}{SEPARADOR}{_assinatura(corpo, segredo)}"


def dono_do_cookie(valor: str | None, segredo: str,
                   agora: datetime | None = None) -> str | None:
    """De quem é esta sessão, ou None se o cookie não vale.

    Recusa por qualquer motivo — ausente, malformado, assinatura errada,
    prazo vencido — devolvendo None. Quem chama não precisa distinguir: em
    todos os casos a resposta é a mesma, mandar para o login."""
    if not valor:
        return None
    nome_hex, sep, resto = valor.partition(SEPARADOR)
    prazo_txt, sep2, assinatura = resto.partition(SEPARADOR)
    if not (sep and sep2 and assinatura):
        return None

    corpo = f"{nome_hex}{SEPARADOR}{prazo_txt}"
    if not hmac.compare_digest(assinatura, _assinatura(corpo, segredo)):
        return None

    # A assinatura já provou que o prazo não foi mexido; só depois dela vale
    # a pena interpretar o conteúdo.
    try:
        prazo = int(prazo_txt)
        nome = bytes.fromhex(nome_hex).decode()
    except (ValueError, UnicodeDecodeError):
        return None

    if (agora or datetime.now()).timestamp() > prazo:
        return None
    return nome


def cookie_seguro() -> bool:
    """Se os cookies de sessão saem com a marca `Secure`.

    É a única função deste módulo que olha o ambiente — as outras são puras.
    Ela mora aqui, e não em `web/app.py`, porque os DOIS cookies do sistema
    precisam da mesma resposta: o do vendedor e o do painel. E `web/adm.py`
    não pode importar `web/app.py`, que é o contrário do que acontece hoje.

    `Secure` faz o navegador NUNCA mandar o cookie por http, o que fecha a
    janela de alguém na mesma rede ler a sessão em trânsito. Vem DESLIGADO
    porque a equipe também entra por `http://192.168.1.250:8000`, e ali
    ligá-la faria o login parar de funcionar sem erro nenhum na tela: o
    cookie sairia e o navegador o descartaria calado.

    Ligue junto com `COTAFRETE_HOST=127.0.0.1` (ver Servidor.bat), depois que
    todo mundo já estiver entrando pelo endereço público:

        setx /M COTAFRETE_COOKIE_SEGURO 1
    """
    return os.getenv("COTAFRETE_COOKIE_SEGURO", "").strip() == "1"


def novo_segredo() -> str:
    """O segredo do servidor. Gerado uma vez e guardado no banco.

    Trocá-lo derruba todas as sessões abertas — é o botão de expulsar todo
    mundo, sem precisar manter lista de sessão para administrar."""
    return secrets.token_hex(32)
