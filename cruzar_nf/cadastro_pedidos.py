"""Cadastro automático de pedidos: planilha Excel dos estagiários -> portal Maestro.

Os pedidos entram SÓ na aba PEDIDOS da "PLANILHA DE CONTROLE VALE - ESTAGIARIOS".
Este robô (CadastrarPedidos.bat, Agendador a cada 10 min) leva cada linha nova
para o PEDIDOS.json, que é o que a tela "Pedidos" do portal mostra. O
planilha_manager recarrega o JSON quando a data do arquivo muda.

Uma rodada:
1. se a planilha não foi salva desde a última rodada, não faz nada;
2. copia a planilha para uma pasta temporária (não briga com quem está com ela
   aberta) e lê a aba PEDIDOS; só vale o que foi SALVO no Excel;
3. linha nova = chave (PEDIDO + RFQ + começo do PRODUTO) que nunca foi vista.
   Na PRIMEIRA rodada nada é gravado: tudo que já está na planilha vira "visto"
   (planilha e portal já tinham sido conferidos à mão e divergem em digitação);
4. linha sem CIDADE, PEDIDO, VALOR, PRODUTO ou REQUISITANTE ainda está sendo
   digitada: fica esperando, sem virar "vista";
5. linha que já está no portal (mesmo PEDIDO ou RFQ e mesmo começo de PRODUTO:
   cadastrada à mão, ou linha antiga com digitação corrigida) não é gravada;
6. grava com backup e com o mesmo cuidado da NF (arquivo_pedidos.py): confere
   se o arquivo mudou, troca de uma vez, relê depois e grava de novo se o
   gerenciador salvou por cima.

Linha apagada no portal não volta: o que já foi "visto" nunca é gravado de novo.
Estado em <SYNC_NF_DADOS>/cadastro_pedidos.json. Compatível com Python 3.8.

    python -m cruzar_nf.cadastro_pedidos [--gravar]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from cruzar_nf.arquivo_pedidos import ConflitoGravacao
from cruzar_nf.maestro import _guardar_backup

ABA = "PEDIDOS"
ARQ_ESTADO = "cadastro_pedidos.json"
OBRIGATORIOS = ("CIDADE", "PEDIDO", "VALOR", "PRODUTO", "REQUISITANTE")
TAM_PRODUTO = 30            # o fim do PRODUTO muda depois ("- entregue em ..."); o começo não
TENTATIVAS = 6
ESPERA_ENTRE_TENTATIVAS_S = 1.0
ESPERA_CONFERENCIA_S = 3.0
MANTER_HISTORICO = 100
PREFIXO_BACKUP = "PEDIDOS antes do cadastro"
COLUNA_NF_MAESTRO = "NF (MAESTRO)"   # coluna que o nf_planilha.py escreve: é do robô, não vai para o portal


# -- leitura da planilha -------------------------------------------------------

def _valor_celula(v: Any) -> Any:
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        return v.strip() or None
    return v


def ler_planilha(caminho: str) -> List[Dict[str, Any]]:
    """Linhas da aba PEDIDOS com os nomes de coluna do PEDIDOS.json (são os mesmos:
    o JSON nasceu desta planilha). Data vira dd/mm/aaaa; célula vazia fica de fora."""
    return [linha for _n, linha in ler_planilha_com_linhas(caminho)]


def ler_planilha_com_linhas(caminho: str) -> List[Tuple[int, Dict[str, Any]]]:
    """Como ler_planilha, com o número da linha no Excel (o cabeçalho é a linha 1)."""
    import openpyxl

    pasta = tempfile.mkdtemp(prefix="cadastro_pedidos_")
    try:
        copia = os.path.join(pasta, "planilha.xlsx")
        shutil.copy2(caminho, copia)
        try:
            wb = openpyxl.load_workbook(copia, read_only=True, data_only=True)
        except (zipfile.BadZipFile, KeyError, OSError) as e:
            raise ValueError(f"Não consegui abrir a planilha (o Excel estava salvando?); "
                             f"tento de novo na próxima rodada. Detalhe: {e}") from e
        try:
            aba = next((ws for ws in wb.worksheets if ws.title.strip().upper() == ABA), None)
            if aba is None:
                raise ValueError(f"A planilha não tem a aba {ABA} (abas: {wb.sheetnames})")
            linhas = aba.iter_rows(values_only=True)
            cabecalho = next(linhas, ())
            resultado = []
            for numero, valores in enumerate(linhas, start=2):
                linha = {}
                for nome, v in zip(cabecalho, valores):
                    v = _valor_celula(v)
                    if nome is not None and v is not None:
                        linha[str(nome)] = v
                if linha:
                    resultado.append((numero, linha))
            return resultado
        finally:
            wb.close()
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


# -- comparação ----------------------------------------------------------------

def _norm(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    texto = unicodedata.normalize("NFKD", str(v if v is not None else ""))
    return re.sub(r"[^A-Z0-9]", "", texto.encode("ascii", "ignore").decode().upper())


def _campo(linha: Dict[str, Any], nome: str) -> Any:
    """Os nomes no JSON têm espaço sobrando ("VALOR ", "REQUISITANTE ")."""
    return next((v for k, v in linha.items() if k.strip().upper() == nome), None)


def chave(linha: Dict[str, Any]) -> str:
    return "|".join((_norm(_campo(linha, "PEDIDO")), _norm(_campo(linha, "NMR DA RFQ")),
                     _norm(_campo(linha, "PRODUTO"))[:TAM_PRODUTO]))


def completa(linha: Dict[str, Any]) -> bool:
    return all(_norm(_campo(linha, nome)) for nome in OBRIGATORIOS)


def _valor(v: Any) -> Optional[float]:
    """650.4, "650,40" e "1.650,40" (como o portal grava) -> número."""
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    texto = str(v or "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return round(float(texto), 2)
    except ValueError:
        return None


def _identidades(p: Dict[str, Any]) -> set:
    """Mesmo PEDIDO, mesma RFQ ou mesma CIDADE+VALOR: qualquer uma basta, junto com o
    começo do PRODUTO. A terceira pega o número do pedido corrigido numa linha sem RFQ."""
    pedido, rfq = _norm(_campo(p, "PEDIDO")), _norm(_campo(p, "NMR DA RFQ"))
    cidade, valor = _norm(_campo(p, "CIDADE")), _valor(_campo(p, "VALOR"))
    ids = {("PEDIDO", pedido), ("RFQ", rfq)}
    if cidade and valor is not None:
        ids.add(("CIDADE+VALOR", f"{cidade}|{valor}"))
    return {i for i in ids if i[1]}


def _sem_colunas_do_robo(linha: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in linha.items() if k != COLUNA_NF_MAESTRO}


def correspondentes(linha: Dict[str, Any], pedidos: List[Dict[str, Any]]) -> List[int]:
    """Posições dos pedidos com o mesmo começo de PRODUTO (um é o começo do outro: no
    portal o texto costuma ser mais longo) e alguma identidade em comum (_identidades)."""
    produto = _norm(_campo(linha, "PRODUTO"))[:TAM_PRODUTO]
    ids = _identidades(linha)
    achados = []
    for i, p in enumerate(pedidos):
        outro = _norm(_campo(p, "PRODUTO"))[:TAM_PRODUTO]
        if (outro.startswith(produto) or produto.startswith(outro)) and ids & _identidades(p):
            achados.append(i)
    return achados


def no_portal(linha: Dict[str, Any], pedidos: List[Dict[str, Any]]) -> bool:
    return bool(correspondentes(linha, pedidos))


# -- estado --------------------------------------------------------------------

def carregar_estado(pasta: str) -> Dict[str, Any]:
    arq = Path(pasta) / ARQ_ESTADO
    if not arq.is_file():
        return {}
    return json.loads(arq.read_text(encoding="utf-8"))


def _salvar_estado(pasta: str, estado: Dict[str, Any]) -> None:
    arq = Path(pasta) / ARQ_ESTADO
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(arq))


def _assinatura(caminho: str) -> List[int]:
    st = os.stat(caminho)
    return [st.st_mtime_ns, st.st_size]


# -- gravação ------------------------------------------------------------------

def _gravar(manager: Any, linhas: List[Dict[str, Any]], dir_backup: Optional[str],
            progresso: Callable[[str], None], dormir: Callable[[float], None]) -> int:
    """Acrescenta as linhas que ainda não estão no PEDIDOS.json e relê para conferir.
    Devolve quantas foram gravadas."""
    gravadas = 0
    backup = dir_backup
    for tentativa in range(1, TENTATIVAS + 1):
        manager.iniciar()
        with manager.lock:
            lista = manager.pedidos.setdefault("PEDIDOS", [])
            faltam = [_sem_colunas_do_robo(l) for l in linhas if not no_portal(l, lista)]
            if not faltam:
                return gravadas
            if gravadas:
                progresso(f"{len(faltam)} pedido(s) sumiram depois de gravados (o gerenciador "
                          f"salvou junto); gravando de novo ({tentativa}/{TENTATIVAS})...")
            if backup:
                _guardar_backup(manager.caminho_pedidos, backup, PREFIXO_BACKUP)
                backup = None
            manager.pedidos["PEDIDOS"] = lista + faltam
            try:
                manager.salvar()
            except ConflitoGravacao as e:
                progresso(f"PEDIDOS.json mudou durante a gravação ({e}); tentando de novo...")
                dormir(ESPERA_ENTRE_TENTATIVAS_S)
                continue
        gravadas = gravadas or len(faltam)
        dormir(ESPERA_CONFERENCIA_S)      # a próxima volta relê e confere
    raise RuntimeError("Não consegui gravar os pedidos: o PEDIDOS.json mudou em todas as tentativas.")


# -- rodada --------------------------------------------------------------------

def cadastrar(planilha: str, manager: Any, pasta_dados: str, gravar: bool = False,
              progresso: Callable[[str], None] = print,
              dormir: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    estado = carregar_estado(pasta_dados)
    primeira_vez = "vistos" not in estado     # o estado pode ter só um erro registrado
    res: Dict[str, Any] = {"rodou_em": _dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                           "gravou": gravar, "primeira_vez": primeira_vez, "sem_mudanca": False,
                           "linhas": 0, "novas": 0, "incompletas": 0, "ja_no_portal": 0,
                           "a_gravar": 0, "gravados": 0, "pedidos": [], "repetidas": []}
    assinatura = _assinatura(planilha)
    if not primeira_vez and estado.get("planilha") == assinatura:
        res["sem_mudanca"] = True
        if gravar:                        # o painel mostra que o robô está vivo
            _salvar_estado(pasta_dados, _verificado(estado, res))
        return res

    linhas = ler_planilha(planilha)
    res["linhas"] = len(linhas)

    if primeira_vez:
        progresso(f"Primeira rodada: {len(linhas)} linhas da planilha marcadas como já cadastradas.")
        if gravar:
            # incompletas antigas também (ex.: pedido sem número): senão viram aviso eterno
            _salvar_estado(pasta_dados, _verificado({"vistos": sorted({chave(l) for l in linhas}),
                                                     "planilha": assinatura, "historico": [_resumo(res)]}, res))
        return res

    vistos = set(estado.get("vistos", []))
    novas: Dict[str, Dict[str, Any]] = {}
    for l in linhas:
        k = chave(l)
        if k in novas:      # ponytail: 2 itens com o mesmo começo de PRODUTO viram 1; só avisa
            res["repetidas"].append(f"{_campo(l, 'PEDIDO')} - {str(_campo(l, 'PRODUTO'))[:50]}")
            progresso(f"AVISO: linha repetida na planilha, não cadastrada: {res['repetidas'][-1]}")
            continue
        if k in vistos:
            continue
        if not completa(l):
            res["incompletas"] += 1
            continue
        novas[k] = l
    res["novas"] = len(novas)

    a_gravar: List[Dict[str, Any]] = []
    if novas:
        manager.iniciar()
        existentes = manager.pedidos.get("PEDIDOS", [])
        a_gravar = [l for l in novas.values() if not no_portal(l, existentes)]
    res["ja_no_portal"] = len(novas) - len(a_gravar)
    res["a_gravar"] = len(a_gravar)
    res["pedidos"] = [f"{_campo(l, 'PEDIDO')} - {str(_campo(l, 'PRODUTO'))[:50]}" for l in a_gravar]
    for p in res["pedidos"]:
        progresso(f"{'Cadastrando' if gravar else 'Cadastraria'}: {p}")
    if not gravar:
        return res

    if a_gravar:
        res["gravados"] = _gravar(manager, a_gravar, str(Path(pasta_dados) / "backups"),
                                  progresso, dormir)
    estado["vistos"] = sorted(vistos | set(novas))
    estado["planilha"] = assinatura
    if novas or res["repetidas"]:
        estado["historico"] = ([_resumo(res)] + estado.get("historico", []))[:MANTER_HISTORICO]
    _salvar_estado(pasta_dados, _verificado(estado, res))
    return res


def _verificado(estado: Dict[str, Any], res: Dict[str, Any]) -> Dict[str, Any]:
    estado = dict(estado, verificado_em=res["rodou_em"])
    estado.pop("erro", None)
    return estado


def registrar_erro(pasta: str, mensagem: str) -> None:
    """Fica no estado até a próxima rodada boa: é o que o painel mostra em vermelho."""
    estado = carregar_estado(pasta)
    estado["erro"] = {"em": _dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "mensagem": mensagem}
    _salvar_estado(pasta, estado)


def estado_para_tela(pasta: str) -> Dict[str, Any]:
    """O que o portal mostra (vai junto com o estado da NF, ver maestro.py)."""
    estado = carregar_estado(pasta)
    cadastros = [h for h in estado.get("historico", []) if h.get("gravados")]
    hoje = _dt.date.today().strftime("%d/%m/%Y")
    return {"ativo": "vistos" in estado, "verificado_em": estado.get("verificado_em"),
            "erro": estado.get("erro"), "ultimo_cadastro": cadastros[0] if cadastros else None,
            "cadastrados_hoje": sum(h["gravados"] for h in cadastros if h["rodou_em"].startswith(hoje)),
            "historico": [h for h in estado.get("historico", [])
                          if h.get("gravados") or h.get("repetidas")][:10]}


def _resumo(res: Dict[str, Any]) -> Dict[str, Any]:
    return {k: res[k] for k in ("rodou_em", "primeira_vez", "linhas", "novas", "incompletas",
                                "ja_no_portal", "a_gravar", "gravados", "pedidos", "repetidas")}


# -- linha de comando ----------------------------------------------------------

PLANILHA_PADRAO = r"\\SERVIDOR2\Publico\PLANILHA DE CONTROLE VALE - ESTAGIARIOS (copia 1).xlsx"


def main(argv: Optional[List[str]] = None) -> int:
    from cruzar_nf.arquivo_pedidos import ArquivoPedidosConcorrente
    from cruzar_nf.sincronizar import DADOS_PADRAO, PEDIDOS_PADRAO

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(prog="cruzar_nf.cadastro_pedidos", description=__doc__.splitlines()[0])
    ap.add_argument("--planilha", default=os.environ.get("CADASTRO_PLANILHA") or PLANILHA_PADRAO)
    ap.add_argument("--dados", default=os.environ.get("SYNC_NF_DADOS") or DADOS_PADRAO,
                    help="pasta do estado e dos backups")
    ap.add_argument("--pedidos", default=os.environ.get("SYNC_NF_PEDIDOS") or PEDIDOS_PADRAO)
    ap.add_argument("--gravar", action="store_true", help="grava no portal (sem isso é só prévia)")
    a = ap.parse_args(argv)

    Path(a.dados).mkdir(parents=True, exist_ok=True)
    manager = ArquivoPedidosConcorrente(a.pedidos, progresso=lambda m: print(m, flush=True))
    try:
        res = cadastrar(a.planilha, manager, a.dados, gravar=a.gravar,
                        progresso=lambda m: print(m, flush=True))
    except Exception as e:      # planilha no meio do salvamento, rede, JSON: o .bat vê o erro
        print(f"[ERRO] {e}", file=sys.stderr)
        if a.gravar:
            try:
                registrar_erro(a.dados, str(e))
            except OSError:
                pass            # sem rede nem para o estado: o log do .bat já tem o erro
        return 1
    if not res["sem_mudanca"]:
        print(json.dumps(_resumo(res), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
