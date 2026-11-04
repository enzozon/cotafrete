import subprocess

import pytest

from orcamento.config import config_do_ambiente


def test_config_do_ambiente_le_as_chaves_do_dav():
    cfg = config_do_ambiente({"HSE_USUARIO": "u", "HSE_SENHA": "segredo-xyz"})
    assert (cfg.usuario, cfg.client_id, cfg.dry_run, cfg.headless, cfg.ia, cfg.pasta) == \
           ("u", "ventura", True, True, "desligada", None)
    assert "segredo-xyz" not in repr(cfg)


def test_config_sem_senha_recusa():
    with pytest.raises(ValueError, match="HSE_SENHA"):
        config_do_ambiente({"HSE_USUARIO": "u"})


def test_ia_claude_cli_vira_desligada(monkeypatch):
    # nenhuma chamada externa: o servidor não tem o Claude Code
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("chamou o claude"))
    cfg = config_do_ambiente({"HSE_USUARIO": "u", "HSE_SENHA": "s", "IA": "claude_cli"})
    assert cfg.ia == "desligada"


def test_config_le_ia_api_e_chaves():
    cfg = config_do_ambiente({"HSE_USUARIO": "u", "HSE_SENHA": "s", "IA": "API", "IA_MODELO": "m",
                              "ANTHROPIC_API_KEY": "chave-abc", "DAV_DRY_RUN": "0", "DAV_HEADLESS": "0",
                              "HSE_CLIENT_ID": "x"})
    assert (cfg.ia, cfg.ia_modelo, cfg.ia_chave, cfg.dry_run, cfg.headless, cfg.client_id) == \
           ("api", "m", "chave-abc", False, False, "x")
    assert "chave-abc" not in repr(cfg)


def test_limite_diario_da_ia():
    base = {"HSE_USUARIO": "u", "HSE_SENHA": "s"}
    assert config_do_ambiente(base).ia_limite_dia == 0.30
    assert config_do_ambiente({**base, "IA_LIMITE_DIA_USD": "0,50"}).ia_limite_dia == 0.50
    assert config_do_ambiente({**base, "IA_LIMITE_DIA_USD": "muito"}).ia_limite_dia == 0.30
