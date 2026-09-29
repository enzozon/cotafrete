"""Cruza PEDIDOS.json com comparar.json pela ordem de compra e grava a NF.

PEDIDOS.json (a planilha da Vale) tem a ordem de compra em "PEDIDO".
comparar.json (a exportação de vendas do ERP) tem a mesma ordem em
"Ordem Compra" e a nota em "NF". O programa acha a NF de cada pedido e
grava PEDIDOS_ATUALIZADO.json: o mesmo arquivo, com "NF" no fim de cada
pedido. O PEDIDOS.json original nunca é alterado.

Junto sai o relatório da rodada (Markdown para ler, JSON para o portal):
quantos bateram, quais têm mais de uma NF, quais estão no ERP sem NF, quais
só existem de um lado, e as divergências de valor.

Só biblioteca padrão: o robô do portal Maestro importa `cruzar()` direto,
sem instalar nada. Rodar à mão: ver README.md desta pasta.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# Status de cada pedido depois do cruzamento
BATEU = "BATEU"                      # exatamente 1 NF
MAIS_DE_UMA_NF = "MAIS_DE_UMA_NF"    # a OC saiu em mais de uma nota
SEM_NF = "SEM_NF"                    # a OC está no ERP, mas a venda ainda não tem NF
NAO_ENCONTRADO = "NAO_ENCONTRADO"    # a OC não aparece no comparar.json
PEDIDO_INVALIDO = "PEDIDO_INVALIDO"  # "PEDIDO" vazio ou sem número

# Diferença de valor abaixo disso é arredondamento, não divergência
TOLERANCIA_VALOR = Decimal("0.05")

# Separador quando a OC tem mais de uma NF: "15016 / 15020"
SEPARADOR_NF = " / "


# --------------------------------------------------------------------------
# normalização
# --------------------------------------------------------------------------

def _chave_campo(nome: str) -> str:
    """'VALOR ' -> 'VALOR', 'Ordem Compra' -> 'ORDEM COMPRA', 'Total Líq.' -> 'TOTAL LIQ.'

    A planilha tem campos com espaço no fim ("VALOR ", "REQUISITANTE ") e o
    ERP tem acento. Procurar pelo nome exato quebra no primeiro espaço que
    alguém apagar na planilha.
    """
    sem_acento = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.upper().split())


def campo(registro: dict, *nomes: str) -> Any:
    """Valor do primeiro campo que existir, ignorando espaço, caixa e acento."""
    indice = {_chave_campo(k): k for k in registro}
    for nome in nomes:
        original = indice.get(_chave_campo(nome))
        if original is not None:
            return registro[original]
    return None


def normalizar_oc(valor: Any) -> str | None:
    """Ordem de compra como texto só de dígitos, ou None se não houver.

    4101141499, "4101141499", " 4101141499 ", 4101141499.0 e
    "4101141499.0" viram todos "4101141499". 0 e vazio viram None.
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, float):
        if valor != valor or not valor.is_integer():  # NaN ou quebrado
            return None
        valor = int(valor)
    texto = str(valor).strip()
    texto = re.sub(r"\.0+$", "", texto)          # 4101141499.0 do Excel
    digitos = re.sub(r"\D", "", texto)
    if not digitos or int(digitos) == 0:
        return None
    return digitos.lstrip("0") or None


def normalizar_nf(valor: Any) -> str | None:
    """NF como texto: 15016 -> "15016". 0, vazio e None viram None."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, float):
        if valor != valor:
            return None
        valor = int(valor) if valor.is_integer() else valor
    texto = re.sub(r"\.0+$", "", str(valor).strip())
    if not texto or texto.strip("0") == "" or texto.upper() in ("-", "NULL", "NONE", "N/A"):
        return None
    return texto


def valor_decimal(valor: Any) -> Decimal | None:
    """Número vindo da planilha (1740, "3,961.46") ou do ERP ("1.740,000000").

    Com ponto E vírgula, o separador que vem por último é o decimal:
    "3.961,46" (brasileiro) e "3,961.46" (americano, digitado na planilha)
    são o mesmo valor. Só com vírgula, ela é decimal ("217,40").
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))
    texto = re.sub(r"[^\d,.\-]", "", str(valor))
    if not texto:
        return None
    if "," in texto and "." in texto and texto.rfind(".") > texto.rfind(","):
        texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


# O ERP exporta dinheiro com 6 casas e vírgula ("1.740,000000"). Abaixo de
# R$ 1.000 não há ponto de milhar, e a conversão para JSON lê a vírgula como
# milhar: "217,400000" chega como o inteiro 217400000. Na rodada real de
# 29/09/2026 foram 299 de 914 linhas; as 73 conferíveis bateram com a planilha
# depois de dividir por um milhão.
CASAS_ERP = Decimal(1_000_000)


def valor_erp(valor: Any) -> Decimal | None:
    """Dinheiro do ERP: texto no formato brasileiro, ou inteiro com 6 casas embutidas."""
    if isinstance(valor, int) and not isinstance(valor, bool):
        return Decimal(valor) / CASAS_ERP
    return valor_decimal(valor)


# --------------------------------------------------------------------------
# leitura
# --------------------------------------------------------------------------

def _carregar(caminho: Path) -> Any:
    bruto = caminho.read_bytes()
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            texto = bruto.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        # mesma tolerância do planilha_manager do Maestro: vírgula sobrando
        # antes de } ou ] (edição à mão) não impede a leitura
        return json.loads(re.sub(r",\s*([}\]])", r"\1", texto))


def ler_json_com_chave(caminho: str | Path) -> tuple[list[dict], str | None]:
    """(registros, chave do envelope).

    Aceita a lista direto ([{...}]) — chave None — ou embrulhada num objeto
    ({"PEDIDOS": [...]}, formato do planilha_manager do Maestro) — chave
    "PEDIDOS". A chave serve para gravar a saída no mesmo formato.
    """
    caminho = Path(caminho)
    dados = _carregar(caminho)
    chave = None
    if isinstance(dados, dict):
        listas = [k for k, v in dados.items() if isinstance(v, list)]
        if len(listas) != 1:
            raise ValueError(
                f"{caminho.name}: esperava uma lista de registros; "
                f"o objeto tem {len(listas)} listas dentro"
            )
        chave = listas[0]
        dados = dados[chave]
    if not isinstance(dados, list):
        raise ValueError(f"{caminho.name}: esperava uma lista de registros")
    return [r for r in dados if isinstance(r, dict)], chave


def ler_json(caminho: str | Path) -> list[dict]:
    """Lista de registros do arquivo (ver ler_json_com_chave)."""
    return ler_json_com_chave(caminho)[0]


# --------------------------------------------------------------------------
# cruzamento
# --------------------------------------------------------------------------

@dataclass
class LinhaERP:
    """Uma linha do comparar.json que interessa ao relatório."""
    oc: str
    nf: str | None
    tipo: str | None
    codigo: Any
    emissao: Any
    total_liquido: Decimal | None
    cliente: Any
    transportadora: Any


@dataclass
class ResultadoPedido:
    posicao: int                 # índice no PEDIDOS.json (1 = primeiro)
    pedido: Any                  # como estava na planilha
    oc: str | None
    status: str
    nfs: list[str] = field(default_factory=list)
    nf_anterior: str | None = None     # NF que já estava na planilha
    nf_gravada: str | None = None      # NF que foi para o arquivo novo
    valor_planilha: str | None = None
    valor_erp: str | None = None       # soma do Total Líq. das vendas da OC
    diferenca_valor: str | None = None
    linhas_erp: int = 0
    tipos_erp: list[str] = field(default_factory=list)
    cidade: Any = None
    requisitante: Any = None
    produto: Any = None


def _linha_que_nao_e_venda(r: dict) -> bool:
    """Cabeçalho repetido no meio da exportação ou a linha de total no fim.

    Os dois apareceram no comparar.json real: {"Tipo": "Tipo", ...} e uma
    linha só com os totais, sem Tipo e sem ordem de compra.
    """
    tipo = campo(r, "Tipo")
    if tipo is not None and _chave_campo(tipo) == "TIPO":
        return True
    return tipo is None and campo(r, "Ordem Compra") is None and campo(r, "NF") is None


def _indexar_erp(registros: list[dict]) -> tuple[dict[str, list[LinhaERP]], int, int]:
    """(linhas por OC, linhas de venda sem OC, linhas que não são venda)."""
    por_oc: dict[str, list[LinhaERP]] = defaultdict(list)
    sem_oc = ignoradas = 0
    for r in registros:
        if _linha_que_nao_e_venda(r):
            ignoradas += 1
            continue
        oc = normalizar_oc(campo(r, "Ordem Compra", "OC", "Ordem de Compra"))
        if oc is None:
            sem_oc += 1
            continue
        por_oc[oc].append(LinhaERP(
            oc=oc,
            nf=normalizar_nf(campo(r, "NF", "Nota Fiscal")),
            tipo=campo(r, "Tipo"),
            codigo=campo(r, "Código", "Codigo"),
            emissao=campo(r, "Emissão", "Emissao"),
            total_liquido=valor_erp(campo(r, "Total Líq.", "Total Liq", "Total Bruto")),
            cliente=campo(r, "Cliente"),
            transportadora=campo(r, "Transportadora"),
        ))
    return por_oc, sem_oc, ignoradas


def _nfs_distintas(linhas: list[LinhaERP]) -> list[str]:
    vistas: list[str] = []
    for l in linhas:
        if l.nf and l.nf not in vistas:
            vistas.append(l.nf)
    return vistas


def _fmt(valor: Decimal | None) -> str | None:
    return None if valor is None else f"{valor:.2f}"


def cruzar(pedidos: list[dict], comparar: list[dict]) -> tuple[list[dict], dict]:
    """Devolve (pedidos atualizados, relatório).

    Os pedidos atualizados são cópias: a lista recebida não é alterada. Cada
    pedido ganha "NF" no fim (texto, como na planilha). Regra da NF gravada:

    - 1 NF no ERP        -> essa NF
    - mais de uma NF     -> todas, separadas por " / "
    - sem NF / não achou -> mantém a NF que o pedido já tinha; se não tinha, ""
    """
    por_oc, erp_sem_oc, erp_ignoradas = _indexar_erp(comparar)
    ocs_planilha = Counter()
    resultados: list[ResultadoPedido] = []
    atualizados: list[dict] = []

    for i, pedido in enumerate(pedidos, start=1):
        bruto = campo(pedido, "PEDIDO")
        oc = normalizar_oc(bruto)
        nf_anterior = normalizar_nf(campo(pedido, "NF"))
        linhas = por_oc.get(oc, []) if oc else []
        nfs = _nfs_distintas(linhas)

        if oc is None:
            status = PEDIDO_INVALIDO
        else:
            ocs_planilha[oc] += 1
            if not linhas:
                status = NAO_ENCONTRADO
            elif not nfs:
                status = SEM_NF
            elif len(nfs) == 1:
                status = BATEU
            else:
                status = MAIS_DE_UMA_NF

        nf_gravada = SEPARADOR_NF.join(nfs) if nfs else (nf_anterior or "")

        valor_planilha = valor_decimal(campo(pedido, "VALOR"))
        totais = [l.total_liquido for l in linhas if l.total_liquido is not None]
        valor_erp = sum(totais, Decimal(0)) if totais else None
        diferenca = None
        if valor_planilha is not None and valor_erp is not None:
            diferenca = valor_erp - valor_planilha

        resultados.append(ResultadoPedido(
            posicao=i,
            pedido=bruto,
            oc=oc,
            status=status,
            nfs=nfs,
            nf_anterior=nf_anterior,
            nf_gravada=nf_gravada or None,
            valor_planilha=_fmt(valor_planilha),
            valor_erp=_fmt(valor_erp),
            diferenca_valor=_fmt(diferenca),
            linhas_erp=len(linhas),
            tipos_erp=sorted({str(l.tipo) for l in linhas if l.tipo is not None}),
            cidade=campo(pedido, "CIDADE"),
            requisitante=campo(pedido, "REQUISITANTE"),
            produto=campo(pedido, "PRODUTO"),
        ))

        novo = {k: v for k, v in pedido.items() if _chave_campo(k) != "NF"}
        novo["NF"] = nf_gravada
        atualizados.append(novo)

    relatorio = _montar_relatorio(resultados, por_oc, ocs_planilha, erp_sem_oc,
                                  erp_ignoradas, total_erp=len(comparar))
    return atualizados, relatorio


def _montar_relatorio(resultados: list[ResultadoPedido],
                      por_oc: dict[str, list[LinhaERP]],
                      ocs_planilha: Counter,
                      erp_sem_oc: int,
                      erp_ignoradas: int,
                      total_erp: int) -> dict:
    def por_status(s: str) -> list[dict]:
        return [asdict(r) for r in resultados if r.status == s]

    so_no_erp = []
    for oc, linhas in sorted(por_oc.items()):
        if oc not in ocs_planilha:
            so_no_erp.append({
                "oc": oc,
                "nfs": _nfs_distintas(linhas),
                "linhas_erp": len(linhas),
                "cliente": linhas[0].cliente,
                "emissao": linhas[0].emissao,
                "total_liquido": _fmt(sum((l.total_liquido or Decimal(0)) for l in linhas)),
            })

    # a mesma NF atendendo várias OCs (uma nota para mais de um pedido)
    ocs_por_nf: dict[str, set[str]] = defaultdict(set)
    for oc, linhas in por_oc.items():
        for l in linhas:
            if l.nf:
                ocs_por_nf[l.nf].add(oc)
    nf_varias_ocs = [
        {"nf": nf, "ocs": sorted(ocs), "na_planilha": sorted(o for o in ocs if o in ocs_planilha)}
        for nf, ocs in sorted(ocs_por_nf.items()) if len(ocs) > 1
    ]

    duplicados = [
        {"oc": oc, "vezes": n, "posicoes": [r.posicao for r in resultados if r.oc == oc]}
        for oc, n in sorted(ocs_planilha.items()) if n > 1
    ]

    nf_alterada = [
        asdict(r) for r in resultados
        if r.nf_anterior and r.nfs and r.nf_anterior != r.nf_gravada
    ]

    divergencia_valor = [
        asdict(r) for r in resultados
        if r.diferenca_valor is not None and abs(Decimal(r.diferenca_valor)) > TOLERANCIA_VALOR
    ]

    contagem = Counter(r.status for r in resultados)
    ocs_unicas = len(ocs_planilha)
    ocs_com_nf = sum(1 for r in resultados if r.status in (BATEU, MAIS_DE_UMA_NF))

    tipos_erp = Counter()
    for linhas in por_oc.values():
        for l in linhas:
            tipos_erp[str(l.tipo)] += 1

    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "resumo": {
            "pedidos_na_planilha": len(resultados),
            "ocs_distintas_na_planilha": ocs_unicas,
            "linhas_no_erp": total_erp,
            "ocs_distintas_no_erp": len(por_oc),
            "linhas_erp_sem_oc": erp_sem_oc,
            "linhas_erp_ignoradas": erp_ignoradas,
            "bateram_1_nf": contagem[BATEU],
            "mais_de_uma_nf": contagem[MAIS_DE_UMA_NF],
            "no_erp_sem_nf": contagem[SEM_NF],
            "nao_encontrados_no_erp": contagem[NAO_ENCONTRADO],
            "pedido_invalido": contagem[PEDIDO_INVALIDO],
            "so_no_erp": len(so_no_erp),
            "pedidos_duplicados_na_planilha": len(duplicados),
            "nf_atendendo_varias_ocs": len(nf_varias_ocs),
            "nf_alterada": len(nf_alterada),
            "divergencia_de_valor": len(divergencia_valor),
            "percentual_com_nf": round(100 * ocs_com_nf / len(resultados), 1) if resultados else 0.0,
            "tipos_no_erp": dict(tipos_erp),
        },
        "bateram": por_status(BATEU),
        "mais_de_uma_nf": por_status(MAIS_DE_UMA_NF),
        "sem_nf": por_status(SEM_NF),
        "nao_encontrados": por_status(NAO_ENCONTRADO),
        "pedido_invalido": por_status(PEDIDO_INVALIDO),
        "so_no_erp": so_no_erp,
        "pedidos_duplicados": duplicados,
        "nf_varias_ocs": nf_varias_ocs,
        "nf_alterada": nf_alterada,
        "divergencia_valor": divergencia_valor,
    }


# --------------------------------------------------------------------------
# relatório em Markdown
# --------------------------------------------------------------------------

def _brl(texto: str | None) -> str:
    if texto is None:
        return "-"
    v = Decimal(texto)
    inteiro, dec = f"{abs(v):,.2f}".split(".")
    return f"{'-' if v < 0 else ''}R$ {inteiro.replace(',', '.')},{dec}"


def _celula(v: Any, limite: int = 60) -> str:
    texto = "-" if v in (None, "") else str(v)
    texto = texto.replace("|", "/").replace("\n", " ")
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def _tabela(cabecalho: list[str], linhas: list[list[Any]]) -> str:
    if not linhas:
        return "_Nenhum._\n"
    saida = ["| " + " | ".join(cabecalho) + " |", "|" + "---|" * len(cabecalho)]
    saida += ["| " + " | ".join(_celula(c) for c in linha) + " |" for linha in linhas]
    return "\n".join(saida) + "\n"


def relatorio_markdown(rel: dict, arquivos: dict[str, str] | None = None) -> str:
    r = rel["resumo"]
    partes = [f"# Relatório do cruzamento de NF\n\nGerado em {rel['gerado_em']}.\n"]
    if arquivos:
        partes.append("\n".join(f"- **{k}:** `{v}`" for k, v in arquivos.items()) + "\n\n")

    partes.append("## Resumo\n\n")
    partes.append(_tabela(["", "quantidade"], [
        ["Pedidos na planilha (PEDIDOS.json)", r["pedidos_na_planilha"]],
        ["Ordens de compra distintas na planilha", r["ocs_distintas_na_planilha"]],
        ["Linhas no ERP (comparar.json)", r["linhas_no_erp"]],
        ["Ordens de compra distintas no ERP", r["ocs_distintas_no_erp"]],
        ["**Bateram (1 NF)**", r["bateram_1_nf"]],
        ["**Mais de uma NF**", r["mais_de_uma_nf"]],
        ["**No ERP, mas sem NF**", r["no_erp_sem_nf"]],
        ["**Na planilha, não no ERP**", r["nao_encontrados_no_erp"]],
        ["**No ERP, não na planilha**", r["so_no_erp"]],
        ["Pedido vazio/inválido na planilha", r["pedido_invalido"]],
        ["Pedido repetido na planilha", r["pedidos_duplicados_na_planilha"]],
        ["Mesma NF para várias OCs", r["nf_atendendo_varias_ocs"]],
        ["NF da planilha trocada pela do ERP", r["nf_alterada"]],
        ["Valor da planilha ≠ valor do ERP", r["divergencia_de_valor"]],
        ["Vendas do ERP sem ordem de compra", r["linhas_erp_sem_oc"]],
        ["Linhas do ERP que não são venda (cabeçalho, total)", r["linhas_erp_ignoradas"]],
        ["Pedidos com NF preenchida", f"{r['percentual_com_nf']:.1f}%".replace(".", ",")],
    ]))
    if r["tipos_no_erp"]:
        tipos = ", ".join(f"{k}: {v}" for k, v in sorted(r["tipos_no_erp"].items()))
        partes.append(f"\nTipos de lançamento no ERP (das linhas com OC): {tipos}.\n")

    def linhas_pedido(itens: list[dict], com_nf: bool = True) -> list[list[Any]]:
        saida = []
        for p in itens:
            linha = [p["posicao"], p["oc"] or p["pedido"]]
            if com_nf:
                linha.append(SEPARADOR_NF.join(p["nfs"]) or "-")
            linha += [_brl(p["valor_planilha"]), p["requisitante"], p["cidade"], p["produto"]]
            saida.append(linha)
        return saida

    partes.append(f"\n## Mais de uma NF ({r['mais_de_uma_nf']})\n\n"
                  "A OC foi faturada em mais de uma nota. No arquivo novo vão todas, "
                  f"separadas por `{SEPARADOR_NF}`.\n\n")
    partes.append(_tabela(["#", "pedido", "NFs", "valor", "requisitante", "cidade", "produto"],
                          linhas_pedido(rel["mais_de_uma_nf"])))

    partes.append(f"\n## No ERP, mas sem NF ({r['no_erp_sem_nf']})\n\n"
                  "A venda existe no ERP, mas ainda não foi faturada (NF vazia ou 0).\n\n")
    partes.append(_tabela(["#", "pedido", "valor", "requisitante", "cidade", "produto"],
                          linhas_pedido(rel["sem_nf"], com_nf=False)))

    partes.append(f"\n## Na planilha, mas não no ERP ({r['nao_encontrados_no_erp']})\n\n"
                  "Nenhuma linha do comparar.json tem esta ordem de compra.\n\n")
    partes.append(_tabela(["#", "pedido", "valor", "requisitante", "cidade", "produto"],
                          linhas_pedido(rel["nao_encontrados"], com_nf=False)))

    partes.append(f"\n## No ERP, mas não na planilha ({r['so_no_erp']})\n\n")
    partes.append(_tabela(["OC", "NFs", "linhas", "emissão", "total líq.", "cliente"], [
        [o["oc"], SEPARADOR_NF.join(o["nfs"]) or "-", o["linhas_erp"], o["emissao"],
         _brl(o["total_liquido"]), o["cliente"]]
        for o in rel["so_no_erp"]
    ]))

    partes.append(f"\n## Divergência de valor ({r['divergencia_de_valor']})\n\n"
                  "VALOR da planilha comparado com a soma do Total Líq. das vendas da OC "
                  f"(tolerância de {_brl(str(TOLERANCIA_VALOR))}).\n\n")
    partes.append(_tabela(["#", "pedido", "NF", "planilha", "ERP", "diferença"], [
        [p["posicao"], p["oc"], p["nf_gravada"], _brl(p["valor_planilha"]),
         _brl(p["valor_erp"]), _brl(p["diferenca_valor"])]
        for p in rel["divergencia_valor"]
    ]))

    partes.append(f"\n## Mesma NF para várias OCs ({r['nf_atendendo_varias_ocs']})\n\n")
    partes.append(_tabela(["NF", "OCs", "dessas, na planilha"], [
        [n["nf"], ", ".join(n["ocs"]), ", ".join(n["na_planilha"]) or "-"]
        for n in rel["nf_varias_ocs"]
    ]))

    partes.append(f"\n## Pedido repetido na planilha ({r['pedidos_duplicados_na_planilha']})\n\n")
    partes.append(_tabela(["OC", "vezes", "posições"], [
        [d["oc"], d["vezes"], ", ".join(map(str, d["posicoes"]))]
        for d in rel["pedidos_duplicados"]
    ]))

    partes.append(f"\n## NF da planilha trocada ({r['nf_alterada']})\n\n"
                  "O pedido já tinha NF e o ERP diz outra. Vale a do ERP.\n\n")
    partes.append(_tabela(["#", "pedido", "NF antes", "NF agora"], [
        [p["posicao"], p["oc"], p["nf_anterior"], p["nf_gravada"]]
        for p in rel["nf_alterada"]
    ]))

    partes.append(f"\n## Pedido vazio ou inválido ({r['pedido_invalido']})\n\n")
    partes.append(_tabela(["#", "PEDIDO", "requisitante", "produto"], [
        [p["posicao"], p["pedido"], p["requisitante"], p["produto"]]
        for p in rel["pedido_invalido"]
    ]))

    partes.append(f"\n## Bateram ({r['bateram_1_nf']})\n\n")
    partes.append(_tabela(["#", "pedido", "NF", "valor", "requisitante", "cidade"], [
        [p["posicao"], p["oc"], p["nf_gravada"], _brl(p["valor_planilha"]),
         p["requisitante"], p["cidade"]]
        for p in rel["bateram"]
    ]))
    return "".join(partes)


def resumo_console(rel: dict) -> str:
    r = rel["resumo"]
    return "\n".join([
        f"  Pedidos na planilha ........ {r['pedidos_na_planilha']}",
        f"  Bateram (1 NF) ............. {r['bateram_1_nf']}",
        f"  Mais de uma NF ............. {r['mais_de_uma_nf']}",
        f"  No ERP sem NF .............. {r['no_erp_sem_nf']}",
        f"  Planilha, nao no ERP ....... {r['nao_encontrados_no_erp']}",
        f"  ERP, nao na planilha ....... {r['so_no_erp']}",
        f"  Pedido repetido ............ {r['pedidos_duplicados_na_planilha']}",
        f"  Mesma NF em varias OCs ..... {r['nf_atendendo_varias_ocs']}",
        f"  NF trocada ................. {r['nf_alterada']}",
        f"  Divergencia de valor ....... {r['divergencia_de_valor']}",
        f"  Pedido vazio/invalido ...... {r['pedido_invalido']}",
        f"  Com NF preenchida .......... {r['percentual_com_nf']}%",
    ])


# --------------------------------------------------------------------------
# arquivos
# --------------------------------------------------------------------------

def gravar_json(caminho: str | Path, dados: Any) -> None:
    """Grava num temporário e troca: se cair no meio, o arquivo anterior fica inteiro."""
    caminho = Path(caminho)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(caminho)


def rodar(pedidos: str | Path, comparar: str | Path, saida: str | Path,
          relatorio_md: str | Path | None = None,
          relatorio_json: str | Path | None = None) -> dict:
    """Lê os dois arquivos, grava o PEDIDOS_ATUALIZADO e os relatórios. Devolve o relatório."""
    pedidos, comparar, saida = Path(pedidos), Path(comparar), Path(saida)
    if saida.resolve() == pedidos.resolve():
        raise ValueError("a saída não pode ser o próprio PEDIDOS.json: o original é preservado")
    registros, envelope = ler_json_com_chave(pedidos)
    atualizados, rel = cruzar(registros, ler_json(comparar))
    rel["arquivos"] = {"pedidos": str(pedidos), "comparar": str(comparar), "saida": str(saida)}
    # mesmo formato da entrada: o planilha_manager do Maestro lê {"PEDIDOS": [...]}
    gravar_json(saida, {envelope: atualizados} if envelope else atualizados)
    if relatorio_json:
        gravar_json(relatorio_json, rel)
    if relatorio_md:
        Path(relatorio_md).write_text(
            relatorio_markdown(rel, {"PEDIDOS": str(pedidos), "comparar": str(comparar),
                                     "gerado": str(saida)}),
            encoding="utf-8",
        )
    return rel
