"""Pergunta à Translovato quais CEPs ela atende. Só CONSULTA, não cota nada.

    python recon/consulta_cep_translovato.py 29105770 60000000
    python recon/consulta_cep_translovato.py --capitais

É a mesma pergunta que o formulário público deles dispara ao sair do campo de
CEP, e a mesma que o adapter faz antes de abrir o navegador. Serve para mapear
a malha sem gastar 40 segundos por praça.

Não envia formulário, não cria cotação, não precisa de login. O endpoint é
público e só responde `true` ou `false`.

Como funciona a chamada (medido em 19/08/2026; detalhes em
carriers/translovato/adapter.py):

1. Abre a página pública para receber o cookie `csrf_cookie_name`.
2. Faz POST em /solicitacao-de-cotacao/validate-cep-attend com o CEP e o
   token de volta no campo `csrf_test_name`.
3. O cabeçalho X-Requested-With é obrigatório. Sem ele a resposta é HTTP 200
   com a página "Página não encontrada" — passa por sucesso em qualquer
   checagem de status.

O mesmo em bash, se precisar conferir fora do Python:

    curl -s -c c.txt -o /dev/null \\
      https://www.translovato.com.br/fale-conosco/solicitacao-de-cotacao
    curl -s -b c.txt -X POST \\
      https://www.translovato.com.br/solicitacao-de-cotacao/validate-cep-attend \\
      -H "X-Requested-With: XMLHttpRequest" \\
      -d "cep=29105770" \\
      -d "csrf_test_name=$(grep csrf_cookie_name c.txt | awk '{print $7}')"
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Este script vive em recon/, mas faz parte do projeto: importa de carriers/.
# Ancorar no __file__ deixa rodar de qualquer pasta.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from carriers.translovato.adapter import TranslovatoAdapter

# Uma por estado, para um retrato rápido da malha. NÃO é a malha inteira: a
# cobertura é por praça, e capital atendida não garante interior atendido.
CAPITAIS = [
    ("29105770", "Vila Velha/ES"),     ("01310100", "São Paulo/SP"),
    ("20040020", "Rio de Janeiro/RJ"), ("30130000", "Belo Horizonte/MG"),
    ("80010000", "Curitiba/PR"),       ("88010000", "Florianópolis/SC"),
    ("90010000", "Porto Alegre/RS"),   ("70040010", "Brasília/DF"),
    ("74003010", "Goiânia/GO"),        ("77001002", "Palmas/TO"),
    ("40010000", "Salvador/BA"),       ("50010000", "Recife/PE"),
    ("60000000", "Fortaleza/CE"),      ("69900000", "Rio Branco/AC"),
    ("68900000", "Macapá/AP"),         ("66010000", "Belém/PA"),
    ("78005000", "Cuiabá/MT"),         ("79002000", "Campo Grande/MS"),
]

# Pausa entre consultas. São requisições ao site de terceiro: uma rajada de
# dezenas por segundo é o jeito mais rápido de ser tratado como robô.
PAUSA_S = 0.4

ROTULO = {True: "ATENDE", False: "NAO ATENDE", None: "nao deu para saber"}


def main() -> int:
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]

    if "--capitais" in sys.argv:
        alvos = CAPITAIS
    elif argumentos:
        alvos = [(cep, "") for cep in argumentos]
    else:
        print("Informe um ou mais CEPs, ou use --capitais.")
        print("  python recon/consulta_cep_translovato.py 29105770 60000000")
        print("  python recon/consulta_cep_translovato.py --capitais")
        return 2

    adapter = TranslovatoAdapter()
    contagem = {True: 0, False: 0, None: 0}

    print(f"{'CEP':<12}{'':<22}resposta")
    print("-" * 58)
    for cep, nome in alvos:
        resposta = adapter._cep_atendido(cep)
        contagem[resposta] += 1
        print(f"{cep:<12}{nome:<22}{ROTULO[resposta]}")
        time.sleep(PAUSA_S)

    print("-" * 58)
    print(f"{contagem[True]} atendidos, {contagem[False]} fora da malha, "
          f"{contagem[None]} sem resposta")

    # Sai com erro se alguma consulta não respondeu: num script de mapeamento,
    # "não deu para saber" no meio da lista precisa saltar aos olhos, senão
    # vira um buraco silencioso no mapa.
    return 1 if contagem[None] else 0


if __name__ == "__main__":
    raise SystemExit(main())
