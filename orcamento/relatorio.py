"""Monta o .txt que acompanha cada planilha processada."""
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from orcamento.planilha import Item


def moeda(v: Decimal) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _pct(v: Decimal) -> str:
    return f"{v.normalize():f}".replace(".", ",") + "%"


def _detalhe(item: Item) -> str:
    return (f"{item.descricao_cadastro} | NCM {item.ncm} | Origem {item.origem} | "
            f"ICMS {_pct(item.icms)} | custo {moeda(item.custo)} | "
            f"grupo {item.grupo} | marca {item.marca}")


class Relatorio:
    def __init__(self, arquivo: str, dry_run: bool, agora: datetime | None = None):
        self.arquivo = arquivo
        self.dry_run = dry_run
        self.agora = agora or datetime.now()
        self.resultado = ""
        self._itens: list[str] = []
        self._infos: list[str] = []
        self._erros: list[str] = []

    @property
    def tem_erro(self) -> bool:
        return bool(self._erros)

    def item_existente(self, n: int, codigo: str, descricao: str, por: str) -> None:
        como = {"codigo": "pelo código informado", "descricao": "encontrado pela descrição"}.get(por, por)
        self._itens.append(f"Item {n}: usou produto existente {codigo} - {descricao} ({como})")

    def item_cadastrado(self, n: int, codigo: str, item: Item) -> None:
        self._itens.append(f"Item {n}: CADASTROU produto novo {codigo} - {_detalhe(item)}")

    def item_cadastraria(self, n: int, item: Item) -> None:
        self._itens.append(f"Item {n}: [DRY_RUN] cadastraria produto novo - {_detalhe(item)}")

    def item_novo_pendente(self, n: int, item: Item) -> None:
        self._itens.append(f"Item {n}: produto novo NÃO cadastrado (planilha com erro) - {_detalhe(item)}")

    def item_erro(self, n: int, motivo: str) -> None:
        self._itens.append(f"Item {n}: ERRO - {motivo}")
        self._erros.append(f"Item {n}: {motivo}")

    def info(self, txt: str) -> None:
        self._infos.append(txt)

    def erro(self, txt: str) -> None:
        self._erros.append(txt)

    def texto(self) -> str:
        modo = "DRY_RUN (simulação, nada foi salvo no HSE)" if self.dry_run else "REAL"
        partes = [
            "Robô de Orçamentos HSE",
            f"Arquivo: {self.arquivo}",
            f"Data: {self.agora:%d/%m/%Y %H:%M}",
            f"Modo: {modo}",
            f"Resultado: {self.resultado}",
            "",
            "Itens:",
            *self._itens,
        ]
        if self._infos:
            partes += ["", "Detalhes:", *self._infos]
        if self._erros:
            partes += ["", "Erros:", *(f"ERRO: {e}" for e in self._erros)]
        return "\n".join(partes) + "\n"

    def gravar(self, destino: Path) -> Path:
        destino.write_text(self.texto(), encoding="utf-8-sig")  # BOM: acentos certos no Bloco de Notas
        return destino
