#!/usr/bin/env python3
"""Teste end-to-end da Jadlog contra o MOCK local. Nada sai para a internet.

    # terminal 1
    uvicorn mock.jadlog_server:app --port 8098
    # terminal 2
    python tests/manuais/testar_jadlog_local.py

Confere as quatro coisas que precisam ser verdade numa cotação síncrona:
status COTADO, valor > 0, prazo preenchido, e o `peso` que chegou na API igual
ao MAIOR entre peso real e peso cubado (regra explícita da doc da Jadlog —
mandar o real numa carga volumosa subcota o frete em silêncio).

Roda dois cenários de propósito: um em que o cubado vence e outro em que o real
vence. Um teste só com carga volumosa passaria mesmo se o código mandasse
sempre o cubado.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

# Estes scripts moram em tests/manuais/, mas importam carriers/, core/ e web/,
# que so existem na RAIZ. `python tests/manuais/testar_x.py` poe tests/manuais
# no sys.path -- a raiz, nao. Sem esta linha, ImportError logo no primeiro
# import, sem chegar a rodar nada.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx

from carriers.jadlog import mapping as j
from carriers.jadlog.adapter import JadlogAdapter
from core.models import (
    TipoFrete,
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, StatusCotacao, Volume,
)

MOCK = "http://localhost:8098"
URL_FRETE = f"{MOCK}/embarcador/api/frete/valor"
TOKEN = "TOKEN-DE-TESTE"          # o mock só aceita este


def montar(volumes: list[Volume]) -> CotacaoRequest:
    return CotacaoRequest(
        solicitante=Solicitante(nome="Enzo Teste", email="enzo@exemplo.com.br",
                                whatsapp="27999887766"),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf="ES", cidade="Vitória", cep="29010-000"),
        destino=Local(uf="SP", cidade="São Paulo", cep="01310-100"),
        remetente=Parte(cnpj="11.222.333/0001-81"),
        destinatario=Parte(cnpj="45.723.174/0001-10"),
        tipo_frete=TipoFrete.CIF,
        volumes=volumes,
        mercadoria=Mercadoria(tipo_material="Eletrônicos"),
        nota_fiscal=NotaFiscal(valor_total=Decimal(1_500)),
    )


# 0,24 m³ com 4 kg -> cubado 72 kg vence; 30³ cm com 25 kg -> real vence
CENARIOS = {
    "volumosa (cubado deve vencer)": [
        Volume(qtd=1, comprimento_cm=Decimal(80), largura_cm=Decimal(60),
               altura_cm=Decimal(50), peso_kg=Decimal(4), descricao="Caixa leve"),
    ],
    "densa (real deve vencer)": [
        Volume(qtd=1, comprimento_cm=Decimal(30), largura_cm=Decimal(30),
               altura_cm=Decimal(30), peso_kg=Decimal(25), descricao="Bloco"),
    ],
}


def conferir(nome: str, volumes: list[Volume]) -> int:
    req = montar(volumes)
    real = req.peso_total_kg
    cubado = req.peso_cubado_kg(j.FATOR_CUBAGEM)
    esperado = max(real, cubado)

    print(f"\n── {nome} ".ljust(60, "─"))
    print(f"  cubagem ......... {req.cubagem_m3} m³")
    print(f"  peso real ....... {real} kg")
    print(f"  peso cubado ..... {cubado} kg  (fator {j.FATOR_CUBAGEM})")
    print(f"  deve ir p/ API .. {esperado} kg")

    res = JadlogAdapter(token=TOKEN, base_url=URL_FRETE).cotar(req)
    enviado = httpx.get(f"{MOCK}/ultimo-payload").json()["frete"][0]

    checks = [
        ("status COTADO", res.status is StatusCotacao.COTADO, res.status.value),
        ("valor > 0", bool(res.valor_frete and res.valor_frete > 0), res.valor_frete),
        ("prazo preenchido", res.prazo_dias is not None, res.prazo_dias),
        ("peso = max(real, cubado)",
         Decimal(str(enviado["peso"])) == esperado, enviado["peso"]),
    ]

    falhas = 0
    print("  ─── conferência ───")
    for rotulo, ok, obtido in checks:
        falhas += not ok
        print(f"  {'✓' if ok else '✗'} {rotulo:<26} {obtido!r}"
              + ("" if ok else f"   ESPERADO {esperado!r}"))
    if res.erro:
        print(f"  erro do adapter: {res.erro}")
    return falhas


def main() -> int:
    falhas = sum(conferir(nome, vols) for nome, vols in CENARIOS.items())
    print("\n" + ("✔ tudo conferido" if not falhas else f"✗ {falhas} divergência(s)"))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
