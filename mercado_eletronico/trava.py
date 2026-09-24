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
   leitura da lista e o login antes de logar.

A paginação (Acao 4 e 11..19) também grava o rascunho da página atual: o
usuário autorizou (23/09/2026), é salvamento, nunca envio.
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
_RE_BUSCA = re.compile(
    r"^https://api\.web\.mercadoe\.com/supplier/transactions/v1/transactions/search$"
)


def do_me(host: str) -> bool:
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS_ME)


def acao_do_corpo(corpo: str | None) -> list[str]:
    return parse_qs(corpo or "", keep_blank_values=True).get("Acao", [])


def motivo_bloqueio(metodo: str, url: str, corpo: str | None,
                    logado: bool = True) -> str | None:
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
    if not _RE_FORM.search(u.path):
        return f"POST fora do formulário da resposta: {u.path}"
    acoes = acao_do_corpo(corpo)
    if len(acoes) != 1 or acoes[0] not in ACOES_LIBERADAS:
        return f"Acao={acoes!r} não é salvar/paginar"
    return None


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
    console.warn('[TRAVA] form.submit BLOQUEADO: ' + this.name + ' Acao=' + acao);
  };
  window.open = () => null;
})();
""" % lista


JS_TRAVA_FORM = _js_trava_form()
