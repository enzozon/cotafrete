"""O formulário de resposta de CADA comprador — e o plano adaptado a ele.

O ME não tem um formulário só: cada comprador configura o seu (recon de
28/09/2026, quatro compradores além do ME geral):

- EDP: NCM se chama `NBM`; sem origem, PIS, COFINS, data e base; exige
  "Ref Fabricante" por item e Contato Principal, Telefone e E-mail.
- Alpek: "Preço a Prazo CIF", valor de frete, só "30 DDL", sem IE.
- WEG: condição já marcada (28 dias), "LUGAR DE ENTREGA" obrigatório,
  moeda por item, IPI sem a opção "Isento", sem Fabricante.
- Oitamérica: sem impostos por item, condição travada, e três campos
  obrigatórios que são DECISÃO da empresa (tipo de pagamento e dois "estou de
  acordo").

Em vez de um robô por comprador, o robô LÊ o formulário da página e o plano
(mapa.plano_pagina, escrito para o ME geral) é adaptado a ele:

- campo que existe: vai; select com outro código para a mesma coisa é
  traduzido (moeda "BRL" ↔ "R$", IPI "Isento" → "Não" onde não há Isento);
- NCM vira NBM onde é esse o nome;
- campo que só informa (PIS, COFINS, origem, base, data...) e a página não
  tem: sai do plano — o comprador não pediu;
- campo ESSENCIAL (preço, prazo, NCM) que não existe, ou campo obrigatório
  do cabeçalho que o robô não conhece: PARA, com o rótulo no motivo. Um
  comprador novo ou funciona ou diz o que falta — nunca salva pela metade.

Sem navegador, exceto `ler` (um evaluate na página).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mercado_eletronico import regras as R
from mercado_eletronico.regras import Conta, EntradaItem


@dataclass(frozen=True)
class Campo:
    tipo: str                           # select / text / textarea / checkbox
    valor: str = ""
    opcoes: tuple[tuple[str, str], ...] = ()   # (value, texto)
    rotulo: str = ""                    # do cabeçalho; "*" = obrigatório
    somente_leitura: bool = False

    @property
    def obrigatorio(self) -> bool:
        return self.rotulo.startswith("*")

    def tem_opcao(self, valor: str) -> bool:
        return any(v == valor for v, _ in self.opcoes)


Formulario = dict[str, Campo]   # name (sem o espaço do fim que o ME às vezes põe)

JS_FORMULARIO = r"""
() => {
  const f = document.forms['RespCota'];
  if (!f) return null;
  const out = {};
  for (const e of f.elements) {
    if (!e.name || e.type === 'hidden' || e.type === 'button' || e.type === 'submit') continue;
    let rotulo = '';
    const td = e.closest('td');
    if (td) {
      let p = td.previousElementSibling;
      while (p && !p.innerText.trim()) p = p.previousElementSibling;
      rotulo = p ? p.innerText.trim().split('\n')[0] : '';
    }
    out[e.name.trim()] = {
      tipo: e.tagName === 'SELECT' ? 'select' : (e.tagName === 'TEXTAREA' ? 'textarea' : e.type),
      valor: e.type === 'checkbox' ? String(e.checked) : (e.value || ''),
      opcoes: e.tagName === 'SELECT' ? [...e.options].map(o => [o.value, o.text.trim()]) : [],
      rotulo: rotulo.slice(0, 80),
      somente_leitura: !!(e.readOnly || e.disabled),
    };
  }
  return out;
}
"""


# Anexo marcado com "*" no cabeçalho ("* Anexo Comercial", EDP) e a célula
# embaixo dizendo "Nenhum anexo existente": o ME não deixa nem SALVAR o
# rascunho (28/09/2026: o clique no Salvar não gerou POST; o ME só pintou o
# anexo de vermelho).
JS_ANEXOS_OBRIGATORIOS = r"""
() => {
  const out = [];
  for (const tab of document.querySelectorAll('table.me-anexo')) {
    const titulos = tab.tHead && tab.tHead.rows[0] ? [...tab.tHead.rows[0].cells] : [];
    const corpo = tab.tBodies[0] && tab.tBodies[0].rows[0];
    titulos.forEach((c, i) => {
      const nome = c.innerText.trim();
      if (!/^\*/.test(nome) || !corpo || !corpo.cells[i]) return;
      const cel = corpo.cells[i];
      const qtd = cel.querySelector('[anexoqtd]');
      const a = cel.querySelector('a[href^="javascript:exibirPopupAnexos"]');
      const args = a ? [...a.getAttribute('href').matchAll(/"([^"]*)"/g)].map(m => m[1]) : [];
      const tipo = (args[0] || '').match(/TipoAnexo=(\w+)/);
      out.push({nome: nome.replace(/^\*\s*/, ''), tipo: tipo ? tipo[1] : '',
                qtd: qtd ? parseInt(qtd.getAttribute('anexoqtd') || '0') : 0,
                url: args.length === 3 ? 'ME/MEAnexo.aspx?' + args[0] + '&' + args[1] + '&hash=' + args[2] : ''});
    });
  }
  return out;
}
"""


@dataclass(frozen=True)
class Anexo:
    """Anexo que o comprador marcou com "*" no cabeçalho da cotação."""
    nome: str        # "Anexo Comercial"
    tipo: str        # TipoAnexo do ME: "RDC"...
    qtd: int         # quantos já estão no ME
    url: str = ""    # a janela de upload (MEAnexo.aspx, com o hash do ME)


def anexos_obrigatorios(page) -> list[Anexo]:
    return [Anexo(**a) for a in page.evaluate(JS_ANEXOS_OBRIGATORIOS)]


def anexos_faltando(page) -> list[str]:
    return [a.nome for a in anexos_obrigatorios(page) if a.qtd == 0]


def ler(page) -> Formulario:
    bruto = page.evaluate(JS_FORMULARIO)
    if bruto is None:
        raise ValueError("a página não tem o formulário de resposta")
    return {k: Campo(v["tipo"], v["valor"], tuple(map(tuple, v["opcoes"])), v["rotulo"],
                     v["somente_leitura"]) for k, v in bruto.items()}


# ------------------------------------------------------------- as decisões
# Decisões do Enzo (28/09/2026) para os campos que só alguns compradores pedem.
CONTATO = "Eliziane Amorim"
EMAIL = "vendas@venturainformatica.com.br"
TELEFONE = R.CAMPOS_FIXOS_COTACAO["telefone_contato"]
# "LUGAR DE ENTREGA" da WEG: o endereço da empresa (é FOB, a WEG retira).
# As três empresas ficam no mesmo endereço (Enzo, 28/09/2026). Vazio = não
# informado → o robô para nessa página e diz o porquê.
_ENDERECO_EMPRESAS = "R. Sete, nº 560 - Cocal, Vila Velha - ES, 29105-770"
ENDERECO: dict[Conta, str] = {Conta.VENTURA: _ENDERECO_EMPRESAS,
                              Conta.UNIAO: _ENDERECO_EMPRESAS,
                              Conta.ALIANCA: _ENDERECO_EMPRESAS}

# Campos do cabeçalho que só alguns compradores têm e o robô sabe preencher.
# name → função (empresa) → valor
EXTRAS_CABECALHO = {
    "atrib_ContatoPrincipal_1_1_0_0": lambda empresa: CONTATO,
    "atrib_TelefonedeContato_1_3_0_0": lambda empresa: TELEFONE,
    "atrib_Email_1_1_0_8": lambda empresa: EMAIL,
    "atrib_LOCALFRETE_1_1_0_0": lambda empresa: ENDERECO.get(empresa, ""),
    # Oitamérica: "Estou de acordo" com o Comunicado aos Fornecedores e com as
    # Condições Gerais de Compra — o Enzo autorizou marcar (28/09/2026).
    "atrib_1COMUNICADO_1_5_0_0": lambda empresa: "Sim",
    "atrib_2CONDICOESGERAIS_1_5_0_0": lambda empresa: "Sim",
    # "Tipo de Pagamento" (boleto/depósito) da Oitamérica: SEM decisão ainda —
    # fica fora daqui e o robô para nele, dizendo o nome do campo.
}

# Campos do item que só INFORMAM o que a empresa cobra: se o comprador não
# pediu (não estão no formulário dele), saem do plano.
SO_INFORMAM = {
    "PIS", "PISIncluso", "COFINS", "COFINSIncluso", "OrigMat", "DataEntregaItemAux",
    "AliquotaSubstituicaoTributaria", "ValorSubstituicaoTributaria", "BaseCalculo",
    "BaseCalculoImposto", "SubstituicaoTributaria", "UnidadeResp", "TipoImposto",
    "IPI", "IPIIncluso", "ICMS", "ICMSIncluso", "Fabricante", "Observacao",
}
ESSENCIAIS = {"Preco", "Prazo", "NCM"}
# Cabeçalho que alguns não têm e tudo bem.
CABECALHO_OPCIONAL = {"atrib_CidadeEstado_1_1_0_0", "NumFoneCota", "ObsForn",
                      "ValidadePropostaAux", "InscricaoEstadual"}
# Campos obrigatórios de tela que não são resposta (filtros, recusa da cotação).
NAO_SAO_RESPOSTA = {"MotivoRecusa", "OrdemExibicao", "FiltroProduto", "FiltroLiberados",
                    "PercentualDesconto", "LimiteFat", "CustoFinanceiro", "Frete"}

_RE_ITEM = re.compile(r"^([A-Za-z]+?)(\d+)$")
_RE_60 = re.compile(r"^\s*60\s*(dias|ddl)\b", re.IGNORECASE)


class FormularioDesconhecido(ValueError):
    """O formulário deste comprador pede algo que o robô não sabe responder."""


def _moeda(campo: Campo) -> str | None:
    for v, t in campo.opcoes:
        if v in ("BRL", "R$") or re.search(r"\breal\b", t, re.I):
            return v
    return None


def condicao_pagamento(campo: Campo, planejada: str) -> str:
    """Decisão do Enzo (28/09/2026): a do comprador quando ele já marcou, travou
    ou só oferece uma; vazio → 60 dias (o código do ME geral, ou a opção
    "60 dias"/"60 DDL" deste comprador)."""
    opcoes = [v for v, _ in campo.opcoes if v]
    if campo.valor or campo.somente_leitura:
        return campo.valor
    if len(opcoes) == 1:
        return opcoes[0]
    if campo.tem_opcao(planejada):
        return planejada
    for v, t in campo.opcoes:
        if v and _RE_60.match(t):
            return v
    raise FormularioDesconhecido("condição de pagamento: nenhuma opção de 60 dias neste comprador")


def _traduzir(nome: str, base: str, valor: str, campo: Campo) -> str:
    if campo.tipo != "select" or campo.tem_opcao(valor):
        return valor
    if base == "IPIIncluso" and valor == "I" and campo.tem_opcao("N"):
        return "N"                       # IPI 0 sem "Isento" (WEG): "Não" incluso
    if nome == "MoedaCot" and (m := _moeda(campo)):
        return m
    if base == "Moeda" and (m := _moeda(campo)):
        return m
    rotulos = ", ".join(t for v, t in campo.opcoes if v)[:120]
    raise FormularioDesconhecido(f"{nome}: a opção {valor!r} não existe neste comprador ({rotulos})")


def adaptar(campos: dict[str, str], marcar: list[int], form: Formulario, *,
            empresa: Conta, itens: dict[int, EntradaItem | None] | None = None,
            unidades: dict[int, str] | None = None, limpeza: bool = False) -> dict[str, str]:
    """Os campos do plano (nomes do ME geral) nos nomes e códigos DESTA página."""
    itens = itens or {}
    out: dict[str, str] = {}
    for nome, valor in campos.items():
        m = _RE_ITEM.match(nome)
        base, indice = (m.group(1), m.group(2)) if m else (nome, "")
        if nome in form and form[nome].somente_leitura:
            continue   # travado pelo comprador (Oitamérica: "30 DIAS"): fica o dele
        if nome == "CondicaoPagamento" and nome in form:
            out[nome] = condicao_pagamento(form[nome], valor)
        elif base == "UnidadeResp" and nome in form and form[nome].tipo != "select":
            # Unidade em texto livre (EDP): responde na unidade que o comprador
            # pediu ("PEÇ"), não no código do ME geral.
            pedida = (unidades or {}).get(int(indice), "")
            out[nome] = pedida or valor
        elif (nome in form and base in SO_INFORMAM and form[nome].tipo == "select"
              and not any(v for v, _ in form[nome].opcoes)):
            # Select sem nenhuma opção: o comprador desligou essa resposta
            # (Alpek, "% Incluso": exibeIPISim/Nao/Isento todos false).
            continue
        elif nome in form:
            try:
                out[nome] = _traduzir(nome, base, valor, form[nome])
            except FormularioDesconhecido:
                if not (limpeza and base in SO_INFORMAM):
                    raise
                # Limpar: o comprador não deixa esvaziar (WEG: tipo de imposto
                # só "IPI") — fica como está; o que importa (preço etc.) sai.
        elif base == "NCM" and f"NBM{indice}" in form:
            out[f"NBM{indice}"] = valor
        elif base in SO_INFORMAM or nome in CABECALHO_OPCIONAL or nome.startswith("txtJustificativa"):
            continue
        elif base in ESSENCIAIS and limpeza:
            continue
        else:
            rot = "NCM" if base == "NCM" else nome
            raise FormularioDesconhecido(f"o formulário deste comprador não tem o campo {rot}")

    # O que só alguns compradores pedem.
    for nome, valor_de in EXTRAS_CABECALHO.items():
        if nome in form and not form[nome].valor and nome not in out:
            valor = valor_de(empresa)
            if not valor:
                raise FormularioDesconhecido(
                    f"\"{form[nome].rotulo.lstrip('* ')}\" é obrigatório neste comprador e "
                    f"ainda não tem valor definido para a {empresa.name}")
            out[nome] = _traduzir(nome, nome, valor, form[nome])
    if "NomeContato" in form and not form["NomeContato"].valor:
        out["NomeContato"] = CONTATO
    if not limpeza:
        for i in marcar:
            if f"itatrib01_RefFabricante_1_{i}" in form:
                ref = (getattr(itens.get(i), "ref_fabricante", "") or "").strip()
                if not ref:
                    num = getattr(itens.get(i), "numero", i)
                    raise FormularioDesconhecido(f"item {num}: este comprador exige a Ref. Fabricante")
                out[f"itatrib01_RefFabricante_1_{i}"] = ref
            if f"Moeda{i}" in form and not form[f"Moeda{i}"].valor:
                out[f"Moeda{i}"] = _traduzir(f"Moeda{i}", "Moeda", "BRL", form[f"Moeda{i}"])

    # Obrigatório do cabeçalho que ninguém preencheu: parar e dizer qual.
    faltam = [c.rotulo.lstrip("* ").rstrip(":") for n, c in form.items()
              if c.obrigatorio and not c.somente_leitura and not c.valor
              and n not in out and n not in NAO_SAO_RESPOSTA and not _RE_ITEM.match(n)
              and not n.startswith(("itatrib", "chkItem", "txtJustificativa"))]
    if faltam and not limpeza:   # limpar só apaga; o próprio ME valida o resto
        raise FormularioDesconhecido(
            "campos obrigatórios deste comprador que o robô não sabe responder: "
            + "; ".join(faltam) + ". Responda pelo site do ME.")
    return out


def exige(html: str) -> tuple[str, ...]:
    """O que este comprador pede a mais NA TELA (lido do HTML salvo)."""
    return ("ref_fabricante",) if "itatrib01_RefFabricante_1_" in html else ()
