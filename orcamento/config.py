"""Configuração do robô de orçamentos, lida das variáveis de ambiente (o .env do Cotafrete)."""
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

PASTA_PROGRAMA = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    usuario: str
    senha: str = field(repr=False)
    client_id: str
    dry_run: bool
    headless: bool
    pasta: Path | None = None          # só o modo pasta usa
    intervalo_min: int = 5
    pasta_programa: Path = PASTA_PROGRAMA
    ia: str = "desligada"              # desligada | api
    ia_modelo: str = "claude-haiku-5-5"
    ia_chave: str = field(default="", repr=False)  # ANTHROPIC_API_KEY, só para IA=api


def _bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "sim", "s", "yes")


def config_do_ambiente(ambiente: Mapping[str, str] | None = None) -> Config:
    env = os.environ if ambiente is None else ambiente

    def get(chave: str, padrao: str = "") -> str:
        return (env.get(chave) or padrao).strip()

    faltando = [k for k in ("HSE_USUARIO", "HSE_SENHA") if not get(k)]
    if faltando:
        raise ValueError(f"Faltam no .env: {', '.join(faltando)}")
    ia = get("IA", "desligada").lower()
    return Config(
        usuario=get("HSE_USUARIO"),
        senha=get("HSE_SENHA"),
        client_id=get("HSE_CLIENT_ID", "ventura"),
        dry_run=_bool(get("DAV_DRY_RUN", "1")),
        headless=_bool(get("DAV_HEADLESS", "1")),
        ia="api" if ia == "api" else "desligada",
        ia_modelo=get("IA_MODELO", "claude-haiku-5-5"),
        ia_chave=get("ANTHROPIC_API_KEY"),
    )
