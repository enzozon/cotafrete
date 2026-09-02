"""Cotafrete — interface do usuário.

    python -m uvicorn web.app:app --port 8001
    # abre http://localhost:8001  (a 8000 e do Servidor.bat, na rede)

FASE 1 do plano: formulário único, as duas transportadoras que devolvem preço
na hora (Camilo e Jadlog) e os três cartões de WhatsApp. Generoso e Della
Volpe entram na fase 2 — são assíncronas e levam ~2 min.

Decisões de tela, todas documentadas em REGRAS_SITE_COTACAO.md:

- UM formulário e UM botão. Ninguém quer "cotar na Camilo"; quer saber quem
  leva mais barato.
- Resultado em DOIS grupos, porque as naturezas são diferentes: as
  automáticas o robô resolve; as de WhatsApp dependem de a pessoa apertar
  enviar.
- Cidade e estado NÃO são campos: saem do CEP. Foi digitar cidade à mão que
  gerou uma ficha dizendo "São José dos Campos" com CEP de São Bernardo.
- Quem falhou aparece COM o erro. Sumir com a transportadora que deu
  problema foi o bug que custou horas neste projeto.

O login é placeholder de propósito: digitou um nome, entrou. Serve para
separar o histórico por pessoa. Não é autenticação e não deve ser exposto
fora da rede local sem virar autenticação de verdade.
"""

from __future__ import annotations

import base64
import os
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import Cookie, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(override=False)

from carriers.braspress.adapter import BraspressAdapter
from carriers.camilo.adapter import CamiloAdapter
from carriers.dellavolpe import bookmarklet as dv_bookmarklet
from carriers.generoso.adapter import GenerosoAdapter
from carriers.jadlog.painel import JadlogPainelAdapter
from carriers.translovato.adapter import TranslovatoAdapter
from core import cep as buscador_cep
from core import cnpj as buscador_cnpj
from core import selecao
from core.banco import Banco
from core.retentativa import (
    ESPERA_MAXIMA_S, SEM_REPETICAO, TENTATIVAS_MAXIMAS, cotar_com_retentativa,
)
from web import adm, transportadoras
from web.layout import LOGO, e, moeda, pagina
from core.models import (
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, StatusCotacao, TipoFrete, Volume, limpa_doc,
)

app = FastAPI(title="Cotafrete — Ventura")
banco = Banco()

app.include_router(adm.router)
# O painel usa o MESMO banco do resto do sistema. Injetado aqui, e não
# importado lá, porque `web/adm.py` importar `web/app.py` seria circular.
adm.banco = banco

# Quantas transportadoras rodam juntas, quantas vezes se tenta de novo e por
# quanto tempo: tudo em core/retentativa.py, porque as três decisões dependem
# umas das outras. ESPERA_MAXIMA_S é usado aqui embaixo pela TELA — e é de
# propósito que seja o MESMO número que a retentativa respeita: se a tela
# desistisse antes, a última tentativa terminaria falando sozinha.

# Qual tentativa cada transportadora está fazendo agora, por cotação.
#
# Vive na memória e não no banco porque só serve para a tela: se o processo
# reiniciar, a tentativa morreu junto e o número não quer dizer mais nada.
# Uma coluna guardaria para sempre um estado que dura 40 segundos.
TENTATIVAS_EM_CURSO: dict[tuple[int, str], int] = {}

COOKIE = "cotafrete_usuario"

# Só atendem por WhatsApp. O resultado delas NUNCA é automático: o máximo que
# o sistema sabe é que a mensagem foi aberta para envio.
#
# O cadastro (nome, número, logo) mora em web/transportadoras.py: acrescentar
# uma é UMA linha lá, e nada aqui. Quem ainda não tem número não entra na
# lista — ver a explicação no topo daquele arquivo.
app.mount("/logos", StaticFiles(directory=transportadoras.PASTA_LOGOS),
          name="logos")

# Prints reais do fluxo da Della Volpe (favoritos, alerta de preenchimento,
# captcha resolvido) — tirados pelo próprio Enzo em 01/09/2026, usados só no
# tutorial de `/dellavolpe/{id}`. Pasta própria porque `/logos` tem teste
# checando "todo arquivo aqui é logo de alguma transportadora" (ver
# tests/test_transportadoras.py) — misturar quebraria essa checagem.
PASTA_AJUDA = Path(__file__).parent / "ajuda"
app.mount("/ajuda", StaticFiles(directory=PASTA_AJUDA), name="ajuda")

# Limites que precisam aparecer ANTES de cotar. A Della Volpe recusa abaixo
# de 1 kg; deixar o usuario esperar 2 minutos para receber "peso invalido" e
# desrespeitoso com o tempo dele.
PESO_MINIMO_KG = Decimal("1")

# Menor medida que faz sentido num campo de CENTÍMETROS. Não existe carga de
# meio centímetro; o que existe é gente digitando metro. Ver a explicação em
# validar_formulario.
MEDIDA_MINIMA_CM = Decimal("1")

# Quem roda automaticamente. A tela usa para saber quantos resultados esperar
# e decidir se ainda esta cotando.
#
# A Della Volpe SAIU daqui em 31/08/2026. Eles puseram Cloudflare Turnstile no
# formulário público — uma caixa "Confirme que é humano" — e sem ela marcada o
# Contact Form 7 recusa como spam sem gerar e-mail nenhum (cotações #78 a #84).
# Enquanto ela estivesse nesta lista, toda cotação gastaria uma vaga de
# navegador para terminar num cartão vermelho que ninguém consegue resolver.
# Hoje ela é acionada pelo vendedor: ver POR_EMAIL em web/transportadoras.py.
AUTOMATICAS = ("camilo", "jadlog", "translovato", "generoso", "braspress")

# As 17 DISTINTAS. A Translovato conta uma vez so: ela e automatica E tem
# WhatsApp. dict.fromkeys em vez de set para a ordem nao mudar a cada
# reinicio do servidor — tela que troca de ordem sozinha confunde quem usa.
TODAS_AS_SLUGS = tuple(dict.fromkeys(
    [*AUTOMATICAS, *(r.slug for r in transportadoras.com_whatsapp()),
     *(r.slug for r in transportadoras.com_email())]))


# Sobrevive à requisição de propósito: o /cotar dispara as transportadoras e
# devolve a tela na hora; cada uma grava o próprio resultado quando termina.
# Sem isso o usuário encara 2 minutos de tela branca para ver a Jadlog, que
# responde em 15 segundos.
#
# Uma vaga por automática, derivado e não fixo. Estava em 4 quando entrou a
# quinta: a última da lista — a Della Volpe — deixava de ser ACEITA e ficava
# esperando thread livre em vez de esperar vaga de navegador. Quem limita o
# peso na máquina é o semáforo NAVEGADORES_SIMULTANEOS, em core/retentativa.py;
# o executor só precisa caber todo mundo.
EXECUTOR = ThreadPoolExecutor(max_workers=len(AUTOMATICAS),
                              thread_name_prefix="cotacao")


def automaticas_da(escolhidas: str | None) -> tuple[str, ...]:
    """Quais automáticas participam DESTA cotação.

    Usada nos dois lugares que precisam concordar: quem é despachada em
    /cotar e quem a tela espera em /cotacao/{id}. Se as duas divergissem, a
    página ficaria esperando resultado de quem nunca foi chamado — ou pior,
    daria a cotação por completa com uma transportadora faltando."""
    return tuple(s for s in AUTOMATICAS if selecao.entra(s, escolhidas))

# Na subida nada pode estar em andamento: o que ficou pendente morreu junto
# com o processo anterior. Fechar aqui evita cartão girando para sempre.
#
# Vem de AUTOMATICAS, e não de uma lista à parte: a lista à parte parou em
# ("camilo", "jadlog") quando a Translovato entrou, e cotação interrompida
# dela ficava girando para sempre. A Generoso é a mais lenta de todas — a
# mais provável de estar no meio do caminho quando alguém fecha a janela.
_orfas = banco.marcar_interrompidas(AUTOMATICAS)
if _orfas:
    print(f"[cotafrete] {_orfas} cotação(ões) pendente(s) marcadas como "
          f"interrompidas — o sistema foi fechado durante elas.")

# A Della Volpe é a única automática que envia um formulário PÚBLICO: cada
# submissão vira uma cotação na fila de um vendedor da transportadora. Por
# isso o adapter exige DV_ENVIO_REAL_AUTORIZADO=sim e, sem a variável, recusa
# o envio — o que é o comportamento certo, mas em silêncio vira um cartão
# vermelho com texto de programador em TODA cotação.
#
# Este aviso existe para a variável faltando ser vista aqui, na subida, e não
# descoberta pelo vendedor no meio de uma cotação.
if "dellavolpe" in AUTOMATICAS and os.getenv("DV_ENVIO_REAL_AUTORIZADO") != "sim":
    print("[cotafrete] AVISO: a Della Volpe está ligada mas o envio real "
          "está travado.")
    print("            Nenhuma cotação vai chegar nela enquanto a linha")
    print("            DV_ENVIO_REAL_AUTORIZADO do arquivo .env desta pasta")
    print("            não disser 'sim'.")

# Logo das automaticas. As de WhatsApp trazem a sua do cadastro
# (web/transportadoras.py); estas quatro nao passam por la.
#
# Slug sem arquivo aqui desenha um espaco vazio no lugar — melhor do que uma
# imagem quebrada. O par e conferido nos dois sentidos por
# tests/test_transportadoras.py: nome cadastrado tem que existir no disco, e
# arquivo no disco tem que estar cadastrado.
LOGOS_AUTOMATICAS = {
    "camilo": "camilo.png",
    "jadlog": "jadlog.png",
    "generoso": "generoso.png",
    # MAIUSCULA de proposito: e o nome exato do arquivo que o Enzo colocou
    # nas duas pastas em 26/08/2026. Renomear para minuscula deixaria um
    # arquivo orfao em cotafrete-producao, onde ele foi posto a mao.
    "dellavolpe": "DELLAVOLPE.png",
    "braspress": "braspress.png",
}

NOMES = {"camilo": "Camilo dos Santos", "jadlog": "Jadlog Entregas",
         "translovato": "Translovato", "generoso": "Transporte Generoso",
         "dellavolpe": "Della Volpe", "braspress": "Braspress"}
NOTAS = {
    "camilo": "Frete fracionado, com coleta. Preço já com taxas e ICMS.",
    "jadlog": "Etiqueta pré-paga, cotada por volume. Você leva ao balcão.",
    "translovato": "Frete fracionado, com coleta. Só atende parte do país — fora da malha ela avisa.",
    "generoso": ("Frete fracionado, com coleta. Cotada com a empresa do "
                 "grupo que você informou no formulário."),
    # A ÚNICA automática que não devolve preço na tela. Se a nota não disser
    # isso, o vendedor lê "Cotação enviada" e fica esperando um número que
    # nunca vai aparecer aqui.
    "dellavolpe": ("Frete fracionado, com coleta. O preço não sai na tela: "
                   "a cotação chega no seu e-mail em poucos minutos."),
    # A Braspress prende um dos lados da carga no CNPJ do LOGIN (a própria
    # conta da Ventura, 08.310.365/0001-24) assim que CIF/FOB é escolhido —
    # mesmo que a ficha tenha outro remetente/destinatário para aquele lado.
    # Pedido do Enzo em 02/09/2026: o vendedor precisa saber disso olhando
    # o cartão, não descobrir depois.
    "braspress": ("Frete fracionado, com coleta. Cotada sempre com o CNPJ "
                  "padrão da Ventura (08.310.365/0001-24) — é o próprio "
                  "login da Braspress, o site não deixa trocar."),
}

# Quanto a resposta por e-mail costuma demorar, por transportadora. MEDIDO,
# não prometido: a Della Volpe respondeu em 2 a 5 minutos nos envios reais de
# 25 e 26/08/2026.
#
# A Generoso NÃO entra aqui de propósito. Quando ela cai neste mesmo cartão,
# quem responde é um vendedor, em horas — herdar "minutos" faria o vendedor
# dar a cotação por perdida antes de ela chegar.
# Prazo prometido no cartão de "cotação enviada", por transportadora.
#
# VAZIO desde 31/08/2026. Tinha a Della Volpe com "2 a 5 minutos", medido nos
# envios reais — mas ela deixou de ser automática, e prometer prazo de um
# e-mail que o sistema não manda mandaria o vendedor esperar o que nunca vem.
# O mecanismo fica: sem entrada, o cartão simplesmente não promete prazo.
ESPERA_DO_EMAIL: dict[str, str] = {}

# Erro técnico -> frase que o vendedor entende.
#
# Pedido do Enzo em 18/08/2026. O motivo é concreto: ele não sabe o que é
# "timeout" nem "wait_for_selector", então lendo o texto cru não distingue
# problema do sistema, da internet dele, ou da carga — e liga para o Enzo.
#
# A frase NÃO substitui o texto técnico no cartão; entra antes dele. Esconder
# o original tiraria de quem for investigar a única pista que existe.
#
# As marcas saem dos erros que a transportadora produziu DE VERDADE em
# produção, não de imaginação. Recusa e senha não estão aqui de propósito:
# essas já viram frase boa na FONTE (`motivo_recusa`), que é onde a
# classificação deve morar — ver core/retentativa.py.
#
# Só a Generoso por enquanto. Uma entrada aqui é dívida: significa que o
# adapter ainda devolve como "não sabemos" algo que dava para classificar.
MENSAGENS_DE_ERRO = {
    "generoso": (
        ("verificar seu navegador",
         "O portal da Generoso está com uma verificação de segurança "
         "barrando o acesso automático. Não é a sua cotação — enquanto isso "
         "durar, nenhuma passa por ela. Cote pelo WhatsApp."),
        ("wait_for_selector",
         "A tela de login da Generoso não abriu a tempo. Pode ser lentidão "
         "do portal ou a verificação de segurança dele."),
        ("nao trouxe o endereco",
         "A Generoso não trouxe o endereço desse CNPJ e não disse por quê. "
         "Confira o CNPJ; se estiver certo, pode ser que ela não tenha esse "
         "cliente cadastrado."),
        ("nao avancou",
         "O portal da Generoso parou numa etapa do formulário e não seguiu. "
         "Costuma ser passageiro — o sistema já tenta de novo sozinho."),
        ("nao trouxe preco nem confirmacao",
         "A Generoso preencheu a cotação inteira mas não mostrou preço na "
         "tela. Vale repetir; se continuar, cote pelo WhatsApp."),
    ),
}


def _sem_acento(texto: str) -> str:
    """Minúsculas e sem acento, para casar a marca.

    O mesmo adapter escreve "endereço" numa linha e "endereco" na outra —
    casar só uma das formas deixaria metade dos erros reais sem tradução."""
    return "".join(c for c in unicodedata.normalize("NFKD", texto.lower())
                   if not unicodedata.combining(c))


def mensagem_amigavel(slug: str, erro: str | None) -> str | None:
    """A frase para este erro, ou None se ninguém o reconhece.

    None é resposta legítima e comum: o cartão então mostra o texto original,
    que é a regra combinada — nunca esconder informação por não saber
    traduzi-la."""
    achatado = _sem_acento(erro or "")
    for marca, frase in MENSAGENS_DE_ERRO.get(slug, ()):
        if _sem_acento(marca) in achatado:
            return frase
    return None

# A calculadora da Jadlog cota UM pacote por vez (carriers/jadlog/painel.py).
# Com mais de um volume o número dela não é comparável com o da Camilo e o da
# Translovato, que cotam a carga inteira — e o menor número na tela é o que
# fecha negócio.
COTAM_POR_VOLUME = ("jadlog",)

# Teto do texto de erro no cartão. Era 180, o bastante para partir um CNPJ no
# meio da mensagem da Translovato — e um CNPJ pela metade é pior do que
# nenhum, porque o vendedor copia assim mesmo. Continua havendo teto: sem ele
# um stack trace inteiro vai para a tela.
LIMITE_MENSAGEM_ERRO = 400

# Quanto tempo a tela espera antes de assumir que ninguém mais responde, em
# minutos — é o número que a aba de Documentação mostra. Derivado e não
# escrito: o teto já mudou uma vez (de 240s para 300s).
ESPERA_MAXIMA_MIN = ESPERA_MAXIMA_S // 60


def saudacao() -> str:
    """Bom dia ate 11h59, boa tarde ate 17h59, boa noite depois."""
    h = datetime.now().hour
    return "Bom dia" if h < 12 else ("Boa tarde" if h < 18 else "Boa noite")


def _img(caminho: str | None) -> str:
    """Embute o print na pagina.

    Base64 em vez de servir o arquivo: teste_real/ tem CNPJ e valor de nota
    fiscal, e abrir a pasta como estatica exporia todas as cotacoes de todo
    mundo. Provisorio — a ideia e passar a so guardar em pasta."""
    if not caminho or not Path(caminho).exists():
        return ""
    dados = base64.b64encode(Path(caminho).read_bytes()).decode()
    return (f'<img class="print" src="data:image/png;base64,{dados}" '
            f'alt="comprovante da cotacao">')


def _kg(valor) -> str:
    """Peso do jeito que se lê aqui: vírgula, sem zeros à toa.

    4,000 vira "4" e 3,333333… vira "3,333". `:f` em vez de str() porque
    normalize() devolve Decimal('1E+2') para 100, e "1E+2 kg" não quer dizer
    nada para quem está conferindo a carga.

    Aceita o que vier do banco (str ou Decimal) e devolve o original se não
    for número: uma linha da ficha com o valor cru ainda informa; uma tela
    que estoura no meio, não."""
    try:
        redondo = Decimal(str(valor)).quantize(Decimal("0.001"),
                                               rounding=ROUND_HALF_UP)
    except (ArithmeticError, TypeError, ValueError):
        return str(valor)
    return f"{redondo.normalize():f}".replace(".", ",")


def peso_por_volume(c: dict) -> Decimal | None:
    """Peso de UM volume. O banco guarda o TOTAL (ver /cotar).

    São grandezas diferentes com o mesmo nome, e é isso que torna o erro
    perigoso: o formulário pede "Peso de UM volume", a coluna peso_kg guarda
    qtd × unitário, e 36 kg é um peso tão válido quanto 12. Nada na tela
    denuncia — a cotação sai com o triplo da carga e o preço vem junto."""
    try:
        qtd = int(c["quantidade"])
        return Decimal(str(c["peso_kg"])) / qtd if qtd > 0 else None
    except (ArithmeticError, TypeError, ValueError):
        return None


# ------------------------------------------------------------- validação
ROTULOS = {
    "cep_origem": "CEP de origem", "cep_destino": "CEP de destino",
    "cnpj_remetente": "CNPJ do remetente",
    "cnpj_destinatario": "CNPJ do destinatário",
    "peso": "Peso de um volume",
    "quantidade": "Quantidade de volumes", "comprimento": "Comprimento",
    "largura": "Largura", "altura": "Altura",
    "valor_nf": "Valor da nota fiscal", "material": "Material",
    "nome": "Nome", "email": "E-mail", "whatsapp": "WhatsApp",
}


def _digitos(v: str) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def validar_formulario(d: dict) -> list[str]:
    """Tudo que dá para saber SEM abrir navegador.

    Cada item aqui é um erro que o usuário descobriria depois de 2 minutos
    de espera, ou pior: uma cotação que sai com a carga errada."""
    erros = []

    # Antes de tudo: cotar em ninguem nao e uma cotacao. Sem isto sobra um
    # registro vazio no historico e um vendedor achando que pediu preco.
    # A chave so existe quando o formulario tem o painel; `is not None`
    # distingue "desmarcou tudo" de "veio de outro lugar".
    if d.get("transportadora") is not None and not d["transportadora"]:
        erros.append(
            "Nenhuma transportadora escolhida. Marque ao menos uma no painel "
            "logo acima do botao Cotar fretes.")

    for campo_ in ("cnpj_remetente", "cnpj_destinatario"):
        n = len(_digitos(d.get(campo_, "")))
        if n != 14:
            erros.append(f"{ROTULOS[campo_]}: precisa de 14 dígitos, "
                         f"veio com {n}.")

    for campo_ in ("cep_origem", "cep_destino"):
        n = len(_digitos(d.get(campo_, "")))
        if n != 8:
            erros.append(f"{ROTULOS[campo_]}: precisa de 8 dígitos, "
                         f"veio com {n}.")

    # Medida abaixo de 1 cm é quase sempre METRO digitado no campo de
    # centímetro. O modelo aceita (só exige > 0) e o estrago aparece longe
    # daqui: o banco guarda int() e a cotação #14 virou "0x1x0 cm", enquanto
    # a Generoso recusava com "a etapa da Carga não avançou. O site diz:
    # (nenhuma mensagem visível)". Uma carga de 87 cm virou uma de 0 cm sem
    # nada na tela dizendo isso.
    for campo_ in ("comprimento", "largura", "altura"):
        bruto = str(d.get(campo_, "")).strip()
        try:
            medida = _num(bruto)
        except Exception:
            continue                       # formato inválido já é pego adiante
        if 0 < medida < MEDIDA_MINIMA_CM:
            erros.append(
                f"{ROTULOS[campo_]}: {bruto} é menos de {MEDIDA_MINIMA_CM} cm. "
                f"O campo é em CENTÍMETROS — se a carga tem {bruto} metro(s), "
                f"escreva {_num(bruto) * 100:.0f}.")

    try:
        peso = _num(d.get("peso", ""))
        if peso < PESO_MINIMO_KG:
            erros.append(
                f"Peso de {peso} kg: a Della Volpe só cota a partir de "
                f"{PESO_MINIMO_KG} kg, e abaixo disso a cotação volta "
                f"recusada depois de dois minutos de espera.")
    except ValueError:
        erros.append("Peso: não entendi o número.")

    for campo_ in ("quantidade", "comprimento", "largura", "altura",
                   "valor_nf"):
        try:
            if _num(d.get(campo_, "")) <= 0:
                erros.append(f"{ROTULOS[campo_]}: precisa ser maior que zero.")
        except ValueError:
            erros.append(f"{ROTULOS[campo_]}: não entendi o número.")

    if "@" not in str(d.get("email", "")):
        erros.append("E-mail: falta o @.")
    if not str(d.get("material", "")).strip():
        erros.append("Material: diga o que é a carga.")
    return erros


def traduzir_erro(exc: Exception) -> str:
    """Exceção crua -> frase que um funcionário entende.

    O Pydantic e o ViaCEP falam com o programador, não com quem usa."""
    texto = str(exc)
    if "CEP não existe" in texto or "CEP precisa" in texto:
        return f"{texto} Confira o CEP digitado."
    if "cnpj" in texto.lower():
        return ("Um dos CNPJs não passou na validação (dígito verificador). "
                "Confira os números.")
    if "ViaCEP" in texto:
        return ("Não consegui consultar o CEP agora. Verifique a internet e "
                "tente de novo.")
    return f"Não deu para montar a cotação: {texto}"


def tela_erro(problemas: list[str], dados: dict, usuario: str | None) -> str:
    """Erro COM os campos preservados: refazer tudo por causa de um dígito
    é o jeito mais rápido de fazer alguém desistir da ferramenta."""
    itens = "".join(f"<li>{e(p)}</li>" for p in problemas)
    guardados = "".join(
        f'<input type="hidden" name="_{k}" value="{e(v)}">'
        for k, v in dados.items() if k in ROTULOS)
    return pagina("Corrija e tente de novo", f"""
<div class="cartao">
  <h1 class="falhou">Falta corrigir {len(problemas)} coisa(s)</h1>
  <p class="sub">Nada foi cotado ainda. Seus dados continuam preenchidos.</p>
  <ul class="listaerro">{itens}</ul>
  <form method="post" action="/voltar">{guardados}
    <button type="submit">Voltar e corrigir</button>
  </form>
</div>""", usuario)


# ------------------------------------------------------------------- login
@app.get("/login", response_class=HTMLResponse)
def tela_login() -> str:
    return pagina("Entrar", f"""
<div class="login">
  <img src="data:image/png;base64,{LOGO}" alt="Ventura">
  <div class="cartao">
    <h1>Cotafrete</h1>
    <p class="sub">Digite seu nome para começar. Suas cotações ficam
    separadas das dos outros.</p>
    <form method="post" action="/login">
      <input name="usuario" placeholder="Seu nome" autofocus required
             style="margin-bottom:12px">
      <button type="submit" style="width:100%">Entrar</button>
    </form>
  </div>
  <p class="sub">Sem senha por enquanto — serve para separar o histórico,
  não para proteger acesso.</p>
</div>""")


@app.post("/login")
def entrar(usuario: str = Form(...)):
    nome = usuario.strip()[:40] or "sem-nome"
    r = RedirectResponse("/", status_code=303)
    r.set_cookie(COOKIE, nome, max_age=60 * 60 * 24 * 30, httponly=True,
                 samesite="lax")
    return r


@app.get("/sair")
def sair():
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(COOKIE)
    return r


# ---------------------------------------------------------------- formulário
# Formulário em BRANCO. Até 24/08/2026 ele vinha preenchido com uma carga de
# desenvolvimento — CNPJ real, "LUVA DE BOMBEIRO", nome e e-mail do Enzo.
# Servia para testar sem redigitar; com a equipe inteira usando, virou risco:
# quem esquecesse de trocar um campo cotava com o dado de outra pessoa, e a
# cotação sai igualzinha a uma certa.
#
# Todo <input> tem `required` (ver campo()), então campo vazio não passa —
# o navegador barra antes de enviar.
#
# tipo_frete continua com valor: é um par de opções, não um campo digitado, e
# sem um marcado o vendedor não teria nenhum selecionado. CIF porque a carga
# sai daqui — quem paga é o remetente.
PADRAO = {
    "cep_origem": "", "cep_destino": "",
    "cnpj_remetente": "", "cnpj_destinatario": "",
    "tipo_frete": "cif",
    "peso": "", "quantidade": "",
    "comprimento": "", "largura": "", "altura": "",
    "valor_nf": "", "material": "",
    "nome": "", "email": "", "whatsapp": "",
}


def campo(nome: str, rotulo: str, v: dict) -> str:
    return (f'<div><label for="{nome}">{rotulo}</label>'
            f'<input id="{nome}" name="{nome}" value="{e(v.get(nome, ""))}"'
            f' required></div>')


TIPOS_DE_FRETE = (
    ("cif", "CIF", "Remetente que paga"),
    ("fob", "FOB", "Destinatário que paga"),
)


def escolha_tipo_frete(v: dict) -> str:
    """Substituiu o campo "CNPJ de quem paga".

    Digitado à parte, aquele CNPJ podia discordar do tipo de frete que cada
    transportadora recebia — e discordava: a Camilo levava tp_frete=2 (FOB)
    enquanto o formulário mandava um CNPJ da Ventura, que é CIF. Escolhendo o
    tipo, o CNPJ passa a ser consequência, e a contradição some.

    Rádio, e não select: as duas opções precisam estar visíveis ao mesmo
    tempo. Escondida atrás de um clique, a diferença entre cobrar de quem
    envia e de quem recebe passa despercebida."""
    escolhido = v.get("tipo_frete", "cif")
    opcoes = "".join(
        f'<label class="opcao"><input type="radio" name="tipo_frete"'
        f' value="{sigla}"{" checked" if sigla == escolhido else ""}>'
        f'<b>{titulo}</b><span>{quem}</span></label>'
        for sigla, titulo, quem in TIPOS_DE_FRETE)
    return (f'<label style="margin-top:10px">Tipo de frete</label>'
            f'<div class="opcoes">{opcoes}</div>')


def _valores_de(c: dict) -> dict:
    """Cotação salva -> campos do formulário, para repetir sem redigitar."""
    # Este campo pede o peso de UM volume; o banco guarda o TOTAL. Devolver o
    # total aqui multiplicava a carga pela quantidade a CADA repetição — e
    # "Repetir esta cotação" é justamente o botão mais usado da tela.
    unitario = peso_por_volume(c)
    return {**PADRAO,
            "cep_origem": c["cep_origem"], "cep_destino": c["cep_destino"],
            "cnpj_remetente": c.get("cnpj_remetente") or PADRAO["cnpj_remetente"],
            "cnpj_destinatario": (c.get("cnpj_destinatario")
                                  or PADRAO["cnpj_destinatario"]),
            "tipo_frete": c.get("tipo_frete") or PADRAO["tipo_frete"],
            "peso": (_kg(unitario) if unitario is not None
                     else str(c["peso_kg"])),
            "quantidade": str(c["quantidade"]),
            "comprimento": str(c["comprimento_cm"]),
            "largura": str(c["largura_cm"]), "altura": str(c["altura_cm"]),
            "valor_nf": str(c["valor_nf"]).replace(".", ","),
            "material": c["material"] or ""}


@app.get("/", response_class=HTMLResponse)
def formulario(usuario: str | None = Cookie(None, alias=COOKIE),
               repetir: int | None = None):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    v = dict(PADRAO)
    aviso = ""
    if repetir:
        # Repetir cotação: o Enzo cota a mesma peça para clientes diferentes.
        # Vir preenchido economiza mais tempo que qualquer outra coisa aqui.
        anterior = banco.buscar_cotacao(repetir, usuario)
        if anterior:
            v = _valores_de(anterior)
            aviso = (f'<div class="aviso">Campos preenchidos a partir da '
                     f'cotação #{repetir}. Ajuste o que mudou e cote de novo.'
                     f'</div>')
    return HTMLResponse(_render_formulario(v, usuario, aviso))


def painel_transportadoras() -> str:
    """O filtro, fechado por padrão e com tudo marcado.

    `<details>` nativo em vez de JavaScript para abrir e fechar: funciona sem
    script, e este projeto não tem framework nenhum — não vai ganhar um por
    causa de um acordeão.

    Os grupos são rotulados pelo que FAZEM, não pelo nome. Era o buraco do
    desenho anterior: uma grade de logos trata igual quem devolve preço na
    tela e quem só abre uma mensagem para você mandar à mão, e essas duas
    coisas não têm nada a ver uma com a outra.

    A Translovato aparece UMA vez, entre as automáticas, com o selo
    "+ WhatsApp". Ela é as duas coisas, e duas caixas para a mesma empresa
    seria exatamente a confusão que este painel veio resolver.
    """
    def caixa(slug: str, nome: str, logo: str | None, selo: str = "") -> str:
        marca = (f'<img src="/logos/{e(logo)}" alt="" loading="lazy">'
                 if logo else '<span class="sem-logo"></span>')
        return (f'<label class="tr"><input type="checkbox"'
                f' name="transportadora" value="{e(slug)}" checked>'
                f'{marca}<span class="tr-nome">{e(nome)}</span>{selo}</label>')

    zap = {r.slug: r for r in transportadoras.com_whatsapp()}

    automaticas = "".join(
        caixa(slug, NOMES[slug],
              LOGOS_AUTOMATICAS.get(slug)
              or (zap[slug].logo if slug in zap else None),
              '<span class="selo-zap">+ WhatsApp</span>' if slug in zap else "")
        for slug in AUTOMATICAS)

    # As de WhatsApp menos as que já apareceram acima (hoje, a Translovato),
    # mais as de e-mail. Vão no MESMO grupo porque o grupo é rotulado pelo que
    # a transportadora FAZ, e para o vendedor as duas fazem a mesma coisa: o
    # sistema deixa a mensagem pronta e ele envia.
    #
    # Esquecer as de e-mail aqui foi um bug real, em 31/08/2026: a Della Volpe
    # sumiu da tela inteira. Sem caixa no painel ela nunca vinha marcada, a
    # lista guardada saía sem ela, e `selecao.entra` passava a responder False
    # para sempre — sem nenhuma mensagem dizendo o que houve.
    manuais = "".join(
        caixa(r.slug, r.nome, r.logo)
        for r in transportadoras.com_whatsapp() if r.slug not in AUTOMATICAS)
    manuais += "".join(
        caixa(r.slug, r.nome, r.logo, '<span class="selo-zap">e-mail</span>')
        for r in transportadoras.com_email())

    def grupo(titulo: str, explica: str, itens: str) -> str:
        return (f'<div class="grupo"><div class="grupo-cab">'
                f'<b>{titulo}</b><span>{explica}</span>'
                f'<span class="atalhos"><a href="#" data-todas="1">todas</a>'
                f' · <a href="#" data-todas="0">nenhuma</a></span></div>'
                f'<div class="caixas">{itens}</div></div>')

    return (
        f'<details class="filtro" id="filtro">'
        f'<summary><span id="resumo-filtro">Cotando em todas as '
        f'{len(TODAS_AS_SLUGS)} transportadoras</span>'
        f'<span class="abrir">Escolher</span></summary>'
        + grupo("AUTOMÁTICAS", "devolvem preço nesta tela", automaticas)
        + grupo("PRECISA DE VOCÊ",
                "abrem a mensagem pronta — por WhatsApp ou e-mail — para "
                "você enviar", manuais)
        + '</details>')


def _render_formulario(v: dict, usuario: str, aviso: str) -> str:
    # String CRUA (rf): o JS aqui embaixo usa \d e \D das regex de máscara.
    # Sem o `r`, o Python lê como escape dele, avisa "invalid escape sequence"
    # e numa versão futura recusa o arquivo — servidor que não sobe.
    return pagina("Nova cotação", rf"""
{aviso}
<h1>Nova cotação</h1>
<p class="sub">Preencha uma vez. Cotamos sozinhos em {len(AUTOMATICAS)}
transportadoras e deixamos a mensagem pronta para as
{len(transportadoras.com_whatsapp())} que atendem por WhatsApp.</p>
<form method="post" action="/cotar" class="cartao">
  <fieldset><legend>Rota</legend><div class="grid">
    {campo("cep_origem", "CEP de origem", v)}
    {campo("cep_destino", "CEP de destino", v)}
  </div>
  <p class="sub" style="margin:8px 0 0">Cidade e estado saem do CEP — não
  precisa digitar.</p></fieldset>

  <fieldset><legend>Documentos</legend><div class="grid">
    {campo("cnpj_remetente", "CNPJ do remetente", v)}
    {campo("cnpj_destinatario", "CNPJ do destinatário", v)}
  </div>
  {escolha_tipo_frete(v)}</fieldset>

  <fieldset><legend>Carga</legend><div class="grid">
    {campo("peso", "Peso de UM volume (kg)", v)}
    {campo("quantidade", "Quantidade de volumes", v)}
    {campo("comprimento", "Comprimento (cm)", v)}
    {campo("largura", "Largura (cm)", v)}
    {campo("altura", "Altura (cm)", v)}
    {campo("valor_nf", "Valor da nota fiscal (R$)", v)}
    {campo("material", "Material", v)}
  </div></fieldset>

  <fieldset><legend>Contato</legend><div class="grid">
    {campo("nome", "Nome", v)}
    {campo("email", "E-mail", v)}
    {campo("whatsapp", "WhatsApp", v)}
  </div></fieldset>

  {painel_transportadoras()}

  <button type="submit">Cotar fretes</button>
</form>
<script>
/* Mascaras enquanto digita. Sao os campos que o usuario mais erra, e um
   digito a menos no CNPJ so aparecia depois de dois minutos de espera. */
function mascara(el, tam, formatar) {{
  const aplicar = () => {{
    const d = el.value.replace(/\D/g, "").slice(0, tam);
    el.value = formatar(d);
    el.style.borderColor = d.length === tam || !d.length ? "" : "#bf2600";
  }};
  el.addEventListener("input", aplicar);
  aplicar();
}}
const fmtCnpj = (d) => d
  .replace(/^(\d{{2}})(\d)/, "$1.$2")
  .replace(/^(\d{{2}})\.(\d{{3}})(\d)/, "$1.$2.$3")
  .replace(/\.(\d{{3}})(\d)/, ".$1/$2")
  .replace(/(\d{{4}})(\d)/, "$1-$2");
const fmtCep = (d) => d.replace(/^(\d{{5}})(\d)/, "$1-$2");

["cnpj_remetente","cnpj_destinatario"].forEach(
  id => mascara(document.getElementById(id), 14, fmtCnpj));
["cep_origem","cep_destino"].forEach(
  id => mascara(document.getElementById(id), 8, fmtCep));

// Contador do filtro. O <details> abre e fecha sozinho (HTML puro);
// isto aqui so mantem o resumo dizendo a verdade, e e o que impede o
// filtro de virar erro silencioso: a linha fica logo acima do botao.
const filtro = document.getElementById("filtro");
const resumo = document.getElementById("resumo-filtro");
const caixas = () => [...filtro.querySelectorAll(
  'input[name="transportadora"]')];
const TOTAL = caixas().length;
function contar() {{
  const n = caixas().filter(c => c.checked).length;
  filtro.classList.toggle("parcial", n !== TOTAL);
  resumo.textContent = n === TOTAL
    ? `Cotando em todas as ${{TOTAL}} transportadoras`
    : `${{n}} de ${{TOTAL}} transportadoras — ${{TOTAL - n}} fora desta cotação`;
}}
filtro.addEventListener("change", contar);
filtro.querySelectorAll("[data-todas]").forEach(a => a.onclick = ev => {{
  ev.preventDefault();
  a.closest(".grupo").querySelectorAll('input[name="transportadora"]')
   .forEach(c => c.checked = a.dataset.todas === "1");
  contar();
}});
contar();
</script>""", usuario)


# -------------------------------------------------------------------- cotar
def _num(txt: str) -> Decimal:
    t = str(txt).strip()
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return Decimal(t)
    except (InvalidOperation, ValueError):
        raise ValueError(f"número inválido: {txt!r}")


def montar_request(d: dict) -> CotacaoRequest:
    """Formulário -> modelo central. Cidade e UF vêm do CEP."""
    origem = buscador_cep.buscar(d["cep_origem"])
    destino = buscador_cep.buscar(d["cep_destino"])
    return CotacaoRequest(
        solicitante=Solicitante(nome=d["nome"], email=d["email"],
                                whatsapp=d["whatsapp"]),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf=origem[1], cidade=origem[0], cep=d["cep_origem"],
                     codigo_ibge=origem[2]),
        destino=Local(uf=destino[1], cidade=destino[0], cep=d["cep_destino"],
                      codigo_ibge=destino[2]),
        remetente=Parte(cnpj=d["cnpj_remetente"]),
        destinatario=Parte(cnpj=d["cnpj_destinatario"]),
        tipo_frete=TipoFrete(d.get("tipo_frete", "cif")),
        volumes=[Volume(qtd=int(_num(d["quantidade"])),
                        comprimento_cm=_num(d["comprimento"]),
                        largura_cm=_num(d["largura"]),
                        altura_cm=_num(d["altura"]),
                        peso_kg=_num(d["peso"]))],
        mercadoria=Mercadoria(tipo_material=d["material"]),
        nota_fiscal=NotaFiscal(valor_total=_num(d["valor_nf"])),
    )


@app.post("/voltar", response_class=HTMLResponse)
async def voltar(request: Request,
                 usuario: str | None = Cookie(None, alias=COOKIE)):
    """Volta ao formulario com o que o usuario ja tinha digitado."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    v = {**PADRAO, **{k[1:]: val for k, val in form.items()
                      if k.startswith("_")}}
    return HTMLResponse(_render_formulario(v, usuario, ""))


@app.post("/cotar", response_class=HTMLResponse)
def cotar(usuario: str | None = Cookie(None, alias=COOKIE),
          cep_origem: str = Form(...), cep_destino: str = Form(...),
          cnpj_remetente: str = Form(...), cnpj_destinatario: str = Form(...),
          tipo_frete: str = Form("cif"), peso: str = Form(...),
          quantidade: str = Form(...), comprimento: str = Form(...),
          largura: str = Form(...), altura: str = Form(...),
          valor_nf: str = Form(...), material: str = Form(...),
          nome: str = Form(...), email: str = Form(...),
          whatsapp: str = Form(...),
          # Checkbox nao marcada nao e enviada: a lista chega so com o que
          # o vendedor deixou ligado. Default [] para o caso de alguem
          # postar sem o painel — que `validar_formulario` recusa embaixo.
          transportadora: list[str] = Form(default=[])):
    """Endpoint SÍNCRONO de propósito: o FastAPI o roda numa thread do pool, e
    a API sync do Playwright não pode conviver com um event loop na mesma
    thread."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)

    dados = {k: v for k, v in locals().items() if k != "usuario"}

    problemas = validar_formulario(dados)
    if problemas:
        return HTMLResponse(tela_erro(problemas, dados, usuario))

    try:
        req = montar_request(dados)
    except Exception as exc:
        return HTMLResponse(tela_erro([traduzir_erro(exc)], dados, usuario))

    # None quando esta tudo marcado: assim a cotacao nao "congela" a lista
    # de hoje, e uma transportadora nova entra nas antigas tambem.
    escolhidas = selecao.para_guardar(transportadora, TODAS_AS_SLUGS)
    dados["transportadoras"] = escolhidas

    v = req.volumes[0]
    cotacao_id = banco.salvar_cotacao(usuario, {
        "cep_origem": req.origem.cep, "cep_destino": req.destino.cep,
        "cidade_origem": req.origem.cidade, "uf_origem": req.origem.uf,
        "cidade_destino": req.destino.cidade, "uf_destino": req.destino.uf,
        "peso_kg": req.peso_total_kg, "quantidade": req.quantidade_volumes,
        "comprimento_cm": int(v.comprimento_cm),
        "largura_cm": int(v.largura_cm), "altura_cm": int(v.altura_cm),
        "valor_nf": req.nota_fiscal.valor_total,
        "material": req.mercadoria.tipo_material,
        "cnpj_remetente": req.remetente.cnpj_formatado,
        "cnpj_destinatario": req.destinatario.cnpj_formatado,
        # Derivado, nunca digitado: e o remetente no CIF e o destinatario
        # no FOB. Guardado junto porque a mensagem do WhatsApp precisa dizer
        # QUEM paga, nao so a sigla.
        "cnpj_pagador": req.pagador_frete.cnpj_formatado,
        "tipo_frete": req.tipo_frete.value,
        "nome_remetente": buscador_cnpj.buscar(req.remetente.cnpj),
        "nome_destinatario": buscador_cnpj.buscar(req.destinatario.cnpj),
        "nome_pagador": buscador_cnpj.buscar(req.pagador_frete.cnpj),
        # É por aqui que a resposta da Generoso chega. Guardado na cotação, e
        # não só no formulário, porque a tela precisa dele em toda visita.
        "email": req.solicitante.email,
        # Mesma razão do e-mail: o bookmarklet da Della Volpe precisa disto
        # em visitas FUTURAS à tela, não só na hora do /cotar.
        "nome_solicitante": req.solicitante.nome,
        "whatsapp_solicitante": req.solicitante.whatsapp_formatado,
        "transportadoras": escolhidas,
    })

    # Dispara e NÃO espera: cada uma grava o próprio resultado ao terminar.
    for slug in automaticas_da(dados.get("transportadoras")):
        EXECUTOR.submit(_rodar, cotacao_id, slug, FABRICAS[slug], req)

    return RedirectResponse(f"/cotacao/{cotacao_id}", status_code=303)


def _cotar_camilo(req):
    # confirmar_envio=True aqui só quer dizer "clique em simular": é cálculo
    # automático, não entra em fila de vendedor.
    return CamiloAdapter().cotar(req, confirmar_envio=True)


def _cotar_jadlog(req):
    return JadlogPainelAdapter().cotar(req)


def _cotar_translovato(req):
    # Cria registro em "Minhas Cotações" no portal deles — é
    # auto-serviço, não entra em fila de vendedor.
    return TranslovatoAdapter().cotar(req)


def _cotar_generoso(req):
    """Cria uma cotação na conta da Ventura no portal deles — auto-serviço,
    como a Translovato, e não fila de vendedor como a Della Volpe.

    Logada, a tela final devolve preço, protocolo e prazo na hora. É por isso
    que o envio é confirmado aqui: sem confirmar não existe preço, só um
    rascunho que ninguém vê."""
    return GenerosoAdapter().cotar(req, confirmar_envio=True)


def _cotar_braspress(req):
    """"Calcular" é cálculo automático (como o "Simular" da Camilo) — não
    entra em fila de vendedor nem cria pendência na conta da Ventura, então
    o envio é confirmado aqui: sem confirmar não existe preço na tela."""
    return BraspressAdapter().cotar(req, confirmar_envio=True)


# No módulo, e não dentro de /cotar: é o que permite a
# tests/test_dellavolpe_automatica.py conferir que quem está em AUTOMATICAS
# tem como ser despachada. Entrar na lista sem fábrica só estourava dentro de
# uma thread do executor, e lá um KeyError vira cartão girando para sempre.
FABRICAS = {"camilo": _cotar_camilo, "jadlog": _cotar_jadlog,
            "translovato": _cotar_translovato, "generoso": _cotar_generoso,
            "braspress": _cotar_braspress}


def _rodar(cotacao_id: int, slug: str, cotar_fn, req) -> None:
    """Roda uma transportadora e grava o resultado, aconteça o que acontecer.

    Sem o try, uma exceção numa thread do executor some em silêncio e o
    cartão fica 'cotando...' para sempre.

    A repetição de quem falhou mora em `core/retentativa.py`: aqui só se
    grava o resultado FINAL. Gravar as tentativas intermediárias encheria o
    histórico de linhas vermelhas de cotações que no fim deram certo."""
    chave = (cotacao_id, slug)

    def anotar(tentativa: int) -> None:
        TENTATIVAS_EM_CURSO[chave] = tentativa

    try:
        res = cotar_com_retentativa(cotar_fn, req, ao_tentar=anotar,
                                    repetir=slug not in SEM_REPETICAO)
        banco.salvar_resultado(
            cotacao_id, slug, status=res.status.value, valor=res.valor_frete,
            # motivo_recusa junto: "recusado" é a transportadora dizendo não,
            # e a frase que explica o porquê é escrita justamente para o
            # vendedor ler. Gravando só `erro`, ela era jogada fora e o cartão
            # caía no genérico "o site respondeu: recusado".
            protocolo=res.protocolo, erro=res.erro or res.motivo_recusa,
            evidencia=res.evidencias[-1] if res.evidencias else None,
            respondido_em=(res.respondido_em.isoformat(timespec="seconds")
                           if res.respondido_em else None))
    except Exception as exc:
        banco.salvar_resultado(cotacao_id, slug, status="erro",
                               erro=f"{type(exc).__name__}: {exc}")
    finally:
        # Sem isto o dicionário cresce para sempre — uma entrada por
        # transportadora por cotação, num processo que fica semanas de pé.
        TENTATIVAS_EM_CURSO.pop(chave, None)


# ------------------------------------------------------------- ver cotação
def _quem(nome: str | None, cnpj: str | None) -> str:
    """Nome da empresa quando a busca por CNPJ funcionou; senão só o CNPJ."""
    return f"{nome}\nCNPJ: {cnpj}" if nome else f"CNPJ: {cnpj}"


def pagador_da_cotacao(c: dict) -> tuple[str, str, str]:
    """Sigla, lado e quem é — tudo derivado do tipo de frete.

    A salvaguarda no fim existe para as cotações anteriores a 20/08/2026, que
    não têm `tipo_frete` guardado: elas caem em CIF, que é como o formulário
    vinha preenchido, e o CNPJ sai da ponta certa em vez de virar "None"."""
    fob = (c.get("tipo_frete") or "cif") == "fob"
    sigla, lado = ("FOB", "DESTINATÁRIO") if fob else ("CIF", "REMETENTE")
    ponta = "destinatario" if fob else "remetente"
    nome = c.get("nome_pagador") or c.get(f"nome_{ponta}")
    cnpj = c.get("cnpj_pagador") or c.get(f"cnpj_{ponta}")
    return sigla, lado, _quem(nome, cnpj)


def mensagem_whatsapp(c: dict) -> str:
    """Mesmo texto para as três — decisão do Enzo em 14/08/2026.

    Os CNPJs e a razão social entram porque a transportadora precisa saber
    QUEM envia, QUEM recebe e QUEM paga para conseguir cotar. Sem isso a
    pessoa do outro lado responde pedindo os dados, e a cotação atrasa um
    dia inteiro."""
    sigla, lado, quem_paga = pagador_da_cotacao(c)
    return "\n".join([
        f"{saudacao()}! Tudo bem?", "", "Pode orçar pra mim, por favor?", "",
        f"REMETENTE: {_quem(c.get('nome_remetente'), c.get('cnpj_remetente'))}",
        f"CEP: {c['cep_origem']} — {c['cidade_origem']}/{c['uf_origem']}",
        "",
        f"DESTINATARIO: "
        f"{_quem(c.get('nome_destinatario'), c.get('cnpj_destinatario'))}",
        f"CEP: {c['cep_destino']} — {c['cidade_destino']}/{c['uf_destino']}",
        "",
        # Antes esta linha era "PAGADOR DO FRETE: (X) <nome>", com o CNPJ
        # digitado a parte no formulario. Agora ela DIZ a regra: a
        # transportadora precisa saber se cobra de quem envia ou de quem
        # recebe, e o nome sozinho nao responde isso.
        f"TIPO DE FRETE: {sigla} — quem paga é o {lado}",
        f"PAGADOR DO FRETE: {quem_paga}",
        "",
        f"TD DE VOLUMES: {c['quantidade']}",
        f"MEDIDAS: {c['comprimento_cm']} cm x {c['largura_cm']} cm x "
        f"{c['altura_cm']} cm",
        f"Peso: {c['peso_kg']} kg",
        f"Valor NF: {moeda(c['valor_nf'])}",
        f"ITEM: {c['material']}",
    ])


def cota_por_volume(slug: str, quantidade: int) -> bool:
    """A transportadora cotou UM volume e a carga tem mais de um?

    Só nesse caso o preço dela deixa de ser comparável. Com um volume só, o
    preço dela É o da carga — avisar ali seria ruído, e aviso que aparece
    sempre é aviso que ninguém lê."""
    return slug in COTAM_POR_VOLUME and quantidade > 1


def _dado(rotulo: str, valor, detalhe: str = "") -> str:
    """Um par rótulo/valor da ficha.

    Campo vazio vira travessão em vez de sumir: uma linha que desaparece faz
    o vendedor achar que aquele dado não existe no sistema."""
    extra = f'<span class="pouco">{e(detalhe)}</span>' if detalhe else ""
    return (f'<div><label>{e(rotulo)}</label>'
            f'<div class="val">{e(valor) or "—"}{extra}</div></div>')


def _lugar(cidade: str | None, uf: str | None) -> str:
    return f"{cidade}/{uf}" if cidade and uf else (cidade or uf or "")


def _parte(rotulo: str, nome: str | None, cnpj: str | None) -> str:
    """Razão social em cima, CNPJ embaixo. Sem a razão social, o CNPJ sobe —
    repetir o mesmo número duas vezes só ocupa espaço."""
    return _dado(rotulo, nome or cnpj, cnpj if nome else "")


def _quando(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y às %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def _frete_por_extenso(c: dict) -> str:
    """"CIF — paga o remetente". A sigla sozinha nao diz nada para quem esta
    conferindo dois orcamentos parecidos na mesa."""
    sigla, lado, _ = pagador_da_cotacao(c)
    return f"{sigla} — paga o {lado.lower()}"


def ficha_da_cotacao(c: dict) -> str:
    """Os dados que geraram esta cotação, com os rótulos do formulário.

    Pedido do Enzo em 19/08/2026. Resolve o caso de dois orçamentos parecidos
    na mesa: sem a ficha, conferir para qual CEP cada preço foi cotado exigia
    abrir o histórico e comparar de cabeça — e o preço certo no cliente
    errado é um prejuízo que ninguém percebe na hora."""
    unitario = peso_por_volume(c)
    detalhe_peso = (f"{c['quantidade']} × {_kg(unitario)} kg cada"
                    if unitario is not None else "")

    return f"""<div class="cartao ficha">
  <h2 style="font-size:15px;margin:0 0 4px">Dados desta cotação</h2>
  <p class="sub">Foi com estes valores que os sites cotaram e que a mensagem
  do WhatsApp foi escrita. Cotada em {e(_quando(c.get("criado_em")))}.</p>

  <fieldset><legend>Rota</legend><div class="grid">
    {_dado("CEP de origem", c["cep_origem"],
           _lugar(c.get("cidade_origem"), c.get("uf_origem")))}
    {_dado("CEP de destino", c["cep_destino"],
           _lugar(c.get("cidade_destino"), c.get("uf_destino")))}
  </div></fieldset>

  <fieldset><legend>Documentos</legend><div class="grid">
    {_parte("Remetente (quem envia)", c.get("nome_remetente"),
            c.get("cnpj_remetente"))}
    {_parte("Destinatário (quem recebe)", c.get("nome_destinatario"),
            c.get("cnpj_destinatario"))}
    {_dado("Tipo de frete", _frete_por_extenso(c))}
    {_parte("Quem paga o frete", c.get("nome_pagador"),
            c.get("cnpj_pagador"))}
  </div></fieldset>

  <fieldset><legend>Carga</legend><div class="grid">
    {_dado("Quantidade de volumes", c["quantidade"])}
    {_dado("Peso total", f"{_kg(c['peso_kg'])} kg", detalhe_peso)}
    {_dado("Comprimento", f"{c['comprimento_cm']} cm")}
    {_dado("Largura", f"{c['largura_cm']} cm")}
    {_dado("Altura", f"{c['altura_cm']} cm")}
    {_dado("Valor da nota fiscal", moeda(c["valor_nf"]))}
    {_dado("Material", c.get("material"))}
  </div></fieldset>
</div>"""


def cartao_resposta_por_email(email: str | None, slug: str = "") -> str:
    """Cartão de quem recebeu o pedido mas responde FORA do sistema.

    A Generoso não devolve preço na tela: confirma o recebimento e um vendedor
    responde por e-mail, horas depois. Sem este cartão ela caía no "Não
    retornou preço" — o mesmo texto de quem falhou — e o vendedor abandonaria
    uma cotação que está a caminho.

    A frase diz três coisas, nesta ordem, porque é a ordem em que a dúvida
    aparece: deu certo, onde a resposta chega, e que não adianta ficar
    olhando esta tela.

    Sem e-mail guardado (cotação anterior a 20/08/2026) o texto continua
    fazendo sentido, só não nomeia a caixa.

    O prazo sai de ESPERA_DO_EMAIL e é opcional de propósito: prometer um
    número que a transportadora não cumpre é pior do que não prometer nada."""
    onde = (f'<b class="caixa">{e(email)}</b> — o mesmo que você digitou no '
            f'formulário'
            if email else 'o e-mail que você digitou no formulário')
    espera = ESPERA_DO_EMAIL.get(slug)
    prazo = f' A resposta costuma chegar em {e(espera)}.' if espera else ''
    return ('<div class="enviada">Cotação enviada</div>'
            f'<div class="alerta email"><b>O preço não vem nesta tela.</b> '
            f'A cotação foi enviada para {onde}. Abra o e-mail para ver o '
            f'preço.{prazo} Confira a caixa de entrada e o spam — esta tela '
            f'não muda quando ela chegar.</div>')


@app.get("/whatsapp/{cotacao_id}/{slug}")
def abrir_whatsapp(cotacao_id: int, slug: str,
                   usuario: str | None = Cookie(None, alias=COOKIE)):
    """Registra a ABERTURA e leva para a conversa com o texto pronto.

    Passar pelo nosso servidor em vez de ligar direto no wa.me é o que
    permite contar. E o número vem SEMPRE do cadastro em transportadoras.py:
    montar a URL com o que chega no pedido viraria redirecionamento aberto.

    "Aberta" e não "enviada" de propósito. Daqui em diante quem age é a
    pessoa, no aplicativo do WhatsApp, e disso não chega notícia nenhuma."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)

    c = banco.buscar_cotacao(cotacao_id, usuario)
    reg = transportadoras.por_slug(slug)
    if c is None or reg is None:
        return HTMLResponse("Não encontrado", status_code=404)

    banco.marcar_whatsapp_aberto(cotacao_id, slug, usuario)
    texto = quote(mensagem_whatsapp(c))
    return RedirectResponse(f"https://wa.me/{reg.telefone}?text={texto}",
                            status_code=303)


@app.get("/email/{cotacao_id}/{slug}", response_class=HTMLResponse)
def preparar_email(cotacao_id: int, slug: str,
                   usuario: str | None = Cookie(None, alias=COOKIE)):
    """A cotação escrita, pronta para o vendedor copiar e mandar por e-mail.

    Existe porque a Della Volpe pôs Cloudflare Turnstile no formulário
    público em 31/08/2026: uma caixa "Confirme que é humano" que, sem estar
    marcada, faz o Contact Form 7 recusar o envio como spam sem gerar e-mail
    nenhum. O robô não marca essa caixa — ela existe justamente para impedir
    isso — então quem envia passou a ser a pessoa.

    Página nossa, e não `mailto:`: parte da equipe lê e-mail pelo navegador, e
    ali um `mailto:` não abre nada. Um botão que não faz nada é pior que
    botão nenhum — o mesmo motivo que deixa transportadora sem número fora da
    lista do WhatsApp.

    O texto é o MESMO do WhatsApp, de propósito: um segundo texto seria mais
    um para divergir do primeiro."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)

    c = banco.buscar_cotacao(cotacao_id, usuario)
    reg = transportadoras.por_slug_email(slug)
    if c is None or reg is None:
        return HTMLResponse("Não encontrado", status_code=404)

    # Mesma tabela do WhatsApp: o fato registrado é idêntico — a pessoa abriu
    # a coisa pronta. Uma tabela nova só daria duas contagens para conciliar.
    banco.marcar_whatsapp_aberto(cotacao_id, slug, usuario)
    texto = mensagem_whatsapp(c)

    return HTMLResponse(pagina(f"Cotação {cotacao_id} — {reg.nome}", f"""
<h1>{e(reg.nome)}</h1>
<p class="sub">Cotação #{cotacao_id} · {e(c['cidade_origem'])}/{e(c['uf_origem'])}
→ {e(c['cidade_destino'])}/{e(c['uf_destino'])}</p>

<div class="cartao">
  <div class="alerta email"><b>Esta é a única que você envia à mão.</b>
  O site da {e(reg.nome)} passou a exigir uma verificação "confirme que é
  humano", e o sistema não marca essa caixa por você. O texto abaixo já está
  pronto — copie e mande para o endereço deles.</div>

  <p>Enviar para <b class="caixa">{e(reg.email)}</b>
  <button class="botao2" type="button" onclick="copiar('endereco')">Copiar
  endereço</button></p>
  <textarea id="endereco" class="escondido">{e(reg.email)}</textarea>

  <p><b>A cotação:</b>
  <button class="botao2" type="button" onclick="copiar('texto')">Copiar
  texto</button></p>
  <textarea id="texto" class="pronto" rows="20" readonly>{e(texto)}</textarea>

  <p class="sub">Depois que você copia, o sistema não tem como saber se a
  mensagem saiu — por isso o contador da cotação diz <b>abertas</b>, e nunca
  enviadas.</p>
</div>

<p><a class="botao2" href="/cotacao/{cotacao_id}">voltar para a cotação</a></p>
<script>
function copiar(id) {{
  const campo = document.getElementById(id);
  campo.classList.remove('escondido');
  campo.select();
  campo.setSelectionRange(0, 99999);
  try {{ document.execCommand('copy'); }} catch (erro) {{ }}
  if (id === 'endereco') campo.classList.add('escondido');
  window.getSelection().removeAllRanges();
}}
</script>""", usuario))


@app.get("/dellavolpe/{cotacao_id}", response_class=HTMLResponse)
def formulario_dellavolpe(cotacao_id: int,
                          usuario: str | None = Cookie(None, alias=COOKIE)):
    """O formulário REAL da Della Volpe, pronto para o vendedor preencher com
    um clique — e por isso respondido em minutos, não em horas.

    Existe porque `/email/{id}/dellavolpe` (o e-mail avulso) demora de 10 a
    12 horas: vira uma mensagem solta que uma pessoa lê na fila. O formulário
    oficial deles responde em 2 a 5 minutos — o mesmo SLA que a automação por
    Playwright tinha, antes do Turnstile ("confirme que é humano") entrar.

    O Turnstile continua lá, e continua exigindo humano de verdade — isto
    aqui não tenta passar por cima dele. Só poupa a digitação: o vendedor
    abre a aba, clica no favorito UMA vez, confere os campos, resolve o
    captcha e envia — tudo com o navegador DELE, sem automação nenhuma no
    meio. Ver carriers/dellavolpe/bookmarklet.py para o porquê completo."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)

    c = banco.buscar_cotacao(cotacao_id, usuario)
    if c is None:
        return HTMLResponse("Não encontrado", status_code=404)

    # Mesma tabela do WhatsApp/e-mail: abrir esta tela já conta como "abriu
    # a coisa pronta", pelo mesmo motivo de sempre — o sistema não tem como
    # saber se o vendedor de fato enviou depois.
    banco.marcar_whatsapp_aberto(cotacao_id, "dellavolpe", usuario)
    url = dv_bookmarklet.url_formulario(c)
    href_favorito = dv_bookmarklet.href_bookmarklet()

    return HTMLResponse(pagina(f"Cotação {cotacao_id} — Della Volpe", f"""
<h1>Della Volpe</h1>
<p class="sub">Cotação #{cotacao_id} · {e(c['cidade_origem'])}/{e(c['uf_origem'])}
→ {e(c['cidade_destino'])}/{e(c['uf_destino'])}</p>

<div class="cartao">
  <div class="alerta email"><b>Esta é a via rápida: responde em 2 a 5
  minutos</b>, contra 10 a 12 horas do e-mail avulso. É o formulário
  OFICIAL deles — o preenchimento só poupa a digitação, quem resolve o
  captcha e clica em enviar é você.</div>

  <p><b>Passo 1 — só na primeira vez:</b> arraste este link para a barra de
  favoritos do navegador.</p>
  <p><a class="botao2" href="{href_favorito}"
  onclick="return confirm('Não clique — ARRASTE este link para a barra de favoritos.')"
  >📋 Preencher cotação (Cotafrete)</a></p>

  <img class="print" src="/ajuda/passo1_barra_favoritos.png"
  alt="Print: o favorito salvo na barra do navegador, com uma seta apontando para ele">
  <p class="sub">Depois de arrastar, o favorito "Preencher cotação
  (Cotafrete)" fica salvo na barra do navegador (seta na imagem) — é nele que
  você vai clicar no Passo 3, sempre na aba NOVA da Della Volpe.</p>

  <p><b>Passo 2:</b> abra o formulário da Della Volpe nesta aba nova.</p>
  <p><a class="botao2" href="{e(url)}" target="_blank" rel="noopener"
  >Abrir formulário da Della Volpe</a></p>

  <p><b>Passo 3:</b> NA ABA NOVA, clique no favorito "Preencher cotação
  (Cotafrete)" que você salvou no passo 1. Os campos enchem sozinhos, e
  aparece um aviso do navegador confirmando — é só clicar OK.</p>

  <img class="print" src="/ajuda/passo3_alerta_preenchido.png"
  alt="Print: aviso do navegador dizendo que o Cotafrete preencheu os campos">
  <p class="sub">É este o aviso que aparece depois do clique: "Cotafrete
  preencheu os campos. Confira, resolva o captcha e clique em 'Pedir
  orçamento'." Clique OK e siga para o Passo 4.</p>

  <p><b>Passo 4:</b> confira os dados preenchidos e resolva o captcha da
  Della Volpe ("confirme que é humano") — quando ele validar, aparece um
  quadradinho verde escrito <b>"Sucesso!"</b>. Só depois clique em
  "Pedir orçamento". Isso o sistema não faz por você — nem deveria.</p>

  <img class="print" src="/ajuda/passo4_captcha_sucesso.png"
  alt="Print: captcha da Della Volpe resolvido, mostrando Sucesso em verde">
  <p class="sub">É este quadradinho verde que confirma que o captcha foi
  resolvido. Só depois dele aparecer o clique em "Pedir orçamento" envia de
  verdade.</p>

  <div class="alerta"><b>É normal o primeiro clique em "Pedir orçamento"
  parecer que não fez nada.</b> Enquanto o captcha não terminar de validar
  (o "Sucesso!" verde acima), o formulário não envia de verdade. Confira se o
  "Sucesso!" apareceu e clique em "Pedir orçamento" outra vez.</div>

  <p class="sub">Anexo de planilha ou FISPQ não entra sozinho — o navegador
  não permite preencher esse tipo de campo por segurança. Anexe à mão se a
  carga precisar.</p>
</div>

<p class="sub">Prefere continuar mandando por e-mail (mais lento)?
<a href="/email/{cotacao_id}/dellavolpe">Abrir e-mail pronto</a></p>

<p><a class="botao2" href="/cotacao/{cotacao_id}">voltar para a cotação</a></p>
<script>
// Mesmo gesto das prints de resultado: clique amplia, porque os detalhes do
// captcha e da barra de favoritos ficam pequenos demais para ler direto.
document.querySelectorAll(".print").forEach(i =>
  i.onclick = () => i.classList.toggle("zoom"));
</script>
""", usuario))


@app.get("/cotacao/{cotacao_id}", response_class=HTMLResponse)
def ver_cotacao(cotacao_id: int,
                usuario: str | None = Cookie(None, alias=COOKIE)):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c = banco.buscar_cotacao(cotacao_id, usuario)
    if c is None:
        return HTMLResponse(pagina("Não encontrada", """
<div class="cartao"><h1>Cotação não encontrada</h1>
<p class="sub">Ou ela não existe, ou é de outro usuário.</p>
<p><a href="/historico">← histórico</a></p></div>""", usuario),
            status_code=404)

    try:
        qtd = int(c["quantidade"])
    except (TypeError, ValueError):
        qtd = 1

    # O selo compara só quem cotou a MESMA coisa. R$ 33,29 por volume não é
    # mais barato que R$ 69,91 pela carga toda quando são 3 volumes — e o
    # menor número com selo verde é o que fecha negócio. Fica de fora em vez
    # de disputar pela estimativa: a estimativa serve para o vendedor pensar,
    # não para o sistema eleger vencedor.
    precos = [r["valor"] for r in c["resultados"]
              if r["valor"] is not None
              and not cota_por_volume(r["transportadora"], qtd)]
    melhor = min(precos) if precos else None

    cartoes = ""
    for r in c["resultados"]:
        slug = r["transportadora"]
        if r["valor"] is not None:
            destaque = " melhor" if r["valor"] == melhor else ""
            selo = '<span class="selo">MAIS BARATO</span>' if destaque else ""
            incerto = " incerto" if cota_por_volume(slug, qtd) else ""
            corpo = (f'<div class="valor{incerto}">'
                     f'{moeda(r["valor"])}</div>')
            if cota_por_volume(slug, qtd):
                corpo += (
                    f'<div class="alerta"><b>Preço de 1 volume, não da '
                    f'carga.</b> São {qtd} volumes: por estimativa, '
                    f'{moeda(r["valor"] * qtd)} no total. Por isso ela não '
                    f'disputa o selo de mais barato.</div>')
            # Preço válido pode vir com uma ressalva (ex.: Camilo "Entrega
            # em área de risco", cotação #99 de 01/09/2026) — não é falha,
            # mas o vendedor precisa ler antes de fechar.
            if r["erro"]:
                corpo += (f'<div class="alerta">'
                          f'{e(r["erro"][:LIMITE_MENSAGEM_ERRO])}</div>')
            corpo += f'<div class="nota">{e(NOTAS.get(slug, ""))}</div>'
            if r["protocolo"]:
                corpo += (f'<div class="nota">Cotação nº '
                          f'{e(r["protocolo"])}</div>')
            corpo += _img(r["evidencia"])
        elif r["status"] == StatusCotacao.INTERVENCAO_NECESSARIA.value:
            # Senha recusada. Diferente de um erro qualquer porque o vendedor
            # NÃO consegue resolver — e se ele repetir a cotação, cada
            # repetição é mais um login errado empurrando a conta da Ventura
            # para o bloqueio. O cartão precisa dizer isso com todas as
            # letras, senão repetir é exatamente o que ele vai fazer.
            destaque, selo = "", ""
            corpo = ('<div class="falhou">Precisa de alguém</div>'
                     f'<div class="alerta email"><b>Repetir a cotação não '
                     f'resolve.</b> A senha desta transportadora precisa ser '
                     f'conferida no sistema. Avise quem cuida do Cotafrete e '
                     f'siga pelo WhatsApp aqui embaixo.</div>'
                     f'<div class="nota">'
                     f'{e((r["erro"] or "")[:LIMITE_MENSAGEM_ERRO])}</div>')
        elif r["status"] == StatusCotacao.AGUARDANDO_RETORNO.value:
            # Recebido, sem preço e sem falha. Precisa vir ANTES do ramo de
            # erro: lá embaixo tudo que não tem valor é tratado como problema.
            destaque, selo = "", ""
            # O print da tela "Recebemos seu pedido" é a prova de que o envio
            # saiu. Sem ele o vendedor só tem a nossa palavra.
            corpo = (cartao_resposta_por_email(c.get("email"), slug)
                     + _img(r["evidencia"]))
        elif r["status"] == StatusCotacao.RECUSADO.value:
            # Recusa NÃO é defeito. O site recebeu a carga inteira, entendeu,
            # e disse não — com estas palavras. Cotação #20 (25/08/2026): a
            # Camilo escreveu "Cliente não possui tabela de frete negociada"
            # e o vendedor leu "Não retornou preço", que é a frase de quando
            # ninguém sabe o que houve. Aí ele repete a cotação três vezes
            # atrás de um preço que nunca vai vir.
            #
            # O print entra junto: é a prova de que o "não" veio do site.
            destaque, selo = "", ""
            corpo = ('<div class="falhou">O site não cotou</div>'
                     f'<div class="alerta">'
                     f'{e((r["erro"] or "")[:LIMITE_MENSAGEM_ERRO])}</div>'
                     + _img(r["evidencia"]))
        else:
            destaque, selo = "", ""
            # Sempre dizer POR QUE não veio preço. "Não retornou preço" sozinho
            # manda o operador adivinhar — e foi status sem explicação que
            # escondeu, neste projeto, cinco envios que nunca saíram.
            #
            # O print faltava justamente aqui, no único ramo em que a tela do
            # site é a informação que importa: é nela que se vê em que passo
            # a coisa parou.
            motivo = r["erro"] or f"o site respondeu: {r['status']}"
            # A frase entra ANTES do texto técnico, nunca no lugar dele: o
            # vendedor lê a primeira linha e resolve; quem for investigar
            # continua tendo o original logo abaixo.
            frase = mensagem_amigavel(slug, r["erro"])
            corpo = ('<div class="falhou">Não retornou preço</div>'
                     + (f'<div class="alerta">{e(frase)}</div>' if frase else '')
                     + f'<div class="nota">'
                       f'{e(motivo[:LIMITE_MENSAGEM_ERRO])}</div>'
                     + _img(r["evidencia"]))
        cartoes += (f'<div class="res{destaque}"><div class="nome">'
                    f'{e(NOMES.get(slug, slug))} {selo}</div>{corpo}</div>')

    # Quem ainda não respondeu ganha um cartão "cotando". Sem isso a
    # transportadora simplesmente não aparece, e o usuário não sabe se ela
    # falhou ou se ainda está rodando.
    respondidas = {r["transportadora"] for r in c["resultados"]}
    escolhidas = c.get("transportadoras")
    faltam = [s for s in automaticas_da(escolhidas) if s not in respondidas]

    # Passado o teto, assume que não vem mais nada. Precisa ser decidido AQUI,
    # antes dos cartões: eles mudam de "cotando…" para "Sem retorno" conforme
    # esta resposta. Calcular depois do laço dava UnboundLocalError em toda
    # cotação recém-enviada — ou seja, na primeira tela que o usuário vê.
    try:
        idade = (datetime.now()
                 - datetime.fromisoformat(c["criado_em"])).total_seconds()
    except (ValueError, TypeError):
        idade = 0
    desistiu = bool(faltam) and idade > ESPERA_MAXIMA_S

    for slug in faltam:
        # A tentativa aparece na tela porque "cotando…" parado por três
        # minutos faz o vendedor achar que travou — e aí ele recarrega no
        # meio, ou desiste e liga para a transportadora à toa.
        tentativa = TENTATIVAS_EM_CURSO.get((cotacao_id, slug), 1)
        andamento = ('cotando…' if tentativa <= 1 else
                     f'tentando de novo ({tentativa} de {TENTATIVAS_MAXIMAS})')
        dentro = ('<div class="falhou">Sem retorno</div>'
                  if desistiu else
                  f'<div class="cotando"><span class="girando"></span>'
                  f'{andamento}</div>')
        cartoes += (f'<div class="res"><div class="nome">'
                    f'{e(NOMES.get(slug, slug))}</div>{dentro}</div>')

    # Recarrega sozinho de 3 em 3 segundos ENQUANTO faltar transportadora.
    # Quando todas responderem, para — recarregar uma página pronta faria a
    # imagem piscar e atrapalharia quem está lendo o resultado. Depois do teto
    # também para: sem isso a página pisca para sempre se um resultado nunca
    # chegar.
    recarrega = ('<meta http-equiv="refresh" content="3">'
                 if faltam and not desistiu else "")
    if desistiu:
        cabecalho_espera = (
            f'<div class="aviso">{len(faltam)} transportadora(s) não '
            f'responderam em {ESPERA_MAXIMA_S // 60} minutos. Pode ter sido '
            f'queda de rede ou o sistema fechado no meio. '
            f'<a href="/?repetir={cotacao_id}">Cotar de novo</a>.</div>')
    elif faltam:
        cabecalho_espera = (
            f'<div class="aviso">Cotando em {len(faltam)} transportadora(s). '
            f'A página se atualiza sozinha — pode deixar aberta.</div>')
    else:
        cabecalho_espera = ""

    lista_zap = [r for r in transportadoras.com_whatsapp()
                 if selecao.entra(r.slug, escolhidas)]
    lista_email = [r for r in transportadoras.com_email()
                   if selecao.entra(r.slug, escolhidas)]
    abertas = banco.whatsapp_abertos(cotacao_id)
    zaps = "".join(
        f'<a class="zap{" aberta" if reg.slug in abertas else ""}"'
        f' id="zap-{e(reg.slug)}"'
        f' href="/whatsapp/{cotacao_id}/{e(reg.slug)}"'
        f' target="_blank" rel="noopener">'
        f'<img class="marca" src="/logos/{e(reg.logo)}" alt="" loading="lazy">'
        f'<b>{e(reg.nome)}</b>'
        + (f'<span class="selo-obs">{e(reg.observacao)}</span>'
           if reg.tem_observacao else '')
        + f'<span class="ir">Abrir no WhatsApp</span>'
        f'<span class="jafoi">Aberta</span></a>'
        for reg in lista_zap)

    # A Della Volpe é um caso à parte: para ela existe uma via mais rápida
    # (o formulário oficial deles, preenchido por bookmarklet — responde em
    # 2 a 5 min) contra 10 a 12h do e-mail avulso das outras. Rápida demais
    # para ficar perdida entre fileiras de "escreva e mande" — vira cartão
    # próprio, abaixo das automáticas e ACIMA do "Precisa de você", com botão
    # maior: o tamanho já diz "comece por aqui" sem precisar de mais texto.
    #
    # Sai de lista_email ANTES do laço abaixo — senão entra duas vezes: uma
    # aqui, genérica, e outra no cartão dela.
    dv = next((r for r in lista_email if r.slug == "dellavolpe"), None)
    lista_email = [r for r in lista_email if r.slug != "dellavolpe"]

    # As de e-mail entram na MESMA seção: para o vendedor o gesto é o mesmo —
    # o sistema deixou pronto e ele age. Só o destino muda, e o rótulo diz.
    for reg in lista_email:
        zaps += (
            f'<a class="zap{" aberta" if reg.slug in abertas else ""}"'
            f' id="zap-{e(reg.slug)}"'
            f' href="/email/{cotacao_id}/{e(reg.slug)}"'
            f' target="_blank" rel="noopener">'
            f'<img class="marca" src="/logos/{e(reg.logo)}" alt="" loading="lazy">'
            f'<b>{e(reg.nome)}</b>'
            f'<span class="ir">Abrir e-mail pronto</span>'
            f'<span class="jafoi">Aberta</span></a>')

    semiautomatica = ""
    if dv:
        semiautomatica = (
            f'<div class="cartao">'
            f'<h2 style="font-size:15px;margin:0 0 4px">Semiautomática</h2>'
            f'<p class="sub">O formulário oficial da Della Volpe já vem '
            f'preenchido — falta só você conferir, resolver o captcha e '
            f'clicar em enviar. Responde em 2 a 5 minutos, contra 10 a 12 '
            f'horas do e-mail avulso.</p>'
            f'<a class="zap zap-dv{" aberta" if dv.slug in abertas else ""}"'
            f' id="zap-{e(dv.slug)}" href="/dellavolpe/{cotacao_id}"'
            f' target="_blank" rel="noopener">'
            f'<img class="marca" src="/logos/{e(dv.logo)}" alt="" loading="lazy">'
            f'<b>{e(dv.nome)}</b>'
            f'<span class="ir">Preencher formulário (rápido)</span>'
            f'<span class="jafoi">Aberta</span></a></div>')

    return HTMLResponse(pagina(f"Cotação {cotacao_id}", f"""
{recarrega}
{cabecalho_espera}
<h1>Cotação #{cotacao_id}</h1>
<p class="sub">{e(c['cidade_origem'])}/{e(c['uf_origem'])} →
{e(c['cidade_destino'])}/{e(c['uf_destino'])} · {e(c['quantidade'])} volume(s)
· {_kg(c['peso_kg'])} kg · {e(c['comprimento_cm'])}×{e(c['largura_cm'])}×{e(c['altura_cm'])} cm
· NF {moeda(c['valor_nf'])} · {e(c['material'])}</p>

<div class="cartao">
  <h2 style="font-size:15px;margin:0 0 12px">Cotadas automaticamente</h2>
  <div class="resultados">{cartoes or '<p class="sub">Nenhum resultado.</p>'}</div>
</div>

{semiautomatica}

<div class="cartao">
  <h2 style="font-size:15px;margin:0 0 4px">Precisa de você
    <span class="contador"><b id="quantas">{len(abertas & {r.slug for r in lista_zap + lista_email})}</b> de
    {len(lista_zap) + len(lista_email)} abertas</span></h2>
  <p class="sub">A mensagem abre pronta — <b>quem aperta enviar é você</b>,
  no WhatsApp. Por isso a conta acima diz <b>abertas</b>, e não enviadas:
  daqui o sistema não tem como saber se a mensagem saiu.</p>
  <div id="grupo-precisa">{zaps}</div>
</div>

{ficha_da_cotacao(c)}

<p><a class="botao2" href="/?repetir={cotacao_id}">Repetir esta cotação</a>
&nbsp;&nbsp; <a href="/">nova cotação</a> &nbsp;·&nbsp;
<a href="/historico">histórico</a></p>
<script>
// O link abre em outra aba; ESTA pagina fica parada. Sem marcar na hora, o
// vendedor volta e ve a lista igualzinha, sem saber onde parou. O servidor ja
// registrou de qualquer jeito -- isto aqui e so o olho acompanhando o dedo.
document.querySelectorAll(".zap").forEach(a => a.addEventListener("click", () => {{
  if (a.classList.contains("aberta")) return;
  a.classList.add("aberta");
  // A Della Volpe tem cartão próprio, fora do #grupo-precisa -- o contador
  // "X de Y abertas" e SO do WhatsApp/e-mail, e contar o clique dela ali
  // faria a conta passar do total mostrado no cabecalho.
  if (!a.closest("#grupo-precisa")) return;
  const q = document.getElementById("quantas");
  q.textContent = String(Number(q.textContent) + 1);
}}));

// clique amplia o print: na tela ele fica pequeno, e o funcionario precisa
// conseguir ler a composicao do frete para explicar ao cliente
document.querySelectorAll(".print").forEach(i =>
  i.onclick = () => i.classList.toggle("zoom"));
</script>
""", usuario))


# ---------------------------------------------------------------- histórico
# ------------------------------------------------------- documentação
def _lista_automaticas() -> str:
    """Os nomes vêm de NOMES e as frases de NOTAS — as MESMAS que o cartão da
    cotação usa. Escrever a lista à mão aqui faria a ajuda descrever um
    sistema que não é este; foi assim que "todas as 17 transportadoras" ficou
    mentindo por semanas."""
    return "".join(
        f"<li><b>{e(NOMES[s])}</b> — {e(NOTAS[s])}</li>" for s in AUTOMATICAS)


def pagina_documentacao() -> str:
    """A ajuda que o vendedor lê.

    Todo número aqui é derivado de onde o sistema o lê de verdade. É a mesma
    razão do subtítulo da home ser calculado: número escrito à mão apodrece em
    silêncio, e ajuda errada é pior que ajuda nenhuma — quem lê erra com
    confiança."""
    com_zap = transportadoras.com_whatsapp()
    zap = len(com_zap)
    # A Translovato e automatica E tem WhatsApp, entao 5 + 14 da 19 e o total
    # e 18. Dizer "e as OUTRAS 14" fazia o vendedor somar 19 e procurar uma
    # transportadora que nao existe. A frase nomeia quem se repete, e o nome
    # sai da intersecao real das duas listas.
    slugs_zap = {r.slug for r in com_zap}
    nas_duas = [NOMES[s] for s in AUTOMATICAS if s in slugs_zap]
    repetida = (f" A {' e a '.join(nas_duas)} "
                f"{'entram' if len(nas_duas) > 1 else 'entra'} nas duas "
                f"listas, por isso a soma não bate." if nas_duas else "")
    return f"""
<h1>Como usar o Cotafrete</h1>
<p class="sub">Você preenche a carga uma vez. O sistema cota sozinho em
{len(AUTOMATICAS)} transportadoras e deixa a mensagem do WhatsApp pronta para
{zap}. São {len(TODAS_AS_SLUGS)} no total.{repetida}</p>

<div class="cartao doc">
<h2>O caminho normal</h2>
<p class="passo">1. Preencha o formulário na aba <b>Nova cotação</b>.<br>
2. Se quiser, escolha quais transportadoras vão cotar.<br>
3. Clique em <b>Cotar fretes</b>. A tela se atualiza sozinha conforme cada uma
responde — não precisa recarregar nem ficar apertando F5.<br>
4. Compare os preços. O mais barato ganha um selo verde.</p>
<p>A cotação inteira leva até {ESPERA_MAXIMA_MIN} minutos. Passado esse tempo
a tela para de atualizar e diz quem não respondeu.</p>

<h2>Preenchendo o formulário</h2>
<ul>
  <li><b>CEP de origem e destino</b> — 8 dígitos. A cidade e o estado aparecem
      sozinhos; você não digita.</li>
  <li><b>CNPJ do remetente e do destinatário</b> — 14 dígitos. O sistema
      confere o dígito verificador e busca a razão social.</li>
  <li><b>Tipo de frete</b> — <b>CIF</b> quem paga é o remetente, <b>FOB</b>
      quem paga é o destinatário. Você não digita quem paga: o sistema tira do
      CNPJ da ponta certa. Marcar errado faz a transportadora cotar para a
      empresa errada.</li>
  <li><b>Quantidade de volumes</b> — quantas caixas.</li>
  <li><b>Peso</b> — o peso <b>de um volume</b>, não o do lote. Três caixas de
      12 kg são <b>12</b> aqui e <b>3</b> na quantidade.</li>
  <li><b>Comprimento, largura e altura</b> — em <b>centímetros</b>, de uma
      caixa.</li>
  <li><b>Valor da nota fiscal</b> e <b>Material</b> — o que é a carga, em
      palavras.</li>
  <li><b>Nome, e-mail e WhatsApp</b> — seus dados de contato, que entram
      na mensagem pronta das transportadoras que você aciona à mão.</li>
</ul>

<h2>Os erros que mais custam caro</h2>
<p>O sistema barra tudo isto <b>antes</b> de cotar, com os seus dados
preservados na tela — você corrige e segue, sem redigitar nada.</p>
<table>
<tr><th>o que acontece</th><th>por que dá problema</th></tr>
<tr><td><span class="errado">Medida em metro</span> no campo de
    centímetro</td>
    <td>O pior de todos. Uma caixa de <span class="certo">30</span> cm
    digitada como <span class="errado">0,3</span> cota uma carga 100 vezes
    menor, e o preço volta barato e errado. Por isso nada abaixo de
    {MEDIDA_MINIMA_CM} cm passa.</td></tr>
<tr><td><span class="errado">Zero</span> em qualquer medida, na quantidade ou
    no valor da nota</td>
    <td>Vira uma carga que não existe. A cotação #14 saiu como "0x1x0 cm" e a
    transportadora recusou sem dizer por quê.</td></tr>
<tr><td><span class="errado">Peso do lote</span> no campo de peso</td>
    <td>O campo é o peso de UM volume. Pôr o total ali multiplica a carga pela
    quantidade e o frete sai caro demais.</td></tr>
<tr><td>Peso abaixo de <span class="errado">{PESO_MINIMO_KG} kg</span></td>
    <td>A {e(NOMES["dellavolpe"])} não cota abaixo disso, e você só
    descobriria depois de dois minutos de espera.</td></tr>
<tr><td>CEP ou CNPJ <span class="errado">incompleto</span></td>
    <td>O sistema diz quantos dígitos vieram e quantos faltam.</td></tr>
<tr><td><span class="errado">Nenhuma</span> transportadora marcada</td>
    <td>Cotar em ninguém não é uma cotação — sobraria uma linha vazia no
    histórico.</td></tr>
</table>

<h2>Escolher as transportadoras</h2>
<p>Acima do botão de cotar há o painel <b>Escolher</b>. Ele vem com todas as
{len(TODAS_AS_SLUGS)} marcadas. Desmarque quem você não quer nesta cotação —
serve para pedir preço só a quem atende aquela rota, ou para repetir uma
cotação só na que faltou.</p>
<p>Quem você desmarcar não aparece na tela do resultado: nem com preço, nem
como "cotando", nem como quem falhou.</p>

<h2>O que cada cartão do resultado quer dizer</h2>
<ul>
  <li><b>Preço em verde</b> — cotou. O menor leva o selo
      <b>MAIS BARATO</b>.</li>
  <li><b>"Preço de 1 volume, não da carga"</b> — a {e(NOMES["jadlog"])} cota
      <b>por volume</b>. Com mais de uma caixa o sistema mostra a estimativa
      do total e tira ela da disputa do selo, porque comparar preço de uma
      caixa com preço da carga inteira elege o vencedor errado.</li>
  <li><b>"Cotação enviada"</b> — o pedido entrou, mas o preço não vem nesta
      tela: chega no seu e-mail.</li>
  <li><b>"O site não cotou"</b> — a transportadora entendeu a carga e disse
      não, com as palavras dela na tela. Repetir dá o mesmo resultado.</li>
  <li><b>"Precisa de alguém"</b> — a senha daquela transportadora foi
      recusada. Repetir não resolve e ainda empurra a conta da Ventura para o
      bloqueio: avise quem cuida do Cotafrete e siga pelo WhatsApp.</li>
  <li><b>"Não retornou preço"</b> — algo deu errado, e o cartão diz o quê.</li>
  <li><b>"cotando…"</b> — ainda esperando. Quando uma tentativa falha o
      sistema tenta de novo sozinho, até {TENTATIVAS_MAXIMAS} vezes, e o
      cartão avisa em qual tentativa está.</li>
</ul>

<h2>Todo erro vem com print</h2>
<p>Sempre que uma transportadora não devolve preço, o sistema guarda uma
<b>foto da tela dela</b> no momento exato do problema e mostra no cartão. É a
prova de que o "não" veio do site e não do Cotafrete — e é o que você manda
para a transportadora quando precisa reclamar.</p>
<p>Nas que dão certo o print também fica: a tela preenchida, com o preço.</p>

<h2>A {e(NOMES["dellavolpe"])} mudou: agora quem envia é você</h2>
<div class="alerta email">
<p>Ela era cotada sozinha até <b>31/08/2026</b>. Nesse dia o site dela passou
a exigir uma verificação <b>"confirme que é humano"</b> — aquela caixinha da
Cloudflare — e o sistema não marca essa caixa por você: ela existe justamente
para impedir que um programa envie o formulário.</p>
<p>Tentar assim mesmo não funcionava e ainda enganava: o site respondia
"submissão marcada como spam" e <b>nenhum e-mail era gerado</b>. Testado com
envio real: nem o segundo clique passa.</p>
<p><b>O que mudou para você:</b> ela saiu da parte de cima da tela e agora
aparece em <b>Precisa de você</b>, junto das do WhatsApp.</p>
<p><b>Preferência: "Preencher formulário (rápido)".</b> Abre o formulário
OFICIAL da Della Volpe com os campos já prontos — na primeira vez você
arrasta um favorito para o navegador; depois disso é clicar nele em cada
cotação nova, conferir, resolver o captcha e enviar. Continua sendo você
que envia — o sistema só poupa a digitação. É a via rápida: costuma
responder em <b>2 a 5 minutos</b>, o mesmo prazo de quando ela cotava
sozinha.</p>
<p><b>Alternativa: "Abrir e-mail pronto".</b> Mostra a cotação já escrita e
o endereço deles — você copia, cola no seu e-mail e manda. Funciona sempre,
mas cai numa fila de e-mail avulso: costuma demorar <b>10 a 12 horas</b>
para responder. Use quando o formulário oficial estiver fora do ar, ou
antes de instalar o favorito.</p>
</div>

<h2>As {zap} do WhatsApp</h2>
<p>As que não têm sistema online ficam na parte de baixo da tela, em
<b>Precisa de você</b>. Clicar em <b>Abrir no WhatsApp</b> abre a conversa com
a mensagem <b>já escrita</b>: remetente, destinatário, quem paga, CEPs,
medidas, peso, valor da nota e o material.</p>
<p><b>Quem aperta enviar é você.</b> Por isso o contador diz <b>abertas</b> e
não "enviadas" — depois que a conversa abre, o sistema não tem como saber se
a mensagem saiu.</p>

<h2>Histórico e repetir</h2>
<p>A aba <b>Histórico</b> guarda suas cotações com a rota, o material, o peso
e o melhor preço. Clique numa linha para rever todos os preços e os prints
daquele dia.</p>
<p>Dentro de uma cotação, <b>Repetir esta cotação</b> devolve o formulário já
preenchido com aqueles dados — serve para mudar só o peso, só o destino, ou
para tentar de novo quem falhou.</p>

<h2>Quem cota sozinho hoje</h2>
<ul>{_lista_automaticas()}</ul>
</div>

<p><a href="/">← nova cotação</a></p>"""


@app.get("/documentacao", response_class=HTMLResponse)
def documentacao(usuario: str | None = Cookie(None, alias=COOKIE)):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(pagina("Documentação", pagina_documentacao(), usuario))


@app.get("/historico", response_class=HTMLResponse)
def historico(usuario: str | None = Cookie(None, alias=COOKIE)):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    linhas = ""
    for c in banco.listar_cotacoes(usuario):
        linhas += (
            f"""<tr onclick="location='/cotacao/{c['id']}'" style="cursor:pointer">
            <td>#{c['id']}</td>
            <td>{e(c['criado_em'].replace('T', ' '))}</td>
            <td><b>{e(c['material'])}</b></td>
            <td>{e(c['cidade_origem'])}/{e(c['uf_origem'])} →
                {e(c['cidade_destino'])}/{e(c['uf_destino'])}</td>
            <td>{e(c['peso_kg'])} kg</td>
            <td><b>{moeda(c['melhor_preco'])}</b></td></tr>""")

    return HTMLResponse(pagina("Histórico", f"""
<h1>Histórico</h1>
<p class="sub">Suas cotações. Clique numa linha para ver o preço de cada
transportadora.</p>
<div class="cartao"><table>
<tr><th>#</th><th>quando</th><th>material</th><th>rota</th><th>peso</th>
<th>melhor preço</th></tr>
{linhas or '<tr><td colspan="6" class="sub">Nenhuma cotação ainda.</td></tr>'}
</table></div>
<p><a href="/">← nova cotação</a></p>""", usuario))
