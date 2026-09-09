"""A faxina de prints velhos (core.evidencias.limpar_antigas) precisa apagar
só o que passou da retenção e nunca a pasta mais recente — é ela que a tela
da cotação de ontem ainda está lendo."""

from __future__ import annotations

import os
import time
from pathlib import Path

from core.evidencias import limpar_antigas

UM_DIA_S = 86400


def _pasta_com_idade(raiz, transportadora, nome, dias_atras):
    pasta = raiz / transportadora / nome
    pasta.mkdir(parents=True)
    (pasta / "resultado.png").write_bytes(b"x")
    idade = time.time() - dias_atras * UM_DIA_S
    os.utime(pasta, (idade, idade))
    return pasta


def test_apaga_so_pasta_mais_velha_que_a_retencao(tmp_path):
    velha = _pasta_com_idade(tmp_path, "braspress", "20260101-000000", 40)
    recente = _pasta_com_idade(tmp_path, "braspress", "20260908-000000", 1)

    apagadas = limpar_antigas(raiz=tmp_path, dias=30)

    assert apagadas == 1
    assert not velha.exists()
    assert recente.exists()


def test_raiz_ausente_nao_apaga_nada_nem_estoura():
    assert limpar_antigas(raiz=Path("pasta_que_nao_existe_de_verdade")) == 0
