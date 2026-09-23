"""Della Volpe — o formulário PÚBLICO deles, preenchido pelo navegador do
próprio vendedor, sem nenhum robô no meio.

Por que isto existe: pelo formulário oficial a resposta chega em 2 a 5
minutos (mesmo SLA que a automação por Playwright tinha, antes do Turnstile).
Pelo e-mail avulso (`/email/{id}/dellavolpe`), o mesmo pedido demora de 10 a
12 horas — vira um e-mail solto que uma pessoa lê na fila, em vez de cair
direto no sistema deles. É diferença grande demais para não perseguir.

Por que não é Playwright de novo: o Turnstile ("confirme que é humano")
continua lá, e continua exigindo humano de verdade — ver
carriers/dellavolpe/adapter.py e web/transportadoras.py para o histórico
completo. A diferença aqui é QUEM abre o navegador: não é mais um Chromium
automatizado que o site pode farejar, é o navegador de verdade do vendedor,
com ele mesmo resolvendo o captcha e clicando em enviar. O bookmarklet só
poupa a parte chata — digitar os mesmos ~15 campos que o Cotafrete já sabe.

Por que os dados vão no PARÂMETRO da URL, e não um fetch() para o nosso
servidor: a página da Della Volpe é HTTPS e este servidor é HTTP puro (rede
interna, sem certificado). Um fetch de https:// para http:// é bloqueado
pelo navegador como "mixed content" — não existe configuração de CORS que
destrave isso do nosso lado. Parâmetro de URL nunca esbarra nessa regra: é
só texto, lido pelo JavaScript que roda NA PÁGINA DELES depois que a aba já
carregou.

Anexo (planilha de volumes, FISPQ) fica de fora de propósito: input[type=file]
não aceita valor via JavaScript — é bloqueio de segurança do navegador,
o mesmo que impede qualquer site de "adivinhar" um arquivo do seu disco.
Quem tiver anexo, anexa à mão depois do preenchimento automático.
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlencode

from carriers.dellavolpe import mapping as m
from carriers.dellavolpe.adapter import SELETOR_POR_ROTULO
from core.models import Servico

URL_BASE = "https://dellavolpe.com.br/"

# "Qual o serviço" sai fixo: o /cotar não pergunta LTL/FTL, então toda
# cotação daqui é Fracionado -LTL (ver web/app.py::montar_request). Se um
# dia o formulário perguntar, este valor precisa vir do pedido — não antes.
SERVICO_FIXO = m.ROTULO_SERVICO[Servico.FRACIONADO_LTL]


def _dec(valor) -> Decimal | None:
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError):
        return None


def campos_por_name(c: dict, email_resposta: str | None = None
                    ) -> dict[str, str]:
    """A cotação salva (linha de `cotacao`), traduzida para os atributos
    name= REAIS do formulário da Della Volpe — os mesmos que
    carriers.dellavolpe.adapter.SELETOR_POR_ROTULO usa para o Playwright
    localizar campo. Função PURA: nenhum browser, nenhuma rede.

    Campo vazio ou ausente simplesmente não entra no resultado — é a mesma
    regra do bookmarklet: sem valor, o campo do site fica como estava.

    Nome e e-mail seguem a MESMA regra do envio automático (mapping.carimbar
    e `email_resposta`): a proposta que volta de um envio feito à mão
    precisa cair no ingestor do mesmo jeito. Sem isso, o caminho assistido
    — justamente o que existe para quando o automático não passa — seria o
    único cujo preço nunca aparece na tela."""
    por_rotulo: dict[str, str] = {
        "Qual o serviço que você procura?": SERVICO_FIXO,
        "Nome completo": (m.carimbar(c["nome_solicitante"], c.get("id"))
                          if c.get("nome_solicitante") else ""),
        "E-mail": email_resposta or c.get("email") or "",
        "WhatsApp": c.get("whatsapp_solicitante") or "",
        "CNPJ - Remetente": c.get("cnpj_remetente") or "",
        "Selecione o estado de origem": c.get("uf_origem") or "",
        "Selecione a cidade de origem": c.get("cidade_origem") or "",
        "CNPJ - Destinatário": c.get("cnpj_destinatario") or "",
        "Selecione o estado de destino": c.get("uf_destino") or "",
        "Selecione a cidade de destino": c.get("cidade_destino") or "",
        "Quantidade de Volumes": str(c.get("quantidade") or ""),
        "Tipo de Material que será transportado": c.get("material") or "",
        "CNPJ da empresa que pagará o frete": c.get("cnpj_pagador") or "",
    }

    if (peso := _dec(c.get("peso_kg"))) is not None:
        por_rotulo["Peso total"] = m.peso_br(peso)

    for rotulo, coluna in (("Comprimento", "comprimento_cm"),
                           ("Largura", "largura_cm"),
                           ("Altura", "altura_cm")):
        if (medida := _dec(c.get(coluna))) is not None:
            por_rotulo[rotulo] = m.medida_br(medida)

    if (valor_nf := _dec(c.get("valor_nf"))) is not None:
        por_rotulo["Valor total da nota fiscal"] = m.num_br(valor_nf)

    return {SELETOR_POR_ROTULO[rotulo]: valor
            for rotulo, valor in por_rotulo.items()
            if valor and rotulo in SELETOR_POR_ROTULO}


def url_formulario(c: dict, email_resposta: str | None = None) -> str:
    """O link que abre o site real da Della Volpe com os dados no parâmetro
    `cf`. Sem preenchimento nenhum por si só — quem preenche é o bookmarklet,
    rodando na aba já aberta."""
    dados = campos_por_name(c, email_resposta)
    b64 = base64.b64encode(
        json.dumps(dados, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"{URL_BASE}?{urlencode({'cf': b64})}#cotacao"


# ---------------------------------------------------------------- o script
# Roda na página da Della Volpe, DEPOIS que o vendedor clica no favorito ali.
# Não é Playwright, não é CDP, não é nada que o site consiga distinguir de
# qualquer outra extensão ou favorito de preenchimento automático — porque é
# exatamente isso que é.
#
# name= reais, não rótulo: aqui não existe get_by_label do Playwright, só
# document.querySelector. Os nomes são os MESMOS de SELETOR_POR_ROTULO.
SCRIPT_JS = """(function () {
  var p = new URLSearchParams(location.search);
  var b64 = p.get('cf');
  if (!b64) {
    alert('Cotafrete: esta aba não tem dados de cotação.\\n\\nAbra o link '
        + '"Preencher formulário" na tela da cotação, e clique neste '
        + 'favorito NESSA aba nova — não numa aba antiga da Della Volpe.');
    return;
  }

  var campos;
  try {
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    campos = JSON.parse(new TextDecoder('utf-8').decode(bytes));
  } catch (erro) {
    alert('Cotafrete: não consegui ler os dados da cotação (' + erro + ').');
    return;
  }

  function disparar(el, tipo) {
    el.dispatchEvent(new Event(tipo, { bubbles: true }));
  }

  function preencher(nome, valor) {
    if (!valor) return;
    var el = document.querySelector(
        'input[name="' + nome + '"], textarea[name="' + nome + '"]');
    if (!el) return;
    el.value = valor;
    disparar(el, 'input');
    disparar(el, 'change');
    disparar(el, 'blur');
  }

  function selecionar(nome, valor) {
    if (!valor) return false;
    var el = document.querySelector('select[name="' + nome + '"]');
    if (!el) return false;
    var opcao = Array.prototype.slice.call(el.options).find(function (o) {
      return o.value === valor || o.textContent.trim() === valor;
    });
    if (!opcao) return false;
    el.value = opcao.value;
    disparar(el, 'change');
    return true;
  }

  // A cidade só popula DEPOIS que o estado dispara o AJAX deles. Espera o
  // select ganhar mais de uma opção antes de tentar escolher — mesma
  // ideia do _esperar_opcoes do adapter Playwright, só que em JS puro.
  function esperarCidade(nomeCidade, cidade, tentativas) {
    if (!cidade) return;
    var el = document.querySelector('select[name="' + nomeCidade + '"]');
    if (!el) return;
    if (el.options.length > 1 || tentativas <= 0) {
      selecionar(nomeCidade, cidade);
      return;
    }
    setTimeout(function () {
      esperarCidade(nomeCidade, cidade, tentativas - 1);
    }, 300);
  }

  // Abre o accordion "Fazer Cotação" se ele existir e estiver fechado.
  Array.prototype.forEach.call(document.querySelectorAll('*'), function (el) {
    if (el.children.length === 0
        && /Fazer Cota[cç][aã]o|Fa[cç]a uma Cota[cç][aã]o/.test(
            el.textContent || '')) {
      el.click();
    }
  });

  setTimeout(function () {
    selecionar('servico', campos.servico);
    preencher('nome', campos.nome);
    preencher('email', campos.email);
    preencher('whatsapp', campos.whatsapp);
    preencher('cnpj_origem', campos.cnpj_origem);
    preencher('cnpj_destino', campos.cnpj_destino);
    preencher('peso', campos.peso);
    preencher('qtd-volume', campos['qtd-volume']);
    preencher('comprimento', campos.comprimento);
    preencher('largura', campos.largura);
    preencher('altura', campos.altura);
    preencher('valor', campos.valor);
    preencher('material', campos.material);
    preencher('cnpj', campos.cnpj);

    selecionar('estado_origem', campos.estado_origem);
    esperarCidade('cidade_origem', campos.cidade_origem, 15);
    selecionar('estado_destino', campos.estado_destino);
    esperarCidade('cidade_destino', campos.cidade_destino, 15);

    // O mesmo tropeço que o robô teve em 22/09/2026: escolher o serviço
    // revela os campos condicionais do CF7, e preencher o RESTO faz o site
    // re-renderizar o grupo e zerar o próprio serviço. Uma segunda escolha,
    // só se ele voltou vazio — igual ao conserto do adapter.
    var servico = document.querySelector('select[name="servico"]');
    if (servico && !servico.value) selecionar('servico', campos.servico);

    alert('Cotafrete preencheu os campos.\\n\\nConfira, resolva o captcha '
        + 'e clique em "Pedir orçamento".');
  }, 700);
})();"""


def href_bookmarklet() -> str:
    """O href= do link que o vendedor arrasta para os favoritos, uma vez só.

    quote() e não uma minificação: o script já roda direto, sem build step —
    dependência nova nenhuma só para economizar alguns bytes numa URL que o
    navegador aceita de sobra."""
    return "javascript:" + quote(SCRIPT_JS)


# ------------------------------------------------------- o script instalado
# O mesmo preenchimento do favorito, mas instalado UMA vez no Tampermonkey e
# rodando SOZINHO quando a aba da Della Volpe abre com os dados no link.
#
# Por que existe, se o favorito já funciona: o favorito pedia três gestos que
# ninguém faz direito na primeira vez — arrastar um link para a barra, abrir
# a aba certa, clicar no favorito NELA. Com o script o vendedor só clica em
# "Abrir formulário" no Cotafrete, e a aba já nasce preenchida. O captcha e o
# "Pedir orçamento" continuam sendo dele: o script não toca em nenhum dos dois.
#
# Decidido em 23/09/2026: todos os vendedores usam Chrome e podem instalar
# extensão. Tampermonkey primeiro (no ar em um dia, sem loja); uma extensão
# própria da empresa fica para quando o uso provar que vale.
VERSAO_USERSCRIPT = "1.0.0"

# Onde o script roda. A Della Volpe, com e sem "www". E as páginas
# /dellavolpe/N do próprio Cotafrete — lá ele não preenche nada, só deixa uma
# marca para a página saber que o script está instalado e esconder o passo a
# passo da instalação. O Cotafrete roda em mais de um endereço (localhost,
# IP da rede, cotafrete.ventura.inf.br), daí o host livre.
_CABECALHO = """// ==UserScript==
// @name         Cotafrete — Della Volpe
// @namespace    https://cotafrete.ventura.inf.br/
// @version      {versao}
// @description  Preenche o formulário de cotação da Della Volpe com os dados que o Cotafrete manda no link. Quem resolve o captcha e envia continua sendo você.
// @match        https://dellavolpe.com.br/*
// @match        https://www.dellavolpe.com.br/*
// @match        *://*/dellavolpe/*
// @run-at       document-idle
// @grant        none
// @updateURL    {url}
// @downloadURL  {url}
// ==/UserScript==
"""

_CORPO = """(function () {
  if (!/(^|\\.)dellavolpe\\.com\\.br$/.test(location.hostname)) {
    // Tela do Cotafrete: só avisa que o script está instalado.
    document.documentElement.setAttribute('data-cotafrete-dv', '__VERSAO__');
    return;
  }
  // Visita normal ao site da Della Volpe, sem dados no link: nada a fazer,
  // e nenhum aviso — o vendedor pode estar só olhando o site.
  if (!new URLSearchParams(location.search).get('cf')) return;

  // O formulário é montado por JavaScript do site e mora dentro de um
  // acordeão. Espera o select de serviço existir, até 15 s.
  var tentativas = 50;
  (function esperar() {
    if (document.querySelector('select[name="servico"]') || tentativas-- <= 0) {
      __PREENCHER__
      return;
    }
    setTimeout(esperar, 300);
  })();
})();
"""


def userscript(url_do_script: str) -> str:
    """O arquivo .user.js que o Tampermonkey instala.

    `url_do_script` é o endereço deste mesmo arquivo no Cotafrete: o
    Tampermonkey volta lá para buscar versão nova, e é assim que uma
    correção chega a todas as máquinas sem ninguém reinstalar nada."""
    corpo = (_CORPO.replace("__VERSAO__", VERSAO_USERSCRIPT)
             .replace("__PREENCHER__", SCRIPT_JS))
    return _CABECALHO.format(versao=VERSAO_USERSCRIPT,
                             url=url_do_script) + corpo
