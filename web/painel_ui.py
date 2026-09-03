"""O desenho do painel administrativo: casco, cartões e gráficos.

Vive fora de `web/adm.py` pelo mesmo motivo de `web/layout.py` existir:
aquele arquivo é sobre QUEM ENTRA e QUAIS NÚMEROS, este é só sobre como eles
aparecem. Juntos, a regra de segurança do topo do adm.py disputaria espaço
com escolha de cor — e quem fosse mexer no visual mexeria no arquivo do
cookie.

Tudo aqui é FUNÇÃO PURA: entra número, sai string. Nenhum banco, nenhuma
requisição — então gráfico se testa sem navegador, do mesmo jeito que
core/painel.py testa conta sem tela.

SEM BIBLIOTECA DE GRÁFICO, de propósito. O Servidor.bat sobe numa máquina da
empresa e a tela precisa abrir com a internet caída; um <script src> de CDN
viraria página em branco justamente no dia do problema — que é o dia em que
alguém quer olhar o painel. Todo gráfico daqui é SVG montado no Python e
animado por CSS, igual à barra do aproveitamento, que já era assim.
"""

from __future__ import annotations

from datetime import date
from math import hypot, pi

from web.layout import CSS as CSS_BASE, LOGO, e

# Cor por categoria de core.painel. Uma cor só, definida uma vez: se a rosca
# pintasse "recusa" de vermelho e a tabela de laranja, a mesma linha contaria
# duas histórias na mesma tela.
#
# Recusa NÃO é vermelha: a transportadora dizendo "não levo isso" está
# funcionando. Vermelho é para o que quebrou.
CORES = {
    "sucesso": "#00875a",
    "recusa": "#d97706",
    "falha": "#bf2600",
    "nossa": "#8b93a3",
    "inesperado": "#7c3aed",
}

ROTULOS = {
    "sucesso": "Sucessos",
    "recusa": "Recusas",
    "falha": "Falhas",
    "nossa": "Interrompidas",
    "inesperado": "Inesperado",
}

# O mesmo rótulo no singular, para a pastilha de UMA ocorrência. "1 sucessos"
# numa tela que a empresa inteira lê passa de descuido a assinatura.
SINGULAR = {
    "sucesso": "sucesso",
    "recusa": "recusa",
    "falha": "falha",
    "nossa": "interrompida",
    "inesperado": "inesperado",
}

MESES = ("jan", "fev", "mar", "abr", "mai", "jun",
         "jul", "ago", "set", "out", "nov", "dez")

SEMANA = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado",
          "domingo")

# Medidas do gráfico do período, em unidades do viewBox — não em pixels. O
# SVG sai com width:100%, então isto é proporção: o desenho acompanha a
# largura da tela sem recalcular nada no servidor.
G_L, G_A = 760, 230
G_ESQ, G_DIR, G_TOPO, G_BASE = 36, 8, 14, 26
G_LARG = G_L - G_ESQ - G_DIR
G_ALT = G_A - G_TOPO - G_BASE

# Acima disto a bolinha do ponto vira sujeira em cima da linha.
MAX_PONTOS_COM_BOLINHA = 32
MAX_ROTULOS_NO_EIXO = 9


CSS = """
/* =========================== painel administrativo ===========================
   Entra DEPOIS do CSS de web/layout.py, e por isso pode sobrescrevê-lo. O
   painel é a única tela com casco próprio: as outras são formulário e
   resultado, esta é um quadro de instrumentos. */
:root{--fundo:#f4f6f9;--sombra:0 1px 2px rgba(16,24,40,.05),
0 2px 8px rgba(16,24,40,.06);--sombra2:0 4px 20px rgba(16,24,40,.10)}
body{background:var(--fundo)}
/* Os links da lateral são âncoras para as seções da própria página; sem
   isto o salto é instantâneo e ninguém percebe para onde a tela foi. */
html{scroll-behavior:smooth}
.painel{display:flex;min-height:100vh}

/* ---- barra lateral ---- */
.lateral{flex:0 0 236px;width:236px;position:sticky;top:0;height:100vh;
background:linear-gradient(175deg,#1b2030 0%,#12151f 100%);color:#aeb7ca;
display:flex;flex-direction:column;padding:20px 0 16px}
.lateral .marca{display:flex;align-items:center;gap:10px;padding:0 20px 20px;
border-bottom:1px solid rgba(255,255,255,.07);margin-bottom:14px}
.lateral .marca img{height:30px;filter:brightness(0) invert(1);opacity:.92}
.lateral .marca b{color:#fff;font-size:15px;letter-spacing:2.4px;
text-transform:uppercase;font-weight:700}
.lateral .secao{padding:14px 20px 6px;font-size:10px;letter-spacing:1.4px;
text-transform:uppercase;color:#5d6780;font-weight:700}
.lateral a{display:flex;align-items:center;gap:11px;padding:9px 20px;
color:#aeb7ca;text-decoration:none;font-size:13.5px;
border-left:3px solid transparent;
transition:background .16s,color .16s,border-color .16s}
.lateral a:hover{background:rgba(255,255,255,.05);color:#fff}
.lateral a.atual{background:rgba(91,110,220,.16);color:#fff;
border-left-color:#6b7cd6;font-weight:600}
.lateral a svg{width:17px;height:17px;flex:none;opacity:.75}
.lateral a.atual svg{opacity:1}
.lateral .rodape{margin-top:auto;padding:12px 20px 0;font-size:11px;
color:#4e5771;border-top:1px solid rgba(255,255,255,.07)}

/* ---- área de conteúdo ---- */
.conteudo{flex:1;min-width:0;padding:24px 28px 64px}
.cabecalho{display:flex;align-items:center;gap:14px;flex-wrap:wrap;
margin-bottom:18px}
.cabecalho h1{font-size:23px;letter-spacing:-.4px;margin:0}
.cabecalho .sub{margin:2px 0 0}
.aovivo{display:inline-flex;align-items:center;gap:7px;font-size:11.5px;
color:var(--fraco);background:#fff;border:1px solid var(--borda);
border-radius:99px;padding:5px 12px}
.aovivo i{width:7px;height:7px;border-radius:50%;background:var(--ok);
animation:pisca 2.2s ease-in-out infinite}
@keyframes pisca{50%{opacity:.2;transform:scale(.7)}}

/* ---- seletor de período, agora em pastilhas ---- */
.periodos{margin-left:auto;display:flex;gap:4px;background:#fff;
border:1px solid var(--borda);border-radius:99px;padding:4px}
.periodo{padding:6px 15px;border-radius:99px;font-size:12.5px;color:#5b6478;
text-decoration:none;transition:background .15s,color .15s;white-space:nowrap}
.periodo:hover{background:var(--fundo)}
.periodo.atual{background:var(--marca);color:#fff;font-weight:600;
text-decoration:none}

/* ---- grade de cartões ---- */
.grade{display:grid;gap:16px;grid-template-columns:repeat(12,1fr);
margin-bottom:16px}
.c4{grid-column:span 4}.c5{grid-column:span 5}.c7{grid-column:span 7}
.c8{grid-column:span 8}.c12{grid-column:span 12}
@media(max-width:1180px){.c4,.c5,.c7,.c8{grid-column:span 12}}
.painel .cartao{background:var(--papel);border:1px solid var(--borda);
border-radius:14px;padding:18px 20px;margin:0;box-shadow:var(--sombra);
min-width:0}
.cartao-cab{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.cartao-cab h2{font-size:14px;margin:0;font-weight:700;letter-spacing:-.1px}
.cartao-cab .nota{font-size:11.5px;color:var(--fraco);font-weight:400}
.cartao-cab .direita{margin-left:auto;display:flex;align-items:center;
gap:12px}
.legenda{display:flex;gap:14px;font-size:11.5px;color:var(--fraco);
flex-wrap:wrap}
.legenda span{display:inline-flex;align-items:center;gap:6px}
.legenda i{width:9px;height:9px;border-radius:3px;display:inline-block}
.vazio{color:var(--fraco);font-size:13px;text-align:center;padding:26px 0;
margin:0}

/* ---- entrada dos cartões: sobem uma vez, escalonados ---- */
@keyframes entra{from{opacity:0;transform:translateY(12px)}
to{opacity:1;transform:none}}
.anima{animation:entra .5s cubic-bezier(.22,.9,.3,1) both}

/* ---- números do topo ---- */
.faixa{display:grid;gap:14px;
grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin:0 0 16px}
.numero{position:relative;overflow:hidden;background:var(--papel);
border:1px solid var(--borda);border-radius:14px;padding:16px 18px 15px;
box-shadow:var(--sombra);transition:transform .18s,box-shadow .18s}
.numero:hover{transform:translateY(-2px);box-shadow:var(--sombra2)}
.numero::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;
background:var(--cor,var(--marca))}
.numero .ico{position:absolute;right:14px;top:14px;width:34px;height:34px;
border-radius:10px;display:grid;place-items:center;
background:var(--fraca,#eef1fb)}
.numero .ico svg{width:17px;height:17px}
.numero b{display:block;font-size:36px;line-height:1.05;font-weight:700;
letter-spacing:-1.4px;font-variant-numeric:tabular-nums;color:var(--tinta)}
.numero span{display:block;font-size:12px;color:var(--fraco);margin-top:3px}
.numero.ruim b{color:var(--erro)}

/* ---- gráfico ---- */
.svg{width:100%;height:auto;display:block}
.svg text{font-family:inherit}
/* O SVG encolhe junto com a tela, e o rótulo do eixo encolhe junto com ele:
   num celular de 420px o desenho fica na metade da escala e "27/08" sai com
   5px de altura, ilegível. Abaixo de .grafico ele para de encolher e passa a
   rolar de lado — o número continua do tamanho que dá para ler. */
.grafico{overflow-x:auto}
.eixo{font-size:10px;fill:#9aa2b1}
.malha{stroke:#eceff4;stroke-width:1}
.fantasma{fill:#f2f4f8}
.barra-g{fill:url(#tintaBarra);transform-box:fill-box;transform-origin:bottom;
animation:sobe .65s cubic-bezier(.22,.9,.3,1) both}
.barra-g:hover{filter:brightness(1.12)}
@keyframes sobe{from{transform:scaleY(0)}to{transform:scaleY(1)}}
.linha-g{fill:none;stroke:var(--ok);stroke-width:2.4;stroke-linecap:round;
stroke-linejoin:round;animation:traca 1.15s ease-out both}
@keyframes traca{from{stroke-dashoffset:var(--comp)}to{stroke-dashoffset:0}}
.ponto-g{fill:#fff;stroke:var(--ok);stroke-width:2;transform-box:fill-box;
transform-origin:center;animation:surge .3s ease-out both}
@keyframes surge{from{opacity:0;transform:scale(0)}
to{opacity:1;transform:scale(1)}}
.area-g{fill:url(#tintaArea);animation:aparece .9s ease-out both}
@keyframes aparece{from{opacity:0}to{opacity:1}}

/* ---- roscas de aproveitamento ---- */
.roscas{display:grid;gap:12px;
grid-template-columns:repeat(auto-fit,minmax(102px,1fr))}
.rosca{text-align:center;padding:6px 2px}
.rosca svg{width:100%;max-width:94px;height:auto}
.rosca .trilho{fill:none;stroke:#edeff4;stroke-width:9}
.rosca .arco{fill:none;stroke-width:9;stroke-linecap:round;
transform:rotate(-90deg);transform-origin:50% 50%;
animation:enche 1.05s cubic-bezier(.22,.9,.3,1) both}
@keyframes enche{from{stroke-dashoffset:var(--vazio)}
to{stroke-dashoffset:var(--cheio)}}
.rosca .meio{font-size:19px;font-weight:700;fill:var(--tinta);
font-variant-numeric:tabular-nums}
.rosca .meio.sem{font-size:15px;fill:#a8aebc}
.rosca .quem{font-size:12px;margin:2px 0 0;font-weight:600;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.rosca .quanto{font-size:11px;color:var(--fraco);margin:0}

/* ---- rosca de fatias (distribuição de status) ---- */
.pizza{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.pizza svg{width:150px;height:150px;flex:none;
animation:gira-entra .7s cubic-bezier(.22,.9,.3,1) both}
@keyframes gira-entra{from{opacity:0;transform:rotate(-25deg) scale(.82)}
to{opacity:1;transform:none}}
.pizza .fatia{fill:none;stroke-width:20;transition:stroke-width .18s}
.pizza .fatia:hover{stroke-width:24}
.pizza .total{font-size:26px;font-weight:700;fill:var(--tinta);
font-variant-numeric:tabular-nums}
.pizza .total-sub{font-size:9.5px;fill:#9aa2b1;letter-spacing:1px}
.tabela-legenda{flex:1;min-width:150px;border-collapse:collapse;
font-size:12.5px}
.painel .tabela-legenda td{padding:5px 0;border:0}
.tabela-legenda td:last-child{text-align:right;font-weight:700;
font-variant-numeric:tabular-nums}
.tabela-legenda i{width:9px;height:9px;border-radius:3px;
display:inline-block;margin-right:8px}

/* ---- barras horizontais (ranking) ---- */
.rank{display:flex;flex-direction:column;gap:11px;margin:0}
.rank .li{display:grid;grid-template-columns:1fr auto;gap:2px 10px;
font-size:12.5px}
.rank .nome{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
font-weight:600}
.rank .qtd{color:var(--fraco);font-variant-numeric:tabular-nums}
.rank .trilho{grid-column:1/-1;height:8px;border-radius:99px;
background:#eef0f5;overflow:hidden}
.rank .trilho i{display:block;height:100%;border-radius:99px;
background:linear-gradient(90deg,#4c5fc7,#8b9be8);
animation:cresce .8s cubic-bezier(.22,.9,.3,1) both}
@keyframes cresce{from{width:0}}

/* ---- avatar de quem cotou ---- */
.eu{display:inline-flex;align-items:center;gap:8px;min-width:0}
.eu .bola{width:24px;height:24px;border-radius:50%;flex:none;display:grid;
place-items:center;font-size:10.5px;font-weight:700;color:#fff;
background:var(--marca);text-transform:uppercase}

/* ---- pastilhas de resultado ---- */
.pilulas{display:flex;gap:5px;flex-wrap:wrap}
.pilula{display:inline-flex;align-items:center;gap:4px;font-size:11px;
font-weight:700;border-radius:99px;padding:2px 8px;line-height:1.5;
font-variant-numeric:tabular-nums;white-space:nowrap}

/* ---- tabelas do painel ---- */
.painel table{font-size:12.5px}
.painel th{padding:8px;position:sticky;top:0;background:var(--papel);z-index:2}
.painel td{padding:9px 8px;vertical-align:middle}
.painel tbody tr{transition:background .12s}
.painel tbody tr:hover td{background:#f7f9fc}
.rolagem{max-height:540px;overflow:auto;margin:0 -20px -18px;
padding:0 20px 6px}
.saude td:nth-child(n+2){font-variant-numeric:tabular-nums}
.barra{display:inline-block;width:74px;height:7px;background:#eef0f5;
border-radius:99px;vertical-align:middle;overflow:hidden}
.barra i{display:block;height:100%;border-radius:99px;
background:linear-gradient(90deg,#00a86b,#00875a);
animation:cresce .8s cubic-bezier(.22,.9,.3,1) both}
.sem-dado{color:#a8aebc;font-size:11.5px;font-style:italic}

/* ---- histórico ---- */
.busca{position:relative}
.busca input{width:216px;padding:7px 11px 7px 30px;border-radius:8px;
font-size:12.5px}
.busca svg{position:absolute;left:9px;top:50%;transform:translateY(-50%);
width:14px;height:14px;opacity:.4;pointer-events:none}
.historico td{border-bottom:1px solid #f2f4f7}
.historico .dia td{background:#f7f9fc;font-size:10.5px;font-weight:700;
letter-spacing:1.1px;text-transform:uppercase;color:#8b93a3;padding:7px 8px;
border-bottom:1px solid var(--borda);position:sticky;top:31px;z-index:1}
.historico .dia .conta{float:right;letter-spacing:0;text-transform:none}
.historico .id{color:#a8aebc;font-variant-numeric:tabular-nums;width:1%;
white-space:nowrap}
.historico .hora{color:var(--fraco);font-variant-numeric:tabular-nums;
width:1%;white-space:nowrap}
.historico .rota{color:#4b5364}
.historico .material{max-width:220px;overflow:hidden;text-overflow:ellipsis;
white-space:nowrap}
/* O preço é o número que o olho procura na linha: alinhado à direita, todas
   as vírgulas na mesma coluna. O travessão de "sem preço" NÃO herda o verde
   — não ter preço não é um preço bom. */
.historico td:nth-child(6){text-align:right;font-weight:700;
font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--ok)}
.historico tr.sem-preco td:nth-child(6){color:#c3c8d2;font-weight:400}
.historico tr.sumiu,.historico tbody.sumiu{display:none}
.nada{display:none;color:var(--fraco);font-size:13px;padding:22px 0;
text-align:center}
.nada.aparece{display:block}

/* Quem lê com movimento reduzido precisa ver o estado FINAL, não o inicial:
   animation:none deixaria a linha do gráfico presa no dashoffset cheio, ou
   seja, invisível. Duração quase zero preserva o `forwards`. */
@media (prefers-reduced-motion:reduce){
*,*::before,*::after{animation-duration:.01ms!important;
animation-iteration-count:1!important;transition-duration:.01ms!important}}

@media(max-width:880px){
.painel{display:block}
.lateral{width:auto;height:auto;position:static;flex-direction:row;
flex-wrap:wrap;align-items:center;padding:12px 16px;gap:4px}
.lateral .marca{border:0;margin:0;padding:0 14px 0 0}
.lateral .secao,.lateral .rodape{display:none}
.lateral a,.lateral a.atual{border-left:0;border-radius:8px;padding:7px 11px}
.conteudo{padding:16px 14px 48px}
.periodos{margin-left:0;width:100%;justify-content:space-between}
.rolagem{margin:0 -20px;padding:0 20px}
.svg{min-width:560px}
}
"""


# ------------------------------------------------------------------ casco

def _icone(caminho: str) -> str:
    """Um <svg> de traço, no tom do resto da tela. Ícone desenhado à mão em
    vez de fonte de ícone pelo mesmo motivo do gráfico: nada de CDN."""
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.9" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{caminho}</svg>')


ICONES = {
    "visao": '<path d="M3 13h4v8H3zM10 3h4v18h-4zM17 9h4v12h-4z"/>',
    "grafico": '<path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 5-6"/>',
    "transportadoras": ('<path d="M1 3h13v13H1z"/><path d="M14 8h4l3 3v5h-7z"/>'
                        '<circle cx="5.5" cy="18.5" r="2"/>'
                        '<circle cx="17.5" cy="18.5" r="2"/>'),
    "historico": ('<path d="M3 3v5h5"/>'
                  '<path d="M3.05 13A9 9 0 106 5.3L3 8"/>'
                  '<path d="M12 7v5l3 2"/>'),
    "sair": ('<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/>'
             '<path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>'),
    "cotacoes": '<path d="M4 4h16v16H4z"/><path d="M4 9h16M9 9v11"/>',
    "preco": ('<circle cx="12" cy="12" r="9"/><path d="M12 6.5v11"/>'
              '<path d="M14.8 9.4a2.4 2.4 0 00-2.3-1.7h-1a2.3 2.3 0 000 4.6h1'
              'a2.3 2.3 0 010 4.6h-1a2.4 2.4 0 01-2.3-1.7"/>'),
    "alerta": ('<path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3'
               'L14.7 3.9a2 2 0 00-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'),
    "relogio": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "busca": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
}

# (ícone, rótulo, id da seção). O id É o destino do link e o valor de
# data-secao: o JavaScript compara os dois para marcar no menu a seção que
# está na frente dos olhos, e dois nomes diferentes para a mesma seção
# deixariam a marcação nunca acender.
MENU = (
    ("visao", "Visão geral", "topo"),
    ("grafico", "Movimento", "movimento"),
    ("transportadoras", "Transportadoras", "transportadoras"),
    ("historico", "Histórico", "historico"),
)


def _lateral() -> str:
    # `if LOGO`: web/logo_b64.txt pode estar vazio numa pasta recém-clonada, e
    # um src="data:image/png;base64," vira ícone de imagem quebrada bem no
    # canto mais visível da tela.
    marca = (f'<img src="data:image/png;base64,{LOGO}" alt="Ventura">'
             if LOGO else "")
    itens = "".join(
        f'<a href="#{alvo}" data-secao="{alvo}">{_icone(ICONES[chave])}'
        f'<span>{e(rotulo)}</span></a>'
        for chave, rotulo, alvo in MENU)
    return f"""<nav class="lateral">
  <div class="marca">{marca}<b>Painel</b></div>
  <div class="secao">Acompanhar</div>
  {itens}
  <div class="secao">Conta</div>
  <a href="/adm/sair">{_icone(ICONES["sair"])}<span>Sair do painel</span></a>
  <div class="rodape">Cotafrete · Ventura</div>
</nav>"""


def pagina_painel(titulo: str, corpo: str) -> str:
    """A página inteira do painel. Casco próprio, e não o `pagina()` do
    layout: aquele é uma faixa em cima e uma coluna de 1080px, desenhada para
    formulário. Quadro de instrumentos quer a largura toda e uma navegação
    que fica parada enquanto a tabela rola."""
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title>
<style>{CSS_BASE}{CSS}</style></head><body>
<div class="painel">{_lateral()}<main class="conteudo">{corpo}</main></div>
</body></html>"""


def cartao(titulo: str, conteudo: str, *, ident: str = "", nota: str = "",
           direita: str = "", classe: str = "c12", atraso: float = 0.0) -> str:
    """Um cartão da grade. `atraso` escalona a entrada — os cartões sobem em
    cascata em vez de piscarem todos de uma vez."""
    onde = f' id="{ident}"' if ident else ""
    dir_html = f'<div class="direita">{direita}</div>' if direita else ""
    nota_html = f'<span class="nota">{e(nota)}</span>' if nota else ""
    return (f'<section class="cartao anima {classe}"{onde} '
            f'style="animation-delay:{atraso:.2f}s">'
            f'<div class="cartao-cab"><h2>{e(titulo)}</h2>{nota_html}'
            f'{dir_html}</div>{conteudo}</section>')


def legenda(itens: tuple[tuple[str, str], ...]) -> str:
    """(cor, rótulo) — a chave de leitura do gráfico, ao lado do título."""
    return ('<div class="legenda">' + "".join(
        f'<span><i style="background:{cor}"></i>{e(rotulo)}</span>'
        for cor, rotulo in itens) + "</div>")


# --------------------------------------------------------------- números

def faixa(resumo: dict) -> str:
    """A faixa ao vivo. Fragmento SEM casco: é ela que o JavaScript troca a
    cada 10s, então nada de <html> aqui dentro.

    O número já vem escrito dentro do elemento. A contagem animada é enfeite
    que o JavaScript aplica UMA vez, no carregamento — se rodasse a cada
    troca, o painel piscaria de zero até o valor a cada 10 segundos, na cara
    de quem está tentando ler."""
    def bloco(rotulo: str, valor: int, cor: str, fraca: str, icone: str,
              ruim: bool = False) -> str:
        return (
            f'<div class="numero{" ruim" if ruim else ""}" '
            f'style="--cor:{cor};--fraca:{fraca}">'
            f'<div class="ico" style="color:{cor}">{_icone(ICONES[icone])}</div>'
            f'<b data-conta>{valor}</b><span>{e(rotulo)}</span></div>')

    return (
        '<div class="faixa">'
        + bloco("cotações hoje", resumo["cotacoes"], "#4c5fc7", "#eef0fb",
                "cotacoes")
        + bloco("com preço", resumo["com_preco"], "#00875a", "#e6f4ee",
                "preco")
        # O número que mais importa: o vendedor ficou na mão.
        + bloco("sem nenhum preço", resumo["sem_nenhum_preco"], "#bf2600",
                "#fdecea", "alerta", ruim=bool(resumo["sem_nenhum_preco"]))
        + bloco("cotando agora", resumo["em_andamento"], "#d97706", "#fdf3e3",
                "relogio")
        + "</div>")


# --------------------------------------------------------------- gráficos

def teto(maior: int) -> int:
    """Topo do eixo Y: o menor número REDONDO em que o maior valor ainda cabe.

    Sempre PAR, porque o eixo tem um risco no meio — com topo ímpar o rótulo
    do meio sairia "7,5 cotações", que não existe."""
    if maior <= 1:
        return 2
    if maior <= 10:
        return maior + maior % 2
    magnitude = 10 ** (len(str(maior)) - 1)
    for multiplo in (1, 2, 4, 5, 6, 8, 10):
        alvo = int(magnitude * multiplo)
        if alvo >= maior:
            return alvo
    return maior


def rotulo_do_balde(chave: str, unidade: str) -> str:
    """"2026-09-02T14" -> "14h"; "2026-09-02" -> "02/09"; "2026-09" -> "set/26".

    A chave vem crua de core.painel para o gráfico não depender de como a
    tela escreve data — e para a conta se testar sem string de tela."""
    if unidade == "hora":
        return f"{chave[11:13]}h"
    if unidade == "mes":
        return f"{MESES[int(chave[5:7]) - 1]}/{chave[2:4]}"
    return f"{chave[8:10]}/{chave[5:7]}"


def _y(valor: float, alto: int) -> float:
    return G_TOPO + (1 - valor / alto) * G_ALT


def grafico_periodo(pontos: list[dict], unidade: str) -> str:
    """Barras de cotações com a linha de "com preço" por cima.

    Duas séries no mesmo desenho de propósito: a distância entre a barra e a
    linha É a pergunta do painel — quantas cotações não viraram preço. Em
    dois gráficos separados, o olho teria que fazer essa subtração sozinho."""
    if not pontos:
        return '<p class="vazio">Nenhuma cotação no período.</p>'

    alto = teto(max(p["cotacoes"] for p in pontos))
    n = len(pontos)
    faixa_x = G_LARG / n
    largura = min(faixa_x * 0.58, 26)
    base = G_TOPO + G_ALT

    def centro(i: int) -> float:
        return G_ESQ + faixa_x * (i + 0.5)

    malha = "".join(
        f'<line class="malha" x1="{G_ESQ}" y1="{_y(v, alto):.1f}" '
        f'x2="{G_L - G_DIR}" y2="{_y(v, alto):.1f}"/>'
        f'<text class="eixo" x="{G_ESQ - 8}" y="{_y(v, alto) + 3.5:.1f}" '
        f'text-anchor="end">{v:g}</text>'
        for v in (0, alto / 2, alto))

    # Rótulos contados a partir do FIM, não do começo. Contando do começo, o
    # último balde — que é "agora", e sem ele o gráfico não diz onde termina —
    # precisava de uma exceção "sempre mostre o último", e essa exceção caía
    # em cima do rótulo anterior: em 35 dias saía "01/0902/09" grudado.
    passo = max(1, -(-n // MAX_ROTULOS_NO_EIXO))
    eixo_x = "".join(
        f'<text class="eixo" x="{centro(i):.1f}" y="{G_A - 8}" '
        f'text-anchor="middle">{e(rotulo_do_balde(p["chave"], unidade))}</text>'
        for i, p in enumerate(pontos) if (n - 1 - i) % passo == 0)

    barras = ""
    for i, p in enumerate(pontos):
        x = centro(i) - largura / 2
        topo_barra = _y(p["cotacoes"], alto)
        dica = (f'{rotulo_do_balde(p["chave"], unidade)}: {p["cotacoes"]} '
                f'cotações · {p["com_preco"]} com preço')
        barras += (
            f'<g><title>{e(dica)}</title>'
            f'<rect class="fantasma" x="{x:.1f}" y="{G_TOPO}" '
            f'width="{largura:.1f}" height="{G_ALT}" rx="3"/>'
            f'<rect class="barra-g" x="{x:.1f}" y="{topo_barra:.1f}" '
            f'width="{largura:.1f}" height="{base - topo_barra:.1f}" rx="3" '
            f'style="animation-delay:{i * 0.022:.3f}s"/></g>')

    coords = [(centro(i), _y(p["com_preco"], alto))
              for i, p in enumerate(pontos)]
    # Comprimento REAL da linha, somado segmento a segmento. Um
    # stroke-dasharray chutado grande "funciona", mas o traço termina no
    # primeiro quarto da animação e o resto do tempo não acontece nada.
    comprimento = sum(hypot(x2 - x1, y2 - y1)
                      for (x1, y1), (x2, y2) in zip(coords, coords[1:])) or 1
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = d + f" L{coords[-1][0]:.1f},{base} L{coords[0][0]:.1f},{base} Z"

    bolinhas = ""
    if n <= MAX_PONTOS_COM_BOLINHA:
        bolinhas = "".join(
            f'<circle class="ponto-g" cx="{x:.1f}" cy="{y:.1f}" r="3.2" '
            f'style="animation-delay:{0.55 + i * 0.022:.3f}s"/>'
            for i, (x, y) in enumerate(coords))

    return f"""<div class="grafico"><svg class="svg" viewBox="0 0 {G_L} {G_A}"
 role="img" aria-label="Cotações por {e(unidade)} no período">
<defs>
<linearGradient id="tintaBarra" x1="0" y1="0" x2="0" y2="1">
<stop offset="0%" stop-color="#8b9be8"/>
<stop offset="100%" stop-color="#4c5fc7"/></linearGradient>
<linearGradient id="tintaArea" x1="0" y1="0" x2="0" y2="1">
<stop offset="0%" stop-color="#00875a" stop-opacity=".18"/>
<stop offset="100%" stop-color="#00875a" stop-opacity="0"/></linearGradient>
</defs>
{malha}{barras}
<path class="area-g" d="{area}"/>
<path class="linha-g" d="{d}" style="--comp:{comprimento:.0f};\
stroke-dasharray:{comprimento:.0f};stroke-dashoffset:{comprimento:.0f}"/>
{bolinhas}{eixo_x}</svg></div>"""


RAIO = 42
VOLTA = 2 * pi * RAIO


def rosca(fracao: float | None, nome: str, detalhe: str = "") -> str:
    """Anel de aproveitamento. `fracao is None` é DESCONHECIDO, não zero — o
    anel fica cinza e o meio escreve "—", porque um anel vazio pintado de
    vermelho acusaria de "nunca acerta" quem só viu o servidor reiniciar."""
    if fracao is None:
        meio = ('<text class="meio sem" x="50" y="56" '
                'text-anchor="middle">—</text>')
        arco = ""
        abaixo = ('<p class="quanto"><span class="sem-dado">'
                  'sem dados ainda</span></p>')
    else:
        # Verde só quando é bom de verdade: anel verde em 40% de
        # aproveitamento tranquiliza justamente quem deveria estar ligando
        # para a transportadora.
        cor = ("#00875a" if fracao >= 0.85 else
               "#d97706" if fracao >= 0.5 else "#bf2600")
        cheio = VOLTA * (1 - fracao)
        meio = (f'<text class="meio" x="50" y="56" text-anchor="middle">'
                f'{fracao * 100:.0f}%</text>')
        arco = (f'<circle class="arco" cx="50" cy="50" r="{RAIO}" '
                f'stroke="{cor}" stroke-dasharray="{VOLTA:.1f}" '
                f'style="--vazio:{VOLTA:.1f};--cheio:{cheio:.1f};'
                f'stroke-dashoffset:{cheio:.1f}"/>')
        abaixo = f'<p class="quanto">{e(detalhe)}</p>'
    return (f'<div class="rosca"><svg viewBox="0 0 100 100" role="img" '
            f'aria-label="{e(nome)}">'
            f'<circle class="trilho" cx="50" cy="50" r="{RAIO}"/>{arco}{meio}'
            f'</svg><p class="quem" title="{e(nome)}">{e(nome)}</p>'
            f'{abaixo}</div>')


def roscas_das_transportadoras(linhas: list[dict]) -> str:
    if not linhas:
        return '<p class="vazio">Nenhuma cotação no período.</p>'

    def quantas(l: dict) -> str:
        # O denominador do aproveitamento, escrito por extenso: sem ele, 100%
        # de uma resposta só parece o mesmo que 100% de cem.
        base = l["sucesso"] + l["recusa"] + l["falha"]
        return f'{l["sucesso"]} de {base} resposta{"" if base == 1 else "s"}'

    return '<div class="roscas">' + "".join(
        rosca(l["aproveitamento"], l["transportadora"], quantas(l))
        for l in linhas) + "</div>"


def pizza_de_status(linhas: list[dict]) -> str:
    """Uma volta inteira repartida entre as categorias, com a contagem ao
    lado. As fatias entram sempre na ordem de CORES — a mesma de core.painel
    — para a figura não trocar de forma entre dois carregamentos com os
    mesmos números."""
    por_categoria = {chave: sum(l[chave] for l in linhas) for chave in CORES}
    total = sum(por_categoria.values())
    if not total:
        return ('<p class="vazio">Nenhuma resposta de transportadora no '
                'período.</p>')

    fatias = ""
    percorrido = 0.0
    for chave, cor in CORES.items():
        n = por_categoria[chave]
        if not n:
            continue
        tamanho = VOLTA * n / total
        # Folga entre as fatias para duas cores parecidas não virarem uma
        # faixa só. Nunca maior que a própria fatia: sem esse limite, a
        # categoria com uma ocorrência sumia do desenho.
        risco = max(tamanho - min(1.2, tamanho / 2), 0.4)
        fatias += (
            f'<circle class="fatia" cx="60" cy="60" r="{RAIO + 8}" '
            f'stroke="{cor}" stroke-dasharray="{risco:.2f} {VOLTA * 1.5:.2f}" '
            f'stroke-dashoffset="{-percorrido:.2f}">'
            f'<title>{e(ROTULOS[chave])}: {n}</title></circle>')
        percorrido += tamanho

    linhas_legenda = "".join(
        f'<tr><td><i style="background:{CORES[chave]}"></i>'
        f'{e(ROTULOS[chave])}</td><td>{por_categoria[chave]}</td></tr>'
        for chave in CORES if por_categoria[chave])

    return f"""<div class="pizza">
<svg viewBox="0 0 120 120" role="img" aria-label="Distribuição dos status">
<g transform="rotate(-90 60 60)">{fatias}</g>
<text class="total" x="60" y="60" text-anchor="middle">{total}</text>
<text class="total-sub" x="60" y="74" text-anchor="middle">RESPOSTAS</text>
</svg>
<table class="tabela-legenda">{linhas_legenda}</table></div>"""


def ranking(itens: list[dict], chave_nome: str, chave_valor: str) -> str:
    """Barras horizontais, a maior sempre cheia. Proporção contra o LÍDER, e
    não contra o total: com dez vendedores, dez barras de 10% não deixam
    comparar ninguém com ninguém."""
    if not itens:
        return '<p class="vazio">Nenhuma cotação no período.</p>'
    maior = max(i[chave_valor] for i in itens) or 1
    return '<div class="rank">' + "".join(
        f'<div class="li"><span class="nome">{e(i[chave_nome])}</span>'
        f'<span class="qtd">{i[chave_valor]}</span>'
        f'<span class="trilho"><i style="'
        f'width:{i[chave_valor] / maior * 100:.1f}%;'
        f'animation-delay:{p * 0.05:.2f}s"></i></span></div>'
        for p, i in enumerate(itens)) + "</div>"


# --------------------------------------------------------------- histórico

def pilulas(contagem: dict) -> str:
    """O que aconteceu na cotação, em cores, no lugar do número de falhas
    cru. "3 sucessos · 1 recusa" se lê de longe; "1" na coluna falhas obriga
    a abrir a cotação para saber se o resto deu certo."""
    def diz(chave: str, quantas: int) -> str:
        return (SINGULAR[chave] if quantas == 1 else ROTULOS[chave].lower())

    partes = "".join(
        f'<span class="pilula" style="color:{CORES[chave]};'
        f'background:{CORES[chave]}1a">'
        f'{contagem[chave]} {e(diz(chave, contagem[chave]))}</span>'
        for chave in CORES if contagem.get(chave))
    return (f'<div class="pilulas">{partes}</div>' if partes
            else '<span class="sem-dado">ainda cotando</span>')


def avatar(nome: str) -> str:
    """Inicial num círculo. A cor sai do próprio nome — o mesmo vendedor tem
    sempre a mesma cor, sem tabela de cor por pessoa para manter."""
    tom = sum(map(ord, nome)) * 47 % 360
    return (f'<span class="eu"><span class="bola" '
            f'style="background:hsl({tom},42%,45%)">{e(nome[:1] or "?")}</span>'
            f'<span>{e(nome)}</span></span>')


def dia_por_extenso(iso: str) -> str:
    """"2026-09-02" -> "hoje · quarta, 02/09". Hoje e ontem ganham nome
    porque é neles que quem abre o painel está interessado."""
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return iso[:10]
    prefixo = {0: "hoje · ", 1: "ontem · "}.get((date.today() - d).days, "")
    return f"{prefixo}{SEMANA[d.weekday()]}, {d.day:02d}/{d.month:02d}"
