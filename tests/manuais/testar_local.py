#!/usr/bin/env python3
"""Teste end-to-end contra o MOCK local. Nada sai para a internet.

    # terminal 1
    uvicorn mock.server:app --port 8099
    # terminal 2
    python tests/manuais/testar_local.py            # headless
    python tests/manuais/testar_local.py --headed   # ver o browser preenchendo

Ele preenche o formulário replicado, envia, e compara campo a campo o que o
servidor recebeu com o que o payload dizia que deveria ser enviado.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path

# Estes scripts moram em tests/manuais/, mas importam carriers/, core/ e web/,
# que so existem na RAIZ. `python tests/manuais/testar_x.py` poe tests/manuais
# no sys.path -- a raiz, nao. Sem esta linha, ImportError logo no primeiro
# import, sem chegar a rodar nada.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from carriers.dellavolpe import mapping as m
from carriers.dellavolpe.adapter import DellavolpeAdapter
from core.models import (
    TipoFrete,
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, Volume,
)

MOCK = "http://localhost:8099"

# name= do mock  ->  rótulo do payload
DE_PARA = {
    "nome": "Nome completo",
    "email": "E-mail",
    "whatsapp": "WhatsApp",
    "servico": "Qual o serviço que você procura?",
    "cnpj_remetente": "CNPJ - Remetente",
    "uf_origem": "Selecione o estado de origem",
    "cidade_origem": "Selecione a cidade de origem",
    "cnpj_destinatario": "CNPJ - Destinatário",
    "uf_destino": "Selecione o estado de destino",
    "cidade_destino": "Selecione a cidade de destino",
    "peso_total": "Peso total",
    "quantidade_volumes": "Quantidade de Volumes",
    "comprimento": "Comprimento",
    "largura": "Largura",
    "altura": "Altura",
    "valor_nf": "Valor total da nota fiscal",
    "tipo_material": "Tipo de Material que será transportado",
    "cnpj_pagador": "CNPJ da empresa que pagará o frete",
}


def carga_exemplo() -> CotacaoRequest:
    """Dois grupos de volumes com medidas diferentes: exercita a planilha."""
    return CotacaoRequest(
        solicitante=Solicitante(nome="Enzo Teste", email="enzo@exemplo.com.br",
                                whatsapp="27999887766"),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf="ES", cidade="Vitória"),
        destino=Local(uf="SP", cidade="São Paulo"),
        remetente=Parte(cnpj="11.222.333/0001-81"),
        destinatario=Parte(cnpj="45.723.174/0001-10"),
        tipo_frete=TipoFrete.CIF,
        volumes=[
            Volume(qtd=3, comprimento_cm=Decimal(100), largura_cm=Decimal(50),
                   altura_cm=Decimal(40), peso_kg=Decimal(10), descricao="Caixas"),
            Volume(qtd=1, comprimento_cm=Decimal(80), largura_cm=Decimal(40),
                   altura_cm=Decimal(30), peso_kg=Decimal(8), descricao="Pallet"),
        ],
        mercadoria=Mercadoria(tipo_material="Peças metálicas"),
        nota_fiscal=NotaFiscal(valor_total=Decimal(25_000)),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    req = carga_exemplo()
    esperado = m.campos_do_formulario(m.preparar_payload(req))

    print("── carga ────────────────────────────────────")
    print(f"  peso total .......... {req.peso_total_kg} kg")
    print(f"  volumes ............. {req.quantidade_volumes}")
    print(f"  cubagem ............. {req.cubagem_m3} m³")
    print(f"  medidas distintas ... {req.tem_medidas_distintas}")

    print("\n── validação ────────────────────────────────")
    for e in m.validar(req):
        print(f"  [{e.severidade.value}] {e.campo}: {e.mensagem}")

    print("\n── enviando ao mock ─────────────────────────")
    adapter = DellavolpeAdapter(base_url=MOCK, headless=not args.headed)
    res = adapter.cotar(req, confirmar_envio=True)   # seguro: é o mock
    print(f"  status: {res.status.value}")
    print(f"  valor:  {res.valor_frete}   <- None é o correto aqui")
    if res.erro:
        print(f"  erro:   {res.erro}")
        return 1

    print("\n── conferência campo a campo ────────────────")
    with urllib.request.urlopen(f"{MOCK}/ultimo-envio") as r:
        recebido = json.load(r)
    campos, arquivos = recebido["campos"], recebido["arquivos"]

    falhas = 0
    for name, rotulo in DE_PARA.items():
        obtido, quero = campos.get(name, ""), esperado.get(rotulo, "")
        ok = obtido == quero
        falhas += not ok
        print(f"  {'✓' if ok else '✗'} {rotulo:<40} {obtido!r}"
              + ("" if ok else f"   ESPERADO {quero!r}"))

    tem_planilha = bool(arquivos.get("planilha"))
    print(f"  {'✓' if tem_planilha else '✗'} planilha de volumes anexada"
          f"                {arquivos.get('planilha')}")
    falhas += not tem_planilha

    print("\n" + ("✔ tudo conferido" if not falhas else f"✗ {falhas} divergência(s)"))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
