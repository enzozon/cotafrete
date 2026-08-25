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
import html
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

from carriers.camilo.adapter import CamiloAdapter
from carriers.generoso.adapter import GenerosoAdapter
from carriers.jadlog.painel import JadlogPainelAdapter
from carriers.translovato.adapter import TranslovatoAdapter
from core import cep as buscador_cep
from core import cnpj as buscador_cnpj
from core import selecao
from core.banco import Banco
from core.retentativa import (
    ESPERA_MAXIMA_S, TENTATIVAS_MAXIMAS, cotar_com_retentativa,
)
from web import transportadoras
from core.models import (
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, StatusCotacao, TipoFrete, Volume, limpa_doc,
)

app = FastAPI(title="Cotafrete — Ventura")
banco = Banco()

# Sobrevive à requisição de propósito: o /cotar dispara as transportadoras e
# devolve a tela na hora; cada uma grava o próprio resultado quando termina.
# Sem isso o usuário encara 2 minutos de tela branca para ver a Jadlog, que
# responde em 15 segundos.
EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cotacao")

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
LOGO = (Path(__file__).parent / "logo_b64.txt").read_text(encoding="utf-8").strip()

# Só atendem por WhatsApp. O resultado delas NUNCA é automático: o máximo que
# o sistema sabe é que a mensagem foi aberta para envio.
#
# O cadastro (nome, número, logo) mora em web/transportadoras.py: acrescentar
# uma é UMA linha lá, e nada aqui. Quem ainda não tem número não entra na
# lista — ver a explicação no topo daquele arquivo.
app.mount("/logos", StaticFiles(directory=transportadoras.PASTA_LOGOS),
          name="logos")

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
AUTOMATICAS = ("camilo", "jadlog", "translovato", "generoso")

# As 17 DISTINTAS. A Translovato conta uma vez so: ela e automatica E tem
# WhatsApp. dict.fromkeys em vez de set para a ordem nao mudar a cada
# reinicio do servidor — tela que troca de ordem sozinha confunde quem usa.
TODAS_AS_SLUGS = tuple(dict.fromkeys(
    [*AUTOMATICAS, *(r.slug for r in transportadoras.com_whatsapp())]))


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
}

NOMES = {"camilo": "Camilo dos Santos", "jadlog": "Jadlog Entregas",
         "translovato": "Translovato", "generoso": "Transporte Generoso"}
NOTAS = {
    "camilo": "Frete fracionado, com coleta. Preço já com taxas e ICMS.",
    "jadlog": "Etiqueta pré-paga, cotada por volume. Você leva ao balcão.",
    "translovato": "Frete fracionado, com coleta. Só atende parte do país — fora da malha ela avisa.",
    "generoso": ("Frete fracionado, com coleta. Cotada com a empresa do "
                 "grupo que você informou no formulário."),
}

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

CSS = """
:root{--tinta:#16181d;--fraco:#6b7280;--borda:#e2e5ea;--fundo:#f5f6f8;
--papel:#fff;--marca:#3b4a9c;--ok:#00875a;--erro:#bf2600;--zap:#25d366}
*{box-sizing:border-box}
body{margin:0;background:var(--fundo);color:var(--tinta);line-height:1.45;
font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--marca)}
.topo{background:var(--papel);border-bottom:1px solid var(--borda);
padding:12px 24px;display:flex;align-items:center;gap:16px}
.topo img{height:38px}
.topo .quem{margin-left:auto;font-size:13px;color:var(--fraco)}
.wrap{max-width:1080px;margin:24px auto;padding:0 24px}
.cartao{background:var(--papel);border:1px solid var(--borda);
border-radius:10px;padding:18px;margin-bottom:16px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--fraco);font-size:13px;margin:0 0 18px}
fieldset{border:1px solid #eceef1;border-radius:8px;margin:0 0 14px;
padding:12px 14px}
legend{font-size:11px;font-weight:700;color:var(--fraco);padding:0 6px;
text-transform:uppercase;letter-spacing:.6px}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
label{display:block;font-size:11px;color:var(--fraco);margin-bottom:3px}
input{width:100%;padding:8px 10px;border:1px solid var(--borda);
border-radius:6px;font-size:14px;font-family:inherit}
button{font:inherit;cursor:pointer;border:0;border-radius:6px;
background:var(--marca);color:#fff;padding:12px 22px;font-weight:600;
font-size:15px}
button:hover{filter:brightness(1.12)}
.resultados{display:grid;gap:12px;
grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.res{border:1px solid var(--borda);border-radius:10px;padding:16px;
background:var(--papel)}
.res.melhor{border-color:var(--ok);box-shadow:0 0 0 1px var(--ok)}
.res .nome{font-weight:700;font-size:14px}
.res .valor{font-size:28px;font-weight:700;color:var(--ok);margin:6px 0 2px}
/* Preço que não é da carga toda não pode usar o verde de "bom preço": o olho
   compara os números grandes antes de ler qualquer aviso, e era exatamente
   assim que R$ 33,29 por volume parecia mais barato que R$ 69,91 pela carga. */
.res .valor.incerto{color:var(--fraco)}
.res .nota{font-size:12px;color:var(--fraco)}
.falhou{color:var(--erro);font-size:13px;font-weight:600}
/* "Enviada" NAO pode usar o vermelho de falha nem o verde de preco: nao deu
   errado e nao ha numero para comparar. Fica na cor da marca, no tamanho que
   ocupa o lugar do preco - o olho passa pelos cartoes procurando o numero
   grande, e precisa parar aqui em vez de saltar. */
.enviada{color:var(--marca);font-size:19px;font-weight:700;margin:6px 0 2px}
.selo{display:inline-block;font-size:10px;font-weight:700;color:#fff;
background:var(--ok);border-radius:99px;padding:2px 8px;letter-spacing:.4px}
.zap{display:flex;align-items:center;gap:10px;border:1px solid var(--borda);
border-radius:8px;padding:10px 12px;text-decoration:none;color:inherit;
margin-bottom:8px;background:var(--papel)}
.zap:hover{border-color:var(--zap)}
/* Já aberta: fica apagada para o olho cair na próxima da lista sozinho, sem
   precisar de seta nem de "next". O visto verde diz que passou por ali. */
.zap.aberta{background:#f7f8f9;border-color:#d6ecdc}
.zap.aberta b{color:var(--fraco);font-weight:600}
.zap.aberta .marca{opacity:.5}
.zap.aberta .ir{display:none}
.zap .jafoi{display:none}
.zap.aberta .jafoi{display:inline-block;margin-left:auto;color:var(--ok);
font-size:13px;font-weight:600}
/* Visto literal, nao escape CSS: o bloco do CSS e uma string normal do
   Python, e "¹3" ali vira escape OCTAL antes de chegar no navegador --
   saia "¹3" na tela em vez do visto. */
.zap.aberta .jafoi::before{content:"✓  "}
.contador{float:right;font-size:12px;font-weight:400;color:var(--fraco)}
/* Altura fixa e contain: as logos vêm em tamanhos e proporções diferentes,
   e sem isto a CGB (359KB, quadrada) empurra a linha inteira para baixo. */
.zap .marca{width:44px;height:44px;object-fit:contain;flex:0 0 auto;
  border-radius:6px;background:#fff}
.zap .ir{margin-left:auto;background:var(--zap);color:#fff;border-radius:6px;
padding:7px 12px;font-size:13px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:11px;color:var(--fraco);text-transform:uppercase;
letter-spacing:.5px;padding:6px 8px;border-bottom:1px solid var(--borda)}
td{padding:8px;border-bottom:1px solid #f0f1f4}
tr:hover td{background:#fafbfc}
.listaerro{margin:0 0 16px;padding-left:20px;font-size:14px}
.listaerro li{margin-bottom:6px}
.cotando{display:flex;align-items:center;gap:10px;color:var(--fraco);
font-size:13px}
.girando{width:16px;height:16px;border:2px solid var(--borda);
border-top-color:var(--marca);border-radius:50%;
animation:gira .8s linear infinite}
@keyframes gira{to{transform:rotate(360deg)}}
.aviso{background:#fffae6;border:1px solid #ffe380;border-radius:6px;
padding:10px 12px;font-size:13px;margin-bottom:14px}
.print{width:100%;margin-top:10px;border:1px solid var(--borda);
border-radius:6px;cursor:zoom-in}
.print.zoom{position:fixed;inset:16px;width:auto;height:auto;z-index:9;
object-fit:contain;background:#fff;box-shadow:0 8px 40px rgba(0,0,0,.4);
cursor:zoom-out}
.botao2{display:inline-block;background:#fff;color:var(--marca);
border:1px solid var(--marca);border-radius:6px;padding:9px 16px;
font-size:14px;font-weight:600;text-decoration:none}
.login{max-width:380px;margin:70px auto;text-align:center}
.login img{height:64px;margin-bottom:18px}
.menu a{margin-right:14px;font-size:13px;text-decoration:none}
/* Aviso DENTRO do cartão, colado no preço que ele qualifica. Numa faixa no
   topo da página ele seria lido antes do número e esquecido depois. */
.alerta{background:#fffae6;border:1px solid #ffe380;border-radius:6px;
padding:8px 10px;font-size:12px;margin:6px 0 2px;line-height:1.35}
/* Amarelo e para "cuidado, esse numero engana". Aqui nao ha erro nenhum: e
   instrucao de onde olhar. Azul separa os dois recados. */
.alerta.email{background:#eef2ff;border-color:#c7d2fe}
/* ---- filtro de transportadoras ---- */
.filtro{border:1px solid var(--borda);border-radius:8px;margin:0 0 14px;
background:var(--papel)}
.filtro>summary{cursor:pointer;padding:11px 14px;display:flex;
align-items:center;gap:10px;font-size:13px;color:var(--fraco);
list-style:none}
.filtro>summary::-webkit-details-marker{display:none}
.filtro>summary .abrir{margin-left:auto;color:var(--marca);font-weight:600}
.filtro>summary .abrir::after{content:" ▾"}
.filtro[open]>summary .abrir::after{content:" ▴"}
/* o aviso fica LOGO acima do botao Cotar: e a rede que impede o filtro de
   virar erro silencioso semanas depois */
.filtro.parcial{border-color:#ffe380;background:#fffae6}
.filtro.parcial>summary{color:#7a5b00;font-weight:600}
.grupo{border-top:1px solid var(--borda);padding:12px 14px}
.grupo-cab{display:flex;align-items:baseline;gap:8px;margin-bottom:9px;
font-size:11px;text-transform:uppercase;letter-spacing:.6px;
color:var(--fraco)}
.grupo-cab span{text-transform:none;letter-spacing:0}
.grupo-cab .atalhos{margin-left:auto;white-space:nowrap}
.caixas{display:grid;gap:6px;
grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
.tr{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--tinta);
margin:0;padding:5px 7px;border-radius:6px;cursor:pointer}
.tr:hover{background:var(--fundo)}
.tr input{width:auto;margin:0;flex:none}
.tr img,.tr .sem-logo{width:26px;height:26px;object-fit:contain;flex:none}
.tr-nome{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* desmarcada fica apagada: o estado precisa ser visivel de longe, que era
   exatamente o que faltava na grade de logos do primeiro desenho */
.tr:has(input:not(:checked)){opacity:.4}
.tr:has(input:not(:checked)) .tr-nome{text-decoration:line-through}
.selo-zap{font-size:10px;background:#e7f8ef;color:var(--ok);
border-radius:10px;padding:1px 7px;font-weight:700;flex:none}
.alerta .caixa{font-size:14px;word-break:break-all}
/* Tipo de frete: as duas opcoes lado a lado, sempre visiveis. Escondida
   atras de um clique, a diferenca entre cobrar de quem envia e de quem
   recebe passa despercebida - e e ela que decide quem paga a conta. */
.opcoes{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:4px}
.opcao{display:flex;align-items:center;gap:8px;border:1px solid var(--borda);
border-radius:8px;padding:10px 12px;cursor:pointer;background:var(--papel)}
.opcao:has(input:checked){border-color:var(--marca);
box-shadow:0 0 0 1px var(--marca)}
.opcao input{width:auto;margin:0}
.opcao b{font-size:14px}
.opcao span{font-size:11px;color:var(--fraco)}
.ficha .val{font-size:14px;font-weight:600;word-break:break-word}
.ficha .pouco{display:block;font-size:11px;font-weight:400;color:var(--fraco)}
"""


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


def e(v) -> str:
    """Escapa para HTML. O material vem do usuário e vai para a tela."""
    return html.escape(str(v if v is not None else ""))


def moeda(v: Decimal | None) -> str:
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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


def pagina(titulo: str, corpo: str, usuario: str | None = None) -> str:
    quem = ""
    if usuario:
        quem = ('<span class="quem"><span class="menu">'
                '<a href="/">Nova cotação</a><a href="/historico">Histórico</a>'
                f'<a href="/sair">Sair</a></span> <b>{e(usuario)}</b></span>')
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title><style>{CSS}</style></head><body>
<div class="topo"><img src="data:image/png;base64,{LOGO}" alt="Ventura">
{quem}</div>
<div class="wrap">{corpo}</div></body></html>"""



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

    # As de WhatsApp menos as que já apareceram acima (hoje, a Translovato).
    whatsapp = "".join(
        caixa(r.slug, r.nome, r.logo)
        for r in transportadoras.com_whatsapp() if r.slug not in AUTOMATICAS)

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
        + grupo("POR WHATSAPP", "abrem a mensagem pronta para você enviar",
                whatsapp)
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
        "transportadoras": escolhidas,
    })

    # Dispara e NÃO espera: cada uma grava o próprio resultado ao terminar.
    fabricas = {"camilo": _cotar_camilo, "jadlog": _cotar_jadlog,
                "translovato": _cotar_translovato,
                "generoso": _cotar_generoso}
    for slug in automaticas_da(dados.get("transportadoras")):
        EXECUTOR.submit(_rodar, cotacao_id, slug, fabricas[slug], req)

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
        res = cotar_com_retentativa(cotar_fn, req, ao_tentar=anotar)
        banco.salvar_resultado(
            cotacao_id, slug, status=res.status.value, valor=res.valor_frete,
            # motivo_recusa junto: "recusado" é a transportadora dizendo não,
            # e a frase que explica o porquê é escrita justamente para o
            # vendedor ler. Gravando só `erro`, ela era jogada fora e o cartão
            # caía no genérico "o site respondeu: recusado".
            protocolo=res.protocolo, erro=res.erro or res.motivo_recusa,
            evidencia=res.evidencias[-1] if res.evidencias else None)
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


def cartao_resposta_por_email(email: str | None) -> str:
    """Cartão de quem recebeu o pedido mas responde FORA do sistema.

    A Generoso não devolve preço na tela: confirma o recebimento e um vendedor
    responde por e-mail, horas depois. Sem este cartão ela caía no "Não
    retornou preço" — o mesmo texto de quem falhou — e o vendedor abandonaria
    uma cotação que está a caminho.

    A frase diz três coisas, nesta ordem, porque é a ordem em que a dúvida
    aparece: deu certo, onde a resposta chega, e que não adianta ficar
    olhando esta tela.

    Sem e-mail guardado (cotação anterior a 20/08/2026) o texto continua
    fazendo sentido, só não nomeia a caixa."""
    onde = (f'no e-mail <b class="caixa">{e(email)}</b> — o mesmo que você '
            f'digitou nesta cotação'
            if email else 'no e-mail que você digitou nesta cotação')
    return ('<div class="enviada">Cotação enviada</div>'
            f'<div class="alerta email"><b>O preço não vem nesta tela.</b> '
            f'A resposta chega {onde}. Confira a caixa de entrada e o spam — '
            f'esta tela não muda quando ela chegar.</div>')


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
            corpo = (cartao_resposta_por_email(c.get("email"))
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
            corpo = ('<div class="falhou">Não retornou preço</div>'
                     f'<div class="nota">'
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
    abertas = banco.whatsapp_abertos(cotacao_id)
    zaps = "".join(
        f'<a class="zap{" aberta" if reg.slug in abertas else ""}"'
        f' id="zap-{e(reg.slug)}"'
        f' href="/whatsapp/{cotacao_id}/{e(reg.slug)}"'
        f' target="_blank" rel="noopener">'
        f'<img class="marca" src="/logos/{e(reg.logo)}" alt="" loading="lazy">'
        f'<b>{e(reg.nome)}</b>'
        f'<span class="ir">Abrir no WhatsApp</span>'
        f'<span class="jafoi">Aberta</span></a>'
        for reg in lista_zap)

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

<div class="cartao">
  <h2 style="font-size:15px;margin:0 0 4px">Precisa de você
    <span class="contador"><b id="quantas">{len(abertas)}</b> de
    {len(lista_zap)} abertas</span></h2>
  <p class="sub">A mensagem abre pronta — <b>quem aperta enviar é você</b>,
  no WhatsApp. Por isso a conta acima diz <b>abertas</b>, e não enviadas:
  daqui o sistema não tem como saber se a mensagem saiu.</p>
  {zaps}
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
