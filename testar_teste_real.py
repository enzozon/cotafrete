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

from dotenv import load_dotenv

from carriers.dellavolpe.adapter import DellavolpeAdapter
from carriers.jadlog.painel import JadlogPainelAdapter
from core import cep
from core.ficha import ler_ficha, ler_modalidade
from core.models import CotacaoRequest, NotaFiscal, StatusCotacao, Volume

# Carrega o .env ANTES de qualquer adapter ler os.getenv. Sem isto o arquivo é
# decorativo: DV_ENVIO_REAL_AUTORIZADO=sim no .env não chega no processo e o
# adapter recusa o envio real, dando a impressão de que a trava está com
# defeito. `override=False`: variável setada no terminal ganha do arquivo.
load_dotenv(override=False)

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
    so_dv = "--so-dellavolpe" in sys.argv
    # cidade e UF saem do CEP: é o CEP que a transportadora usa para calcular
    req = ler_ficha(ficha, buscar_cep=cep.buscar)
    # Lida para validar o que veio na ficha, mas a calculadora do painel NÃO
    # tem seletor de modalidade: ela devolve todas (Express, Standard...) na
    # tela de resultado. Vira filtro de leitura, não campo de preenchimento.
    modalidade = ler_modalidade(ficha)

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

    casos = [] if "--sem-original" in sys.argv else [("ficha original", req)]
    casos += [(nome, variar(req, peso, medidas, valor))
              for nome, peso, medidas, valor in VARIACOES]

    por_jadlog = []
    if so_dv:
        print("\n--- Jadlog: PULADA (--so-dellavolpe) ---")
    else:
        # UM cálculo por volume: a calculadora do painel cota um pacote de
        # cada vez. Somar os N no fim dá o frete da carga inteira.
        jadlog = JadlogPainelAdapter(workdir=str(PASTA_JADLOG))
        volumes = req.quantidade_volumes
        print(f"\n--- Jadlog painel ({len(casos)} cargas x {volumes} volume(s) "
              f"= {len(casos) * volumes} calculos) ---")
        for nome, r in casos:
            do_lote = []
            for i in range(r.quantidade_volumes):
                do_lote.append(cotar(jadlog, r,
                                     f"{nome} vol {i + 1}/{r.quantidade_volumes}"))
            por_jadlog += do_lote
            valores = [x.valor_frete for x in do_lote if x.valor_frete]
            if len(do_lote) > 1 and valores:
                print(f"  {'-> total da carga':<22} {'':>5}   "
                      f"R$ {sum(valores)}")

    # Sem autorização a Della Volpe roda em DRY-RUN: preenche o formulário
    # inteiro, printa e para antes do submit. Prova que a ficha virou os campos
    # certos, sem gerar cotação na fila de ninguém.
    dv = DellavolpeAdapter(workdir=str(PASTA_DELLAVOLPE))
    if "--so-jadlog" in sys.argv:
        print("\n--- Della Volpe: PULADA (--so-jadlog) ---")
        por_dv = []
    elif enviar_dv:
        print(f"\n--- Della Volpe: {len(casos)} ENVIOS REAIS "
              f"({PAUSA_ENTRE_ENVIOS_S}s entre eles) ---")
        por_dv = []
        for i, (nome, r) in enumerate(casos):
            if i:
                time.sleep(PAUSA_ENTRE_ENVIOS_S)
            por_dv.append(cotar(dv, r, nome, confirmar_envio=True))
    else:
        print("\n--- Della Volpe: DRY-RUN, nada e enviado ---")
        por_dv = [cotar(dv, req, "ficha original")]

    if por_jadlog:
        cotadas = sum(r.status is StatusCotacao.COTADO for r in por_jadlog)
        print(f"\nJadlog: {cotadas}/{len(casos)} com valor")
    ok = sum(r.status is not StatusCotacao.ERRO for r in por_dv)
    if enviar_dv:
        print(f"Della Volpe: {ok}/{len(por_dv)} enviadas sem erro — "
              f"confira a caixa de {req.solicitante.email}, inclusive o spam")
    else:
        print(f"Della Volpe: {ok}/{len(por_dv)} preenchidas (dry-run)")
    print(f"\nEvidencias em {RAIZ.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
