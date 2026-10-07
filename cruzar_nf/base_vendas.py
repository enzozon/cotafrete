"""Base acumulada das vendas do HSE (vendas_hse.json).

Cada exportação do HSE cobre um período. A base junta todas: o cruzamento
usa a base INTEIRA, porque um pedido registrado hoje na planilha pode ter
sido faturado num período já sincronizado antes.

Regras:
- chave da venda = empresa + código da venda (cada empresa numera as suas);
- venda que veio de novo substitui a antiga (OC corrigida, NF emitida depois);
- a exportação manda na sua janela: venda da base com emissão DENTRO do
  período exportado que não veio no Excel novo foi cancelada/excluída e sai;
- a base guarda os períodos já cobertos (para mostrar a última sincronização
  e calcular a próxima janela).

Formato do arquivo:
    {"versao": 1, "cobertura": [["01/01/2025", "29/09/2026"]],
     "vendas": {"VENTURA MATRIZ|2635": {"Tipo": "VEN", "Código": 2635, ...}}}

Compatível com Python 3.8.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cruzar_nf.cruzar import campo, gravar_json, normalizar_nf, normalizar_oc, valor_decimal

FORMATO_DATA = "%d/%m/%Y"


def data_br(texto: Any) -> Optional[_dt.date]:
    """'29/09/2026' -> date. Aceita date/datetime. Outra coisa -> None."""
    if isinstance(texto, _dt.datetime):
        return texto.date()
    if isinstance(texto, _dt.date):
        return texto
    try:
        return _dt.datetime.strptime(str(texto).strip(), FORMATO_DATA).date()
    except ValueError:
        return None


def chave_venda(venda: Dict[str, Any]) -> str:
    empresa = " ".join(str(campo(venda, "Filial") or "").split()).upper()
    return f"{empresa}|{campo(venda, 'Código')}"


def _assinatura(venda: Dict[str, Any]) -> Tuple:
    """O que importa para o cruzamento: mudou, conta como 'alterada'."""
    return (normalizar_oc(campo(venda, "Ordem Compra")), normalizar_nf(campo(venda, "NF")),
            str(valor_decimal(campo(venda, "Total Líq.", "Total Liq"))), campo(venda, "Tipo"))


def _juntar_periodos(periodos: List[Tuple[_dt.date, _dt.date]]) -> List[Tuple[_dt.date, _dt.date]]:
    juntos: List[Tuple[_dt.date, _dt.date]] = []
    for de, ate in sorted(periodos):
        if juntos and de <= juntos[-1][1] + _dt.timedelta(days=1):
            juntos[-1] = (juntos[-1][0], max(juntos[-1][1], ate))
        else:
            juntos.append((de, ate))
    return juntos


class BaseVendas:
    def __init__(self, vendas: Optional[Dict[str, Dict[str, Any]]] = None,
                 cobertura: Optional[List[Tuple[_dt.date, _dt.date]]] = None):
        self.vendas: Dict[str, Dict[str, Any]] = dict(vendas or {})
        self.cobertura: List[Tuple[_dt.date, _dt.date]] = _juntar_periodos(list(cobertura or []))

    # -- arquivo ------------------------------------------------------------
    @classmethod
    def carregar(cls, caminho: "str | Path") -> "BaseVendas":
        caminho = Path(caminho)
        if not caminho.is_file():
            return cls()
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        cobertura = [(data_br(a), data_br(b)) for a, b in dados.get("cobertura", [])]
        return cls(dados.get("vendas", {}), [p for p in cobertura if p[0] and p[1]])

    def salvar(self, caminho: "str | Path") -> None:
        gravar_json(caminho, {
            "versao": 1,
            "atualizado_em": _dt.datetime.now().isoformat(timespec="seconds"),
            "cobertura": [[a.strftime(FORMATO_DATA), b.strftime(FORMATO_DATA)] for a, b in self.cobertura],
            "vendas": self.vendas,
        })

    # -- uso ----------------------------------------------------------------
    def lista(self) -> List[Dict[str, Any]]:
        return list(self.vendas.values())

    def ultima_data(self) -> Optional[_dt.date]:
        return self.cobertura[-1][1] if self.cobertura else None

    def mesclar(self, vendas: List[Dict[str, Any]], de: _dt.date, ate: _dt.date) -> Dict[str, int]:
        """Junta uma exportação do período [de, ate]. Devolve a estatística."""
        novas = alteradas = 0
        chaves_novas = set()
        for v in vendas:
            k = chave_venda(v)
            chaves_novas.add(k)
            antiga = self.vendas.get(k)
            if antiga is None:
                novas += 1
            elif _assinatura(antiga) != _assinatura(v):
                alteradas += 1
            self.vendas[k] = v
        removidas = 0
        for k in list(self.vendas):
            emissao = data_br(campo(self.vendas[k], "Emissão"))
            if k not in chaves_novas and emissao and de <= emissao <= ate:
                del self.vendas[k]
                removidas += 1
        self.cobertura = _juntar_periodos(self.cobertura + [(de, ate)])
        return {"recebidas": len(vendas), "novas": novas, "alteradas": alteradas,
                "removidas": removidas, "total_na_base": len(self.vendas)}
