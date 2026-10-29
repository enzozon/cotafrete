"""Regras de decisão e fluxo de cada planilha (independente do navegador)."""
import hashlib
import json
import logging
import msvcrt
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Protocol

from orcamento.config import Config
from orcamento.ia import Ajudantes, ajudantes
from orcamento.planilha import ErroPlanilha, Item, Orcamento, ler_planilha, normalizar
from orcamento.relatorio import Relatorio, moeda

log = logging.getLogger("robo")

ESTABILIDADE_S = 60
PASTA_MODELO = "PLANILHA"
MODELO_PREFIXO = "PLANILHA-BASE"
MAX_DESCRICAO = 100  # limite do campo descrição no cadastro de produto do HSE
MIN_REFERENCIA = 6   # tamanho mínimo de um código de modelo (letras + números) para checar duplicata
SUBPASTAS = ("DAVs", "PROCESSADOS", "ERRO", "DRYRUN")
# Desconto máximo sobre o preço de tabela que o HSE aceita no Incluir (visto em 28/10/2026:
# "Desconto máximo 15%"). Fixo para todos os itens, por decisão do Enzo (29/10/2026).
DESCONTO_MAX = Decimal("15")


@dataclass(frozen=True)
class Cliente:
    codigo: str
    nome: str
    documento: str


@dataclass(frozen=True)
class Produto:
    codigo: str
    descricao: str
    ativo: bool
    preco: Decimal | None = None  # preço de tabela no HSE (None = não conferir o desconto)


@dataclass(frozen=True)
class Resultado:
    estado: str             # "pronto" | "erro" | "incerto" | "simulado" | "adiado"
    numero: str | None      # nº do orçamento no HSE (pronto/incerto)
    pdf: Path | None        # PDF gravado (só "pronto")
    relatorio: str          # Relatorio.texto()
    cliente: str            # "8411 - BELO VALE ..." ou "" se não chegou a achar


class HseIndisponivel(Exception):
    """Rede/login/HSE fora do ar: a planilha fica para o próximo ciclo."""


class SalvoIncerto(Exception):
    """Clicou em Salvar mas não deu para confirmar: o orçamento pode existir — nunca cancelar."""

    def __init__(self, numero: str, motivo: str):
        super().__init__(f"orçamento {numero}: {motivo}")
        self.numero = numero


class HseApi(Protocol):
    rascunho: str | None
    avisos: list[str]  # avisos que o HSE mostrou ao montar o orçamento (ex.: cliente bloqueado)
    def buscar_cliente(self, chave: str) -> list[Cliente]: ...
    def vendedor_existe(self, nome: str) -> bool: ...
    def buscar_produtos(self, termo: str) -> list[Produto]: ...
    def cadastrar_produto(self, item: Item, filial: int, salvar: bool) -> str | None: ...
    def montar_orcamento(self, orc: Orcamento, cliente: Cliente,
                         itens: list[tuple[Item, Produto | None]], incluir: bool) -> None: ...
    def salvar_orcamento(self) -> str: ...
    def baixar_dav(self, numero: str, destino: Path) -> None: ...
    def cancelar_rascunho(self) -> str | None: ...
    def marcas(self) -> list[str]: ...
    def grupos(self) -> list[str]: ...
    def ncm_existe(self, ncm: str) -> bool: ...


@dataclass(frozen=True)
class Resolucao:
    item: Item
    produto: Produto | None = None
    por: str = ""            # "codigo" | "descricao" | "novo"
    erro: str | None = None
    notas: tuple[str, ...] = ()  # ex.: descrição resumida por IA, marca achada na descrição


# --- arquivos ----------------------------------------------------------------

def sanitizar(nome: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome).strip(" .")[:80]


def destino_livre(caminho: Path) -> Path:
    n = 2
    destino = caminho
    while destino.exists():
        destino = caminho.with_name(f"{caminho.stem}_{n}{caminho.suffix}")
        n += 1
    return destino


def _mover(origem: Path, pasta: Path) -> Path:
    destino = destino_livre(pasta / origem.name)
    os.replace(origem, destino)
    return destino


def _livre(path: Path) -> bool:
    """False se outro programa (Excel) está com o arquivo aberto."""
    try:
        with open(path, "r+b"):
            return True
    except OSError:
        return False


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _estado(cfg: Config, nome: str) -> tuple[Path, dict]:
    p = cfg.pasta_programa / nome
    try:
        return p, json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return p, {}


def _marcar(cfg: Config, nome: str, h: str, arquivo: Path) -> None:
    p, estado = _estado(cfg, nome)
    estado = {**estado, h: {"arquivo": arquivo.name, "quando": datetime.now().isoformat(timespec="seconds")}}
    p.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")


def _estado_nome(cfg: Config) -> str:
    return "dryrun_estado.json" if cfg.dry_run else "processados_estado.json"


def arquivos_prontos(pasta: Path, agora: float, estabilidade: float = ESTABILIDADE_S) -> list[Path]:
    prontos = []
    sub = pasta / PASTA_MODELO  # quem salvar a planilha junto do modelo também é atendido
    for p in sorted(pasta.iterdir()) + (sorted(sub.iterdir()) if sub.is_dir() else []):
        if p.suffix.lower() != ".xlsx" or p.name.startswith("~$"):
            continue
        if p.name.upper().startswith(MODELO_PREFIXO):
            continue  # o modelo fica na pasta para as pessoas copiarem
        try:
            if not p.is_file() or agora - p.stat().st_mtime < estabilidade:
                continue  # ainda pode estar sendo salvo
        except OSError:  # sumiu/bloqueado entre a listagem e o stat
            continue
        prontos.append(p)
    return prontos


# --- regras de decisão -------------------------------------------------------

def _resumo(e: Exception) -> str:
    """Primeira linha da exceção (o call log do Playwright vai só para o robo.log)."""
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def resolver_cliente(chave: str, hse: HseApi) -> tuple[Cliente | None, str | None]:
    doc = _so_digitos(chave)
    achados = {c.codigo: c for c in hse.buscar_cliente(chave)
               if c.codigo == chave or (len(doc) >= 11 and _so_digitos(c.documento) == doc)}
    if len(achados) == 1:
        return next(iter(achados.values())), None
    if not achados:
        return None, f"Cliente {chave} não encontrado no HSE (use o código ou CNPJ/CPF exato)"
    return None, f"Cliente {chave} corresponde a vários cadastros: {', '.join(achados)}"


def _por_descricao(texto: str, hse: HseApi) -> dict[str, Produto]:
    alvo = normalizar(texto)
    return {p.codigo: p for p in hse.buscar_produtos(alvo) if p.ativo and normalizar(p.descricao) == alvo}


def _referencias(texto: str) -> set[str]:
    """Códigos de modelo/referência (letras E números, 6+ caracteres), ex.: MDRT572EVD013."""
    return {t for t in re.findall(r"[A-Z0-9]+", normalizar(texto))
            if len(t) >= MIN_REFERENCIA and re.search(r"[A-Z]", t) and re.search(r"\d", t)}


def _por_referencia(item: Item, hse: HseApi) -> str:
    """Antes de cadastrar: algum produto ativo já tem o mesmo código de modelo? (evita duplicata)"""
    achados: dict[str, str] = {}
    for ref in sorted(_referencias(f"{item.produto} {item.descricao_cadastro}")):
        for p in hse.buscar_produtos(ref):
            if p.ativo and ref in normalizar(p.descricao):
                achados[p.codigo] = f"{p.codigo} - {p.descricao} ({ref})"
    return "; ".join(achados.values())


def detectar_marca(texto: str, marcas: list[str]) -> str | None:
    """Marca do HSE escrita na descrição (palavra inteira). Só aceita quando há exatamente uma."""
    t = normalizar(texto)
    achadas = {normalizar(m): m for m in marcas
               if normalizar(m) and re.search(rf"(?<![A-Z0-9]){re.escape(normalizar(m))}(?![A-Z0-9])", t)}
    return next(iter(achadas.values())) if len(achadas) == 1 else None


def _completar(item: Item, hse: HseApi, ajuda: Ajudantes) -> tuple[Item, list[str]]:
    """Produto novo: preenche MARCA (da descrição), GRUPO e NCM (IA) que o vendedor deixou vazios."""
    n, notas = item.numero, []
    if not item.marca:
        marca = detectar_marca(f"{item.produto} {item.descricao_cadastro}", hse.marcas())
        if marca:
            item = replace(item, marca=marca)
            notas.append(f"Item {n}: marca encontrada na descrição: {marca}")
    if not item.grupo and ajuda.grupo:
        grupo = ajuda.grupo(item.descricao_cadastro, hse.grupos())
        if grupo:
            item = replace(item, grupo=grupo)
            notas.append(f"Item {n}: grupo escolhido por IA: {grupo}")
    if not item.ncm and ajuda.ncm:
        ncm = ajuda.ncm(item.descricao_cadastro)
        if ncm and hse.ncm_existe(ncm):
            item = replace(item, ncm=ncm)
            notas.append(f"Item {n}: NCM sugerido por IA: {ncm} (confira antes de faturar)")
        elif ncm:
            notas.append(f"Item {n}: NCM sugerido por IA ({ncm}) não existe no HSE")
    return item, notas


def resolver_item(item: Item, hse: HseApi, ajuda: Ajudantes | None = None) -> Resolucao:
    ajuda = ajuda or Ajudantes()
    if item.codigo:
        achados = [p for p in hse.buscar_produtos(item.codigo) if p.codigo == item.codigo]
        if not achados:
            return Resolucao(item, erro=f"código {item.codigo} não encontrado no HSE")
        if not any(p.ativo for p in achados):
            return Resolucao(item, erro=f"código {item.codigo} está inativo no HSE")
        return Resolucao(item, next(p for p in achados if p.ativo), "codigo")

    achados = _por_descricao(item.produto, hse)
    if not achados and normalizar(item.descricao_cadastro) != normalizar(item.produto):
        # o robô cadastra com a coluna O: procurar por ela evita duplicar o produto
        achados = _por_descricao(item.descricao_cadastro, hse)
    notas: list[str] = []
    if not achados and ajuda.resumir and len(item.descricao_cadastro) > MAX_DESCRICAO:
        resumo = ajuda.resumir(item.descricao_cadastro)
        if resumo:
            item = replace(item, descricao_cadastro=resumo)
            notas.append(f"Item {item.numero}: descrição de cadastro resumida por IA: {resumo}")
            achados = _por_descricao(resumo, hse)  # já cadastrado antes com esse resumo?
    if len(achados) == 1:
        return Resolucao(item, next(iter(achados.values())), "descricao", notas=tuple(notas))
    if achados:
        return Resolucao(item, erro=f"descrição encontrada em vários produtos ativos "
                                    f"({', '.join(sorted(achados))}); preencha o CÓDIGO HSE")
    existentes = _por_referencia(item, hse)
    if existentes:
        return Resolucao(item, erro=f"possível produto já cadastrado (mesma referência): {existentes}; "
                                    f"confira e preencha o CÓDIGO HSE", notas=tuple(notas))
    if item.custo > 0 and len(item.descricao_cadastro) <= MAX_DESCRICAO:  # sem isso já é ERRO: não gasta IA
        item, completados = _completar(item, hse, ajuda)
        notas += completados
    faltando = [nome for nome, ok in (("NCM", item.ncm), ("CUSTO", item.custo > 0),
                                      ("GRUPO", item.grupo), ("MARCA", item.marca)) if not ok]
    problemas = [f"sem {', '.join(faltando)}"] if faltando else []
    if len(item.descricao_cadastro) > MAX_DESCRICAO:
        problemas.append(f"DESCRIÇÃO P/ CADASTRO com {len(item.descricao_cadastro)} caracteres "
                         f"(máximo {MAX_DESCRICAO}; preencha a coluna O com uma descrição curta)")
    if problemas:
        return Resolucao(item, erro=f"produto novo {'; '.join(problemas)} "
                                    f"(não encontrado no HSE pela descrição '{item.produto[:60]}')",
                         notas=tuple(notas))
    return Resolucao(item, por="novo", notas=tuple(notas))


def validar_online(orc: Orcamento, hse: HseApi, rel: Relatorio,
                   ajuda: Ajudantes | None = None) -> tuple[Cliente | None, list[Resolucao]]:
    cliente, erro = resolver_cliente(orc.cliente, hse)
    if erro:
        rel.erro(erro)
    else:
        rel.info(f"Cliente: {cliente.codigo} - {cliente.nome} ({cliente.documento})")
    if not hse.vendedor_existe(orc.vendedor):
        rel.erro(f"Vendedor '{orc.vendedor}' não encontrado no HSE (use o nome exato da lista)")
    return cliente, [conferir_desconto(resolver_item(it, hse, ajuda)) for it in orc.itens]


def conferir_desconto(r: Resolucao) -> Resolucao:
    """Barra antes de criar qualquer coisa o item que o HSE recusaria no Incluir por desconto,
    e assim todos os itens nessa situação aparecem de uma vez no relatório."""
    if r.erro or r.produto is None or r.produto.preco is None:
        return r
    minimo = r.produto.preco * (100 - DESCONTO_MAX) / 100
    if r.item.valor_unit >= minimo:
        return r
    return replace(r, erro=f"valor unitário {moeda(r.item.valor_unit)} abaixo do mínimo {moeda(minimo)} "
                           f"(preço de tabela {moeda(r.produto.preco)}, desconto máximo {DESCONTO_MAX}%)")


def _listar_itens(rel: Relatorio, resolucoes: list[Resolucao], dry_run: bool) -> None:
    for r in resolucoes:
        n = r.item.numero
        for nota in r.notas:
            rel.info(nota)
        if r.erro:
            rel.item_erro(n, r.erro)
        elif r.por == "novo":
            if dry_run:
                rel.item_cadastraria(n, r.item)
        else:
            rel.item_existente(n, r.produto.codigo, r.produto.descricao, r.por)
    if not dry_run and rel.tem_erro:
        for r in resolucoes:
            if r.por == "novo":
                rel.item_novo_pendente(r.item.numero, r.item)


# --- fluxo -------------------------------------------------------------------

def _gravar(texto: str, destino: Path) -> None:
    try:
        destino.write_text(texto, encoding="utf-8-sig")  # BOM: acentos certos no Bloco de Notas
    except OSError as e:  # o conteúdo não se perde: vai inteiro para o robo.log
        log.error("Não consegui gravar %s (%s). Conteúdo:\n%s", destino, e, texto)


def _finalizar(path: Path, cfg: Config, texto: str, destino: str) -> str:
    pasta = cfg.pasta / destino
    if destino == "DRYRUN":
        _gravar(texto, destino_livre(pasta / f"{path.stem}.txt"))
        _marcar(cfg, "dryrun_estado.json", _hash(path), path)
        return destino
    try:
        movida = _mover(path, pasta)
    except OSError as e:
        log.error("Não consegui mover %s para %s: %s", path.name, destino, e)
        texto += f"\nERRO: a planilha não pôde ser movida para {destino} ({e}); mova manualmente\n"
        movida = path
    _gravar(texto, destino_livre(pasta / f"{movida.stem}.txt"))
    return destino


def _executar_real(orc: Orcamento, cliente: Cliente, resolucoes: list[Resolucao],
                   hse: HseApi, rel: Relatorio, pasta_pdf: Path,
                   ao_salvar: Callable[[str], None] | None = None) -> "Resultado":
    cadastrados: list[str] = []
    novos: dict[str, tuple[Produto, int]] = {}  # descrição normalizada → (produto, item que cadastrou)
    numero = None
    nome_cliente = _nome_cliente(cliente)
    try:
        pares = []
        for r in resolucoes:
            produto = r.produto
            if r.por == "novo":
                chave = normalizar(r.item.descricao_cadastro)
                if chave in novos:  # mesma peça em outra linha: reaproveita, não duplica
                    produto, origem = novos[chave]
                    rel.item_existente(r.item.numero, produto.codigo, produto.descricao,
                                       f"cadastrado no item {origem}")
                else:
                    codigo = hse.cadastrar_produto(r.item, orc.filial, salvar=True)
                    cadastrados.append(f"{codigo} - {r.item.descricao_cadastro}")
                    rel.item_cadastrado(r.item.numero, codigo, r.item)
                    produto = Produto(codigo, r.item.descricao_cadastro, True)
                    novos[chave] = (produto, r.item.numero)
            pares.append((r.item, produto))
        try:
            hse.montar_orcamento(orc, cliente, pares, incluir=True)
        finally:
            _avisos_do_hse(hse, rel)
        numero = hse.salvar_orcamento()
        if ao_salvar:
            ao_salvar(numero)
        pasta_pdf.mkdir(parents=True, exist_ok=True)
        dav = destino_livre(pasta_pdf / f"DAV_{numero}_{sanitizar(cliente.nome)}.pdf")
        hse.baixar_dav(numero, dav)
        rel.resultado = f"OK - orçamento {numero} salvo; DAV {dav.name}"
        return Resultado("pronto", numero, dav, rel.texto(), nome_cliente)
    except SalvoIncerto as e:
        if ao_salvar:
            ao_salvar(e.numero)
        log.exception("Salvar sem confirmação em %s", orc.arquivo.name)
        rel.erro(_resumo(e))
        rel.resultado = (f"ERRO - Salvar foi clicado mas não confirmei: o orçamento {e.numero} PODE ter sido "
                         f"salvo. Confira no HSE e NÃO reenvie a planilha")
        if cadastrados:
            rel.info("Produtos cadastrados no HSE (continuam lá): " + "; ".join(cadastrados))
        return Resultado("incerto", e.numero, None, rel.texto(), nome_cliente)
    except Exception as e:  # noqa: BLE001 — qualquer falha precisa desfazer o rascunho
        log.exception("Falha em %s", orc.arquivo.name)
        rel.erro(f"falha durante a criação no HSE: {_resumo(e)}")
        if numero:  # salvou mas o DAV falhou: o orçamento existe
            rel.resultado = f"ERRO - orçamento {numero} FOI SALVO no HSE, mas o DAV falhou; NÃO reenvie a planilha"
            estado = "incerto"
        else:
            rel.resultado = "ERRO - orçamento não criado"
            _desfazer_rascunho(hse, rel)
            estado = "erro"
        if cadastrados:
            rel.info("Produtos cadastrados no HSE (continuam lá): " + "; ".join(cadastrados))
        return Resultado(estado, numero, None, rel.texto(), nome_cliente)


def _desfazer_rascunho(hse: HseApi, rel: Relatorio) -> None:
    if not hse.rascunho:
        return
    pendente = hse.rascunho
    try:
        rel.info(f"rascunho {hse.cancelar_rascunho() or pendente} ficou vazio no HSE (itens removidos; "
                 "não precisa fazer nada)")
    except Exception as e:  # noqa: BLE001
        log.exception("Falha ao esvaziar rascunho %s", pendente)
        rel.erro(f"o rascunho {pendente} pode ter ficado com itens no HSE ({e}); avise o responsável pelo robô")


def _executar_dry(orc: Orcamento, cliente: Cliente, resolucoes: list[Resolucao],
                  hse: HseApi, rel: Relatorio) -> None:
    for r in resolucoes:
        if r.por == "novo":
            hse.cadastrar_produto(r.item, orc.filial, salvar=False)
    try:
        hse.montar_orcamento(orc, cliente, [(r.item, r.produto) for r in resolucoes], incluir=False)
    finally:
        _avisos_do_hse(hse, rel)
    rel.resultado = "DRY_RUN - simulação concluída sem erros (nada foi salvo)"


def _avisos_do_hse(hse: HseApi, rel: Relatorio) -> None:
    for aviso in getattr(hse, "avisos", ()):
        rel.info(f"O HSE avisou: {aviso}")


def _nome_cliente(cliente: Cliente | None) -> str:
    return f"{cliente.codigo} - {cliente.nome}" if cliente else ""


def gerar(path: Path, cfg: Config, hse: HseApi, pasta_pdf: Path,
          ao_salvar: Callable[[str], None] | None = None,
          nome: str | None = None) -> Resultado:
    """Gera o orçamento/DAV de uma planilha. Não move arquivos nem grava .txt: só devolve o resultado."""
    rel = Relatorio(nome or path.name, cfg.dry_run)
    cliente = None

    def pronto(estado: str, resultado: str = "") -> Resultado:
        if resultado:
            rel.resultado = resultado
        return Resultado(estado, None, None, rel.texto(), _nome_cliente(cliente))

    try:
        orc = ler_planilha(path)
    except ErroPlanilha as e:
        for erro in e.erros:
            rel.erro(erro)
        return pronto("erro", "ERRO na planilha (nada foi feito no HSE)")
    for aviso in orc.avisos:
        rel.info(aviso)

    try:
        cliente, resolucoes = validar_online(orc, hse, rel, ajudantes(cfg))
        _listar_itens(rel, resolucoes, cfg.dry_run)
        if rel.tem_erro:
            return pronto("erro", "ERRO na validação com o HSE (nada foi criado)")
        if cfg.dry_run:
            _executar_dry(orc, cliente, resolucoes, hse, rel)
            return pronto("simulado")
    except HseIndisponivel as e:
        log.warning("HSE indisponível ao processar %s: %s", path.name, e)
        return pronto("adiado")
    except Exception as e:  # noqa: BLE001 — antes de qualquer criação: só reporta
        log.exception("Falha inesperada em %s", path.name)
        rel.erro(_resumo(e))
        return pronto("erro", "ERRO inesperado (nada foi criado no HSE)")

    return _executar_real(orc, cliente, resolucoes, hse, rel, pasta_pdf, ao_salvar)


def processar_arquivo(path: Path, cfg: Config, hse: HseApi) -> str:
    """Retorna "PROCESSADOS" | "ERRO" | "DRYRUN" | "ADIADO"."""
    for sub in SUBPASTAS:
        (cfg.pasta / sub).mkdir(exist_ok=True)
    h = _hash(path)
    if not cfg.dry_run:
        if h in _estado(cfg, "processados_estado.json")[1]:
            log.warning("%s já gerou orçamento antes e continua na pasta; mova manualmente", path.name)
            return "ADIADO"
        if not _livre(path):
            log.info("%s está aberto em outro programa; fica para o próximo ciclo", path.name)
            return "ADIADO"

    def marcar(_numero: str) -> None:  # logo após o Salvar: uma queda durante o download não duplica o orçamento
        if not cfg.dry_run:
            _marcar(cfg, "processados_estado.json", h, path)

    r = gerar(path, cfg, hse, cfg.pasta / "DAVs", marcar)
    if r.estado == "adiado":
        return "ADIADO"
    destino = {"pronto": "PROCESSADOS", "simulado": "DRYRUN"}.get(r.estado, "DRYRUN" if cfg.dry_run else "ERRO")
    return _finalizar(path, cfg, r.relatorio, destino)


@contextmanager
def trava(cfg: Config):
    """Só um ciclo por vez (serviço + gerar_orcamento.bat): evita orçamento duplicado."""
    with open(cfg.pasta_programa / "robo.lock", "a+") as f:
        f.seek(0)  # a+ abre no fim; trava e destrava o mesmo byte 0
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def processar_pasta(cfg: Config, hse_factory: Callable, estabilidade: float = ESTABILIDADE_S) -> None:
    """Um ciclo: processa as planilhas prontas; só abre o navegador se houver trabalho."""
    with trava(cfg) as conseguiu:
        if not conseguiu:
            log.info("Outro ciclo já está rodando; pulo este")
            return
        _processar_pasta(cfg, hse_factory, estabilidade)


def _processar_pasta(cfg: Config, hse_factory: Callable, estabilidade: float) -> None:
    _, ja_feitos = _estado(cfg, _estado_nome(cfg))
    arquivos = []
    for a in arquivos_prontos(cfg.pasta, time.time(), estabilidade):
        try:
            h = _hash(a)
        except OSError as e:
            log.warning("Não consegui ler %s (%s); fica para o próximo ciclo", a.name, e)
            continue
        if h not in ja_feitos:
            arquivos.append(a)
        elif not cfg.dry_run:
            log.warning("%s já gerou orçamento antes e continua na pasta; mova manualmente", a.name)
    if not arquivos:
        return
    log.info("%d planilha(s) para processar", len(arquivos))
    try:
        with hse_factory() as hse:
            for arquivo in arquivos:
                try:
                    resultado = processar_arquivo(arquivo, cfg, hse)
                except HseIndisponivel:
                    raise
                except Exception:  # noqa: BLE001 — um arquivo ruim não trava os outros
                    log.exception("Falha ao processar %s; fica para o próximo ciclo", arquivo.name)
                    continue
                log.info("%s → %s", arquivo.name, resultado)
    except HseIndisponivel as e:
        log.warning("HSE indisponível; tento no próximo ciclo: %s", e)
