"""Roda a cotação da Jadlog VÁRIAS vezes e confere se o print sai certo sempre.

    python testar_jadlog_repetido.py [n]

O modo de falha que isso caça é o print cinza: o JSF SUBSTITUI #panel_resultado
no partial update, então existe uma janela em que o elemento já tem texto mas
ainda não foi pintado. O screenshot sai vazio e o valor "some" — sem erro
nenhum, o status continua COTADO.

Cada rodada usa uma rota diferente: repetir a mesma rota testaria cache, não
o adapter.
"""

from __future__ import annotations

import sys
import time
import zlib
from pathlib import Path

from carriers.jadlog.simulador import JadlogSimuladorAdapter
from core.models import StatusCotacao
from web.app import montar_request

# Rotas variadas. Distâncias diferentes = valores diferentes, o que também
# denuncia um resultado repetido vindo de tela não atualizada.
ROTAS = [
    ("29065-560", "ES", "Vitória", "01310-100", "SP", "São Paulo"),
    ("29065-560", "ES", "Vitória", "29300-000", "ES", "Cachoeiro de Itapemirim"),
    ("01310-100", "SP", "São Paulo", "30130-000", "MG", "Belo Horizonte"),
    ("29065-560", "ES", "Vitória", "80010-000", "PR", "Curitiba"),
    ("01310-100", "SP", "São Paulo", "40010-000", "BA", "Salvador"),
    ("29065-560", "ES", "Vitória", "90010-000", "RS", "Porto Alegre"),
]

BASE = {
    "nome": "Enzo Teste", "email": "enzo@exemplo.com.br", "whatsapp": "27999887766",
    "cnpj_remetente": "11.222.333/0001-81", "cnpj_destinatario": "45.723.174/0001-10",
    "cnpj_pagador": "61.139.432/0001-72", "qtd": "1", "peso": "10",
    "comprimento": "15", "largura": "15", "altura": "15", "valor_nf": "30",
    "tipo_material": "Peças metálicas",
}

# Um PNG de cor sólida, depois do filtro do PNG, vira uma sequência quase toda
# de zeros: pouquíssimos valores de byte distintos. Texto renderizado com
# antialiasing passa fácil de 100. 40 é folgado para os dois lados.
#
# ⚠ Isto responde "a imagem tem conteúdo?", NÃO "a imagem está certa?". Uma
# tela bloqueada pelo overlay do PrimeFaces, cinza e com spinner, passa aqui
# com 256 bytes distintos — foi exatamente assim que prints quebrados passaram
# por bons em três baterias seguidas, em 13/08/2026. Olhe as imagens.
MIN_BYTES_DISTINTOS = 40


def inspecionar_png(caminho: Path) -> tuple[int, int, int]:
    """(largura, altura, nº de valores de byte distintos nos dados crus)."""
    dados = caminho.read_bytes()
    largura = int.from_bytes(dados[16:20], "big")
    altura = int.from_bytes(dados[20:24], "big")

    idat, i = b"", 8
    while i + 8 <= len(dados):
        tam = int.from_bytes(dados[i:i + 4], "big")
        if dados[i + 4:i + 8] == b"IDAT":
            idat += dados[i + 8:i + 8 + tam]
        i += 12 + tam
    return largura, altura, len(set(zlib.decompress(idat)))


def rodada(n: int, rota: tuple[str, ...]) -> dict:
    cep_o, uf_o, cid_o, cep_d, uf_d, cid_d = rota
    # cidade e UF saem do CEP; ficam aqui so para o rotulo da linha
    req = montar_request({**BASE, "cep_origem": cep_o, "cep_destino": cep_d})

    inicio = time.monotonic()
    res = JadlogSimuladorAdapter(modalidade="expresso").cotar(req)
    seg = time.monotonic() - inicio

    linha = {"n": n, "rota": f"{cid_o}/{uf_o} -> {cid_d}/{uf_d}", "seg": seg,
             "status": res.status.value, "valor": res.valor_frete,
             "erro": res.erro, "recusa": res.motivo_recusa,
             "print_ok": False, "detalhe": ""}

    # RECUSADO ("CEP nao atendido") é resposta boa da Jadlog, e o print dela
    # também precisa sair legível — é a evidência de que foi a transportadora
    # que disse não, e não o nosso robô que se perdeu.
    if res.status not in (StatusCotacao.COTADO, StatusCotacao.RECUSADO):
        linha["detalhe"] = "sem cotacao"
        return linha

    if not res.evidencias:
        linha["detalhe"] = "nenhum print gerado"
        return linha

    png = Path(res.evidencias[0])          # o recorte do painel de resultado
    if not png.exists():
        linha["detalhe"] = f"arquivo sumiu: {png}"
        return linha

    larg, alt, variedade = inspecionar_png(png)
    linha["detalhe"] = f"{larg}x{alt}px, {variedade} bytes distintos"
    linha["print_ok"] = variedade >= MIN_BYTES_DISTINTOS and larg > 50 and alt > 20
    if not linha["print_ok"]:
        linha["detalhe"] += "  <-- PRINT VAZIO/CHAPADO"
    return linha


def main() -> int:
    total = int(sys.argv[1]) if len(sys.argv) > 1 else len(ROTAS)
    print(f"Jadlog - {total} cotacoes seguidas, conferindo o print de cada uma\n")

    linhas = [rodada(i + 1, ROTAS[i % len(ROTAS)]) for i in range(total)]

    print(f"\n{'#':>2}  {'rota':<38} {'seg':>5}  {'valor':>10}  print")
    print("-" * 86)
    for l in linhas:
        valor = f"R$ {l['valor']}" if l["valor"] is not None else l["status"]
        marca = "OK   " if l["print_ok"] else "FALHA"
        print(f"{l['n']:>2}  {l['rota']:<38} {l['seg']:>5.1f}  {valor:>10}  "
              f"{marca} {l['detalhe']}")
        if l["recusa"]:
            print(f"     recusa: {l['recusa']}")
        if l["erro"]:
            print(f"     erro: {l['erro']}")

    respondidas = sum(l["status"] in ("cotado", "recusado") for l in linhas)
    prints = sum(l["print_ok"] for l in linhas)
    valores = {str(l["valor"]) for l in linhas if l["valor"] is not None}

    print(f"\nresponderam:      {respondidas}/{total}")
    print(f"prints nao-vazios:{prints}/{total}  (nao garante que estao corretos)")
    print(f"valores distintos: {len(valores)} -> {sorted(valores)}")
    if len(valores) == 1 and len([l for l in linhas if l["valor"]]) > 1:
        print("  ATENCAO: valor identico em rotas diferentes - tela nao atualizou?")

    ok = respondidas == total and prints == total
    print("\n" + ("TUDO OK" if ok else "TEM FALHA - ver linhas marcadas acima"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
