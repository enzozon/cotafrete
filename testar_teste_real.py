"""Cota uma ficha real na Jadlog e (com autorização) na Della Volpe.

    python testar_teste_real.py C:/Users/vendas12/Desktop/teste.txt
    python testar_teste_real.py ficha.txt --dellavolpe    # ENVIO REAL

Roda a carga da ficha e mais 5 variações, para ver se o formulário da Della
Volpe barra várias cotações em sequência.

⚠ `--dellavolpe` ENVIA de verdade: cada envio vira uma cotação na fila de um
vendedor. Além do flag, exige DV_ENVIO_REAL_AUTORIZADO=sim no ambiente — trava
do próprio adapter, e quem define essa variável é o Enzo, não este script.

Evidências:
    teste_real/jadlog/<timestamp>/      print da tela com o valor
    teste_real/dellavolpe/<timestamp>/  print do formulário enviado
"""

from __future__ import annotations

import os
import sys
import time
from decimal import Decimal
from pathlib import Path

from carriers.dellavolpe.adapter import DellavolpeAdapter
from carriers.jadlog.simulador import JadlogSimuladorAdapter
from core.ficha import ler_ficha
from core.models import CotacaoRequest, NotaFiscal, StatusCotacao, Volume

RAIZ = Path("teste_real")
PASTA_JADLOG = RAIZ / "jadlog"
PASTA_DELLAVOLPE = RAIZ / "dellavolpe"

# 5 cargas diferentes da ficha, para o teste de rajada. Rota e e-mail ficam
# iguais de propósito: o que está sendo testado é o volume de envios, não a
# variedade de destino.
VARIACOES = [
    ("2 kg, 40x30x20",   Decimal(2),     (40, 30, 20), Decimal("1200.00")),
    ("5 kg, 50x40x30",   Decimal(5),     (50, 40, 30), Decimal("2350.50")),
    ("12 kg, 60x40x40",  Decimal(12),    (60, 40, 40), Decimal("890.00")),
    ("0,5 kg, 20x15x10", Decimal("0.5"), (20, 15, 10), Decimal("320.90")),
    ("25 kg, 80x60x50",  Decimal(25),    (80, 60, 50), Decimal("4100.00")),
]

# Espera entre envios à Della Volpe. Disparar 6 POSTs em 30s é o jeito mais
# rápido de ser barrado por rate limit — e aí o teste mede o nosso robô, não
# o comportamento normal do site.
PAUSA_ENTRE_ENVIOS_S = 45


def variar(req: CotacaoRequest, peso: Decimal, medidas: tuple[int, int, int],
           valor_nf: Decimal) -> CotacaoRequest:
    comp, larg, alt = medidas
    return req.model_copy(update={
        "volumes": [Volume(qtd=1, comprimento_cm=Decimal(comp),
                           largura_cm=Decimal(larg), altura_cm=Decimal(alt),
                           peso_kg=peso)],
        "nota_fiscal": NotaFiscal(valor_total=valor_nf),
    })


def linha_resultado(rotulo: str, res, seg: float) -> str:
    if res.status is StatusCotacao.COTADO and res.valor_frete is not None:
        desfecho = f"R$ {res.valor_frete}"
    elif res.motivo_recusa:
        desfecho = f"recusado: {res.motivo_recusa}"
    elif res.erro:
        desfecho = f"ERRO: {res.erro[:70]}"
    else:
        desfecho = res.status.value
    evid = Path(res.evidencias[0]).as_posix() if res.evidencias else "-"
    return f"  {rotulo:<22} {seg:>5.1f}s  {desfecho:<38} {evid}"


def cotar(adapter, req, rotulo: str, **kwargs):
    inicio = time.monotonic()
    res = adapter.cotar(req, **kwargs)
    print(linha_resultado(rotulo, res, time.monotonic() - inicio))
    return res


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    ficha = Path(sys.argv[1]).read_text(encoding="utf-8")
    enviar_dv = "--dellavolpe" in sys.argv
    req = ler_ficha(ficha)

    PASTA_JADLOG.mkdir(parents=True, exist_ok=True)
    PASTA_DELLAVOLPE.mkdir(parents=True, exist_ok=True)

    print(f"\nFicha: {req.origem.cidade}/{req.origem.uf} ({req.origem.cep})"
          f" -> {req.destino.cidade}/{req.destino.uf} ({req.destino.cep})")
    print(f"Carga: {req.peso_total_kg} kg, {req.quantidade_volumes} volume(s),"
          f" NF R$ {req.nota_fiscal.valor_total}, {req.mercadoria.tipo_material}")
    print(f"E-mail de retorno: {req.solicitante.email}")

    if enviar_dv and os.getenv("DV_ENVIO_REAL_AUTORIZADO") != "sim":
        print("\nDV_ENVIO_REAL_AUTORIZADO nao esta 'sim' — a Della Volpe vai "
              "ser pulada.\n  Defina no terminal antes de rodar com --dellavolpe.")
        enviar_dv = False

    casos = [("ficha original", req)]
    casos += [(nome, variar(req, peso, medidas, valor))
              for nome, peso, medidas, valor in VARIACOES]

    print(f"\n--- Jadlog ({len(casos)} cotacoes) ---")
    jadlog = JadlogSimuladorAdapter(workdir=str(PASTA_JADLOG))
    por_jadlog = [cotar(jadlog, r, nome) for nome, r in casos]

    por_dv = []
    if enviar_dv:
        print(f"\n--- Della Volpe: {len(casos)} ENVIOS REAIS "
              f"({PAUSA_ENTRE_ENVIOS_S}s entre eles) ---")
        dv = DellavolpeAdapter(workdir=str(PASTA_DELLAVOLPE))
        for i, (nome, r) in enumerate(casos):
            if i:
                time.sleep(PAUSA_ENTRE_ENVIOS_S)
            por_dv.append(cotar(dv, r, nome, confirmar_envio=True))
    else:
        print("\n--- Della Volpe: PULADA (nenhum envio real) ---")

    cotadas = sum(r.status is StatusCotacao.COTADO for r in por_jadlog)
    print(f"\nJadlog: {cotadas}/{len(casos)} com valor")
    if por_dv:
        ok = sum(r.status is not StatusCotacao.ERRO for r in por_dv)
        print(f"Della Volpe: {ok}/{len(por_dv)} enviadas sem erro — "
              f"confira a caixa de {req.solicitante.email}, inclusive o spam")
    print(f"\nEvidencias em {RAIZ.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
