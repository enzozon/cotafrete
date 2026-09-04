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

from core.painel import categoria
from web.layout import CSS as CSS_BASE, LOGO, e

# `categoria` é a ÚNICA coisa que este arquivo importa de fora do desenho, e
# é função pura. Vem de lá em vez de ser reescrita aqui porque é ela quem diz
# se um status é sucesso, recusa ou falha — a mesma classificação que pinta a
# rosca, a pizza e a pastilha. Uma segunda tabela aqui daria à mesma linha
# duas leituras na mesma tela.

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
background:linear-gradient(175deg,#24305e 0%,#141a35 100%);color:#b6c2dd;
display:flex;flex-direction:column;padding:20px 0 16px}
.lateral .marca{display:flex;align-items:center;gap:10px;padding:0 20px 20px;
border-bottom:1px solid rgba(255,255,255,.07);margin-bottom:14px}
.lateral .marca img{height:30px;filter:brightness(0) invert(1);opacity:.92}
.lateral .marca b{color:#fff;font-size:15px;letter-spacing:2.4px;
text-transform:uppercase;font-weight:700}
.lateral .secao{padding:14px 20px 6px;font-size:10px;letter-spacing:1.4px;
text-transform:uppercase;color:#7280a6;font-weight:700}
.lateral a{display:flex;align-items:center;gap:11px;padding:9px 20px;
color:#b6c2dd;text-decoration:none;font-size:13.5px;
border-left:3px solid transparent;
transition:background .16s,color .16s,border-color .16s}
.lateral a:hover{background:rgba(255,255,255,.05);color:#fff}
.lateral a.atual{background:rgba(112,200,224,.14);color:#fff;
border-left-color:#70c8e0;font-weight:600}
.lateral a svg{width:17px;height:17px;flex:none;opacity:.75}
.lateral a.atual svg{opacity:1}
.lateral .rodape{margin-top:auto;padding:12px 20px 0;font-size:11px;
color:#606e94;border-top:1px solid rgba(255,255,255,.07)}

/* ---- área de conteúdo ---- */
.conteudo{flex:1;min-width:0;padding:24px 28px 64px}
.cabecalho{display:flex;align-items:center;gap:14px;flex-wrap:wrap;
margin-bottom:18px}
.cabecalho h1{font-size:23px;letter-spacing:-.4px;margin:0}
.cabecalho .sub{margin:2px 0 0;display:flex;align-items:center;gap:6px;
flex-wrap:wrap}
.cabecalho .direita{margin-left:auto;display:flex;align-items:center;gap:10px}
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
/* Dois cartões baixos empilhados numa coluna da grade. Sem isto eles caem em
   linhas diferentes: a grade é de 12 colunas com colocação automática, e o
   segundo c4 volta para a coluna 1 da linha seguinte em vez de ficar embaixo
   do primeiro — deixando meia tela em branco ao lado de um cartão alto. */
.coluna{display:flex;flex-direction:column;gap:16px;min-width:0}
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
background:linear-gradient(90deg,#384890,#70c8e0);
animation:cresce .8s cubic-bezier(.22,.9,.3,1) both}
@keyframes cresce{from{width:0}}

/* ---- avatar de quem cotou ---- */
/* A bolinha é regra SOLTA, e não `.eu .bola`: ela também aparece sozinha, no
   lugar da logo de uma transportadora sem arquivo cadastrado. */
.eu{display:inline-flex;align-items:center;gap:8px;min-width:0}
.bola{width:24px;height:24px;border-radius:50%;flex:none;display:grid;
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

/* ---- alertas: falha seguida ---- */
/* Só aparece quando existe algo. Um cartão "nenhum alerta" ocupando o topo
   todo dia treina o olho a pular a região — e aí ele pula também no dia em
   que o alerta está lá. */
.alertas{display:flex;flex-direction:column;gap:10px;margin:0}
.alerta-linha{display:flex;gap:12px;align-items:flex-start;
border:1px solid #ffd5cc;background:#fff6f4;border-radius:12px;
padding:12px 14px}
.alerta-linha .sino{width:32px;height:32px;border-radius:9px;flex:none;
display:grid;place-items:center;background:#fdece9;color:var(--erro)}
.alerta-linha .sino svg{width:17px;height:17px}
.alerta-linha .diz{min-width:0;flex:1}
.alerta-linha b{font-size:13.5px}
.alerta-linha .quando{font-size:11.5px;color:var(--fraco);margin:1px 0 0}
/* O texto de erro é de programador e pode ser longo. Duas linhas dizem qual
   é o problema; o resto está na cotação, a um clique daqui. */
.alerta-linha .porque{font-size:12px;color:#7a3b2e;margin:6px 0 0;
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
overflow:hidden}
.alerta-linha .quais{margin-left:auto;display:flex;gap:5px;flex-wrap:wrap;
justify-content:flex-end}
.alerta-linha .quais a{font-size:11.5px;font-weight:700;text-decoration:none;
color:var(--erro);background:#fdece9;border-radius:99px;padding:2px 9px;
white-space:nowrap}
.alerta-linha .quais a:hover{background:#fbdcd6}

/* ---- filtros do histórico ---- */
.filtros{display:flex;align-items:center;gap:6px;flex-wrap:wrap;
margin:0 0 12px}
.filtros .rotulo{font-size:11px;text-transform:uppercase;letter-spacing:1px;
color:#9aa2b1;font-weight:700;margin-right:2px}
.filtro-p{padding:5px 12px;border-radius:99px;font-size:12px;color:#5b6478;
text-decoration:none;border:1px solid var(--borda);background:var(--papel);
white-space:nowrap;transition:background .15s,color .15s,border-color .15s}
.filtro-p:hover{background:var(--fundo)}
.filtro-p.atual{background:var(--marca);border-color:var(--marca);color:#fff;
font-weight:600}
.filtro-p.perigo.atual{background:var(--erro);border-color:var(--erro)}

/* ---- linha do histórico que abre a cotação ---- */
/* A linha inteira é clicável (o JavaScript leva), mas o número continua
   sendo um <a> de verdade: é ele que responde ao teclado, ao botão do meio e
   ao "abrir em nova aba" — coisas que um onclick sozinho tira de quem
   trabalha com o teclado o dia inteiro. */
.historico tbody tr[data-abrir]{cursor:pointer}
.historico .id a{color:#7b839a;text-decoration:none;font-weight:700}
.historico tbody tr:hover .id a{color:var(--marca);text-decoration:underline}
.historico .seta{width:1%;color:#c7ccd8;text-align:right;padding-right:2px}
.historico tbody tr:hover .seta{color:var(--marca)}

/* ---- tela de UMA cotação ---- */
.voltar{display:inline-flex;align-items:center;gap:6px;font-size:12px;
color:var(--fraco);text-decoration:none;margin-bottom:2px}
.voltar:hover{color:var(--marca)}
.voltar svg{width:13px;height:13px}
/* align-items:start para cada cartão ter a altura do que tem dentro. Esticado
   até o mais alto da fileira, o cartão de quem só respondeu "enviada" virava
   uma caixa quase vazia do tamanho do cartão que traz print e stack trace. */
.respostas{display:grid;gap:12px;align-items:start;
grid-template-columns:repeat(auto-fit,minmax(258px,1fr))}
.resposta{border:1px solid var(--borda);border-radius:12px;padding:14px 15px;
background:var(--papel);min-width:0}
/* A mais barata ganha borda verde, e não fundo verde: o preço já é verde, e
   dois verdes empilhados fazem o olho procurar o que está diferente em vez
   de ler o número. */
.resposta.melhor{border-color:var(--ok);box-shadow:0 0 0 1px var(--ok)}
.resposta-cab{display:flex;align-items:center;gap:9px;margin-bottom:9px}
.resposta-cab img.marca{width:30px;height:30px;object-fit:contain;flex:none;
border-radius:6px;background:#fff}
.resposta-cab .bola{width:30px;height:30px;font-size:13px}
/* O nome QUEBRA em duas linhas em vez de virar reticências: com a pastilha
   de status ao lado, "Camilo dos Santos" saía "Camilo do…" — e o cartão
   passava a não dizer de quem era o preço, que é a única coisa que ele
   precisa dizer. */
.resposta-cab b{font-size:13px;min-width:0;flex:1;line-height:1.25;
overflow-wrap:anywhere}
.resposta-cab .pilula{flex:none}
.resposta .preco{font-size:25px;font-weight:700;color:var(--ok);
letter-spacing:-1px;font-variant-numeric:tabular-nums;margin:2px 0}
/* Preço que não é da carga toda perde o verde: o olho compara os números
   grandes antes de ler qualquer aviso, e era assim que R$ 33,29 por volume
   parecia mais barato que R$ 69,91 pela carga. Mesma regra da tela do
   vendedor (web/layout.py, .res .valor.incerto). */
.resposta .preco.incerto{color:var(--fraco)}
.resposta .sem{font-size:14px;font-weight:700;color:#9aa2b1;margin:2px 0}
.resposta .miudos{font-size:11.5px;color:var(--fraco);margin-top:8px;
display:flex;gap:5px;flex-wrap:wrap}
.resposta .miudos span:not(:last-child)::after{content:" ·";color:#c7ccd8}
.resposta .alerta{font-size:11.5px}
/* O texto técnico vem INTEIRO na tela do adm — é ela que existe para
   investigar, e cortar a mensagem no meio esconde justamente a linha que
   explica. Rola dentro da caixa em vez de esticar o cartão: um stack trace
   empurraria o print e os miúdos para fora do campo de visão. */
.resposta .erro-cru{margin-top:8px;max-height:150px;overflow:auto;
font-family:ui-monospace,Consolas,monospace;font-size:11px;line-height:1.45;
color:#5b6478;background:#f7f8fa;border:1px solid var(--borda);
border-radius:8px;padding:8px 10px;white-space:pre-wrap;word-break:break-word}
.resposta .print{margin-top:9px}

/* ---- tempos de resposta ---- */
.tempos{display:flex;flex-direction:column;gap:11px;margin:0}
.tempos .li{display:grid;grid-template-columns:1fr auto;gap:2px 10px;
font-size:12.5px}
.tempos .nome{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
font-weight:600}
.tempos .quanto{color:var(--fraco);font-variant-numeric:tabular-nums}
.tempos .trilho{grid-column:1/-1;height:8px;border-radius:99px;
background:#eef0f5;overflow:hidden}
.tempos .trilho i{display:block;height:100%;border-radius:99px;
animation:cresce .8s cubic-bezier(.22,.9,.3,1) both}

/* ---- lista de WhatsApp aberto ---- */
.abertas{list-style:none;margin:0;padding:0;font-size:12.5px}
.abertas li{display:flex;align-items:center;gap:8px;padding:7px 0;
border-bottom:1px solid #f2f4f7}
.abertas li:last-child{border-bottom:0}
.abertas svg{width:15px;height:15px;flex:none;color:var(--zap)}
.abertas .hora{margin-left:auto;color:var(--fraco);
font-variant-numeric:tabular-nums;font-size:11.5px}

/* ---- ficha dentro do painel ---- */
/* A ficha vem inteira de web/ficha_ui.py, a MESMA que o vendedor vê. Aqui só
   encolhe para caber no cartão do painel, que é mais apertado que a coluna
   de 1080px da tela dele. */
.painel .ficha fieldset{margin-bottom:10px}
.painel .ficha .val{font-size:13px}

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
/* No celular a lista de cotações do alerta desce para baixo do texto em vez
   de espremer as duas colunas: encolhido, o "#49 #50 #51" ficava com um
   número por linha. */
.alerta-linha{flex-wrap:wrap}
.alerta-linha .quais{margin-left:42px;justify-content:flex-start}
}

/* ==================== acabamento da identidade Ventura ======================
   Entra no fim do arquivo de propósito: são regras que ajustam o que já foi
   desenhado acima, e ficam juntas para quem for mexer na marca achar tudo num
   lugar só. O sistema de cores mora em web/layout.py — aqui só se USA. */

/* A mesma assinatura de 3px da faixa do vendedor, agora no alto da lateral.
   É o que faz as duas telas serem reconhecidas como o mesmo sistema: o painel
   tem casco próprio e, sem isto, parecia software de outra empresa. */
.lateral{position:relative}
.lateral::before{content:"";position:absolute;left:0;right:0;top:0;height:3px;
background:var(--marca-grad);z-index:1}

/* Cartão que sobe sob o cursor. Num quadro de instrumentos com onze blocos
   brancos iguais, é o que confirma qual deles o olho está seguindo — e custa
   duas linhas. O `will-change` fica de fora de propósito: onze camadas
   promovidas de graça custam mais memória de vídeo do que a animação
   economiza. */
.cartao{border-radius:var(--raio);box-shadow:var(--sombra-1);
transition:transform .2s var(--suave),box-shadow .2s var(--suave)}
.cartao:hover{transform:translateY(-2px);box-shadow:var(--sombra-2)}

/* O pulso do "ao vivo" ganha um halo em vez de só piscar. Agora que a tela se
   atualiza sozinha, este ponto é a única coisa que diz que ela está viva
   quando nada mudou — e piscar sozinho lê como defeito, não como batimento. */
.aovivo{border-color:var(--borda-forte)}
.aovivo i{animation:pisca 2.2s ease-in-out infinite,halo 2.2s ease-out infinite}
@keyframes halo{
0%{box-shadow:0 0 0 0 rgba(0,120,90,.45)}
70%{box-shadow:0 0 0 7px rgba(0,120,90,0)}
100%{box-shadow:0 0 0 0 rgba(0,120,90,0)}}

/* Pastilha de período: a escolhida ganha uma sombra baixa além do fundo, para
   o estado ler de longe. Antes era só troca de cor, e num monitor fraco as
   quatro pareciam iguais. */
.periodo.atual{box-shadow:0 2px 6px -1px rgba(47,63,136,.45)}
.periodo:hover{background:var(--lavagem);color:var(--marca)}

/* Linha do histórico: o realce de hover passa a ser a lavagem da marca, e não
   um cinza qualquer. A linha inteira é clicável — o fundo precisa dizer isso
   antes de o cursor mudar. */
#historico tr[data-abrir]{cursor:pointer;
transition:background .12s var(--suave)}
#historico tr[data-abrir]:hover td{background:var(--lavagem)}

/* Cabeçalho do dia, na tabela: vira uma faixa da marca em vez de linha solta.
   Com a tabela se atualizando sozinha, o agrupamento por dia é a âncora que
   impede a leitura de se perder quando uma linha nova entra no topo. */
#historico tr.dia td{background:var(--lavagem);color:var(--marca);
font-weight:700;letter-spacing:.2px}

/* A lateral marca o item atual com o ciano da logo. Era um violeta que não
   existe em lugar nenhum da marca — a única cor da tela sem origem. */
.lateral a.atual{border-left-color:var(--ciano-claro)}
.lateral a:focus-visible{outline:2px solid var(--ciano-claro);
outline-offset:-2px}
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
    "voltar": '<path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/>',
    "zap": ('<path d="M21 11.5a8.4 8.4 0 01-9 8.4 8.5 8.5 0 01-4-1L3 21l2.1-5'
            'a8.4 8.4 0 01-1-4 8.5 8.5 0 018.4-8.5h.5a8.5 8.5 0 018 8v.5z"/>'),
    "balanca": ('<path d="M12 3v18"/><path d="M5 7h14"/>'
                '<path d="M5 7l-3 7h6zM19 7l-3 7h6"/>'),
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


def _lateral(base: str = "") -> str:
    """A navegação da esquerda.

    `base` é o que vai na frente da âncora. Vazio no painel — os links são
    âncoras da própria página. Na tela de UMA cotação ele vale "/adm": ali as
    seções não existem, e um `href="#movimento"` que não sai do lugar deixa o
    menu inteiro parecendo quebrado."""
    # `if LOGO`: web/logo_b64.txt pode estar vazio numa pasta recém-clonada, e
    # um src="data:image/png;base64," vira ícone de imagem quebrada bem no
    # canto mais visível da tela.
    marca = (f'<img src="data:image/png;base64,{LOGO}" alt="Ventura">'
             if LOGO else "")
    itens = "".join(
        f'<a href="{base}#{alvo}" data-secao="{alvo}">{_icone(ICONES[chave])}'
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


def pagina_painel(titulo: str, corpo: str, *, base: str = "") -> str:
    """A página inteira do painel. Casco próprio, e não o `pagina()` do
    layout: aquele é uma faixa em cima e uma coluna de 1080px, desenhada para
    formulário. Quadro de instrumentos quer a largura toda e uma navegação
    que fica parada enquanto a tabela rola."""
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title>
<style>{CSS_BASE}{CSS}</style></head><body>
<div class="painel">{_lateral(base)}<main class="conteudo">{corpo}</main></div>
</body></html>"""


def voltar_para(destino: str, rotulo: str) -> str:
    """O caminho de volta, no alto do cabeçalho. Sem ele, quem abriu uma
    cotação a partir do histórico só volta pelo botão do navegador — e quem
    chegou pelo link de um alerta não volta de jeito nenhum."""
    return (f'<a class="voltar" href="{destino}">{_icone(ICONES["voltar"])}'
            f'{e(rotulo)}</a>')


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

def numero(rotulo: str, valor, cor: str, fraca: str, icone: str, *,
           ruim: bool = False, conta: bool = False) -> str:
    """Um dos quadradões do topo.

    `conta=True` marca o número para o JavaScript animar a contagem — só vale
    para inteiro. Um "R$ 1.234,50" com data-conta viraria `Number(...)` NaN e
    o valor sumiria da tela no primeiro quadro da animação."""
    return (
        f'<div class="numero{" ruim" if ruim else ""}" '
        f'style="--cor:{cor};--fraca:{fraca}">'
        f'<div class="ico" style="color:{cor}">{_icone(ICONES[icone])}</div>'
        f'<b{" data-conta" if conta else ""}>{e(valor)}</b>'
        f'<span>{e(rotulo)}</span></div>')


def faixa(resumo: dict) -> str:
    """A faixa ao vivo. Fragmento SEM casco: é ela que o JavaScript troca a
    cada 10s, então nada de <html> aqui dentro.

    O número já vem escrito dentro do elemento. A contagem animada é enfeite
    que o JavaScript aplica UMA vez, no carregamento — se rodasse a cada
    troca, o painel piscaria de zero até o valor a cada 10 segundos, na cara
    de quem está tentando ler."""
    return (
        '<div class="faixa">'
        + numero("cotações hoje", resumo["cotacoes"], "#384890", "#eef3fb",
                 "cotacoes", conta=True)
        + numero("com preço", resumo["com_preco"], "#00875a", "#e6f4ee",
                 "preco", conta=True)
        # O número que mais importa: o vendedor ficou na mão.
        + numero("sem nenhum preço", resumo["sem_nenhum_preco"], "#bf2600",
                 "#fdecea", "alerta", conta=True,
                 ruim=bool(resumo["sem_nenhum_preco"]))
        + numero("cotando agora", resumo["em_andamento"], "#d97706",
                 "#fdf3e3", "relogio", conta=True)
        + "</div>")


def alertas(linhas: list[dict], nome_de) -> str:
    """As transportadoras que estão falhando seguido.

    A parte mais valiosa da tela, e a razão de o painel existir: a Jadlog
    falhou no login em 5 tentativas seguidas e ninguém notou até um vendedor
    reclamar, quase um dia depois.

    Cada alerta traz os NÚMEROS das cotações afetadas, e cada número é um
    link. Sem eles o alerta manda procurar — e procurar dá trabalho o
    bastante para o alerta virar decoração.

    `nome_de` é injetado (web/transportadoras.nome_de) em vez de importado:
    este módulo é só desenho, e o cadastro de quem é quem não é desenho."""
    if not linhas:
        return ""

    itens = ""
    for l in linhas:
        # Só os cinco mais recentes: numa transportadora quebrada há duas
        # semanas, a lista inteira cobriria o alerta seguinte.
        alguns = l["ids"][:5]
        restam = len(l["ids"]) - len(alguns)
        quais = "".join(f'<a href="/adm/cotacao/{i}">#{i}</a>'
                        for i in alguns)
        if restam:
            quais += f'<a href="/adm?falhas=1">+{restam}</a>'
        porque = (f'<p class="porque">{e(l["erro"])}</p>' if l["erro"] else "")
        itens += (
            f'<div class="alerta-linha">'
            f'<span class="sino">{_icone(ICONES["alerta"])}</span>'
            f'<span class="diz"><b>{e(nome_de(l["transportadora"]))} falhou '
            f'nas últimas {l["quantas"]} tentativas.</b>'
            f'<p class="quando">desde {e(dia_e_hora(l["desde"]))} · '
            f'a última foi {e(dia_e_hora(l["ultima"]))}</p>{porque}</span>'
            f'<span class="quais">{quais}</span></div>')
    return f'<div class="alertas">{itens}</div>'


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
<stop offset="0%" stop-color="#70c8e0"/>
<stop offset="100%" stop-color="#384890"/></linearGradient>
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


def roscas_das_transportadoras(linhas: list[dict], nome_de=None) -> str:
    """`nome_de` é injetado (web/transportadoras.nome_de) para o anel dizer
    "Jadlog Entregas" onde o banco guardou "jadlog". Sem ele, cai no slug —
    é o que os testes puros deste arquivo usam, e é melhor do que exigir o
    cadastro inteiro para desenhar um círculo."""
    if not linhas:
        return '<p class="vazio">Nenhuma cotação no período.</p>'

    def quantas(l: dict) -> str:
        # O denominador do aproveitamento, escrito por extenso: sem ele, 100%
        # de uma resposta só parece o mesmo que 100% de cem.
        base = l["sucesso"] + l["recusa"] + l["falha"]
        return f'{l["sucesso"]} de {base} resposta{"" if base == 1 else "s"}'

    quem = nome_de or (lambda slug: slug)
    return '<div class="roscas">' + "".join(
        rosca(l["aproveitamento"], quem(l["transportadora"]), quantas(l))
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


def bola(nome: str) -> str:
    """Só o círculo com a inicial. A cor sai do próprio nome — o mesmo
    vendedor tem sempre a mesma cor, sem tabela de cor por pessoa para
    manter."""
    tom = sum(map(ord, nome)) * 47 % 360
    return (f'<span class="bola" style="background:hsl({tom},42%,45%)">'
            f'{e(nome[:1] or "?")}</span>')


def avatar(nome: str) -> str:
    """A bolinha com o nome ao lado, para a linha do histórico."""
    return f'<span class="eu">{bola(nome)}<span>{e(nome)}</span></span>'


def dia_por_extenso(iso: str) -> str:
    """"2026-09-02" -> "hoje · quarta, 02/09". Hoje e ontem ganham nome
    porque é neles que quem abre o painel está interessado."""
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return iso[:10]
    prefixo = {0: "hoje · ", 1: "ontem · "}.get((date.today() - d).days, "")
    return f"{prefixo}{SEMANA[d.weekday()]}, {d.day:02d}/{d.month:02d}"


def dia_e_hora(iso: str) -> str:
    """"2026-09-02T14:33:07" -> "02/09 às 14:33".

    Dia E hora porque é assim que se conta um alerta: "desde ontem de manhã"
    e "desde ontem às 23h" pedem reações diferentes. Fatiado em vez de
    `fromisoformat`, pelo mesmo motivo do resto do arquivo: `criado_em` é
    TEXTO no banco, e uma linha torta some do rótulo em vez de derrubar a
    tela."""
    if len(iso or "") < 16:
        return iso or ""
    return f"{iso[8:10]}/{iso[5:7]} às {iso[11:16]}"


# ------------------------------------------------- a tela de uma cotação

# O rótulo humano de cada status do banco. A COR não mora aqui: sai de
# `categoria()`, no core, que é de onde a rosca, a pizza e a pastilha também
# tiram a delas.
ROTULO_STATUS = {
    "cotado": "Cotou",
    "aguardando_retorno": "Enviada",
    "recusado": "Recusou",
    "erro": "Falhou",
    "intervencao_necessaria": "Precisa de alguém",
    "interrompido": "Interrompida",
}

# O que dizer no lugar do preço quando não veio preço. A pastilha diz o
# STATUS; esta linha diz o que ele significa para quem procura o número — e
# é ela que ocupa o lugar onde o olho vai procurar o valor.
#
# "sem preço" seco (o padrão) só sobra para status desconhecido: escrito
# embaixo de "Enviada", ele contradizia a própria pastilha, porque a Della
# Volpe e a Generoso mandam o preço por e-mail e não falharam em nada.
SEM_PRECO = {
    "aguardando_retorno": "o preço vem por e-mail",
    "recusado": "o site não cotou",
    "erro": "não retornou preço",
    "intervencao_necessaria": "credencial recusada",
    "interrompido": "fechado no meio",
}


def selo_status(status: str) -> str:
    """A pastilha de status de UMA resposta.

    Status que ninguém previu aparece com o texto CRU do banco em vez de
    sumir — esconder o desconhecido foi como "(nenhuma mensagem visível)"
    nasceu neste projeto."""
    cor = CORES[categoria(status)]
    return (f'<span class="pilula" style="color:{cor};background:{cor}1a">'
            f'{e(ROTULO_STATUS.get(status, status))}</span>')


def marca(logo: str, nome: str) -> str:
    """A logo da transportadora — ou a inicial num círculo quando não há
    arquivo cadastrado. Nunca o ícone de imagem quebrada, que na tela do adm
    parece defeito do sistema e não cadastro faltando."""
    if not logo:
        return bola(nome)
    return f'<img class="marca" src="/logos/{e(logo)}" alt="" loading="lazy">'


def segundos_por_extenso(s: float | None) -> str:
    """25.4 -> "25 s"; 125 -> "2 min 05 s"; None -> "sem dados ainda".

    None é DESCONHECIDO: `respondido_em` é NULL nas linhas anteriores a
    28/08/2026, e escrever "0 s" nelas inventaria a transportadora mais
    rápida do sistema."""
    if s is None:
        return "sem dados ainda"
    if s < 60:
        return f"{s:.0f} s"
    return f"{int(s // 60)} min {int(s % 60):02d} s"


def cartao_resposta(*, nome: str, logo: str, status: str, valor: str = "",
                    incerto: bool = False, melhor: bool = False,
                    avisos: tuple[str, ...] = (), erro_cru: str = "",
                    miudos: tuple[str, ...] = (),
                    print_html: str = "") -> str:
    """O que UMA transportadora respondeu nesta cotação.

    Recebe tudo pronto — `valor` já em moeda, o print já embutido — porque
    formatar dinheiro e ler arquivo do disco não é desenho, e este módulo
    inteiro se testa sem banco e sem disco.

    Sem preço NÃO vira "R$ 0,00" nem célula vazia: vira o travessão com o
    motivo logo abaixo. Zero seria um preço."""
    selo = ('<span class="selo">MAIS BARATO</span>' if melhor else "")
    if valor:
        corpo = (f'<div class="preco{" incerto" if incerto else ""}">'
                 f'{e(valor)} {selo}</div>')
    else:
        corpo = (f'<div class="sem">'
                 f'{e(SEM_PRECO.get(status, "sem preço"))}</div>')
    corpo += "".join(f'<div class="alerta">{e(a)}</div>' for a in avisos)
    if erro_cru:
        corpo += f'<div class="erro-cru">{e(erro_cru)}</div>'
    if miudos:
        corpo += ('<div class="miudos">'
                  + "".join(f"<span>{e(m)}</span>" for m in miudos)
                  + "</div>")
    return (f'<article class="resposta{" melhor" if melhor else ""}">'
            f'<div class="resposta-cab">{marca(logo, nome)}'
            f'<b title="{e(nome)}">{e(nome)}</b>{selo_status(status)}</div>'
            f'{corpo}{print_html}</article>')


def tempos_de_resposta(itens: list[dict]) -> str:
    """Quanto cada transportadora demorou nesta cotação.

    Barra proporcional à MAIS LENTA, e não a um teto fixo: o que a tela
    responde é "quem segurou a cotação", e isso é comparação entre elas.

    Quem não tem hora registrada aparece assim mesmo, com "sem dados ainda"
    no lugar da barra. Sumir da lista faria a transportadora parecer não ter
    sido chamada."""
    medidos = [i["segundos"] for i in itens if i["segundos"] is not None]
    if not itens:
        return '<p class="vazio">Nenhuma resposta ainda.</p>'
    maior = max(medidos) if medidos else 0

    linhas = ""
    for p, i in enumerate(itens):
        s = i["segundos"]
        if s is None:
            barra = '<span class="sem-dado">sem dados ainda</span>'
        else:
            largura = (s / maior * 100) if maior else 0
            barra = (f'<span class="trilho"><i style="width:{largura:.1f}%;'
                     f'background:{i["cor"]};'
                     f'animation-delay:{p * 0.05:.2f}s"></i></span>')
        linhas += (f'<div class="li"><span class="nome">{e(i["nome"])}</span>'
                   f'<span class="quanto">{e(segundos_por_extenso(s))}</span>'
                   f'{barra}</div>')
    return f'<div class="tempos">{linhas}</div>'


def abertas_no_whatsapp(itens: list[dict], nome_de) -> str:
    """Quais conversas o vendedor ABRIU com o texto pronto.

    "Aberta", nunca "enviada": daqui em diante quem age é a pessoa, no
    aplicativo, e disso não chega notícia nenhuma. A tela do adm precisa
    dizer isso com todas as letras — senão o alerta vira "a transportadora
    não respondeu" quando a mensagem talvez nem tenha saído."""
    if not itens:
        return ('<p class="vazio">Nenhuma conversa de WhatsApp foi aberta '
                'nesta cotação.</p>')
    linhas = "".join(
        f'<li>{_icone(ICONES["zap"])}'
        f'<span>{e(nome_de(i["transportadora"]))}</span>'
        f'<span class="hora">{e(dia_e_hora(i["aberto_em"]))}</span></li>'
        for i in itens)
    return f'<ul class="abertas">{linhas}</ul>'
