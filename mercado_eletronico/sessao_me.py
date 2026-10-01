"""Uma sessão NOVA do ME para o vendedor abrir a cotação já na conta certa.

O ME guarda uma conta logada por navegador; o link da cotação abria na conta
que estivesse logada, e o login com `?dest=` é ignorado por quem já está
logado (29/09/2026). A saída sem mandar a SENHA ao navegador: o servidor faz
um login novo daquela conta e entrega só os dois cookies da sessão
(`ASP.NET_SessionId` e `ME`, ambos httpOnly) à extensão do CotaFrete, que os
põe no Chrome do vendedor e abre a cotação (web/me_extensao.py).

Provado no ME real (29/09/2026): a cópia da sessão abre a cotação na conta
certa, e nem a sessão do servidor nem a salva do robô caem — o ME aceita
várias sessões da mesma conta.

O login é pela `robo.Sessao` (mesmas travas: nada além do login sai) numa
pasta temporária, para não tocar no estado.json do robô.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from mercado_eletronico import logins as L
from mercado_eletronico import robo as R

COOKIES_DA_SESSAO = ("ASP.NET_SessionId", "ME")
URL_LOGIN = "https://www.me.com.br/do/Login.mvc/LoginNew/"

# Identidade fixa da extensão (Chrome deriva o ID da chave pública do
# manifesto). Só a pública existe: extensão carregada sem empacotar não
# precisa da privada. O ID sai desta chave — tests/test_me_extensao.py confere.
CHAVE_PUBLICA = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAzxi0WQLP2u18CHHTuSyEC2VnWQvt0p029KJjrze54zn6FjUW"
    "/GgImcbek72KiSDKMeq0H0sn5a2iNHem5XS1PgiGP9DpIfWBuftvx49+/r6QdiS+7Jjs8k05V9VEABHmWeJFBtWobeNE"
    "jc2ntzL0E7C5Sbc7iI2NF7LzVRuP0wQ1ddOxynxjrBJayiRFTU4/2/L8GvZIytAC82BmFcpdYGRUHV9tjEmVqskRId8Z"
    "S2eBL5FOc7AB5wAFG7wDLukVTHqURgYOtsNZNPVZwICFDR9E73OQukm5Z2OEJJy/sU0R3+Rt/gEyxUTqCNR+CwagvjuF"
    "1l04W93C/H/nOJN6nwIDAQAB")
EXTENSAO_ID = "lonngcfhgkifjckgafjlemkolaehphnf"


def id_da_extensao(chave_b64: str = CHAVE_PUBLICA) -> str:
    """Como o Chrome calcula o ID: sha256 da chave (DER), 32 primeiros
    dígitos hex trocados por a..p."""
    import base64
    import hashlib
    digest = hashlib.sha256(base64.b64decode(chave_b64)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def url_da_cotacao(numero: int) -> str:
    """O link da LISTA de Oportunidades (redireciona ao formulário): abre até
    a cotação que o link direto não abre (robo.URL_PELA_LISTA)."""
    return R.URL_PELA_LISTA.format(n=int(numero))


def sessao_nova(chave: str) -> list[dict]:
    """Login novo na conta `chave`; devolve só os cookies da sessão."""
    login = L.de(chave)
    if not login.credenciais():
        raise R.RoboRecusou(f"Faltam {login.prefixo}_LOGIN / {login.prefixo}_SENHA no .env.")
    with tempfile.TemporaryDirectory() as tmp:
        with R.Sessao(login, pasta=Path(tmp)) as s:
            s.page.goto(URL_LOGIN, wait_until="domcontentloaded")
            s.login()
            cookies = [c for c in s.ctx.cookies("https://www.me.com.br")
                       if c["name"] in COOKIES_DA_SESSAO]
    if {c["name"] for c in cookies} != set(COOKIES_DA_SESSAO):
        raise R.RoboRecusou("o ME não devolveu a sessão depois do login")
    return [{"name": c["name"], "value": c["value"], "path": c.get("path") or "/",
             "expires": c.get("expires", -1)} for c in cookies]
