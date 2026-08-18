"""Roda 3 cotações em CADA transportadora e salva print de todas.

    python tests/manuais/testar_tudo.py teste1.txt

Serve para validar um ambiente novo (servidor, outra máquina). Cada rodada
grava em teste_real/<transportadora>/<timestamp>/.

Roda TUDO em dry-run: preenche, printa e para. Nenhuma cotação entra na fila
de um vendedor. Para envio real existem os scripts próprios de cada uma.
"""

from __future__ import annotations

import platform
import sys
import time
import traceback
from decimal import Decimal
from pathlib import Path

# Estes scripts moram em tests/manuais/, mas importam carriers/, core/ e web/,
# que so existem na RAIZ. `python tests/manuais/testar_x.py` poe tests/manuais
# no sys.path -- a raiz, nao. Sem esta linha, ImportError logo no primeiro
# import, sem chegar a rodar nada.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MIN_PYTHON = (3, 10)


def checar_ambiente() -> list[str]:
    """Avisa ANTES de instalar 400 MB de navegador.

    Python 3.10+ exige Windows 8.1+; o Chromium do Playwright exige Windows
    10+ (o Chrome 109, de 2023, foi o último a rodar no 7). Num Windows 7
    isto não é questão de configuração — é incompatibilidade de binário."""
    problemas = []
    if sys.version_info < MIN_PYTHON:
        problemas.append(
            f"Python {'.'.join(map(str, sys.version_info[:3]))} e antigo demais; "
            f"o projeto precisa de {'.'.join(map(str, MIN_PYTHON))}+")
    if platform.system() == "Windows":
        try:
            if int(platform.version().split(".")[0]) < 10:
                problemas.append(
                    f"Windows versao {platform.version()} — o Chromium do "
                    f"Playwright precisa de Windows 10 ou mais novo")
        except (ValueError, IndexError):
            pass
    return problemas


def cabecalho() -> None:
    print("=" * 72)
    print("COTAFRETE — teste de ambiente")
    print("=" * 72)
    print(f"  Python  : {sys.version.split()[0]}")
    print(f"  Sistema : {platform.system()} {platform.release()} "
          f"({platform.version()})")
    print(f"  Maquina : {platform.machine()}")
    print()

    problemas = checar_ambiente()
    if problemas:
        print("  !! ESTE AMBIENTE NAO SUPORTA O PROJETO:")
        for p in problemas:
            print(f"     - {p}")
        print()
        print("  Pode continuar para ver onde quebra, mas o resultado")
        print("  esperado e falha ao abrir o navegador.")
        print()


# Tres por transportadora: leve, media, pesada. Cargas diferentes de
# proposito — repetir a mesma tres vezes testaria cache, nao o adapter.
CARGAS = [
    ("leve 1 kg 30x30x30",   Decimal(1),  (30, 30, 30), Decimal("568.77")),
    ("media 5 kg 50x40x30",  Decimal(5),  (50, 40, 30), Decimal("2350.50")),
    ("pesada 25 kg 80x60x50", Decimal(25), (80, 60, 50), Decimal("4100.00")),
]


def variar(base, peso, medidas, valor):
    from core.models import NotaFiscal, Volume
    comp, larg, alt = medidas
    return base.model_copy(update={
        "volumes": [Volume(qtd=1, comprimento_cm=Decimal(comp),
                           largura_cm=Decimal(larg), altura_cm=Decimal(alt),
                           peso_kg=peso)],
        "nota_fiscal": NotaFiscal(valor_total=valor),
    })


def main() -> int:
    cabecalho()

    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
        from carriers.camilo.adapter import CamiloAdapter
        from carriers.dellavolpe.adapter import DellavolpeAdapter
        from carriers.generoso.adapter import GenerosoAdapter
        from carriers.jadlog.painel import JadlogPainelAdapter
        from core import cep
        from core.ficha import ler_ficha
        from core.models import StatusCotacao
    except Exception as exc:
        print(f"  !! Falhou ao importar o projeto: {type(exc).__name__}: {exc}")
        print("     Rode antes:  pip install -r requirements.txt")
        return 1

    try:
        base = ler_ficha(Path(sys.argv[1]).read_text(encoding="utf-8"),
                         buscar_cep=cep.buscar)
    except Exception as exc:
        print(f"  !! Falhou ao ler a ficha: {type(exc).__name__}: {exc}")
        return 1

    print(f"  Rota    : {base.origem.cidade}/{base.origem.uf} -> "
          f"{base.destino.cidade}/{base.destino.uf}")
    print(f"  Material: {base.mercadoria.tipo_material}")
    print()

    alvos = [
        ("Camilo (SSW)", CamiloAdapter()),
        ("Jadlog painel", JadlogPainelAdapter()),
        ("Generoso", GenerosoAdapter()),
        ("Della Volpe", DellavolpeAdapter()),
    ]

    linhas = []
    for nome, adapter in alvos:
        print(f"--- {nome} " + "-" * max(4, 58 - len(nome)))
        for rotulo, peso, medidas, valor in CARGAS:
            req = variar(base, peso, medidas, valor)
            inicio = time.monotonic()
            try:
                res = adapter.cotar(req)      # dry-run: sem confirmar_envio
                seg = time.monotonic() - inicio
                if res.valor_frete is not None:
                    desfecho = f"R$ {res.valor_frete}"
                elif res.status is StatusCotacao.RASCUNHO:
                    desfecho = "preenchido (dry-run)"
                else:
                    desfecho = (res.erro or res.status.value)[:50]
                evid = (Path(res.evidencias[-1]).as_posix()
                        if res.evidencias else "sem print")
                ok = res.status in (StatusCotacao.COTADO,
                                    StatusCotacao.RASCUNHO,
                                    StatusCotacao.RECUSADO)
            except Exception as exc:
                seg = time.monotonic() - inicio
                desfecho = f"EXCECAO {type(exc).__name__}: {exc}"[:50]
                evid, ok = "sem print", False
                traceback.print_exc(limit=2)

            print(f"  {'ok   ' if ok else 'FALHA'} {rotulo:<22} {seg:>6.1f}s  "
                  f"{desfecho:<34} {evid}")
            linhas.append((nome, ok))
        print()

    print("=" * 72)
    bons = sum(1 for _, ok in linhas if ok)
    print(f"RESULTADO: {bons}/{len(linhas)} rodaram sem falha")
    for nome in dict.fromkeys(n for n, _ in linhas):
        do_alvo = [ok for n, ok in linhas if n == nome]
        print(f"  {nome:<18} {sum(do_alvo)}/{len(do_alvo)}")
    print()
    print("Prints em teste_real/ — mande a pasta inteira para conferencia.")
    print("=" * 72)
    return 0 if bons == len(linhas) else 1


if __name__ == "__main__":
    raise SystemExit(main())
