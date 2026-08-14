"""Cinco cotações REAIS no Generoso, a partir de uma ficha.

    python testar_generoso_real.py teste1.txt

⚠ ENVIA de verdade: cada uma vira uma cotação na fila de um vendedor. O preço
volta por e-mail, como na Della Volpe.

Cargas diferentes de propósito: repetir a mesma cinco vezes testaria o
formulário, não o comportamento da transportadora.
"""

from __future__ import annotations

import sys
import time
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

from carriers.generoso.adapter import GenerosoAdapter
from core import cep
from core.ficha import ler_ficha
from core.models import CotacaoRequest, NotaFiscal, StatusCotacao, Volume

# Espaçamento entre envios. Cinco POSTs em um minuto é o jeito mais rápido de
# ser tratado como robô — e aí o teste mede a nossa pressa, não o site.
PAUSA_S = 45

VARIACOES = [
    ("1 kg, 30x30x30",  Decimal(1),  (30, 30, 30), Decimal("568.77")),
    ("2 kg, 40x30x20",  Decimal(2),  (40, 30, 20), Decimal("1200.00")),
    ("5 kg, 50x40x30",  Decimal(5),  (50, 40, 30), Decimal("2350.50")),
    ("12 kg, 60x40x40", Decimal(12), (60, 40, 40), Decimal("890.00")),
    ("25 kg, 80x60x50", Decimal(25), (80, 60, 50), Decimal("4100.00")),
]


def variar(req: CotacaoRequest, peso: Decimal,
           medidas: tuple[int, int, int], valor: Decimal) -> CotacaoRequest:
    comp, larg, alt = medidas
    return req.model_copy(update={
        "volumes": [Volume(qtd=1, comprimento_cm=Decimal(comp),
                           largura_cm=Decimal(larg), altura_cm=Decimal(alt),
                           peso_kg=peso)],
        "nota_fiscal": NotaFiscal(valor_total=valor),
    })


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    ficha = Path(sys.argv[1]).read_text(encoding="utf-8")
    base = ler_ficha(ficha, buscar_cep=cep.buscar)
    adapter = GenerosoAdapter()

    print(f"\nGeneroso — 5 ENVIOS REAIS ({PAUSA_S}s entre eles)")
    print(f"origem {base.origem.cep} -> destino {base.destino.cep}")
    print(f"material: {base.mercadoria.tipo_material}")
    print(f"retorno por e-mail para: {base.solicitante.email}\n")

    resultados = []
    for i, (nome, peso, medidas, valor) in enumerate(VARIACOES):
        if i:
            time.sleep(PAUSA_S)
        inicio = time.monotonic()
        res = adapter.cotar(variar(base, peso, medidas, valor),
                            confirmar_envio=True)
        seg = time.monotonic() - inicio
        desfecho = (res.status.value if not res.erro
                    else f"{res.status.value} - {res.erro[:80]}")
        evid = (Path(res.evidencias[-1]).parent.as_posix()
                if res.evidencias else "-")
        print(f"  {nome:<18} {seg:>5.1f}s  {desfecho:<45} {evid}")
        resultados.append(res)

    ok = sum(r.status is StatusCotacao.AGUARDANDO_RETORNO for r in resultados)
    print(f"\nconfirmadas pelo site: {ok}/{len(VARIACOES)}")
    print(f"confira a caixa de {base.solicitante.email}, inclusive o spam")
    return 0 if ok == len(VARIACOES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
