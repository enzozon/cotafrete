"""Configuração comum dos testes.

Só UMA coisa aqui, e de propósito estreita: o plano B da proposta da Della
Volpe (carriers/dellavolpe/proposta_ia.py) fica DESLIGADO por padrão. Sem
isso, os testes do ingestor que usam PDF sem valor chamariam a IA de verdade
sempre que o .env tivesse chave (web/app.py carrega o .env ao ser importado).

NÃO desliga a IA em geral: core/ia.py, IA_MODELOS e as chaves ficam como
estão, porque test_ia, test_me_revisao, test_extrair_carga, test_me_ncm,
test_adm_me e test_contraste ligam a IA de propósito com provedor falso.
Quem testa o plano B religa com `monkeypatch.setattr(proposta_ia, "LIGADA", True)`.
"""

from __future__ import annotations

import pytest

from carriers.dellavolpe import proposta_ia


@pytest.fixture(autouse=True)
def _plano_b_della_volpe_desligado(monkeypatch):
    monkeypatch.setattr(proposta_ia, "LIGADA", False)
