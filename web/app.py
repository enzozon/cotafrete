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

import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

load_dotenv(override=False)

from carriers.braspress.adapter import BraspressAdapter
from carriers.camilo.adapter import CamiloAdapter
from carriers.dellavolpe import bookmarklet as dv_bookmarklet
from carriers.dellavolpe import caixa as dv_caixa
from carriers.dellavolpe import ingestor as dv_ingestor
from carriers.dellavolpe.adapter import DellavolpeAdapter
from carriers.generoso.adapter import GenerosoAdapter
from carriers.jadlog.painel import JadlogPainelAdapter
from carriers.translovato.adapter import TranslovatoAdapter
from core import cep as buscador_cep
from core import sessao
from core import cnpj as buscador_cnpj
from core import selecao
from core.aceite import rotulo_validade, vencida
from carriers.generoso.mapping import Agendamento, validar_agendamento
from core.banco import Banco
from core.evidencias import limpar_antigas, montar_zip_de_prints
from core.retentativa import (
    ESPERA_MAXIMA_S, SEM_REPETICAO, TENTATIVAS_MAXIMAS, cotar_com_retentativa,
)
from web import adm, transportadoras
from web.ficha_ui import (
    ficha_da_cotacao, kg as _kg, pagador_da_cotacao, peso_por_volume,
    quando as quando_humano, quem_e as _quem,
)
from web.layout import (MALHA_CORREDORES, cabecalho, e_pdf, entrada, e, moeda,
                        pagina, print_embutido as _img)
from web.transportadoras import cota_por_volume
from web.aceite_ui import COM_ACEITE, celula_de_aceite, tela_aceite
from core.models import (
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, StatusCotacao, TipoFrete, Volume, limpa_doc,
)

# O ingestor de e-mail da Della Volpe (carriers/dellavolpe/ingestor.py): uma
# thread que lê a caixa do suporte de minuto em minuto e grava o preço que
# chega em PDF.
#
# Sobe no LIFESPAN, e não no import, ao contrário de marcar_interrompidas lá
# embaixo: o import acontece também no pytest, num script solto, num segundo
# processo na mesma pasta — e cada um deles abriria a caixa do suporte e
# brigaria com o servidor pelos mesmos e-mails. O lifespan só roda quando o
# uvicorn sobe de verdade (o TestClient sem `with` nem o chama).
INGESTOR: dv_ingestor.Vigia | None = None


@asynccontextmanager
async def _vida(_app):
    global INGESTOR
    if INGESTOR is None:
        INGESTOR = dv_ingestor.iniciar(banco)
        if INGESTOR is not None:
            print(f"[cotafrete] Della Volpe: lendo as propostas em "
                  f"{INGESTOR.cx.usuario} a cada "
                  f"{INGESTOR.cx.intervalo_s} s.")
    yield
    if INGESTOR is not None:
        INGESTOR.parar.set()


app = FastAPI(title="Cotafrete — Ventura", lifespan=_vida)
banco = Banco()

# Faxina dos prints velhos (>30 dias) a cada início do servidor — não há
# scheduler no projeto, e reiniciar já é rotina (ver core/evidencias.py).
limpar_antigas()

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

# As peças da marca. Servidas como ARQUIVO, e não embutidas em base64 como a
# logo antiga: aquela tinha 26 KB e cabia dentro de cada página; estas somam
# ~110 KB, e 110 KB em toda resposta não cabe. Assim o navegador busca uma
# vez e guarda — que é o que /logos já faz com as transportadoras.
PASTA_MARCA = Path(__file__).parent / "marca"
app.mount("/marca", StaticFiles(directory=PASTA_MARCA), name="marca")

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
#
# Em 22/09/2026 a caixinha tinha sumido (0 desafios em 12 aberturas, ver
# recon/recon_dellavolpe_turnstile.py), e ela pode VOLTAR — pelo .env, com a
# data do dia (ver carriers/dellavolpe/caixa.py). Se a caixinha reaparecer,
# a cotação não vira cartão vermelho: cai no formulário assistido.
#
# Vem de lá, e não é definida aqui, porque web/adm.py também precisa desta
# lista (para não alertar sobre quem já saiu da automação) e não pode
# importar este módulo — é este que registra as rotas do adm.
AUTOMATICAS = transportadoras.AUTOMATICAS

# Desde quando cada automática existe de verdade em produção (ISO 8601) —
# para marcar_interrompidas nunca carimbar "sistema fechado no meio" numa
# cotação de ANTES da transportadora nascer. Sem esta data, toda vez que uma
# automática nova entra aqui a varredura de cotação-sem-resposta volta a TODO
# o histórico: foi o que aconteceu com a Braspress em 02-03/09/2026 (118
# linhas fantasma) e, num susto menor, com a Generoso em 20-24/08 (4 linhas).
# Camilo e Jadlog usam a data mais antiga que o banco tem (19/08/2026) porque
# são as duas originais — não há cotação anterior a elas para carimbar errado.
AUTOMATICA_DESDE = {
    "camilo": "2026-08-14T00:00:00",
    "jadlog": "2026-08-14T00:00:00",
    "translovato": "2026-08-18T17:28:00",
    "generoso": "2026-08-24T10:47:15",
    "braspress": "2026-09-03T08:51:41",
}
# A data dela vem do .env, junto com a decisão de ligá-la: é o dia em que ela
# volta a cotar NO SERVIDOR, que nenhum commit sabe.
if "dellavolpe" in AUTOMATICAS:
    AUTOMATICA_DESDE["dellavolpe"] = dv_caixa.automatica_desde()

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
#
# A Della Volpe fica de fora: desde 23/09/2026 ela só sai quando o vendedor
# escolhe, na tela, para onde vai a proposta — e "ninguém escolheu" não é
# cotação interrompida. O "enviando" dela que morreu com o processo é fechado
# lá dentro, pelo relógio do clique (`pedido_em`).
_orfas = banco.marcar_interrompidas(
    {s: d for s, d in AUTOMATICA_DESDE.items() if s != "dellavolpe"})
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
#
# Desde 22/09/2026 ela só entra na lista COM a trava liberada (ver
# dv_caixa.automatica), então o que sobra para avisar é o .env pela metade:
# alguém tentou ligar e faltou uma linha.
for _falta in dv_caixa.o_que_falta():
    print(f"[cotafrete] AVISO: Della Volpe — falta no .env: {_falta}")

# Nome de tela e logo das automáticas. O cadastro mora em
# web/transportadoras.py, junto com o das de WhatsApp — foi para lá em
# 04/09/2026, quando o painel do adm passou a precisar dos mesmos nomes e não
# pode importar este arquivo de volta (seria circular).
#
# Os dois apelidos ficam: são o nome pelo qual o resto deste módulo — e os
# testes — já chamavam as duas tabelas.
LOGOS_AUTOMATICAS = transportadoras.LOGOS_AUTOMATICAS
NOMES = transportadoras.NOMES_AUTOMATICAS
NOTAS = {
    "camilo": "Frete fracionado, com coleta. Preço já com taxas e ICMS.",
    "jadlog": "Etiqueta pré-paga, cotada por volume. Você leva ao balcão.",
    "translovato": "Frete fracionado, com coleta. Só atende parte do país — fora da malha ela avisa.",
    "generoso": ("Frete fracionado, com coleta. Cotada com a empresa do "
                 "grupo que você informou no formulário."),
    # Até 22/09/2026 era a ÚNICA automática sem preço na tela, e a nota
    # avisava isso. Desde 22/09/2026 o preço dela VOLTA para a tela, lido do PDF que chega
    # por e-mail (carriers/dellavolpe/ingestor.py). Esta nota só aparece ao
    # lado de um preço, então ela diz o que o número cobre — e de onde veio.
    "dellavolpe": ("Frete fracionado, com coleta. Valor total da proposta, "
                   "com taxas e ICMS — lido do PDF que ela manda por "
                   "e-mail."),
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

# Por quanto tempo a tela da cotação continua se atualizando sozinha à espera
# da proposta da Della Volpe. Ela chega em 2 a 5 minutos; meia hora cobre um
# dia ruim sem deixar uma aba esquecida recarregando para sempre.
ESPERA_PELA_PROPOSTA_S = 30 * 60

# Onde o vendedor instala o Tampermonkey (o gerenciador de scripts que roda o
# preenchimento da Della Volpe — ver carriers/dellavolpe/bookmarklet.py).
ID_TAMPERMONKEY = "dhdgffkkebhmkfjojejmpbldmpobfkfo"
URL_TAMPERMONKEY = ("https://chromewebstore.google.com/detail/tampermonkey/"
                    + ID_TAMPERMONKEY)
# Os detalhes do Tampermonkey em chrome://extensions, direto na chave
# "Permitir scripts de usuário". Vai para a área de transferência, e não num
# link: o Chrome não abre chrome:// a partir de um site — o clique não faz
# nada, e isso não tem configuração do nosso lado.
URL_DETALHES_TAMPERMONKEY = f"chrome://extensions/?id={ID_TAMPERMONKEY}"

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

# Quem cota UM volume por vez, e por isso não disputa o selo de mais barato
# com mais de uma caixa. A lista mora no cadastro (web/transportadoras.py)
# desde 04/09/2026, para a tela do adm eleger o mesmo vencedor que esta.
COTAM_POR_VOLUME = transportadoras.COTAM_POR_VOLUME

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


# _kg e peso_por_volume moraram aqui até 04/09/2026, e _img junto. Foram para
# web/ficha_ui.py e web/layout.py com o resto da ficha, que agora é desenhada
# nas duas telas — a do vendedor e a do adm, que não pode importar este
# arquivo. Continuam com o mesmo nome aqui dentro, pelo import lá em cima.


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
# Atraso na senha errada, mesmo motivo do /adm: transforma "testar mil senhas"
# em "esperar mil segundos". Ver web/adm.py.
PAUSA_SENHA_ERRADA_S = 1.0


# A política da marca `Secure` mora em core/sessao.py porque os DOIS cookies
# do sistema precisam dela — o do vendedor aqui e o do painel em web/adm.py —
# e `web/adm.py` não pode importar `web/app.py` (é o contrário que acontece).
cookie_seguro = sessao.cookie_seguro


def vendedor(usuario: str | None = Cookie(None, alias=COOKIE)) -> str | None:
    """Quem está nesta sessão, ou None.

    TODA rota do vendedor passa por aqui. Antes cada uma lia o cookie crua e
    acreditava no que estava escrito: trocar `cotafrete_usuario=joao` por
    `=enzo` no inspetor do navegador era virar o Enzo. A verificação mora num
    lugar só de propósito — com dez rotas conferindo por conta própria,
    bastava uma esquecer.

    Confere a assinatura E se a conta ainda existe. Só a assinatura não
    bastaria: tirar alguém do sistema levaria até
    `sessao.DIAS_DE_SESSAO` dias para fazer efeito, que é o prazo do cookie
    que a pessoa já tem na máquina. Demitiu, perdeu o acesso agora."""
    nome = sessao.dono_do_cookie(usuario, banco.segredo_sessao())
    if nome is None or banco.conta(nome) is None:
        return None
    return nome


def _tela_login(erro: str = "", nome: str = "",
                escolher_senha: bool = False) -> str:
    """A porta da frente, nos seus dois estados: entrar, ou escolher a senha
    no primeiro acesso."""
    aviso = (f'<p class="erro" role="alert">{e(erro)}</p>' if erro else "")
    valor = e(nome)
    if escolher_senha:
        campos = f"""
    <input type="hidden" name="usuario" value="{valor}">
    <input name="senha" type="password" placeholder="Escolha sua senha"
           autofocus required autocomplete="new-password"
           style="margin-bottom:12px">
    <input name="confirmacao" type="password" placeholder="Repita a senha"
           required autocomplete="new-password" style="margin-bottom:12px">"""
        titulo = "Primeiro acesso"
        explicacao = (f"<b>{valor}</b>, escolha a senha que você vai usar "
                      f"daqui em diante. Mínimo de "
                      f"{sessao.MINIMO_DA_SENHA} caracteres. Ninguém mais "
                      f"consegue vê-la — nem o administrador.")
        botao = "Salvar senha e entrar"
    else:
        campos = f"""
    <input name="usuario" placeholder="Seu nome" required
           autocomplete="username" value="{valor}"
           style="margin-bottom:12px"{'' if valor else ' autofocus'}>
    <input name="senha" type="password" placeholder="Sua senha" required
           autocomplete="current-password"
           style="margin-bottom:12px"{' autofocus' if valor else ''}>"""
        titulo = "Entrar"
        explicacao = ("Suas cotações ficam separadas das dos outros. Se é "
                      "seu primeiro acesso, digite qualquer coisa no campo "
                      "da senha: o sistema vai pedir que você escolha a sua.")
        botao = "Entrar"

    cartao = f"""
<div class="cartao">
  <h1>{titulo}</h1>
  <p class="sub">{explicacao}</p>
  {aviso}
  <form method="post" action="/login">{campos}
    <button type="submit" style="width:100%">{botao}</button>
  </form>
</div>"""
    return entrada(
        "Entrar", cartao,
        chamada="Uma carga. Todas as transportadoras.",
        apoio="Preencha os dados da carga uma vez. O sistema cota sozinho nas "
              "automáticas e deixa a mensagem pronta para as demais.",
        paradas=("sua carga",
                 f"{len(AUTOMATICAS)} cotam sozinhas",
                 "o mais barato"),
        rodape="Sua conta é criada pelo administrador. A senha quem escolhe "
               "é você, no primeiro acesso.")


@app.get("/login", response_class=HTMLResponse)
def tela_login() -> str:
    return _tela_login()


def _abrir_sessao(nome: str) -> RedirectResponse:
    r = RedirectResponse("/", status_code=303)
    # httponly: JavaScript não lê, então um XSS não leva a sessão embora.
    # samesite=lax: site de terceiro não consegue postar cotação em nome de
    # quem está logado.
    r.set_cookie(COOKIE, sessao.assinar(nome, banco.segredo_sessao()),
                 max_age=sessao.DIAS_DE_SESSAO * 86400, httponly=True,
                 samesite="lax", secure=cookie_seguro())
    return r


def _recusar(erro: str, nome: str = "", escolher_senha: bool = False):
    resposta = HTMLResponse(_tela_login(erro, nome, escolher_senha))
    resposta.status_code = 401
    return resposta


# response_class=HTMLResponse: sem isto, um `return` de str sai daqui como
# JSON — a pessoa recebe a página inteira escapada, com \n literal na tela, em
# vez de HTML. Foi o que aconteceu com o primeiro acesso em 17/09/2026: os
# caminhos de erro passavam por _recusar(), que embrulha, e só o ramo do
# convite devolvia str crua. Declarado na ROTA, vale para todo `return` dela,
# inclusive os que vierem depois.
@app.post("/login", response_class=HTMLResponse)
def entrar(usuario: str = Form(...), senha: str = Form(""),
           confirmacao: str = Form("")):
    """Uma rota, três caminhos: conta inexistente, primeiro acesso e entrada
    normal.

    A conta NÃO é criada aqui. Quem cria é o administrador, em /adm — senão
    qualquer pessoa que achasse o endereço na internet se cadastraria
    sozinha, que é exatamente o buraco que este login veio fechar."""
    nome = usuario.strip()[:40]

    # O administrador entra por aqui também, com a senha do painel. Vem antes
    # da busca de conta porque o nome é reservado: /adm/contas recusa criar
    # conta de vendedor com ele, então não há ambiguidade.
    if adm.nome_reservado(nome):
        resposta = adm.entrada_pelo_login(senha)
        if resposta is not None:
            return resposta
        time.sleep(PAUSA_SENHA_ERRADA_S)
        # MESMO texto da senha de vendedor errada, de propósito: mensagem
        # diferente transformaria a tela num detector de nome válido.
        return _recusar("Nome ou senha não conferem.", nome)

    conta = banco.conta(nome) if nome else None

    if conta is None:
        time.sleep(PAUSA_SENHA_ERRADA_S)
        return _recusar("Nome ou senha não conferem. Se você ainda não tem "
                        "conta, peça ao administrador para criar a sua.", nome)

    if conta["senha_hash"] is None:
        # Convite aberto: a primeira visita escolhe a senha. A senha digitada
        # nesta passada é ignorada de propósito — quem chega aqui ainda não
        # tem senha, e aproveitar o que foi digitado no campo errado viraria
        # senha escolhida por engano.
        if not confirmacao:
            return _tela_login("", nome, escolher_senha=True)
        recusa = sessao.recusa_da_senha(senha)
        if recusa:
            return _recusar(recusa, nome, escolher_senha=True)
        if senha != confirmacao:
            return _recusar("As duas senhas não são iguais.", nome,
                            escolher_senha=True)
        if not banco.definir_senha(nome, sessao.hash_senha(senha)):
            # Só chega aqui se outra aba fechou o convite no meio do caminho.
            return _recusar("Essa conta já tem senha. Entre com ela.", nome)
        return _abrir_sessao(nome)

    if not sessao.senha_confere(senha, conta["senha_hash"]):
        time.sleep(PAUSA_SENHA_ERRADA_S)
        # Nunca repetir o que foi digitado: nem na tela, nem em log.
        return _recusar("Nome ou senha não conferem.", nome)

    return _abrir_sessao(nome)


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
def formulario(usuario: str | None = Depends(vendedor),
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
<div class="faixa-marca">
  {MALHA_CORREDORES}
  <span class="marca-peca marca-lockup" role="img"
        aria-label="Ventura Comércio"></span>
  <span class="diz"><b>Todos os produtos num só lugar</b>
  Uma carga, todas as transportadoras: o Cotafrete preenche os sites por
  você e devolve os preços lado a lado.</span>
</div>
{cabecalho("Nova cotação", tarja="Cotar",
           sub=f"Preencha uma vez. Cotamos sozinhos em {len(AUTOMATICAS)} "
               f"transportadoras e deixamos a mensagem pronta para as "
               f"{len(transportadoras.com_whatsapp())} que atendem por "
               f"WhatsApp.")}
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
                 usuario: str | None = Depends(vendedor)):
    """Volta ao formulario com o que o usuario ja tinha digitado."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    v = {**PADRAO, **{k[1:]: val for k, val in form.items()
                      if k.startswith("_")}}
    return HTMLResponse(_render_formulario(v, usuario, ""))


@app.post("/cotar", response_class=HTMLResponse)
def cotar(usuario: str | None = Depends(vendedor),
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
        # A Della Volpe espera o vendedor escolher, na tela da cotação, para
        # onde vai a proposta (POST /cotacao/{id}/dellavolpe). O e-mail do
        # formulário dela depende dessa escolha, então ela não pode sair antes.
        if slug == "dellavolpe":
            continue
        # O id vai amarrado na fábrica, e não como parâmetro do `_rodar`: a
        # retentativa chama `cotar_fn(req)` e não precisa saber de cotação.
        EXECUTOR.submit(_rodar, cotacao_id, slug,
                        partial(FABRICAS[slug], cotacao_id=cotacao_id), req)

    return RedirectResponse(f"/cotacao/{cotacao_id}", status_code=303)


# Toda fábrica recebe (req, cotacao_id), mesmo as que não usam o id: é a
# Della Volpe que precisa dele — vira o carimbo "(cot. N)" que devolve a
# proposta do e-mail à cotação certa — e uma assinatura só evita que o
# /cotar tenha de saber quem é quem.
def _cotar_camilo(req, cotacao_id=None):
    # confirmar_envio=True aqui só quer dizer "clique em simular": é cálculo
    # automático, não entra em fila de vendedor.
    return CamiloAdapter().cotar(req, confirmar_envio=True)


def _cotar_jadlog(req, cotacao_id=None):
    return JadlogPainelAdapter().cotar(req)


def _cotar_translovato(req, cotacao_id=None):
    # Cria registro em "Minhas Cotações" no portal deles — é
    # auto-serviço, não entra em fila de vendedor.
    return TranslovatoAdapter().cotar(req)


def _cotar_generoso(req, cotacao_id=None):
    """Cria uma cotação na conta da Ventura no portal deles — auto-serviço,
    como a Translovato, e não fila de vendedor como a Della Volpe.

    Logada, a tela final devolve preço, protocolo e prazo na hora. É por isso
    que o envio é confirmado aqui: sem confirmar não existe preço, só um
    rascunho que ninguém vê."""
    return GenerosoAdapter().cotar(req, confirmar_envio=True)


def _cotar_braspress(req, cotacao_id=None):
    """"Calcular" é cálculo automático (como o "Simular" da Camilo) — não
    entra em fila de vendedor nem cria pendência na conta da Ventura, então
    o envio é confirmado aqui: sem confirmar não existe preço na tela."""
    return BraspressAdapter().cotar(req, confirmar_envio=True)


def _cotar_dellavolpe(req, cotacao_id=None, resposta_em="tela"):
    """Envia o formulário público deles — cai na fila de um vendedor da Della
    Volpe, e o preço volta por e-mail (carriers/dellavolpe/ingestor.py).

    `resposta_em` é a escolha do vendedor na tela: "tela" põe o e-mail do
    suporte no formulário (o ingestor lê e o preço aparece sozinho); "email"
    põe o dele. Sem a caixa do suporte no .env, "tela" não tem como
    funcionar e cai no e-mail do vendedor."""
    email = dv_caixa.email_de_resposta() if resposta_em == "tela" else None
    return DellavolpeAdapter(workdir="teste_real/dellavolpe").cotar(
        req, confirmar_envio=True, cotacao_id=cotacao_id,
        email_resposta=email)


def request_da_cotacao(c: dict) -> CotacaoRequest:
    """A cotação GRAVADA de volta no modelo central, sem consultar o CEP.

    A Della Volpe sai depois do /cotar (quando o vendedor escolhe o destino
    da proposta), e aí o pedido original já não existe mais. Cidade e UF
    estão no banco desde o /cotar; consultar o CEP de novo só traria mais um
    jeito de falhar."""
    unitario = peso_por_volume(c)
    qtd = int(c["quantidade"])
    peso = unitario if unitario is not None else Decimal(c["peso_kg"]) / qtd
    return CotacaoRequest(
        solicitante=Solicitante(nome=c.get("nome_solicitante") or "Ventura",
                                email=c.get("email") or "",
                                whatsapp=c.get("whatsapp_solicitante") or ""),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf=c["uf_origem"], cidade=c["cidade_origem"],
                     cep=c["cep_origem"]),
        destino=Local(uf=c["uf_destino"], cidade=c["cidade_destino"],
                      cep=c["cep_destino"]),
        remetente=Parte(cnpj=c["cnpj_remetente"]),
        destinatario=Parte(cnpj=c["cnpj_destinatario"]),
        tipo_frete=TipoFrete(c.get("tipo_frete") or "cif"),
        volumes=[Volume(qtd=qtd, comprimento_cm=Decimal(c["comprimento_cm"]),
                        largura_cm=Decimal(c["largura_cm"]),
                        altura_cm=Decimal(c["altura_cm"]),
                        peso_kg=Decimal(peso))],
        mercadoria=Mercadoria(tipo_material=c.get("material") or ""),
        nota_fiscal=NotaFiscal(valor_total=Decimal(c["valor_nf"])),
    )


# No módulo, e não dentro de /cotar: é o que permite a
# tests/test_dellavolpe_automatica.py conferir que quem está em AUTOMATICAS
# tem como ser despachada. Entrar na lista sem fábrica só estourava dentro de
# uma thread do executor, e lá um KeyError vira cartão girando para sempre.
FABRICAS = {"camilo": _cotar_camilo, "jadlog": _cotar_jadlog,
            "translovato": _cotar_translovato, "generoso": _cotar_generoso,
            "braspress": _cotar_braspress}
# Só com ela ligada: fábrica de quem não está em AUTOMATICAS nunca roda, e
# tests/test_dellavolpe_automatica.py não deixa sobrar fábrica órfã.
if "dellavolpe" in AUTOMATICAS:
    FABRICAS["dellavolpe"] = _cotar_dellavolpe


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
            # `is not None`, e não o `if` natural: entrega no mesmo dia é
            # prazo_dias=0, que é falso em Python — e 0 é justamente o prazo
            # que mais ajuda a fechar negócio. O adapter preenchia isto desde
            # sempre e esta linha não existia: 414 resultados no banco de
            # produção (21/09/2026), nenhum com prazo, e a coluna "Prazo" da
            # tela nascia vazia em toda cotação, para todas as transportadoras.
            prazo=str(res.prazo_dias) if res.prazo_dias is not None else None,
            # Até quando o preço ainda fecha negócio. É o que decide se o
            # botão "Aceitar" aparece — sem isto a coluna nasceria morta.
            validade=res.validade,
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
# `_quem` e `pagador_da_cotacao` vêm de web/ficha_ui.py (ver o import no topo):
# são a mesma leitura de CIF/FOB que a ficha faz, e a mensagem do WhatsApp não
# pode discordar dela sobre quem paga o frete.


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


def cartao_proposta_a_caminho() -> str:
    """A Della Volpe recebeu, e a proposta vai cair na caixa do SUPORTE.

    Diferente de `cartao_resposta_por_email`: lá o preço chega no e-mail do
    vendedor e esta tela nunca muda. Aqui o ingestor lê a caixa do suporte e
    o preço aparece NESTA linha sozinho — mandar o vendedor abrir o e-mail
    dele seria mandá-lo procurar uma coisa que nunca vai chegar lá."""
    return ('<div class="enviada">Cotação enviada</div>'
            '<div class="alerta email"><b>O preço aparece aqui sozinho.</b> '
            'A Della Volpe responde por e-mail, em 2 a 5 minutos, para a '
            'caixa do suporte — o sistema lê a proposta e preenche esta '
            'linha com preço, prazo, validade e o PDF. Pode deixar a página '
            'aberta.</div>')


def _idade(iso: str | None) -> float:
    """Segundos desde um horário ISO do banco. Texto estragado conta como
    agora: melhor a tela esperar um pouco mais do que desistir à toa."""
    try:
        return (datetime.now() - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return 0


def _envio_expirou(r: dict) -> bool:
    """O "enviando" da Della Volpe passou do teto sem gravar nada — o robô
    morreu no meio. O relógio é o do clique, não o da cotação."""
    return _idade(r.get("pedido_em")) > ESPERA_MAXIMA_S


def _proposta_na_tela(r: dict) -> bool:
    """A proposta desta linha vai para a caixa do suporte (e daí para a tela)?

    Linha anterior à escolha (23/09/2026) não diz: vale o .env de hoje, que
    era a regra daquela época."""
    if r.get("resposta_em"):
        return r["resposta_em"] == "tela"
    return bool(dv_caixa.email_de_resposta())


def escolha_da_dellavolpe(cotacao_id: int, email: str | None) -> str:
    """Os dois botões da Della Volpe, na linha dela.

    Ela é a única automática que manda a cotação para a fila de uma PESSOA,
    e a resposta chega por e-mail — por isso o vendedor decide para onde. Sem
    a caixa do suporte no .env, "aqui na tela" não tem como funcionar, e o
    botão nem aparece."""
    seu = f' ({e(email)})' if email else ''
    botao_tela = (
        '<button class="botao" name="destino" value="tela">Mostrar aqui '
        '(2 a 5 min)</button> ' if dv_caixa.email_de_resposta() else '')
    return (
        f'<form method="post" action="/cotacao/{cotacao_id}/dellavolpe"'
        f' class="escolha-dv">'
        f'<div class="alerta email"><b>Para onde vai a proposta da Della '
        f'Volpe?</b> O site dela não mostra o preço na hora: responde por '
        f'e-mail, em 2 a 5 minutos, com um PDF.'
        + (' <b>Mostrar aqui</b> manda para a caixa do suporte, e o preço e '
           'o PDF aparecem nesta linha sozinhos.' if botao_tela else '')
        + f' <b>Meu e-mail</b> manda para você{seu}.</div>'
        f'<p>{botao_tela}<button class="botao2" name="destino" value="email">'
        f'Mandar para o meu e-mail</button></p></form>')


@app.post("/cotacao/{cotacao_id}/dellavolpe")
def enviar_dellavolpe(cotacao_id: int, destino: str = Form(...),
                      usuario: str | None = Depends(vendedor)):
    """O clique num dos dois botões: reserva a linha e solta o robô.

    A reserva vem ANTES do robô e é atômica (banco.reservar_envio): o segundo
    clique, o F5 que reenvia o POST, a aba duplicada — nenhum deles manda a
    mesma cotação duas vezes para a fila da Della Volpe."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c = banco.buscar_cotacao(cotacao_id, usuario)
    if c is None:
        raise HTTPException(404, "Cotação não encontrada")
    volta = RedirectResponse(f"/cotacao/{cotacao_id}", status_code=303)
    if ("dellavolpe" not in automaticas_da(c.get("transportadoras"))
            or destino not in ("tela", "email")):
        return volta
    if destino == "tela" and not dv_caixa.email_de_resposta():
        # O .env perdeu a caixa entre a tela e o clique. Mandar para o
        # suporte sem ninguém lendo seria perder a proposta.
        destino = "email"
    try:
        req = request_da_cotacao(c)
    except Exception as exc:
        banco.salvar_resultado(cotacao_id, "dellavolpe", status="erro",
                               erro=f"a cotação gravada não deu para "
                                    f"reenviar: {type(exc).__name__}: {exc}")
        return volta
    if banco.reservar_envio(cotacao_id, "dellavolpe", resposta_em=destino):
        EXECUTOR.submit(_rodar, cotacao_id, "dellavolpe",
                        partial(FABRICAS.get("dellavolpe", _cotar_dellavolpe),
                                cotacao_id=cotacao_id, resposta_em=destino),
                        req)
    return volta


@app.get("/whatsapp/{cotacao_id}/{slug}")
def abrir_whatsapp(cotacao_id: int, slug: str,
                   usuario: str | None = Depends(vendedor)):
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
                   usuario: str | None = Depends(vendedor)):
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
{cabecalho(reg.nome, tarja="E-mail pronto",
           contexto=(("rota", f"{c['cidade_origem']}/{c['uf_origem']} → "
                              f"{c['cidade_destino']}/{c['uf_destino']}"),
                     ("cotação", f"#{cotacao_id}")),
           acoes=f'<a class="botao2" href="/cotacao/{cotacao_id}">'
                 f'Voltar para a cotação</a>')}

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


def _url_formulario_dv(c: dict) -> str:
    """O link do site da Della Volpe com os dados desta cotação.

    O e-mail segue a escolha do vendedor: se ele pediu a proposta no
    PRÓPRIO e-mail, o formulário vai com o dele; senão, com a caixa do
    suporte (quando configurada), para a proposta cair no ingestor."""
    dv_r = next((r for r in c["resultados"]
                 if r["transportadora"] == "dellavolpe"), None)
    escolheu_email = dv_r is not None and dv_r.get("resposta_em") == "email"
    return dv_bookmarklet.url_formulario(
        c, None if escolheu_email else dv_caixa.email_de_resposta())


@app.get("/dellavolpe/{cotacao_id}/abrir")
def abrir_formulario_dellavolpe(cotacao_id: int,
                                usuario: str | None = Depends(vendedor)):
    """O atalho do cartão "Semiautomática" quando o script está em dia: vai
    direto para o site da Della Volpe já preenchido, sem a tela de instruções.

    Passa por aqui, e não direto para o site, para REGISTRAR a abertura —
    é o relógio que o ingestor usa para casar a proposta que chegar com esta
    cotação (banco.candidatas_dellavolpe, a porta do formulário assistido)."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c = banco.buscar_cotacao(cotacao_id, usuario)
    if c is None:
        return HTMLResponse("Não encontrado", status_code=404)
    banco.marcar_whatsapp_aberto(cotacao_id, "dellavolpe", usuario)
    return RedirectResponse(_url_formulario_dv(c), status_code=303)


@app.get("/dellavolpe/{cotacao_id}", response_class=HTMLResponse)
def formulario_dellavolpe(cotacao_id: int,
                          usuario: str | None = Depends(vendedor)):
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
    # A mesma caixa de resposta do envio automático: a proposta de um envio
    # feito à mão também precisa cair no ingestor.
    url = _url_formulario_dv(c)
    href_favorito = dv_bookmarklet.href_bookmarklet()

    # Duas versões da mesma tela, e quem escolhe é o NAVEGADOR: o script do
    # Tampermonkey marca o <html> com data-cotafrete-dv quando está
    # instalado, e aí o passo a passo da instalação some. Sem o script, a
    # tela ensina a instalar — e guarda o favorito antigo como plano B.
    return HTMLResponse(pagina(f"Cotação {cotacao_id} — Della Volpe", f"""
<style>
  body:not(.com-script) .so-com {{ display: none; }}
  body.com-script .so-sem {{ display: none; }}
  body:not(.script-velho) .so-velho {{ display: none; }}
  body.script-velho .so-em-dia {{ display: none; }}
</style>
{cabecalho("Della Volpe", tarja="Fluxo assistido",
           contexto=(("rota", f"{c['cidade_origem']}/{c['uf_origem']} → "
                              f"{c['cidade_destino']}/{c['uf_destino']}"),
                     ("cotação", f"#{cotacao_id}")),
           acoes=f'<a class="botao2" href="/cotacao/{cotacao_id}">'
                 f'Voltar para a cotação</a>')}

<div class="cartao">
  <div class="alerta email"><b>Esta é a via rápida: responde em 2 a 5
  minutos</b>, contra 10 a 12 horas do e-mail avulso. É o formulário
  OFICIAL deles — o preenchimento só poupa a digitação, quem resolve o
  captcha e clica em enviar é você.</div>

  <div class="so-com">
    <p class="sub so-em-dia">✓ O script do Cotafrete está instalado neste
    navegador (versão {dv_bookmarklet.VERSAO_USERSCRIPT}).</p>
    <div class="alerta so-velho"><b>O script deste navegador está
    desatualizado</b> (versão <span id="versao-instalada"></span>; a atual
    é a {dv_bookmarklet.VERSAO_USERSCRIPT}).
    <a class="botao2" href="{rota_script_versionada()}" target="_blank"
    rel="noopener">Atualizar o script</a> — o Tampermonkey abre uma tela;
    clique em <b>"Atualizar"</b> e depois recarregue esta página.</div>
  </div>

  <div class="so-sem">
    <div class="passo-n" data-n="1"><b>Só na primeira vez, neste
    computador:</b> instale o preenchimento automático. São três etapas
    rápidas (a, b e c) e valem para todas as cotações daqui para a frente.</div>
    <div style="margin-left:46px">
    <p><b>a) Instale a extensão Tampermonkey no Chrome.</b>
    <a class="botao2" href="{URL_TAMPERMONKEY}" target="_blank"
    rel="noopener">Abrir Tampermonkey na Chrome Web Store</a>
    — na página que abrir, clique em <b>"Usar no Chrome"</b> e confirme.</p>
    <img class="print" style="max-width:640px"
    src="/ajuda/tampermonkey_1_loja.png"
    alt="Print: página do Tampermonkey na Chrome Web Store, com uma seta no botão Usar no Chrome">

    <p><b>b) Libere os scripts do Tampermonkey.</b> Clique para copiar o
    endereço dos detalhes da extensão, cole na barra de endereço do Chrome
    e aperte Enter:</p>
    <p><code id="end-extensoes">{URL_DETALHES_TAMPERMONKEY}</code>
    <button type="button" class="botao2" id="copiar-extensoes"
    >Copiar endereço</button>
    <span class="sub" id="copiou" hidden>✓ copiado — cole na barra de
    endereço</span></p>
    <p class="sub">Por que copiar, e não um link: o Chrome não deixa nenhum
    site abrir as telas <code>chrome://</code> por clique — é uma trava de
    segurança dele. Se preferir o caminho pelo menu: digite
    <code>chrome://extensions</code> na barra de endereço e, no cartão do
    Tampermonkey, clique em <b>"Saiba mais"</b> (em alguns Chrome o botão se
    chama <b>"Detalhes"</b>):</p>
    <img class="print" style="max-width:420px"
    src="/ajuda/tampermonkey_2_cartao.png"
    alt="Print: cartão do Tampermonkey em chrome://extensions, com uma seta no botão Saiba mais">
    <p>Na tela de detalhes, ligue a chave <b>"Permitir scripts de
    usuário"</b> (a do círculo no print). Em Chrome mais antigo essa chave não
    existe: ligue o <b>"Modo do desenvolvedor"</b>, no canto de cima da tela
    <code>chrome://extensions</code>.</p>
    <img class="print" style="max-width:700px"
    src="/ajuda/tampermonkey_3_permitir.png"
    alt="Print: detalhes do Tampermonkey com a chave Permitir scripts de usuário ligada e circulada">

    <p><b>c) Instale o script do Cotafrete.</b>
    <a class="botao2" href="{rota_script_versionada()}"
    target="_blank" rel="noopener">Instalar o script do Cotafrete</a>
    — o Tampermonkey abre a tela abaixo; clique em <b>"Instalar"</b>. Depois
    volte aqui e recarregue esta página.</p>
    <img class="print"
    src="/ajuda/tampermonkey_4_instalar.png"
    alt="Print: tela de instalação do Tampermonkey para o script Cotafrete — Della Volpe, com uma seta no botão Instalar">
    </div>
  </div>

  <div class="passo-n so-com" data-n="1">Abra o formulário da Della Volpe.
  Ele já abre preenchido.</div>
  <div class="passo-n so-sem" data-n="2">Abra o formulário da Della Volpe.
  Ele abre preenchido quando o script do passo 1 estiver instalado.</div>
  <p><a class="botao2" href="{e(url)}" target="_blank" rel="noopener"
  >Abrir formulário da Della Volpe</a></p>
  <p class="sub">Os campos enchem sozinhos alguns segundos depois de a
  página abrir, e aparece um aviso do navegador confirmando — é só clicar
  OK.</p>

  <div class="passo-n so-com" data-n="2">Confira os dados preenchidos e
  resolva o captcha da Della Volpe ("confirme que é humano") — quando ele
  validar, aparece um quadradinho verde escrito <b>"Sucesso!"</b>. Só
  depois clique em "Pedir orçamento".</div>
  <div class="passo-n so-sem" data-n="3">Confira os dados preenchidos e
  resolva o captcha da Della Volpe ("confirme que é humano") — quando ele
  validar, aparece um quadradinho verde escrito <b>"Sucesso!"</b>. Só
  depois clique em "Pedir orçamento".</div>

  <img class="print" src="/ajuda/passo4_captcha_sucesso.png"
  alt="Print: captcha da Della Volpe resolvido, mostrando Sucesso em verde">

  <div class="alerta"><b>É normal o primeiro clique em "Pedir orçamento"
  parecer que não fez nada.</b> Enquanto o captcha não terminar de validar
  (o "Sucesso!" verde acima), o formulário não envia de verdade. Confira se o
  "Sucesso!" apareceu e clique em "Pedir orçamento" outra vez.</div>

  <p class="sub">Anexo de planilha ou FISPQ não entra sozinho — o navegador
  não permite preencher esse tipo de campo por segurança. Anexe à mão se a
  carga precisar.</p>

  <details class="so-sem">
    <summary>Não dá para instalar agora? Use o favorito (jeito antigo)</summary>
    <p>Arraste este link para a barra de favoritos:
    <a class="botao2" href="{href_favorito}"
    onclick="return confirm('Não clique — ARRASTE este link para a barra de favoritos.')"
    >📋 Preencher cotação (Cotafrete)</a></p>
    <img class="print" src="/ajuda/passo1_barra_favoritos.png"
    alt="Print: o favorito salvo na barra do navegador">
    <p class="sub">Depois abra o formulário (passo 2) e, <b>na aba nova da
    Della Volpe</b>, clique no favorito. Os campos enchem e aparece o aviso
    de confirmação.</p>
    <img class="print" src="/ajuda/passo3_alerta_preenchido.png"
    alt="Print: aviso do navegador dizendo que o Cotafrete preencheu os campos">
  </details>
</div>

<p class="sub" style="margin-top:24px">Prefere continuar mandando por e-mail
(mais lento)? <a href="/email/{cotacao_id}/dellavolpe">Abrir e-mail pronto</a>
</p>
<script>
// "Copiar endereço". navigator.clipboard só existe em página segura
// (https ou localhost); pelo IP da rede o servidor é http puro, e aí vale o
// jeito antigo, com um textarea escondido.
(function () {{
  var botao = document.getElementById('copiar-extensoes');
  if (!botao) return;
  botao.addEventListener('click', function () {{
    var texto = document.getElementById('end-extensoes').textContent;
    function avisar() {{
      document.getElementById('copiou').hidden = false;
    }}
    function antigo() {{
      var t = document.createElement('textarea');
      t.value = texto;
      t.style.position = 'fixed';
      t.style.opacity = '0';
      document.body.appendChild(t);
      t.select();
      try {{ document.execCommand('copy'); avisar(); }} catch (e) {{}}
      document.body.removeChild(t);
    }}
    if (navigator.clipboard && window.isSecureContext) {{
      navigator.clipboard.writeText(texto).then(avisar, antigo);
    }} else {{
      antigo();
    }}
  }});
}})();

// O script do Tampermonkey roda depois que a página carrega e marca o
// <html>. Olha por 3 segundos; sem marca, fica a versão "instale".
(function () {{
  var voltas = 15;
  (function olhar() {{
    var instalada = document.documentElement.getAttribute('data-cotafrete-dv');
    if (instalada) {{
      document.body.classList.add('com-script');
      // O script marca o <html> com a PRÓPRIA versão. Diferente da do
      // servidor, a tela oferece a atualização — sem depender de quando o
      // Tampermonkey resolver procurar versão nova sozinho.
      if (instalada !== '{dv_bookmarklet.VERSAO_USERSCRIPT}') {{
        document.body.classList.add('script-velho');
        document.getElementById('versao-instalada').textContent = instalada;
      }}
    }} else if (voltas-- > 0) {{
      setTimeout(olhar, 200);
    }}
  }})();
}})();
</script>
""", usuario))


# O .user.js do Tampermonkey. SEM login de propósito: o Tampermonkey volta
# aqui sozinho para buscar versão nova, sem o cookie do vendedor — e o
# arquivo não tem dado nenhum, só o código de preencher o formulário.
#
# Dois endereços para o mesmo arquivo. O fixo é o que vai no @updateURL — o
# Tampermonkey guarda esse e volta nele para sempre. O com a versão no nome é
# o do botão da tela: endereço novo a cada versão, e nenhum cache no caminho
# (do Chrome, do Tampermonkey, de um proxy) consegue devolver o arquivo
# velho. Foi o que aconteceu em 23/09/2026: o botão abriu a 1.0.0 com a 1.1.0
# já no servidor, e sem "Atualizar" o vendedor fica preso na versão errada.
ROTA_SCRIPT = "/extensao/cotafrete-dellavolpe.user.js"


def rota_script_versionada() -> str:
    return (f"/extensao/cotafrete-dellavolpe-"
            f"{dv_bookmarklet.VERSAO_USERSCRIPT}.user.js")


def _entregar_script(request: Request) -> Response:
    fixo = str(request.base_url).rstrip("/") + ROTA_SCRIPT
    return Response(dv_bookmarklet.userscript(fixo),
                    media_type="text/javascript; charset=utf-8",
                    headers={"Cache-Control": "no-store, max-age=0"})


@app.get(ROTA_SCRIPT)
def script_tampermonkey(request: Request):
    return _entregar_script(request)


@app.get("/extensao/cotafrete-dellavolpe-{versao}.user.js")
def script_tampermonkey_versionado(versao: str, request: Request):
    """Qualquer versão no nome entrega a ATUAL: um link velho guardado em
    algum lugar leva à versão nova, e não a um 404."""
    return _entregar_script(request)


# Rótulo e classe de cada estado. Um lugar só: a linha e a pílula têm de
# concordar, e quando cada uma decidia por conta a tela dizia "Cotou" ao lado
# de um travessão.
ESTADOS = {
    "ok": ("Cotou", "estado-ok"),
    "aguardando": ("Enviada", "estado-aguardando"),
    "recusa": ("Recusou", "estado-recusa"),
    "falha": ("Falhou", "estado-falha"),
    "intervencao": ("Precisa de alguém", "estado-falha"),
    "cotando": ("Cotando", "estado-cotando"),
    # A Della Volpe esperando o vendedor escolher para onde vai a proposta.
    # Nada saiu ainda: "Enviada" ali seria a mentira mais cara da tela.
    "escolher": ("Falta escolher", "estado-aguardando"),
}


def _linha_resultado(slug: str, principal: str, prazo: str, estado: str,
                     selo: str, destaque: str, evidencia: str | None,
                     avisos: str, nota: str = "", validade: str = "",
                     cotacao_id: int | None = None) -> str:
    """Uma transportadora, em duas linhas de tabela.

    A de cima compara: nome, frete, prazo, o que inclui, estado, print. A de
    baixo só existe quando há o que avisar, e aí atravessa a tabela inteira —
    aviso solto numa célula estreita vira duas palavras por linha.

    `nota` (a coluna "o que inclui") só vem quando houve PREÇO. Ela descreve
    o que aquele preço cobre — sem preço não descreve nada, e a da Braspress
    ainda cita o CNPJ da Ventura, que a tela não pode prometer numa linha que
    não cotou (`test_a_tela_nao_promete_mais_um_cnpj_fixo_na_generoso`).

    A MINIATURA aparece em TODA transportadora que tenha print, e não só na
    mais barata: o print é a prova de que aquele preço veio do site, e prova
    que só a vencedora tem não prova nada sobre as outras. O que o print não
    pode é afastar os preços um do outro, e era isso que 300px por cartão
    faziam — o olho comparava dois números com meia tela de distância.
    Clicar abre a lupa, que já existe desde 09/09/2026.
    """
    rotulo, classe_estado = ESTADOS.get(estado, ("—", "estado-falha"))
    if evidencia and e_pdf(evidencia) and cotacao_id is not None:
        # A Della Volpe não tem print: a prova do preço dela é o PDF da
        # proposta, lido do e-mail. Link, e não imagem embutida — PDF dentro
        # de <img> é ícone quebrado.
        mini = (f'<a class="botao2" href="/cotacao/{cotacao_id}/proposta/'
                f'{e(slug)}" target="_blank" rel="noopener">PDF</a>')
    elif evidencia and not e_pdf(evidencia):
        mini = f'<span class="mini">{_img(evidencia)}</span>'
    else:
        mini = '<span class="sem-print">—</span>'
    detalhe = (f'<tr class="r-extra"><td colspan="7">{avisos}</td></tr>'
               if avisos else "")
    # `data-t` com o slug: e o que deixa o teste (e o JavaScript, se um dia
    # precisar) achar a linha de UMA transportadora sem fatiar o HTML no
    # olho. A versao anterior destes testes cortava a string em
    # `</div></div>` e, quando o cartao virou linha de tabela, passou a
    # medir o pedaco errado da tela sem falhar por isso.
    return (
        f'<tr class="r{destaque}" data-t="{e(slug)}">'
        f'<td class="r-nome">{e(NOMES.get(slug, slug))} {selo}</td>'
        f'<td class="r-preco">{principal}</td>'
        f'<td class="r-prazo">{e(prazo)}</td>'
        f'<td class="r-nota">{e(nota)}</td>'
        # Já vem montado por quem chama: a célula da validade é a mesma que
        # abriga o botão "Aceitar", e aí ela deixa de ser só texto.
        f'<td class="r-validade">{validade}</td>'
        f'<td class="r-estado"><span class="{classe_estado}">'
        f'{e(rotulo)}</span></td>'
        f'<td class="r-print">{mini}</td>'
        f'</tr>{detalhe}')


@app.get("/cotacao/{cotacao_id}", response_class=HTMLResponse)
def ver_cotacao(cotacao_id: int,
                usuario: str | None = Depends(vendedor)):
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

    # Quais já tiveram coleta pedida. Uma consulta só, fora do laço.
    aceites = banco.aceites(cotacao_id)

    linhas = ""
    for r in c["resultados"]:
        slug = r["transportadora"]
        # `avisos` vai para a LINHA DE DETALHE, abaixo da linha da
        # transportadora. Cada frase aqui e a mesma de quando isto era cartao:
        # elas foram escritas em cima de cotacao real que deu errado, e trocar
        # o desenho da tela nao e motivo para reescrever nenhuma.
        avisos = ""
        prazo = ""
        # Até quando este preço ainda fecha negócio. Só faz sentido onde HÁ
        # preço: validade é a data de vencimento de um número, e linha sem
        # número não tem o que vencer.
        validade = ""
        if r["valor"] is not None:
            destaque = " melhor" if r["valor"] == melhor else ""
            selo = '<span class="selo">MAIS BARATO</span>' if destaque else ""
            incerto = " incerto" if cota_por_volume(slug, qtd) else ""
            principal = (f'<span class="preco{incerto}">'
                         f'{moeda(r["valor"])}</span>')
            estado = "ok"
            # O prazo estava no banco desde sempre e a tela nunca mostrou.
            # Sem ele a comparacao e so preco - e frete se decide comparando
            # preco CONTRA prazo.
            if r["prazo"]:
                prazo = f'{e(str(r["prazo"]))} dias'
            # Validade e botão "Aceitar" na MESMA célula: é a validade que
            # decide se ainda vale a pena aceitar, e separá-los faria o
            # vendedor ler "vence hoje" num canto e clicar no outro.
            validade = celula_de_aceite(slug, r["valor"], r["validade"],
                                        aceites.get(slug), cotacao_id)
            if cota_por_volume(slug, qtd):
                avisos += (
                    f'<div class="alerta"><b>Preço de 1 volume, não da '
                    f'carga.</b> São {qtd} volumes: por estimativa, '
                    f'{moeda(r["valor"] * qtd)} no total. Por isso ela não '
                    f'disputa o selo de mais barato.</div>')
            # Preço válido pode vir com uma ressalva (ex.: Camilo "Entrega
            # em área de risco", cotação #99 de 01/09/2026) — não é falha,
            # mas o vendedor precisa ler antes de fechar.
            if r["erro"]:
                avisos += (f'<div class="alerta">'
                           f'{e(r["erro"][:LIMITE_MENSAGEM_ERRO])}</div>')
            if r["protocolo"]:
                avisos += (f'<div class="nota">Cotação nº '
                           f'{e(r["protocolo"])}</div>')
        elif (r["status"] == StatusCotacao.INTERVENCAO_NECESSARIA.value
              and slug == "dellavolpe"):
            # A caixinha "confirme que é humano" apareceu (ou o site barrou o
            # envio como spam). NÃO é o caso da senha, logo abaixo: aqui nada
            # saiu, e quem resolve é o próprio vendedor, em dois cliques, pelo
            # formulário preenchido que aparece no cartão "Semiautomática".
            destaque, selo, estado = "", "", "intervencao"
            principal = '<span class="sem">Envie pelo formulário</span>'
            avisos = (f'<div class="alerta email"><b>Nada foi enviado à Della '
                      f'Volpe.</b> O site dela pediu a confirmação de humano, '
                      f'que o robô não resolve. Use o formulário já preenchido '
                      f'no cartão "Semiautomática", logo abaixo: você marca a '
                      f'caixinha e envia.</div>'
                      f'<div class="nota">'
                      f'{e((r["erro"] or "")[:LIMITE_MENSAGEM_ERRO])}</div>')
        elif r["status"] == StatusCotacao.INTERVENCAO_NECESSARIA.value:
            # Senha recusada. Diferente de um erro qualquer porque o vendedor
            # NÃO consegue resolver — e se ele repetir a cotação, cada
            # repetição é mais um login errado empurrando a conta da Ventura
            # para o bloqueio. A linha precisa dizer isso com todas as
            # letras, senão repetir é exatamente o que ele vai fazer.
            destaque, selo, estado = "", "", "intervencao"
            principal = '<span class="sem">Precisa de alguém</span>'
            avisos = (f'<div class="alerta email"><b>Repetir a cotação não '
                      f'resolve.</b> A senha desta transportadora precisa ser '
                      f'conferida no sistema. Avise quem cuida do Cotafrete e '
                      f'siga pelo WhatsApp aqui embaixo.</div>'
                      f'<div class="nota">'
                      f'{e((r["erro"] or "")[:LIMITE_MENSAGEM_ERRO])}</div>')
        elif r["status"] == StatusCotacao.AGUARDANDO_RETORNO.value:
            # Recebido, sem preço e sem falha. Precisa vir ANTES do ramo de
            # erro: lá embaixo tudo que não tem valor é tratado como problema.
            destaque, selo, estado = "", "", "aguardando"
            principal = '<span class="sem">preço por e-mail</span>'
            if slug == "dellavolpe" and _proposta_na_tela(r):
                principal = '<span class="sem">aguardando proposta</span>'
                avisos = cartao_proposta_a_caminho()
            else:
                avisos = cartao_resposta_por_email(c.get("email"), slug)
                if slug == "dellavolpe" and r["evidencia"]:
                    # Escolheu o próprio e-mail: a única prova que ESTA tela
                    # tem de que a cotação saiu é a confirmação do site.
                    # Grande, e não só a miniatura da coluna "Print".
                    avisos += (f'<div class="nota">Confirmação do site da '
                               f'Della Volpe:</div>{_img(r["evidencia"])}')
        elif r["status"] == StatusCotacao.RECUSADO.value:
            # Recusa NÃO é defeito. O site recebeu a carga inteira, entendeu,
            # e disse não — com estas palavras. Cotação #20 (25/08/2026): a
            # Camilo escreveu "Cliente não possui tabela de frete negociada"
            # e o vendedor leu "Não retornou preço", que é a frase de quando
            # ninguém sabe o que houve. Aí ele repete a cotação três vezes
            # atrás de um preço que nunca vai vir.
            destaque, selo, estado = "", "", "recusa"
            principal = '<span class="sem">O site não cotou</span>'
            avisos = (f'<div class="alerta">'
                      f'{e((r["erro"] or "")[:LIMITE_MENSAGEM_ERRO])}</div>')
        elif (slug == "dellavolpe"
              and r["status"] == StatusCotacao.ENVIANDO.value
              and not _envio_expirou(r)):
            # O vendedor escolheu e o robô está no site dela agora.
            destaque, selo, estado = "", "", "cotando"
            principal = ('<span class="cotando"><span class="girando"></span>'
                         'enviando…</span>')
            avisos = (
                '<div class="alerta email"><b>Cotando automaticamente na '
                'Della Volpe.</b> O robô está preenchendo o formulário do '
                'site dela. Depois do envio a proposta leva de 2 a 5 minutos '
                'para chegar — o preço e o PDF aparecem nesta linha sozinhos. '
                'Pode deixar a página aberta.</div>'
                if r.get("resposta_em") == "tela" else
                '<div class="alerta email"><b>Enviando para a Della '
                'Volpe.</b> O robô está preenchendo o formulário do site '
                'dela. A proposta vai para o seu e-mail, '
                f'{e(c.get("email") or "o do formulário")}, em 2 a 5 '
                'minutos.</div>')
        else:
            destaque, selo, estado = "", "", "falha"
            # Sempre dizer POR QUE não veio preço. "Não retornou preço" sozinho
            # manda o operador adivinhar — e foi status sem explicação que
            # escondeu, neste projeto, cinco envios que nunca saíram.
            motivo = r["erro"] or f"o site respondeu: {r['status']}"
            # A frase entra ANTES do texto técnico, nunca no lugar dele: o
            # vendedor lê a primeira linha e resolve; quem for investigar
            # continua tendo o original logo abaixo.
            frase = mensagem_amigavel(slug, r["erro"])
            principal = '<span class="sem">Não retornou preço</span>'
            avisos = ((f'<div class="alerta">{e(frase)}</div>' if frase else '')
                      + f'<div class="nota">'
                        f'{e(motivo[:LIMITE_MENSAGEM_ERRO])}</div>')
        linhas += _linha_resultado(slug, principal, prazo, estado, selo,
                                   destaque, r["evidencia"], avisos,
                                   NOTAS.get(slug, "")
                                   if r["valor"] is not None else "",
                                   validade, cotacao_id)

    # Quem ainda não respondeu ganha um cartão "cotando". Sem isso a
    # transportadora simplesmente não aparece, e o usuário não sabe se ela
    # falhou ou se ainda está rodando.
    respondidas = {r["transportadora"] for r in c["resultados"]}
    escolhidas = c.get("transportadoras")
    # A Della Volpe sem linha não está "faltando": está esperando o vendedor
    # escolher para onde vai a proposta. Contá-la aqui faria a tela recarregar
    # de 3 em 3 segundos e, passado o teto, dizer "Sem retorno" de uma
    # transportadora que ninguém mandou cotar.
    faltam = [s for s in automaticas_da(escolhidas)
              if s not in respondidas and s != "dellavolpe"]
    if "dellavolpe" in automaticas_da(escolhidas) \
            and "dellavolpe" not in respondidas:
        linhas += _linha_resultado(
            "dellavolpe", '<span class="sem">escolha onde receber</span>',
            "", "escolher", "", "", None,
            escolha_da_dellavolpe(cotacao_id, c.get("email")))

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
        if desistiu:
            estado = "falha"
            principal = '<span class="sem">Sem retorno</span>'
        else:
            estado = "cotando"
            principal = (f'<span class="cotando"><span class="girando">'
                         f'</span>{e(andamento)}</span>')
        linhas += _linha_resultado(slug, principal, "", estado, "", "",
                                   None, "")

    # Recarrega sozinho de 3 em 3 segundos ENQUANTO faltar transportadora.
    # Quando todas responderem, para — recarregar uma página pronta faria a
    # imagem piscar e atrapalharia quem está lendo o resultado. Depois do teto
    # também para: sem isso a página pisca para sempre se um resultado nunca
    # chegar.
    # A Della Volpe já respondeu "recebido", mas o preço ainda vem pelo
    # e-mail. Enquanto o ingestor estiver lendo a caixa, a tela continua se
    # atualizando — devagar, porque o e-mail leva minutos e não segundos — por
    # meia hora no máximo. Passado isso, quem quiser vê recarregando à mão.
    dv_r = next((r for r in c["resultados"]
                 if r["transportadora"] == "dellavolpe"), None)
    esperando_proposta = (
        dv_r is not None and dv_r["valor"] is None
        and dv_r["status"] == StatusCotacao.AGUARDANDO_RETORNO.value
        and _proposta_na_tela(dv_r) and INGESTOR is not None
        and _idade(dv_r.get("pedido_em") or c["criado_em"])
        < ESPERA_PELA_PROPOSTA_S)
    dv_enviando = (dv_r is not None
                   and dv_r["status"] == StatusCotacao.ENVIANDO.value
                   and not _envio_expirou(dv_r))
    if (faltam and not desistiu) or dv_enviando:
        recarrega = '<meta http-equiv="refresh" content="3">'
    elif esperando_proposta:
        recarrega = '<meta http-equiv="refresh" content="20">'
    else:
        recarrega = ""
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

    # Com ela automática, o cartão só aparece quando o robô NÃO enviou:
    # captcha na tela, site recusando, erro. Enquanto ela cota, e depois que
    # a proposta foi aceita ou já tem preço, ele some — oferecer o formulário
    # ali é convidar o vendedor a mandar a MESMA cotação duas vezes para a
    # fila de uma pessoa de verdade.
    dv_automatica = "dellavolpe" in automaticas_da(escolhidas)
    dv_resolvida = dv_r is not None and (
        dv_r["valor"] is not None
        or dv_r["status"] == StatusCotacao.AGUARDANDO_RETORNO.value
        or dv_enviando)
    # Vale também para a assistida cuja proposta já chegou (o vendedor
    # enviou à mão e o ingestor leu): não há o que enviar de novo. Já a
    # automática que passou do teto sem responder nada ("Sem retorno") volta
    # a oferecer o formulário — ali ninguém sabe se saiu, e esperar mais não
    # resolve.
    if dv_resolvida or (dv_automatica and dv_r is None and not desistiu):
        dv = None
    # "Erro" é o único estado em que o envio pode ter saído mesmo assim: a
    # confirmação do site às vezes não é lida. Sem esta ressalva, o
    # vendedor reenviaria às cegas.
    ressalva = ""
    if dv_automatica and dv_r is not None and (
            dv_r["status"] != StatusCotacao.INTERVENCAO_NECESSARIA.value):
        ressalva = (' <b>O envio automático falhou</b> — se a Della Volpe '
                    'responder mesmo assim, o preço aparece na tabela acima '
                    'e você não precisa enviar de novo.')

    semiautomatica = ""
    if dv:
        semiautomatica = (
            f'<div class="cartao">'
            f'<h2 style="font-size:15px;margin:0 0 4px">Semiautomática</h2>'
            f'<p class="sub">O formulário oficial da Della Volpe já vem '
            f'preenchido — falta só você conferir, resolver o captcha e '
            f'clicar em enviar. Responde em 2 a 5 minutos, contra 10 a 12 '
            f'horas do e-mail avulso.{ressalva}</p>'
            f'<a class="zap zap-dv{" aberta" if dv.slug in abertas else ""}"'
            f' id="zap-{e(dv.slug)}" href="/dellavolpe/{cotacao_id}"'
            # O destino final quem decide é o script do Tampermonkey (ver o
            # <script> no fim da página): em dia, vai direto ao site
            # preenchido; velho ou ausente, fica na tela de instruções.
            f' data-direto="/dellavolpe/{cotacao_id}/abrir"'
            f' data-versao="{e(dv_bookmarklet.VERSAO_USERSCRIPT)}"'
            f' target="_blank" rel="noopener">'
            f'<img class="marca" src="/logos/{e(dv.logo)}" alt="" loading="lazy">'
            f'<b>{e(dv.nome)}</b>'
            f'<span class="ir">Preencher formulário (rápido)</span>'
            f'<span class="jafoi">Aberta</span></a></div>')

    # Só depois que todas responderam (ou desistiram): baixar no meio da
    # espera daria um zip incompleto, com metade das transportadoras ainda
    # sem print nenhum.
    baixar_prints = (
        f'<a class="botao2"'
        f' href="/cotacao/{cotacao_id}/evidencias.zip">Baixar prints</a>'
        if linhas and not faltam else "")

    # A mesma frase corrida de seis campos que ficava embaixo do título, agora
    # em pastilhas: rótulo em versalete, valor na monoespaçada. Nenhum campo
    # saiu nem entrou — só pararam de disputar a mesma linha de texto.
    ficha_curta = (
        ("rota", f"{c['cidade_origem']}/{c['uf_origem']} → "
                 f"{c['cidade_destino']}/{c['uf_destino']}"),
        ("volumes", str(c["quantidade"])),
        ("peso", f"{_kg(c['peso_kg'])} kg"),
        ("caixa", f"{c['comprimento_cm']}×{c['largura_cm']}"
                  f"×{c['altura_cm']} cm"),
        ("nota fiscal", moeda(c["valor_nf"])),
        ("material", str(c["material"] or "—")),
    )

    return HTMLResponse(pagina(f"Cotação {cotacao_id}", f"""
{recarrega}
{cabecalho_espera}
{cabecalho(f"Cotação #{cotacao_id}", tarja="Resultado",
           contexto=ficha_curta,
           acoes=f'<a class="botao2" href="/?repetir={cotacao_id}">'
                 f'Repetir esta cotação</a>{baixar_prints}')}

<div class="cartao">
  <div class="r-cab">
    <h2>Cotadas automaticamente</h2>
  </div>
  <div class="rolagem-r">
    <table class="resultados">
      <thead><tr>
        <th class="r-nome">Transportadora</th>
        <th class="r-preco">Frete</th>
        <th class="r-prazo">Prazo</th>
        <th class="r-nota">O que inclui</th>
        <th class="r-validade">Validade</th>
        <th class="r-estado">Estado</th>
        <th class="r-print">Print</th>
      </tr></thead>
      <tbody>{linhas or '<tr><td colspan="7" class="sub">Nenhum resultado.</td></tr>'}</tbody>
    </table>
  </div>
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

<p class="sub" style="margin-top:24px"><a href="/">← nova cotação</a>
&nbsp;·&nbsp; <a href="/historico">histórico</a></p>
<script>
// O botao da Della Volpe e o script do Tampermonkey. O script marca o <html>
// com a PROPRIA versao (tambem nesta tela, desde a 1.2.0):
//   - em dia: o botao vai direto ao site dela ja preenchido;
//   - velho: vai para /dellavolpe/N, que explica como atualizar;
//   - ausente (ou a 1.1.0, que nao roda aqui): idem, que ensina a instalar.
// O padrao do HTML ja e o caminho seguro; isto so encurta quando da.
(function () {{
  var dv = document.getElementById('zap-dellavolpe');
  if (!dv || !dv.dataset.direto) return;
  var voltas = 15;
  (function olhar() {{
    var instalada = document.documentElement.getAttribute('data-cotafrete-dv');
    if (!instalada) {{
      if (voltas-- > 0) setTimeout(olhar, 200);
      return;
    }}
    var rotulo = dv.querySelector('.ir');
    if (instalada === dv.dataset.versao) {{
      dv.href = dv.dataset.direto;
      dv.dataset.modo = 'direto';
      rotulo.textContent = 'Abrir formulário já preenchido';
    }} else {{
      dv.dataset.modo = 'atualizar';
      rotulo.textContent = 'Atualizar o script e preencher';
    }}
  }})();
}})();

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
</script>
""", usuario))


# ------------------------------------------------------- aceitar a cotação
def _agendar(cotacao_id: int, slug: str, protocolo: str, ag,
             usuario: str) -> None:
    """Pede a coleta no portal e guarda o que aconteceu. Roda em thread.

    Mesmo desenho do `_rodar` das cotações, e pelo mesmo motivo: o portal leva
    uns 40 segundos, e segurar a resposta HTTP tudo isso faria o vendedor
    achar que travou e apertar de novo. A vaga do aceite já está reservada no
    banco antes daqui — o segundo clique não chega a este ponto.

    O try é obrigatório: exceção em thread do executor some em silêncio, e o
    aceite ficaria "agendando…" para sempre."""
    try:
        res = GenerosoAdapter().agendar_coleta(protocolo, ag, confirmar=True)
        banco.concluir_aceite(
            cotacao_id, slug,
            status="agendado" if res.ok else "erro",
            protocolo=res.protocolo, erro=res.erro,
            evidencia=res.evidencias[-1] if res.evidencias else None)
    except Exception as exc:
        banco.concluir_aceite(cotacao_id, slug, status="erro",
                              erro=f"{type(exc).__name__}: {exc}")


def _cotacao_para_aceitar(cotacao_id: int, slug: str, usuario: str):
    """A cotação e a linha da transportadora, ou um 404.

    O `usuario` entra na busca de propósito, como em `ver_cotacao`: sem isso,
    trocar o número na URL pediria coleta na cotação de outro vendedor."""
    if slug not in COM_ACEITE:
        raise HTTPException(404, f"{slug} não aceita cotação pelo site.")
    c = banco.buscar_cotacao(cotacao_id, usuario)
    if c is None:
        raise HTTPException(404, "Cotação não encontrada")
    r = next((x for x in c["resultados"] if x["transportadora"] == slug), None)
    if r is None or r["valor"] is None:
        raise HTTPException(404, f"A {NOMES.get(slug, slug)} não cotou esta "
                                 f"carga — não há o que aceitar.")
    return c, r


@app.get("/aceitar/{cotacao_id}/{slug}", response_class=HTMLResponse)
def tela_de_aceite(cotacao_id: int, slug: str,
                   usuario: str | None = Depends(vendedor)):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c, r = _cotacao_para_aceitar(cotacao_id, slug, usuario)
    return HTMLResponse(pagina(
        f"Aceitar cotação {cotacao_id}",
        tela_aceite(c, r, NOMES.get(slug, slug)), usuario))


@app.post("/aceitar/{cotacao_id}/{slug}", response_class=HTMLResponse)
def confirmar_aceite(cotacao_id: int, slug: str,
                     usuario: str | None = Depends(vendedor),
                     data_coleta: str = Form(...),
                     hora_limite: str = Form(...),
                     # Checkbox desmarcada não é enviada — mas os dois selects
                     # SÃO, porque existem no HTML de qualquer jeito. Sem esta
                     # distinção todo agendamento sairia com um almoço que
                     # ninguém pediu, e o coletador programaria a rota por isso.
                     fecha_almoco: str = Form(default=""),
                     almoco_inicio: str = Form(default=""),
                     almoco_fim: str = Form(default=""),
                     observacao: str = Form(default="")):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c, r = _cotacao_para_aceitar(cotacao_id, slug, usuario)

    enviado = {"data_coleta": data_coleta, "hora_limite": hora_limite,
               "almoco_inicio": almoco_inicio if fecha_almoco else None,
               "almoco_fim": almoco_fim if fecha_almoco else None,
               "observacao": observacao}

    def recusar(erros: list[str]):
        return HTMLResponse(pagina(
            f"Aceitar cotação {cotacao_id}",
            tela_aceite(c, r, NOMES.get(slug, slug), erros=erros,
                        enviado=enviado), usuario))

    # Esconder o botão não basta: a URL continua existindo, e uma aba aberta
    # desde ontem ainda a tem. A validade é conferida DE NOVO aqui.
    if vencida(r["validade"]):
        return recusar([
            f"Esta cotação {rotulo_validade(r['validade'])} e não pode mais "
            f"ser aceita. Faça uma cotação nova para ter um preço válido."])

    try:
        dia = date.fromisoformat(data_coleta)
    except (TypeError, ValueError):
        return recusar([f"Não entendi a data {data_coleta!r}."])

    ag = Agendamento(data=dia, hora_limite=hora_limite,
                     almoco_inicio=enviado["almoco_inicio"],
                     almoco_fim=enviado["almoco_fim"],
                     observacao=observacao.strip())
    erros = validar_agendamento(ag)
    if erros:
        return recusar(erros)

    # A RESERVA vem antes do navegador, e é ela que trava o clique duplo: o
    # segundo pedido perde a corrida aqui e nunca chega ao portal.
    if not banco.registrar_aceite(
            cotacao_id, slug, usuario, data_coleta=dia.isoformat(),
            hora_limite=ag.hora_limite, almoco_inicio=ag.almoco_inicio,
            almoco_fim=ag.almoco_fim, observacao=ag.observacao):
        return RedirectResponse(f"/cotacao/{cotacao_id}", status_code=303)

    EXECUTOR.submit(_agendar, cotacao_id, slug, r["protocolo"], ag, usuario)
    return RedirectResponse(f"/cotacao/{cotacao_id}", status_code=303)


@app.get("/cotacao/{cotacao_id}/evidencias.zip")
def baixar_evidencias_zip(cotacao_id: int,
                          usuario: str | None = Depends(vendedor)):
    """Todos os prints desta cotação num .zip só — mesma ideia do painel adm
    (core.evidencias.montar_zip_de_prints), só que aqui filtrado pelo dono:
    `banco.buscar_cotacao` é a mesma checagem que a tela usa para não abrir
    a cotação de outro vendedor."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c = banco.buscar_cotacao(cotacao_id, usuario)
    if c is None:
        raise HTTPException(404, "Cotação não encontrada")

    return Response(
        montar_zip_de_prints(c["resultados"]), media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="cotacao-{cotacao_id}-prints.zip"'})


@app.get("/cotacao/{cotacao_id}/proposta/{slug}")
def baixar_proposta(cotacao_id: int, slug: str,
                    usuario: str | None = Depends(vendedor)):
    """O PDF da proposta (Della Volpe), aberto no navegador.

    Pela mesma porta da tela — `buscar_cotacao` com o usuário — e nunca por
    pasta estática: teste_real/ tem as propostas de todo mundo. O caminho do
    arquivo vem do BANCO, e não da URL, então não há como pedir outro."""
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    c = banco.buscar_cotacao(cotacao_id, usuario)
    if c is None:
        raise HTTPException(404, "Cotação não encontrada")
    r = next((r for r in c["resultados"] if r["transportadora"] == slug),
             None)
    if r is None or not e_pdf(r["evidencia"]) or not Path(
            r["evidencia"]).exists():
        raise HTTPException(404, "Proposta não encontrada")
    return Response(
        Path(r["evidencia"]).read_bytes(), media_type="application/pdf",
        headers={"Content-Disposition":
                 f'inline; filename="cotacao-{cotacao_id}-{slug}.pdf"'})


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
    # A seção da Della Volpe depende de como ELA está neste servidor: com a
    # chave do .env ligada ela cota sozinha, e a explicação de "agora quem
    # envia é você" mandaria o vendedor enviar uma cotação que já saiu.
    if "dellavolpe" in AUTOMATICAS:
        secao_dellavolpe = f"""<h2>A {e(NOMES["dellavolpe"])} voltou a cotar sozinha</h2>
<div class="alerta email">
<p>Ela entra na tabela de cima como as outras. O site dela não mostra preço
na hora: responde por e-mail, em <b>poucos minutos</b>, com uma proposta em
PDF. O sistema lê esse PDF e o preço <b>aparece na linha dela</b>, com prazo,
validade e o link do PDF.</p>
<p><b>Se a linha disser "Envie pelo formulário"</b>, o site dela pediu a
caixinha "confirme que é humano" e nada foi enviado. Aí vale o cartão
<b>Semiautomática</b>, logo abaixo: o formulário oficial já vem preenchido, e
você só confere, marca a caixinha e envia.</p>
</div>
"""
    else:
        secao_dellavolpe = f"""<h2>A {e(NOMES["dellavolpe"])} mudou: agora quem envia é você</h2>
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
"""
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
{cabecalho("Como usar o Cotafrete", tarja="Documentação",
           sub=f"Você preenche a carga uma vez. O sistema cota sozinho em "
               f"{len(AUTOMATICAS)} transportadoras e deixa a mensagem do "
               f"WhatsApp pronta para {zap}. São {len(TODAS_AS_SLUGS)} no "
               f"total.{repetida}",
           acoes='<a class="botao2" href="/">Nova cotação</a>')}

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

{secao_dellavolpe}

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
def documentacao(usuario: str | None = Depends(vendedor)):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(pagina("Documentação", pagina_documentacao(), usuario))


@app.get("/historico", response_class=HTMLResponse)
def historico(usuario: str | None = Depends(vendedor)):
    if not usuario:
        return RedirectResponse("/login", status_code=303)
    linhas = ""
    for c in banco.listar_cotacoes(usuario):
        # Sem preço nenhum: o travessão perde o verde lá no CSS. Verde é
        # "veio preço", e uma coluna inteira verde esconde justamente a
        # cotação em que ninguém respondeu.
        sem = "" if c["melhor_preco"] is not None else " vazio"
        # A linha inteira leva (o JavaScript no fim da página), mas o número é
        # um <a> DE VERDADE: é ele que responde ao teclado, ao botão do meio e
        # ao "abrir em nova aba". O `onclick` sozinho tirava a tela inteira de
        # quem trabalha sem mouse — o painel do adm já resolvia assim, e o
        # histórico do vendedor tinha ficado para trás.
        linhas += (
            f"""<tr data-abrir="/cotacao/{c['id']}">
            <td class="id-l"><a href="/cotacao/{c['id']}">#{c['id']}</a></td>
            <td class="hora">{e(quando_humano(c['criado_em']))}</td>
            <td><b>{e(c['material'])}</b></td>
            <td>{e(c['cidade_origem'])}/{e(c['uf_origem'])} →
                {e(c['cidade_destino'])}/{e(c['uf_destino'])}</td>
            <td>{e(c['peso_kg'])} kg</td>
            <td class="melhor{sem}">{moeda(c['melhor_preco'])}</td></tr>""")

    return HTMLResponse(pagina("Histórico", f"""
{cabecalho("Histórico", tarja="Suas cotações",
           sub="Clique numa linha para ver o preço de cada transportadora.",
           acoes='<a class="botao2" href="/">Nova cotação</a>')}
<div class="cartao"><div class="rolagem-r"><table>
<thead><tr><th>#</th><th>quando</th><th>material</th><th>rota</th><th>peso</th>
<th style="text-align:right">melhor preço</th></tr></thead>
<tbody>
{linhas or '<tr><td colspan="6" class="sub">Nenhuma cotação ainda.</td></tr>'}
</tbody></table></div></div>
<script>
// A linha inteira leva para a cotação. O <a> do número continua sendo quem
// atende o teclado; isto aqui só amplia o alvo do mouse para a linha toda.
// `closest("a")` porque clicar no próprio link já navega — sem isso o clique
// contaria duas vezes e o "abrir em nova aba" perderia o Ctrl.
document.querySelectorAll("tr[data-abrir]").forEach(tr =>
  tr.addEventListener("click", ev => {{
    if (ev.target.closest("a")) return;
    location = tr.dataset.abrir;
  }}));
</script>""", usuario))
