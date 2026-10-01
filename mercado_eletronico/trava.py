"""Trava de envio do robô do Mercado Eletrônico — camada PURA, sem navegador.

Regra do usuário: o robô preenche e SALVA; o envio ao comprador é sempre
humano. No ME, Salvar (Acao=9) e Confirmar (Acao=1, "enviar ao comprador")
fazem POST do mesmo form `RespCota` para a mesma URL — só o campo `Acao` do
corpo distingue. Por isso as três camadas olham o que importa:

1. clique — `botao_e_salvar`: só se clica no botão cujo title é o do Salvar;
2. formulário — `JS_TRAVA_FORM`: `form.submit()` só vale para RespCota com
   Acao liberada; qualquer outro vira no-op (injetado antes do JS do ME);
3. rede — `motivo_bloqueio`: todo POST/PUT/PATCH/DELETE aos domínios do ME
   morre, exceto RespostaCotaItem.asp com UM Acao liberado, a busca de
   leitura da lista, o login antes de logar e a CHECAGEM de ICMS do ME
   (`ConsistirICMS`, só confere a alíquota digitada — 28/09/2026: bloqueada,
   o ME pintava "Erro ao consistir ICMS" na tela da EDP).

A paginação (Acao 4 e 11..19) também grava o rascunho da página atual: o
usuário autorizou (23/09/2026), é salvamento, nunca envio.

ANEXO (28/09/2026, autorizado pelo Enzo): EDP e Oitamérica só deixam salvar
com a proposta anexada. A janela `ME/MEAnexo.aspx` sobe o arquivo num
postback ASP.NET; liberado SÓ o botão "Enviar" dela (`__EVENTTARGET` =
`UPLOAD_ALVO`) e SÓ para os tipos de anexo da resposta do fornecedor
(`TIPOS_ANEXO`: comercial e técnica), em modo de edição. Anexar não envia a
cotação: o arquivo fica no rascunho, como o resto.

EXCLUIR ANEXO (29/09/2026, autorizado pelo Enzo para o "Limpar no ME"): o
postback `grdAnexos`/`ColumnOnClick_Excluir` passa SÓ se TODOS os arquivos que
ele cita (a linha clicada e as marcadas) estão em `excluiveis` — os nomes que
o próprio robô subiu naquela cotação. Arquivo de outra pessoa: bloqueado.
Qualquer outro botão da janela continua bloqueado.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

HOSTS_ME = ("me.com.br", "mercadoe.com")
METODOS_ESCRITA = frozenset({"POST", "PUT", "PATCH", "DELETE"})

ACAO_SALVAR = "9"
ACOES_PAGINAR = frozenset({"4"} | {str(n) for n in range(11, 20)})
ACOES_LIBERADAS = frozenset({ACAO_SALVAR}) | ACOES_PAGINAR

TITULO_SALVAR = "Salvar informações para enviar mais tarde"
TEXTO_SALVAR = "Salvar"
CONFIRM_SALVAR = "Você verificou todas as informações digitadas?"
PALAVRAS_DE_ENVIO = ("comprador", "confirmar", "finalizar", "recusar", "responder")

_RE_FORM = re.compile(r"/RespostaCotaItem\.asp$", re.IGNORECASE)
_RE_LOGIN = re.compile(r"^/do/Login\.mvc/", re.IGNORECASE)
_RE_ANEXO = re.compile(r"^/ME/MEAnexo\.aspx$", re.IGNORECASE)
UPLOAD_ALVO = "ctl00$conteudo$formUpload$btnEnviar"
TIPOS_ANEXO = frozenset({"RDC", "RDCT"})   # Proposta/Anexo Comercial, Proposta Técnica
EXCLUIR_ALVO = "ctl00$conteudo$grdAnexos"
EXCLUIR_ARG = "ColumnOnClick_Excluir"
_CAMPO_SINGLE = "jsTable_ctl00$conteudo$grdAnexos_hidden_single"
_CAMPO_MULTIPLE = "jsTable_ctl00$conteudo$grdAnexos_hidden_multiple"
_RE_ALVO_MULTIPART = re.compile(r'name="__EVENTTARGET"\r?\n\r?\n([^\r\n]*)')
_RE_CONSISTIR_ICMS = re.compile(r"^/do/Cotacao\.mvc/ConsistirICMS$", re.IGNORECASE)
_RE_BUSCA = re.compile(
    r"^https://api\.web\.mercadoe\.com/supplier/transactions/v1/transactions/search$"
)


def do_me(host: str) -> bool:
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS_ME)


def acao_do_corpo(corpo: str | None) -> list[str]:
    return parse_qs(corpo or "", keep_blank_values=True).get("Acao", [])


def motivo_bloqueio(metodo: str, url: str, corpo: str | None,
                    logado: bool = True, excluiveis: frozenset[str] = frozenset()) -> str | None:
    """None = pode passar. Texto = por que a requisição tem de morrer."""
    u = urlparse(url)
    if not do_me(u.hostname or "") or metodo.upper() not in METODOS_ESCRITA:
        return None
    if metodo.upper() != "POST":
        return f"{metodo} no ME"
    if _RE_BUSCA.match(url):
        return None
    if _RE_LOGIN.match(u.path) and not logado:
        return None
    if _RE_CONSISTIR_ICMS.match(u.path) and not u.query:
        return None
    if _RE_ANEXO.match(u.path):
        return motivo_anexo(u.query, corpo, excluiveis)
    if not _RE_FORM.search(u.path):
        return f"POST fora do formulário da resposta: {u.path}"
    acoes = acao_do_corpo(corpo)
    if len(acoes) != 1 or acoes[0] not in ACOES_LIBERADAS:
        return f"Acao={acoes!r} não é salvar/paginar"
    return None


def campo_do_postback(corpo: str | None, nome: str) -> str | None:
    """Um campo de um postback ASP.NET, multipart ou urlencoded."""
    corpo = corpo or ""
    m = re.search(r'name="' + re.escape(nome) + r'"\r?\n\r?\n(.*?)\r?\n--', corpo, re.S)
    if m:
        return m.group(1)
    if 'name="' in corpo:
        return None
    valores = parse_qs(corpo, keep_blank_values=True).get(nome, [])
    return valores[0] if len(valores) == 1 else None


def alvo_do_postback(corpo: str | None) -> str | None:
    """O __EVENTTARGET de um postback ASP.NET, multipart ou urlencoded."""
    if m := _RE_ALVO_MULTIPART.search(corpo or ""):
        return m.group(1)
    return campo_do_postback(corpo, "__EVENTTARGET")


def arquivos_da_exclusao(corpo: str | None) -> set[str] | None:
    """Os NomeArquivo que um "Excluir" da janela de anexo cita (linha clicada e
    linhas marcadas). None = não deu para ler — e aí não passa."""
    import json
    nomes: set[str] = set()
    for campo in (_CAMPO_SINGLE, _CAMPO_MULTIPLE):
        bruto = campo_do_postback(corpo, campo)
        if bruto in (None, ""):
            continue
        try:
            dados = json.loads(bruto)
        except ValueError:
            return None
        for linha in dados if isinstance(dados, list) else [dados]:
            if not isinstance(linha, dict) or not linha.get("NomeArquivo"):
                return None
            nomes.add(str(linha["NomeArquivo"]))
    return nomes


def motivo_anexo(query: str, corpo: str | None,
                 excluiveis: frozenset[str] = frozenset()) -> str | None:
    q = parse_qs(query or "", keep_blank_values=True)
    tipo = q.get("TipoAnexo", [""])[0]
    if tipo not in TIPOS_ANEXO:
        return f"anexo do tipo {tipo!r} não é da resposta do fornecedor"
    if q.get("isReadOnly") != ["0"]:
        return "janela de anexo só de leitura"
    alvo = alvo_do_postback(corpo)
    if alvo == UPLOAD_ALVO:
        return None
    if alvo == EXCLUIR_ALVO and campo_do_postback(corpo, "__EVENTARGUMENT") == EXCLUIR_ARG:
        nomes = arquivos_da_exclusao(corpo)
        if not nomes:
            return "exclusão de anexo sem arquivo identificável"
        if not nomes <= excluiveis:
            return f"exclusão de anexo que o robô não subiu: {sorted(nomes - excluiveis)}"
        return None
    return "na janela de anexo, só o \"Enviar\" do arquivo (e excluir o do robô) passa"


def botao_e_salvar(titulo: str, texto: str) -> bool:
    """Só o Salvar do ME: title exato, texto exato, nada que cheire a envio."""
    titulo, texto = (titulo or "").strip(), (texto or "").strip()
    if titulo != TITULO_SALVAR or texto != TEXTO_SALVAR:
        return False
    return not any(p in titulo.lower() for p in PALAVRAS_DE_ENVIO)


def confirm_aceito(mensagem: str, salvando: bool) -> bool:
    """O único confirm aceito é o do Salvar, e só durante o clique nele."""
    return salvando and (mensagem or "").strip() == CONFIRM_SALVAR


def _js_trava_form() -> str:
    lista = ", ".join(f"'{a}'" for a in sorted(ACOES_LIBERADAS, key=int))
    return """
(() => {
  const LIBERADAS = [%s];
  const original = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function () {
    const campo = this.elements && this.elements['Acao'];
    const acao = campo && campo.value !== undefined ? String(campo.value) : null;
    if (this.name === 'RespCota' && LIBERADAS.includes(acao)) {
      console.warn('[TRAVA] RespCota Acao=' + acao + ' liberado');
      return original.call(this);
    }
    const alvo = this.elements && this.elements['__EVENTTARGET'];
    const arg = this.elements && this.elements['__EVENTARGUMENT'];
    if (/\\/ME\\/MEAnexo\\.aspx$/i.test(location.pathname) && this.id === 'aspnetForm' && alvo
        && (alvo.value === '%s'
            || (alvo.value === '%s' && arg && arg.value === '%s'))) {
      // Upload, ou excluir: a rede ainda confere QUAIS arquivos (motivo_anexo).
      console.warn('[TRAVA] anexo liberado: ' + alvo.value);
      return original.call(this);
    }
    console.warn('[TRAVA] form.submit BLOQUEADO: ' + this.name + ' Acao=' + acao);
  };
  window.open = () => null;
})();
""" % (lista, UPLOAD_ALVO, EXCLUIR_ALVO, EXCLUIR_ARG)


JS_TRAVA_FORM = _js_trava_form()
