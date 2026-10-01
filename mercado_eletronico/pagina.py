"""Leitura da página de resposta do ME (`RespostaCotaItem.asp`) — sem navegador.

Recebe o HTML de UMA página de itens (o robô ou a cópia em
tests/fixtures/me_real) e devolve o que a tela precisa mostrar para o
usuário preencher: cabeçalho da cotação e, por item, descrição, quantidade,
unidade pedida, observação do comprador e os "Campos Adicionais" já lidos
por `regras.ler_campos_adicionais` (UF de entrega, origem, data de remessa).

Só lê. Quem digita é o robô (mercado_eletronico/robo.py).

Regex e não parser de DOM porque o projeto não tem nenhum, e a página é ASP
gerado por template: os ids (`spanItem_N`, `spanContratoIDN`, `quantidadeN`,
`chkItem_N`) são estáveis entre cotações e entre as duas contas — conferido
nas três cópias de 23/09/2026.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field, replace
from datetime import datetime

from mercado_eletronico.regras import UFS, PedidoDoComprador, ler_campos_adicionais

# "... GOIANIA - GO - 74672-400": a UF logo antes do CEP.
# O CEP vem torto às vezes ("55.59-000", Alpek em 28/09/2026): basta o formato.
_RE_UF_DO_LOCAL = re.compile(r"-\s*(" + "|".join(sorted(UFS)) + r")\s*-\s*\d[\d.]*-\d{3}\b")


@dataclass(frozen=True)
class ItemDaPagina:
    indice: int              # N dos campos do formulário (Preco{N}), 1..MaxItem
    numero: int              # número do item na cotação (10, 20, ...)
    produto_id: str          # value do chkItem_N
    descricao: str
    quantidade: str          # como o ME escreve: "2,00"
    unidade: str             # a pedida pelo comprador: "UND"
    obs_comprador: str
    campos_adicionais: str
    pedido: PedidoDoComprador = field(default_factory=PedidoDoComprador)
    local_entrega: str = ""


@dataclass(frozen=True)
class PaginaDaCotacao:
    numero: int
    titulo: str              # "308-029226_00002"
    comprador: str
    fornecedor: str
    data_limite: datetime | None
    obs_comprador: str
    pagina: int
    paginas: list[int]
    itens: list[ItemDaPagina]
    # Os "Atenção: ..." do comprador no alto da página (frete padrão, anexos
    # obrigatórios, horário de recebimento), sem o "Atenção:".
    avisos: list[str] = field(default_factory=list)
    # "CIF" quando o próprio formulário pede o preço CIF ("Preço a Prazo
    # CIF", Alpek em 28/09/2026); "" quando não diz.
    frete_formulario: str = ""
    # Anexos marcados com "*" (sem eles o ME não deixa nem salvar): EDP pede
    # o comercial (RDC), Oitamérica o comercial e o técnico (RDCT).
    anexos: list[dict] = field(default_factory=list)
    # O que o comprador pede a mais por item ("ref_fabricante": EDP).
    exige: tuple[str, ...] = ()


def _texto(fragmento: str) -> str:
    """HTML → texto de uma linha só: tags viram espaço, `<br>` quebra linha."""
    t = re.sub(r"<br\s*/?>", "\n", fragmento, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t).replace("\xa0", " ")
    linhas = [" ".join(l.split()) for l in t.split("\n")]
    return "\n".join(l for l in linhas if l).strip()


def _oculto(html: str, nome: str) -> str:
    m = re.search(rf'<input[^>]*name="{re.escape(nome)}"[^>]*value="([^"]*)"', html)
    return _html.unescape(m.group(1)).replace("\xa0", " ").strip() if m else ""


def _data_limite(texto: str) -> datetime | None:
    try:
        return datetime.strptime(texto, "%d/%m/%Y %H:%M")
    except ValueError:
        return None


def _item(bloco: str, indice: int) -> ItemDaPagina:
    numero = re.search(rf'id="spanItem_{indice}"[^>]*>\s*(\d+)', bloco)
    produto = re.search(rf'id="chkItem_{indice}"[^>]*value="(\d+)"', bloco)
    desc = re.search(rf'id="spanContratoID{indice}"[^>]*>(.*?)</span>', bloco, re.S)
    unidade = re.search(r"<td>\s*Unidade:\s*([^<]*)</td>", bloco)
    obs = re.search(r"Observação(?:&nbsp;|\s)*</td>\s*<td>(.*?)</td>", bloco, re.S)
    adic = re.search(r"Campos Adicionais:</b>.*?<th[^>]*>(.*?)</th>", bloco, re.S)
    local = re.search(r"Local de Entrega:(.*?)</td>", bloco, re.S)
    campos = _texto(adic.group(1)) if adic else ""
    entrega = _texto(local.group(1)).strip(" -") if local else ""
    pedido = ler_campos_adicionais(campos)
    if pedido.uf_destino is None and (m := _RE_UF_DO_LOCAL.search(entrega)):
        # EDP (28/09/2026): sem Campos Adicionais; a UF só está no endereço.
        pedido = replace(pedido, uf_destino=m.group(1))
    return ItemDaPagina(
        indice=indice,
        numero=int(numero.group(1)) if numero else 0,
        produto_id=produto.group(1) if produto else "",
        descricao=_texto(desc.group(1)) if desc else "",
        quantidade=_oculto(bloco, f"quantidade{indice}"),
        unidade=_texto(unidade.group(1)) if unidade else "",
        obs_comprador=_texto(obs.group(1)) if obs else "",
        campos_adicionais=campos,
        pedido=pedido,
        local_entrega=entrega,
    )


def ler_avisos(html: str) -> list[str]:
    """Os avisos do comprador, na ordem, sem repetir (a Alpek repete os do
    alto no pé da página)."""
    vistos: list[str] = []
    for bloco in re.findall(r'<div class="me-info"[^>]*>(.*?)</div>', html, re.S):
        texto = re.sub(r"^Aten[çc][ãa]o:\s*", "", _texto(bloco), flags=re.I).strip()
        if texto and texto not in vistos and not texto.startswith(_AVISO_DO_ME):
            vistos.append(texto)
    return vistos


# Rodapé que o ME põe em TODA cotação — não é do comprador, e fala em "enviar".
_AVISO_DO_ME = "Após preencher em todas as páginas"


def ler_anexos_obrigatorios(html: str) -> list[dict]:
    """[{"nome": "Anexo Comercial", "tipo": "RDC", "qtd": 0}] — os do cabeçalho com "*".

    Cada célula da tabela `me-anexo` tem UM link (com o TipoAnexo) e UM
    contador, na mesma ordem dos títulos: basta casar pela posição."""
    out = []
    for bloco in html.split('<table class="me-anexo"')[1:]:
        cabeca, _, corpo = bloco.partition("</thead>")
        titulos = [_texto(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", cabeca, re.S)]
        tipos = re.findall(r"TipoAnexo=(\w+)&amp;Chave1", corpo)[:len(titulos)]
        qtds = [int(q) for q in re.findall(r'anexoqtd="(\d+)"', corpo)[:len(titulos)]]
        for nome, tipo, qtd in zip(titulos, tipos, qtds + [0] * (len(titulos) - len(qtds))):
            if nome.startswith("*"):
                out.append({"nome": nome.lstrip("* ").strip(), "tipo": tipo, "qtd": qtd})
    return out


def ler_frete_formulario(html: str) -> str:
    return "CIF" if re.search(r"Pre[çc]o\s+a\s+Prazo\s+CIF", html, re.I) else ""


def ler(html: str) -> PaginaDaCotacao:
    """Uma página de itens. Levanta ValueError se não for a de resposta."""
    numero = _oculto(html, "CotacaoID")
    if not numero:
        raise ValueError("Não é a página de resposta de cotação do ME.")
    max_item = int(_oculto(html, "MaxItem") or 0)

    # Cada item começa no seu chkItem_N; o bloco vai até o próximo.
    inicios = [m.start() for m in re.finditer(r'<input[^>]*id="chkItem_\d+"', html)]
    blocos = [html[a:b] for a, b in zip(inicios, inicios[1:] + [len(html)])]
    itens = [_item(b, n) for n, b in enumerate(blocos[:max_item], start=1)]

    paginas = sorted({int(n) - 10 for n in re.findall(r"Envia\((1\d)\)", html)}) or [1]
    return PaginaDaCotacao(
        numero=int(numero),
        titulo=_oculto(html, "Resumo"),
        comprador=_oculto(html, "Nome"),
        fornecedor=_oculto(html, "NomeFor"),
        data_limite=_data_limite(_oculto(html, "DataLimite")),
        obs_comprador=_oculto(html, "ObsComp"),
        pagina=int(_oculto(html, "CurrentPage") or 1),
        paginas=paginas,
        itens=itens,
        avisos=ler_avisos(html),
        frete_formulario=ler_frete_formulario(html),
        anexos=ler_anexos_obrigatorios(html),
        exige=("ref_fabricante",) if "itatrib01_RefFabricante_1_" in html else (),
    )


def juntar(paginas: list[PaginaDaCotacao]) -> PaginaDaCotacao:
    """Todas as páginas de uma cotação como uma só, itens em ordem."""
    if not paginas:
        raise ValueError("Nenhuma página.")
    base = min(paginas, key=lambda p: p.pagina)
    itens = [i for p in sorted(paginas, key=lambda p: p.pagina) for i in p.itens]
    avisos = list(dict.fromkeys(a for p in paginas for a in p.avisos))
    frete = next((p.frete_formulario for p in paginas if p.frete_formulario), "")
    anexos = next((p.anexos for p in paginas if p.anexos), [])
    return PaginaDaCotacao(**{**base.__dict__, "itens": itens, "avisos": avisos,
                              "frete_formulario": frete, "anexos": anexos,
                              "exige": tuple(sorted({e for p in paginas for e in p.exige})),
                              "paginas": sorted({p.pagina for p in paginas} | set(base.paginas))})
