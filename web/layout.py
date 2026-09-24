"""O casco visual compartilhado: logo, CSS, escape e a moldura da página.

Vive fora de web/app.py porque web/adm.py precisa das mesmas peças, e
web/app.py registra as rotas do adm — um importar o outro seria circular.

Nada aqui conhece banco, cotação ou transportadora. É só desenho."""

from __future__ import annotations

import base64
import html
from decimal import Decimal
from pathlib import Path

# As peças da marca, servidas por /marca (montado em web/app.py). Endereço, e
# não base64: as três somam ~110 KB e não cabem dentro de cada página, como
# cabiam os 26 KB da logo antiga.
#
# Todas têm o fundo VAZADO e letras PRATEADAS — feitas para fundo escuro. No
# claro as letras somem, e é por isso que o CSS põe a placa marinha atrás
# (`.marca-placa`). Ver o bloco "a marca" no CSS.
MARCA_COMPACTA = "/marca/lockup-compacto.png"        # fundo escuro
# A MESMA peça com o prateado virado tinta escura. Duas artes, e não um
# filtro: sobre branco o prateado #f0f0f0 dá 1.1:1, e a placa preta que
# resolvia isso cortava a página clara ao meio.
MARCA_COMPACTA_CLARA = "/marca/lockup-compacto-claro.png"
MARCA_SIMBOLO = "/marca/simbolo-web.png"        # lateral do painel

# O ícone da aba do navegador. Serve o mesmo PNG do símbolo, que tem canal
# alfa — então o V azul fica legível tanto na aba clara quanto na escura, sem
# um quadrado branco em volta.
#
# Sem favicon.ico: nenhum navegador atual precisa dele, e um arquivo a mais
# seria outro lugar para a marca sair de sincronia quando ela mudar. O
# `sizes="any"` autoriza o navegador a redimensionar este à vontade.
ICONE_ABA = (f'<link rel="icon" type="image/png" sizes="any" '
             f'href="{MARCA_SIMBOLO}">')

# A assinatura ("todos os produtos num só lugar") NÃO vem em imagem em lugar
# nenhum: dentro do lockup ela ocupa 6px de 120, e só fica legível a partir
# de ~180px de altura da peça inteira — altura que tela nenhuma do sistema
# tem. Onde ela aparece, aparece como TEXTO: legível em qualquer tamanho,
# selecionável, e acompanha o tema.
ASSINATURA = "Todos os produtos num só lugar"


CSS = """
/* ============================ identidade Ventura =============================
   Toda cor sai da MARCA, medida pixel a pixel em web/marca/: matiz 218
   graus, saturação 100%, de #002472 a #3096fc, com prateado #f0f0f0.

   Os tons abaixo não são amostras soltas da imagem: são DERIVADOS nessa
   matiz, com a luminosidade escolhida pelo contraste que cada um precisa ter
   contra o fundo em que é usado. A conta vem antes da cor — foi escrevendo
   primeiro e medindo depois que a versão anterior desta paleta deixou dois
   pares abaixo do mínimo sem ninguém perceber.

   Não há ciano nenhum. A paleta anterior vinha da logo velha (elipse ciano
   #70c8e0 → índigo #384890, matiz 230 a 49% de saturação) e o ciano não
   existe no desenho atual da empresa; os tokens que o guardavam chamam-se
   agora --realce e --realce-claro.

   Neutros puxados para o azul de propósito. Cinza neutro (#6b7280) ao lado de
   um índigo saturado parece sujo; o mesmo cinza com um empurrão de azul lê
   como escolha. */
:root{
/* marca */
--marca:#003fb0;--marca-forte:#002f85;--marca-viva:#0f56e0;
--realce:#0047c4;--realce-claro:#3d84ff;--lavagem:#e9f0fe;
--marca-grad:linear-gradient(135deg,#3d84ff 0%,#0f56e0 45%,#003fb0 100%);
/* neutros com viés azul */
--tinta:#0c1526;--tinta2:#39465c;--fraco:#59667e;
--borda:#dce3ef;--borda-forte:#bdc8dc;--fundo:#f2f5fa;--papel:#fff;
/* semânticos: sentido, não marca — mudar estes muda o que a tela AFIRMA */
--ok:#00785a;--erro:#bf3320;--atencao:#96560a;--zap:#25d366;
--ok-fraco:#e4f3ee;--erro-fraco:#fdeae6;--atencao-fraco:#fff8e3;
--atencao-borda:#ffe380;--atencao-tinta:var(--tinta);
--sobre-marca:#fff;--cova:#f6f8fc;
--brilho-marca:rgba(0,63,176,.42);
/* Os tons do quadro de instrumentos. Moram aqui, e não no CSS do
   painel, porque quem os ESCREVE é o Python (o número do topo sai com
   `style="--cor:..."`), e hexadecimal escrito pelo servidor não muda
   quando a pessoa clica no botão de tema. Token muda. */
--tom-marca:#0042b5;--tom-marca-fraco:#eaf1fd;
--tom-ok:#00785a;--tom-ok-fraco:#e6f4ee;
--tom-atencao:#a15c00;--tom-atencao-fraco:#fdf3e3;
--tom-erro:#bf2600;--tom-erro-fraco:#fdecea;
--tom-neutro:#5f6675;--tom-neutro-fraco:#eef0f4;
--tom-roxo:#7c3aed;--tom-roxo-fraco:#f1eafe;
--alerta-fundo:#fff6f4;--alerta-borda:#ffd5cc;--alerta-tinta:#7a3b2e;
/* ---- tipografia -----------------------------------------------------------
   Três famílias, nenhuma baixada da internet: o sistema roda em rede interna
   e fonte que não chegou é a página inteira remontando na cara de quem lê.
   O que muda é a ESCOLHA dentro do que a máquina já tem.

   A de título pede a Segoe UI Variable Display, o corte que a Microsoft
   desenhou justamente para tamanho grande: contraste maior, espaço entre
   letras menor. A de texto pede o corte Text, desenhado para 12-16px. Nas
   máquinas antigas as duas caem na Segoe UI de sempre e nada piora.

   A MONOESPAÇADA é a mudança que mais se vê. Preço, peso, prazo e os números
   do painel saem nela: o rótulo vira uma coisa, o valor vira outra, e a
   coluna de dinheiro alinha por desenho e não por sorte. `tabular-nums`
   sozinho alinha, mas não separa rótulo de valor — e separar é metade do
   trabalho de um quadro de instrumentos. */
--fonte:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,
        "Helvetica Neue",Arial,sans-serif;
--fonte-titulo:"Segoe UI Variable Display","Segoe UI",system-ui,-apple-system,
        "Helvetica Neue",Arial,sans-serif;
--fonte-num:"Cascadia Mono",ui-monospace,"Segoe UI Mono",Consolas,
        "SF Mono",monospace;
/* A escala. Razão ~1.22 nos tamanhos de leitura e um salto maior nos de
   display, que é onde o contraste de tamanho precisa aparecer de longe.
   Os dois maiores são fluidos: num celular de 390px um título de 40px come
   três linhas antes de o texto começar. */
--t-micro:10.5px;--t-mini:11.5px;--t-p:12.5px;--t-base:13px;--t-m:14px;
--t-g:16px;--t-gg:clamp(20px,1rem + .8vw,24px);
--t-display:clamp(25px,1.1rem + 2vw,34px);
/* Entrelinha: 1.5 no texto corrido, 1.25 no que é rótulo, 1.08 no display —
   título grande com entrelinha de parágrafo lê como duas frases soltas. */
--ent:1.55;--ent-curta:1.3;--ent-display:1.08;
/* O espaçamento entre letras. Positivo no que é RÓTULO (versalete curto só
   fica legível espaçado) e negativo no display (a Segoe abre demais em 40px). */
--letra-rotulo:.09em;--letra-display:-.028em;
/* ---- espaço -------------------------------------------------------------
   Escala de 4px. Existia como número solto em cada regra: 11px aqui, 13px
   ali, 9px na do lado — e o resultado é uma tela onde nada se alinha a nada.
   Estes oito degraus são o ritmo da página inteira. */
--e1:4px;--e2:8px;--e3:12px;--e4:16px;--e5:22px;--e6:30px;--e7:44px;--e8:64px;
/* A coluna de leitura. Era 1080px; num monitor grande sobrava tanta margem
   que a página parecia um documento perdido no meio da tela. */
--coluna:1160px;
/* O anel de foco, num token só. Estava escrito à mão em quatro regras, cada
   uma com um rgba() diferente — e foco é a peça que mais aparece para quem
   trabalha no teclado. */
--anel:0 0 0 3px rgba(61,132,255,.38);
/* elevação: três degraus, e não sombra solta por regra. Borda de 1px em tudo
   achata a hierarquia — quem precisa se destacar sobe, o resto fica no plano */
--sombra-1:0 1px 2px rgba(12,21,38,.05),0 1px 3px rgba(12,21,38,.045);
--sombra-2:0 2px 4px rgba(12,21,38,.04),0 12px 26px -10px rgba(12,21,38,.16);
--sombra-3:0 22px 52px -14px rgba(12,21,38,.3);
/* `--sombra` e `--sombra2` sem hífen ficaram escritos em web/painel_ui.py
   (`.numero`, `.painel .cartao`) e nunca existiram aqui: `var()` sem valor
   descarta a propriedade inteira, então os cartões do painel estavam SEM
   sombra nenhuma desde que o casco dele virou arquivo próprio. Os apelidos
   custam duas linhas e consertam a elevação de onze cartões. */
--sombra:var(--sombra-1);--sombra2:var(--sombra-2);
/* Raios maiores, e uma escala de verdade: 6/10/14/20. O sistema tinha 12px
   em tudo — cartão, campo e pílula com o mesmo canto achatam a hierarquia. */
--raio-pp:6px;--raio-p:10px;--raio:14px;--raio-g:20px;
--suave:cubic-bezier(.2,.6,.3,1);--mola:cubic-bezier(.34,1.32,.46,1);
--lento:cubic-bezier(.16,.84,.44,1)}
/* ========================== o mesmo sistema, no escuro ======================
   Segundo conjunto de tokens, ligado por um atributo no <html>. Não é um
   tema "do painel": é do SISTEMA, e por isso mora aqui, junto do claro, e
   não no CSS de uma tela só. Quem escolhe é a pessoa, no botão do cabeçalho.

   O padrão de cada casco continua o que era: o vendedor abre claro, o painel
   abre escuro. Quem nunca mexer no botão não vê diferença nenhuma.

   As razões de contraste saíram da fórmula da WCAG ANTES de a regra ser
   escrita: 4.5:1 para texto, 3:1 para o que é gráfico e carrega sentido
   (SC 1.4.11). O pior caso de cada grupo está anotado na frente. */
html[data-tema="escuro"]{
/* No escuro a marca é o azul CLARO — #5291ff, a ponta viva do gradiente do
   "V" — e não o azul cheio: #0042b5 sobre #111e34 dá 1.9:1, e a cor da marca
   estaria na tela sem ninguém ver. O azul cheio continua sendo marca, mas
   como FUNDO: a lateral do painel, o filete do topo. */
--marca:#5d97ff;--marca-forte:#8ab6ff;--marca-viva:#0f56e0;
--realce:#5d97ff;--realce-claro:#82b0ff;--lavagem:#1a2740;
--anel:0 0 0 3px rgba(93,151,255,.42);
/* O que se escreve EM CIMA de um preenchimento da marca. Herdar o #fff do
   claro daria 2.6:1 sobre o azul claro: o botão sumiria por dentro. */
--sobre-marca:#061021;
/* neutros: 14.4:1, 10.1:1 e 6.8:1 sobre o cartão */
--tinta:#e8ebf2;--tinta2:#bfc7d6;--fraco:#97a3b9;
--borda:#2a3c58;--borda-forte:#445b82;--fundo:#050c1a;--papel:#101b30;
/* Um degrau ABAIXO do papel, para o que é buraco e não cartão: campo de
   digitar, caixa de texto técnico, ficha dentro do cartão. No claro esse
   papel é o próprio branco e o buraco se faz com borda; no escuro é a
   luminância que separa, então o buraco precisa existir como cor. */
--cova:#08121f;
/* Semânticos: o SENTIDO é o mesmo, só a luminância sobe. Verde 8.4:1, âmbar
   7.8:1, vermelho 7.5:1 sobre o cartão — contra 3.7, 5.2 e 2.8 que as cores
   claras dariam aqui. O vermelho de falha, no escuro, era ilegível. */
--ok:#3fd394;--erro:#ff9279;--atencao:#e8a94e;
/* As lavagens de cada semântico: o fundo das pílulas e dos avisos. */
--ok-fraco:#112a24;--erro-fraco:#2c1e1d;--atencao-fraco:#2a2312;
--atencao-borda:#5c4a1c;--atencao-tinta:#e8cf9a;
--brilho-marca:rgba(93,151,255,.5);
/* Os mesmos tons, com a luminância que o fundo escuro exige. O pior é
   o roxo, com 6.1:1 sobre o cartão; no claro o vermelho de falha dava
   2.8:1 aqui e não passava nem como gráfico (SC 1.4.11). */
--tom-marca:#5d97ff;--tom-marca-fraco:#17253d;
--tom-ok:#3fd394;--tom-ok-fraco:#112a24;
--tom-atencao:#e8a94e;--tom-atencao-fraco:#2a2416;
--tom-erro:#ff9279;--tom-erro-fraco:#2c1e1d;
--tom-neutro:#97a3b9;--tom-neutro-fraco:#1d253d;
--tom-roxo:#a98cfb;--tom-roxo-fraco:#222645;
--alerta-fundo:#281917;--alerta-borda:#5a2f26;--alerta-tinta:#e0ab9c;
/* No escuro sombra não separa nada: quem separa é o degrau de luminância
   entre #0b0f1c e #161d33. A sombra fica só para dizer o que está POR CIMA
   quando o cursor levanta um cartão. */
--sombra-1:0 1px 2px rgba(0,0,0,.45);
--sombra-2:0 12px 30px -10px rgba(0,0,0,.62);
--sombra-3:0 24px 54px -14px rgba(0,0,0,.78);
/* Diz ao NAVEGADOR que a página é escura, para ele pintar de escuro o que
   desenha sozinho: barra de rolagem, cursor de texto, caixa de seleção. Sem
   isto a barra de rolagem branca era a coisa mais clara da tela. */
color-scheme:dark}

/* ---- o que ficou cravado em claro quando o sistema só tinha um tema -------
   Token nenhum alcança um `#fffae6` escrito dentro de uma regra. São estes,
   e ficam juntos para quem for mexer no tema achar num lugar só, em vez de
   caçar um fundo branco perdido no meio do arquivo. */
[data-tema="escuro"] fieldset{background:#13203a}
[data-tema="escuro"] input,[data-tema="escuro"] .pronto{
background:var(--cova);color:var(--tinta)}
[data-tema="escuro"] input:hover,[data-tema="escuro"] .opcao:hover{
border-color:var(--borda-forte)}
[data-tema="escuro"] .opcao:hover{background:var(--lavagem)}
[data-tema="escuro"] td{border-bottom-color:var(--borda)}

/* O aviso amarelo. No escuro ele herdava a tinta clara dentro de um #fffae6:
   texto quase branco sobre papel quase branco. */
[data-tema="escuro"] .alerta,[data-tema="escuro"] .aviso,
[data-tema="escuro"] .filtro.parcial{background:var(--atencao-fraco);
border-color:var(--atencao-borda);color:var(--atencao-tinta)}
[data-tema="escuro"] .filtro.parcial>summary{color:var(--atencao-tinta)}
[data-tema="escuro"] .filtro.parcial>summary:hover{background:#3a2f16}
[data-tema="escuro"] .alerta.email{background:var(--lavagem);
border-color:var(--borda-forte);color:var(--tinta2)}
[data-tema="escuro"] .selo-obs{background:var(--atencao-fraco);
border-color:var(--atencao-borda)}

/* Texto escrito EM CIMA de um preenchimento: o #fff do claro dá 1.7:1 sobre
   o verde e 2.6:1 sobre o azul claro da marca. */
[data-tema="escuro"] .selo{color:#08130f}
/* `:not(.tema)` porque esta regra fala de texto sobre PREENCHIMENTO da
   marca, e o botão de tema não tem preenchimento nenhum — ele é um contorno
   sobre o papel. Sem o `:not`, o seletor com atributo (0,1,1) ganhava do
   `.tema` (0,1,0) e pintava o ícone do sol de #0b0f1c, que é a cor do fundo
   da página: o sol ficava desenhado em preto sobre preto, presente na tela e
   invisível para quem olha. */
/* `:not(.botao2)` pelo mesmo motivo: o botão secundário é contorno sobre o
   papel, com o texto na cor da marca. Sem ele, a regra pintava o texto de
   #061021 sobre o papel #101b30 (1.1:1) — "Reler itens do ME", "Testar sem
   salvar", "Marcar como enviada"... todos presentes e ilegíveis (print do
   usuário, 24/09/2026). */
[data-tema="escuro"] button:not(.tema):not(.botao2){color:var(--sobre-marca)}
[data-tema="escuro"] .selo-zap{background:var(--ok-fraco)}
[data-tema="escuro"] .zap.aberta{background:#13203a;border-color:#22503b}

/* A tabela do resultado. O verde da linha vencedora vira um verde de FUNDO
   escuro: no claro ele é uma lavagem, e lavagem clara no escuro é um rasgo
   branco no meio da tabela. */
[data-tema="escuro"] table.resultados th{background:#15233d}
[data-tema="escuro"] tr.r.melhor td{background:#112a23}
[data-tema="escuro"] tr.r.melhor:hover td{background:#16352c}
[data-tema="escuro"] tr.r-extra td{background:#0d1728}
[data-tema="escuro"] .estado-ok{background:var(--ok-fraco)}
[data-tema="escuro"] .estado-recusa{background:var(--atencao-fraco)}
[data-tema="escuro"] .estado-falha{background:var(--erro-fraco)}

/* As logos das TRANSPORTADORAS continuam em chip branco nos dois temas:
   são arte de terceiro, uma por transportadora, e não há negativa delas.
   A da Ventura resolve-se com a placa — ver o bloco "a marca". */

/* ---- o botão que troca ---------------------------------------------------
   Fica no cabeçalho das duas telas. Um botão, e não um seletor de três
   opções com "seguir o sistema": quem quer trocar já sabe para onde, e um
   terceiro estado é mais uma coisa para explicar num sistema usado por quem
   está com pressa. */
.tema{display:inline-flex;align-items:center;justify-content:center;
width:34px;height:34px;padding:0;flex:none;border-radius:99px;
background:var(--papel);color:var(--fraco);border:1px solid var(--borda);
box-shadow:none;cursor:pointer;
transition:color .16s var(--suave),border-color .16s var(--suave),
background .16s var(--suave)}
.tema:hover{color:var(--marca);border-color:var(--marca-forte);
background:var(--lavagem);transform:none;box-shadow:none}
.tema svg{width:17px;height:17px;display:block}
/* Cada tema mostra o ícone do que a pessoa VAI receber, e não do que já tem:
   um sol numa tela que já está clara não diz o que o botão faz. */
.tema .p-sol{display:none}
[data-tema="escuro"] .tema .p-sol{display:block}
[data-tema="escuro"] .tema .p-lua{display:none}

*{box-sizing:border-box}
body{margin:0;background:var(--fundo);color:var(--tinta);
line-height:var(--ent);font-family:var(--fonte);
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
/* O sistema é uma tela de números: peso, cubagem, preço. Dígito de largura
   fixa faz as colunas de dinheiro alinharem sem tabela e sem monoespaçada. */
font-variant-numeric:tabular-nums}
a{color:var(--marca)}
/* Texto selecionado na cor da casa. Custa uma linha e é das poucas coisas
   que o navegador pinta sozinho na tela inteira. */
::selection{background:var(--lavagem);color:var(--marca-forte)}
/* O fundo da página é chapado desde sempre. Duas manchas de luz muito baixas,
   fixas no topo, dão a ele a mesma profundidade que a tela de entrada tem —
   sem imagem nenhuma e sem atrapalhar a leitura do que vem por cima. */
body::before{content:"";position:fixed;inset:0 0 auto;height:420px;z-index:-1;
pointer-events:none;
background:
 radial-gradient(60% 100% at 12% 0%,rgba(61,132,255,.09),transparent 70%),
 radial-gradient(48% 100% at 88% 0%,rgba(15,86,224,.06),transparent 72%)}

/* Movimento é enfeite até virar obstáculo. Quem pediu para o sistema parar de
   se mexer não pode receber um formulário que entra deslizando. Uma regra, no
   topo, valendo para todas as telas — inclusive as do painel, que empilha
   o seu CSS depois deste. */
@media(prefers-reduced-motion:reduce){
*,*::before,*::after{animation-duration:.01ms !important;
animation-iteration-count:1 !important;transition-duration:.01ms !important;
scroll-behavior:auto !important}}

/* ---- pular para o conteúdo ----
   Primeiro foco da página, e invisível até receber foco. A faixa do topo tem
   cinco links; sem isto, quem navega pelo teclado atravessa os cinco em toda
   tela antes de chegar no formulário. */
.pular{position:absolute;left:var(--e4);top:-100px;z-index:60;
background:var(--marca);color:var(--sobre-marca);padding:10px 16px;
border-radius:var(--raio-p);font-size:var(--t-p);font-weight:600;
text-decoration:none;transition:top .16s var(--suave)}
.pular:focus{top:var(--e2)}

/* ---- faixa do topo ---- */
/* Gruda no topo. A faixa tem a navegação inteira do vendedor, e numa tela de
   resultado com sete transportadoras ela some da vista na primeira rolada —
   voltar para "nova cotação" virava rolar a página inteira de volta.
   `backdrop-filter` para o conteúdo passar por baixo dela borrado em vez de
   bater numa barra opaca; onde não houver suporte, fica o fundo sólido. */
.topo{background:color-mix(in srgb,var(--papel) 86%,transparent);
backdrop-filter:saturate(1.6) blur(12px);
-webkit-backdrop-filter:saturate(1.6) blur(12px);
border-bottom:1px solid var(--borda);position:sticky;top:0;z-index:30;
padding:var(--e3) var(--e5);display:flex;align-items:center;gap:var(--e4)}
/* O filete do gradiente da logo, atravessando a tela inteira. É a assinatura
   da marca no lugar mais barato possível: 3px que nenhuma outra tela de
   sistema interno tem, e que ninguém precisa ler para reconhecer. */
.topo::before{content:"";position:absolute;left:0;right:0;top:0;height:3px;
background:var(--marca-grad)}
.topo img{height:38px}
.topo .quem{margin-left:auto;font-size:var(--t-p);color:var(--fraco);
display:flex;align-items:center;gap:var(--e3)}
/* O nome de quem está logado vira pastilha: era um <b> solto ao lado dos
   links, e num cabeçalho de seis itens nada dizia qual deles era a pessoa. */
.topo .quem>b{font-weight:600;color:var(--tinta2);background:var(--cova);
border:1px solid var(--borda);border-radius:99px;padding:5px 12px;
font-size:var(--t-mini);white-space:nowrap}
.wrap{max-width:var(--coluna);margin:var(--e6) auto var(--e7);
padding:0 var(--e5)}

/* Entrada em cascata. O formulário tem cinco blocos; todos aparecendo no
   mesmo quadro é um susto, escalonados o olho acompanha de cima para baixo. */
/* Nome com sufixo: web/painel_ui.py empilha o CSS dele depois
   deste e ja tem um @keyframes `sobe` proprio, das barras do
   grafico. Dois com o mesmo nome na mesma folha e o de baixo
   ganha em silencio. */
@keyframes sobe-bloco{from{opacity:0;transform:translateY(10px)}
to{opacity:1;transform:none}}
.cartao{background:var(--papel);border:1px solid var(--borda);
border-radius:var(--raio);padding:var(--e5) var(--e5) var(--e5);
margin-bottom:var(--e4);
box-shadow:var(--sombra-1);animation:sobe-bloco .42s var(--suave) both}
/* ---- a escala dos títulos --------------------------------------------------
   Três níveis e só. O sistema tinha um <h1> de 24px e <h2> escritos à mão com
   `style="font-size:15px"` em cinco lugares — que é o jeito de ter cinco
   escalas diferentes sem ninguém decidir nenhuma. */
h1{font-family:var(--fonte-titulo);font-size:var(--t-gg);margin:0 0 var(--e1);
letter-spacing:var(--letra-display);font-weight:700;
line-height:var(--ent-display)}
h2{font-family:var(--fonte-titulo);font-size:var(--t-g);
letter-spacing:-.018em;line-height:var(--ent-curta)}
.sub{color:var(--fraco);font-size:var(--t-base);margin:0 0 var(--e5);
max-width:72ch;line-height:var(--ent)}
fieldset{border:1px solid var(--borda);border-radius:var(--raio-p);
margin:0 0 var(--e4);padding:var(--e4) var(--e4) var(--e5);
background:var(--cova)}
/* A legenda sai de cima da borda e vira um RÓTULO de seção, alinhado à
   esquerda com o resto do bloco. Cavalgando a linha ela é um adorno de
   formulário de 2004; encostada no conteúdo ela agrupa. */
legend{font-size:var(--t-micro);font-weight:700;color:var(--marca);
padding:0 var(--e2) 0 0;text-transform:uppercase;
letter-spacing:var(--letra-rotulo);margin-left:-2px}
.grid{display:grid;gap:var(--e3) var(--e4);
grid-template-columns:repeat(auto-fit,minmax(168px,1fr))}
label{display:block;font-size:var(--t-mini);color:var(--tinta2);
margin-bottom:var(--e1);font-weight:600;letter-spacing:.012em}
input{width:100%;padding:11px 13px;border:1px solid var(--borda-forte);
border-radius:var(--raio-p);font-size:var(--t-base);font-family:inherit;
background:var(--papel);color:var(--tinta);
transition:border-color .16s var(--suave),box-shadow .16s var(--suave)}
input:hover{border-color:var(--fraco)}
/* O azul de realce da marca: o anel de foco é a peça que mais aparece
   num sistema onde se digita o dia inteiro, e era o contorno cinza do
   navegador. */
input:focus{outline:0;border-color:var(--realce);box-shadow:var(--anel)}
/* Campo de número escrito na monoespaçada da casa: CEP, CNPJ, peso e medida
   são exatamente os campos em que um dígito a mais passa despercebido, e é a
   largura fixa que faz a falta aparecer. */
input[inputmode="numeric"],#cep_origem,#cep_destino,#cnpj_remetente,
#cnpj_destinatario,#peso,#quantidade,#comprimento,#largura,#altura,#valor_nf{
font-family:var(--fonte-num);letter-spacing:.01em;font-size:13.5px}
button{font:inherit;cursor:pointer;border:0;border-radius:var(--raio-p);
background:var(--marca);color:#fff;padding:13px 26px;font-weight:600;
font-size:var(--t-m);letter-spacing:.005em;
/* O brilho da marca embaixo do botão, e não uma sombra cinza. É o único
   elemento cheio da tela — a sombra dele pode dizer de que cor ele é. */
box-shadow:0 1px 2px rgba(12,21,38,.18),0 10px 22px -10px var(--brilho-marca);
transition:transform .16s var(--mola),box-shadow .16s var(--suave),
background .16s var(--suave)}
button:hover{background:var(--marca-forte);transform:translateY(-1px);
box-shadow:0 2px 4px rgba(12,21,38,.2),0 16px 30px -12px var(--brilho-marca)}
/* Afunda no clique. Num formulário que dispara cinco navegadores e leva dois
   minutos, o retorno imediato do botão é o que diz "recebi" antes de a
   primeira transportadora responder. */
button:active{transform:translateY(1px);box-shadow:var(--sombra-1)}
/* Desabilitado tem que PARECER desabilitado e continuar legível. Antes o
   botão travado era idêntico ao ativo, e o campo travado ficava no cinza do
   navegador (1.8:1 no escuro). Tudo em token: vale para os dois temas. */
button:disabled,button:disabled:hover{background:var(--borda-forte);color:var(--tinta);
box-shadow:none;transform:none;cursor:not-allowed}
[data-tema="escuro"] button:disabled:not(.tema):not(.botao2){color:var(--tinta)}
.botao2:disabled,.botao2:disabled:hover{background:var(--papel);color:var(--fraco);
border-color:var(--borda);border-style:dashed}
:is(input,select,textarea):disabled{background:var(--cova);color:var(--fraco);
border-color:var(--borda);opacity:1;cursor:not-allowed}
/* UM anel de foco para tudo que recebe teclado, e não só para botão, link e
   summary. A lista curta deixava de fora `<input type=checkbox>` (as vinte
   caixas do filtro de transportadoras), `<textarea>`, `[tabindex]` e as
   linhas clicáveis do histórico: quem navega pelo teclado atravessava o
   filtro inteiro sem enxergar onde estava. */
:is(button,a,summary,select,textarea,[tabindex],input[type="checkbox"],
input[type="radio"],input[type="search"],input[type="password"]):focus-visible{
outline:2px solid var(--realce);outline-offset:2px;border-radius:var(--raio-pp)}

.falhou{color:var(--erro);font-size:13px;font-weight:600}
/* "Enviada" NAO pode usar o vermelho de falha nem o verde de preco: nao deu
   errado e nao ha numero para comparar. Fica na cor da marca, no tamanho que
   ocupa o lugar do preco - o olho passa pelos cartoes procurando o numero
   grande, e precisa parar aqui em vez de saltar. */
.enviada{color:var(--marca);font-size:20px;font-weight:700;margin:6px 0 2px}
.selo{display:inline-block;font-size:9.5px;font-weight:700;color:#fff;
background:var(--ok);border-radius:99px;padding:3px 9px;
letter-spacing:var(--letra-rotulo);text-transform:uppercase;
vertical-align:1px}
.zap{display:flex;align-items:center;gap:var(--e3);
border:1px solid var(--borda);border-radius:var(--raio);
padding:12px 14px;text-decoration:none;position:relative;overflow:hidden;
color:inherit;margin-bottom:var(--e2);background:var(--papel);
transition:border-color .16s var(--suave),transform .16s var(--suave),
box-shadow .16s var(--suave)}
/* Filete verde que cresce da esquerda sob o cursor. É a mesma gramática do
   sublinhado do menu e do filete do topo: a decoração do sistema é sempre
   uma linha que nasce e cresce, nunca um fundo que acende. */
.zap::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
background:var(--zap);transform:scaleY(0);transform-origin:center;
transition:transform .18s var(--suave)}
.zap:hover::before{transform:scaleY(1)}
.zap:hover{border-color:var(--zap);transform:translateX(2px);
box-shadow:var(--sombra-2)}
/* Já aberta: fica apagada para o olho cair na próxima da lista sozinho, sem
   precisar de seta nem de "next". O visto verde diz que passou por ali. */
.zap.aberta{background:#f7f9fb;border-color:#d6ecdc}
.zap.aberta:hover{transform:none}
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
  border-radius:var(--raio-p);background:#fff}
.zap .ir{margin-left:auto;background:var(--zap);color:#07301f;
border-radius:var(--raio-p);padding:8px 13px;font-size:13px;font-weight:600}
/* Especialidade da transportadora — cor diferente de tudo no cartão de
   propósito, para o olho parar aí antes de decidir para quem manda. */
.selo-obs{display:inline-block;font-size:10px;font-weight:700;
color:var(--atencao);background:#fff4e2;border:1px solid #ffd699;
border-radius:99px;padding:2px 9px;letter-spacing:.2px;margin-left:4px}
/* A Della Volpe fica sozinha no cartão "Semiautomática", e o botão maior é o
   que diz "comece por aqui" sem precisar de mais nenhuma frase. */
.zap-dv{padding:16px 18px;margin-bottom:0;border-color:var(--zap)}
.zap-dv .marca{width:60px;height:60px}
.zap-dv b{font-size:16px}
.zap-dv .ir{font-size:14px;padding:11px 19px}
table{width:100%;border-collapse:collapse;font-size:var(--t-p)}
th{text-align:left;font-size:var(--t-micro);color:var(--fraco);
text-transform:uppercase;letter-spacing:var(--letra-rotulo);
padding:10px var(--e2);border-bottom:1px solid var(--borda-forte);
font-weight:700}
td{padding:11px var(--e2);border-bottom:1px solid var(--borda)}
tr:hover td{background:var(--lavagem)}
.listaerro{margin:0 0 16px;padding-left:20px;font-size:14px}
.listaerro li{margin-bottom:6px}
.cotando{display:flex;align-items:center;gap:10px;color:var(--fraco);
font-size:13px}
.girando{width:16px;height:16px;border:2px solid var(--borda);
border-top-color:var(--realce);border-radius:50%;
animation:gira .8s linear infinite}
@keyframes gira{to{transform:rotate(360deg)}}
/* Enquanto a transportadora não respondeu, a LINHA fica com um brilho que
   atravessa devagar. Diz "vivo, esperando" sem ocupar espaço com texto — e a
   Della Volpe leva ~110s, que é muito tempo olhando para uma linha parada.

   Ligado por `:has(.cotando)`, o estado que web/app.py já monta, e não por
   uma classe que alguém precise lembrar de escrever. */
@keyframes brilho{to{background-position:200% 0}}
tr.r:has(.cotando) td{background:linear-gradient(100deg,var(--papel) 38%,
var(--lavagem) 50%,var(--papel) 62%);background-size:200% 100%;
animation:brilho 2.2s var(--suave) infinite}
/* Aviso e alerta passam a ter a BARRA à esquerda em vez de só fundo amarelo.
   Num cartão branco o amarelo chapado lê como decoração; a barra lê como
   marcação de margem, que é o que ele é. */
.aviso{background:var(--atencao-fraco);border:1px solid var(--atencao-borda);
border-left:3px solid var(--atencao);
border-radius:var(--raio-pp) var(--raio-p) var(--raio-p) var(--raio-pp);
padding:12px 14px;font-size:var(--t-base);margin-bottom:var(--e4);
color:var(--atencao-tinta)}
.print{width:100%;margin-top:10px;border:1px solid var(--borda);
border-radius:var(--raio-p);cursor:zoom-in;transition:box-shadow .16s}
.print:hover{box-shadow:var(--sombra-2)}
/* ---- lupa do comprovante ----
   O diálogo modal vive na CAMADA DE TOPO do navegador: fica acima de todo o
   documento sem precisar de z-index, e — o que importa aqui — não se ancora
   em ancestral com `transform`. O zoom antigo era `position:fixed` na própria
   imagem, e abria preso dentro do cartão, por cima do texto: todo cartão
   carrega um `transform` identidade, deixado pela animação de entrada com
   `fill-mode:both`. Ver o comentário de LUPA, mais abaixo neste arquivo.

   Largura de leitura, e não "caber na tela": o comprovante é para ser LIDO —
   o vendedor explica a composição do frete ao cliente a partir dele. Encolher
   um print de 1100x1700 até caber em 900px de altura deixaria a letra menor
   que na miniatura. Aqui ele abre na largura cheia e rola dentro do diálogo. */
.lupa{border:0;padding:0;background:transparent;
width:min(1180px,94vw);max-height:92vh;overflow:auto;overscroll-behavior:contain;
border-radius:var(--raio);box-shadow:var(--sombra-3)}
.lupa::backdrop{background:rgba(16,22,35,.72)}
.lupa img{display:block;width:100%;height:auto;background:#fff;cursor:zoom-out}
/* Entrada curta. O `::backdrop` escurece junto — sem isso o comprovante
   aparece de estalo sobre a página clara e o olho perde onde ele nasceu.
   A regra global de prefers-reduced-motion, lá no topo, desliga as duas. */
@keyframes lupa-entra{from{opacity:0;transform:scale(.97)}to{opacity:1;transform:none}}
@keyframes lupa-fundo{from{opacity:0}to{opacity:1}}
.lupa[open]{animation:lupa-entra .18s var(--suave)}
.lupa[open]::backdrop{animation:lupa-fundo .18s var(--suave)}
.botao2{display:inline-flex;align-items:center;gap:var(--e2);
background:var(--papel);color:var(--marca);
border:1px solid var(--borda-forte);border-radius:var(--raio-p);
padding:10px 18px;font-size:var(--t-base);font-weight:600;
text-decoration:none;
transition:border-color .16s var(--suave),background .16s var(--suave),
transform .16s var(--suave),box-shadow .16s var(--suave)}
.botao2:hover{border-color:var(--marca);background:var(--lavagem);
transform:translateY(-1px);box-shadow:var(--sombra-1)}
.login{max-width:380px;margin:70px auto;text-align:center;
animation:sobe-bloco .5s var(--suave) both}
.login img{height:64px;margin-bottom:18px}
.menu{display:flex;align-items:center;gap:var(--e1)}
.menu a{font-size:var(--t-p);text-decoration:none;color:var(--tinta2);
position:relative;padding:0 var(--e3);font-weight:500;
transition:color .16s var(--suave)}
.menu a:hover{color:var(--marca)}
/* Sublinhado que cresce do centro. É a única decoração de navegação do
   sistema, e cabe em duas linhas. */
.menu a::after{content:"";position:absolute;left:50%;right:50%;bottom:6px;
height:2px;background:var(--marca-grad);border-radius:2px;
transition:left .2s var(--suave),right .2s var(--suave)}
.menu a:hover::after{left:var(--e3);right:var(--e3)}
/* Aviso DENTRO do cartão, colado no preço que ele qualifica. Numa faixa no
   topo da página ele seria lido antes do número e esquecido depois. */
/* Aba de Documentacao. Escopo proprio: o resto do sistema quase nao usa
   texto corrido, e soltar estilo de <h2>/<ul> no global mexeria nas telas
   de cotacao. */
.doc h2{font-size:16px;margin:24px 0 6px;color:var(--marca);
letter-spacing:-.2px}
.doc h2:first-child{margin-top:0}
.doc p{margin:0 0 10px;font-size:14px}
.doc ul{margin:0 0 12px;padding-left:20px;font-size:14px}
.doc li{margin-bottom:6px}
.doc table{margin-bottom:12px}
.doc td{vertical-align:top}
.doc .errado{color:var(--erro);font-weight:600}
.doc .certo{color:var(--ok);font-weight:600}
.doc .passo{font-size:14px;margin:0 0 10px;padding-left:20px}
.alerta{background:var(--atencao-fraco);border:1px solid var(--atencao-borda);
border-left:3px solid var(--atencao);
border-radius:var(--raio-pp) var(--raio-p) var(--raio-p) var(--raio-pp);
padding:10px 12px;font-size:var(--t-p);margin:var(--e2) 0 var(--e1);
line-height:var(--ent-curta);color:var(--atencao-tinta)}
/* Amarelo e para "cuidado, esse numero engana". Aqui nao ha erro nenhum: e
   instrucao de onde olhar. Azul separa os dois recados. */
.alerta.email{background:var(--lavagem);border-color:#c7d6f5;
border-left-color:var(--marca);color:var(--tinta2)}
/* ---- filtro de transportadoras ---- */
.filtro{border:1px solid var(--borda);border-radius:var(--raio-p);
margin:0 0 14px;background:var(--papel)}
.filtro>summary{cursor:pointer;padding:12px 15px;display:flex;
align-items:center;gap:10px;font-size:13px;color:var(--fraco);
list-style:none;border-radius:var(--raio-p);transition:background .16s}
.filtro>summary:hover{background:var(--lavagem)}
.filtro>summary::-webkit-details-marker{display:none}
.filtro>summary .abrir{margin-left:auto;color:var(--marca);font-weight:600}
.filtro>summary .abrir::after{content:" ▾"}
.filtro[open]>summary .abrir::after{content:" ▴"}
/* o aviso fica LOGO acima do botao Cotar: e a rede que impede o filtro de
   virar erro silencioso semanas depois */
.filtro.parcial{border-color:#ffe380;background:#fffae6}
.filtro.parcial>summary{color:#7a5b00;font-weight:600}
.filtro.parcial>summary:hover{background:#fff5d6}
.grupo{border-top:1px solid var(--borda);padding:12px 14px}
.grupo-cab{display:flex;align-items:baseline;gap:8px;margin-bottom:9px;
font-size:10.5px;text-transform:uppercase;letter-spacing:.8px;
color:var(--fraco);font-weight:700}
.grupo-cab span{text-transform:none;letter-spacing:0;font-weight:400}
.grupo-cab .atalhos{margin-left:auto;white-space:nowrap}
.caixas{display:grid;gap:6px;
grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
.tr{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--tinta);
margin:0;padding:6px 8px;border-radius:var(--raio-p);cursor:pointer;
transition:background .14s var(--suave),opacity .14s var(--suave)}
.tr:hover{background:var(--lavagem)}
.tr input{width:auto;margin:0;flex:none;accent-color:var(--marca)}
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
.opcao{display:flex;align-items:center;gap:8px;border:1px solid
var(--borda-forte);border-radius:var(--raio-p);padding:11px 13px;
cursor:pointer;background:var(--papel);
transition:border-color .16s var(--suave),background .16s var(--suave),
box-shadow .16s var(--suave)}
.opcao:hover{border-color:#b6c2d6;background:#fcfdff}
.opcao:has(input:checked){border-color:var(--marca);background:var(--lavagem);
box-shadow:0 0 0 1px var(--marca)}
.opcao input{width:auto;margin:0;accent-color:var(--marca)}
.opcao b{font-size:14px}
.opcao span{font-size:11px;color:var(--fraco)}
.ficha .val{font-size:14px;font-weight:600;word-break:break-word}
.ficha .pouco{display:block;font-size:11px;font-weight:400;color:var(--fraco)}
/* .faixa, .numero, .barra, .sem-dado e .periodo moraram aqui até o painel
   ganhar casco próprio. Agora vivem em web/painel_ui.py, junto do resto do
   desenho do /adm — que é a ÚNICA tela que usa qualquer um deles. Manter uma
   segunda definição aqui não deixaria nada mais bonito: só faria toda página
   do vendedor carregar regra que ela não aplica, e daria dois lugares para
   alguém mudar a cor da barra pela metade. */

/* Tela da cotação pronta para o vendedor copiar (rota /email/...). */
.pronto{width:100%;font-family:ui-monospace,Consolas,monospace;font-size:13px;
        line-height:1.5;padding:13px;border:1px solid var(--borda-forte);
        border-radius:var(--raio-p);background:#fafbfe;color:#222;
        resize:vertical}
.pronto:focus{outline:0;border-color:var(--realce);
box-shadow:0 0 0 3px rgba(82,145,255,.35)}
/* O campo do endereço existe só para o botão Copiar ter o que selecionar:
   selecionar exige um campo de verdade, e display:none não é selecionável. */
.escondido{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}

/* ================= a porta da frente: rota, em tema escuro =================
   A única tela do sistema onde vale gastar área com apresentação. É vista uma
   vez por sessão, não tem trabalho para atrapalhar, e é a primeira impressão
   que a empresa tem do Cotafrete — as outras são formulário e resultado, onde
   área gasta com enfeite é área tirada de quem está cotando.

   Escura, e só ela. O resto do sistema é claro de propósito: é lido o dia
   inteiro, e tela escura para leitura contínua de tabela cansa mais. Aqui a
   pessoa passa cinco segundos, então o contraste com o resto é uma VIRADA de
   página, não uma inconsistência.

   Casco próprio (`entrada()`) e não `pagina()`: a faixa do topo existe para
   navegar, e quem ainda não entrou não tem para onde ir. Ela aparecia ali só
   mostrando a logo — e o cartão logo abaixo mostrava a MESMA logo de novo.

   Contraste medido com a fórmula do WCAG antes de escrever, não a olho. Os
   nove pares da tela passam; os apertados estão travados em teste. */
.entrada{min-height:100vh;display:grid;grid-template-columns:1.12fr .88fr;
background:#050c1a;color:#e8ebf2}
.entrada-marca{position:relative;overflow:hidden;
padding:clamp(34px,4.4vw,72px);display:flex;flex-direction:column;
justify-content:center;gap:clamp(26px,3.2vw,40px);
background:linear-gradient(158deg,#102542 0%,#091629 52%,#040a16 100%)}
/* Dois clarões fora de eixo. O índigo chapado é uma parede; os halos dão
   profundidade sem desenhar nada e sem depender de arquivo de imagem — o
   sistema roda em rede interna, e imagem que não chegou é buraco na tela. */
.entrada-marca::before,.entrada-marca::after{content:"";position:absolute;
border-radius:50%;pointer-events:none}
.entrada-marca::before{inset:-28% auto auto -18%;width:56%;aspect-ratio:1;
background:radial-gradient(circle,rgba(61,132,255,.2),transparent 66%)}
.entrada-marca::after{inset:auto -20% -34% auto;width:58%;aspect-ratio:1;
background:radial-gradient(circle,rgba(15,86,224,.34),transparent 68%)}
.entrada-marca>*{position:relative;z-index:1}

/* ================= o hero: a malha de corredores =============================
   Referência de direção, não de código: os sites de logística que funcionam
   (project44, Uber Freight) mostram a CARGA se movendo, e não uma foto de
   navio; o ArcBest põe uma malha de linhas discreta sobre o marinho escuro.
   Os links estão em docs/rebranding/IMPLEMENTACAO.md.

   Aqui a malha é desenhada à mão, em SVG, e diz o que o sistema faz: quatro
   corredores saindo de um ponto de origem para destinos diferentes, que é
   literalmente uma cotação. Nenhum arquivo, nenhuma biblioteca — o sistema
   roda em rede interna e o que não chegou é buraco na tela.

   TODA a animação é FINITA. Os corredores se desenham uma vez, o pulso de
   carga percorre três vezes e para. Um hero que se mexe para sempre atrás do
   campo de digitar é ruído permanente numa tela em que a pessoa veio fazer
   uma coisa só. A regra global de prefers-reduced-motion, lá no topo, deixa
   tudo no estado final. */
.tecido{position:absolute;inset:0;width:100%;height:100%;z-index:0;
pointer-events:none;opacity:.92}
.tecido .malha{stroke:rgba(126,170,255,.09);stroke-width:1}
/* Cada corredor se desenha do começo ao fim, um depois do outro. O
   `--comp` é o comprimento do traçado, escrito no elemento. */
.tecido .via{fill:none;stroke:rgba(126,170,255,.34);stroke-width:1.6;
stroke-linecap:round;stroke-dasharray:var(--comp);
stroke-dashoffset:var(--comp);
animation:via-tracada 1.5s var(--lento) both;
animation-delay:var(--atraso,0s)}
@keyframes via-tracada{to{stroke-dashoffset:0}}
/* O corredor principal é o que leva o preço de volta: mais claro e mais
   grosso que os outros três. */
.tecido .via.principal{stroke:rgba(93,151,255,.66);stroke-width:2.4}
/* O pulso de carga: um traço curto correndo por cima do corredor principal.
   Três voltas e para — é o gesto do sistema, não um letreiro. */
.tecido .pulso{fill:none;stroke:#9cc2ff;stroke-width:2.6;stroke-linecap:round;
stroke-dasharray:26 var(--comp);stroke-dashoffset:26;
animation:pulso-corre 2.9s var(--suave) 1.4s 3 both}
@keyframes pulso-corre{
0%{stroke-dashoffset:26;opacity:0}
12%{opacity:1}
88%{opacity:1}
100%{stroke-dashoffset:calc(-1 * var(--comp));opacity:0}}
/* Os destinos. Aparecem na ordem em que o corredor chega neles. */
.tecido .destino{fill:#5d97ff;opacity:0;
animation:destino-acende .5s var(--mola) both;
animation-delay:var(--atraso,0s)}
.tecido .destino-anel{fill:none;stroke:rgba(93,151,255,.5);stroke-width:1.4;
opacity:0;animation:destino-acende .5s var(--mola) both;
animation-delay:var(--atraso,0s)}
@keyframes destino-acende{from{opacity:0;transform:scale(.2)}
to{opacity:1;transform:none}}
.tecido .destino,.tecido .destino-anel{transform-box:fill-box;
transform-origin:center}
/* A origem pulsa três vezes e sossega: é de onde a carga sai. */
.tecido .origem{fill:#9cc2ff;
animation:origem-bate 2.2s var(--suave) 3 both}
@keyframes origem-bate{0%,100%{opacity:.95}50%{opacity:.45}}
/* Em cores naturais, sobre uma pastilha branca. `brightness(0) invert(1)`
   pintaria o desenho inteiro de branco — e o "V" da marca é um RECORTE, já
   branco: some contra a elipse e a logo vira um borrão. Passa despercebido na
   lateral do painel, onde ela tem 30px; aqui é a primeira coisa que se vê. */
/* Sem placa atrás: esta tela é escura por desenho, e a peça da marca tem
   fundo vazado — ela se apoia no próprio fundo da tela. */
.marca-entrada{align-self:flex-start}
/* A entrada é escura por desenho: sempre a peça prateada, sem o par
   claro que o resto do sistema tem. */
.entrada-marca .logo{height:68px;aspect-ratio:469/120;
background-image:url({MARCA_COMPACTA})}
/* A assinatura da marca, em TEXTO: dentro do lockup ela tem 6px de 120 e só
   se lê a partir de ~180px de altura da peça inteira. Aqui ela acompanha a
   largura da logo e fica legível em qualquer tela. */
.entrada-marca .assinatura{margin:11px 0 0;font-size:10.5px;
letter-spacing:.24em;text-transform:uppercase;color:rgba(255,255,255,.58);
font-weight:600;white-space:nowrap}
/* A tarja de cima: o que ESTA tela é, antes do título dizer o que ela
   promete. Duas palavras em versalete e um filete — é o degrau que faltava
   entre a marca e um título de 40px. */
.entrada-marca .tarja{display:inline-flex;align-items:center;gap:10px;
font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;
font-weight:700;color:#9cc2ff;margin:0 0 14px}
.entrada-marca .tarja::before{content:"";width:26px;height:2px;
border-radius:2px;background:linear-gradient(90deg,#5d97ff,transparent)}
/* Numa tela estreita a entrelinha larga faria a frase estourar a coluna:
   ela aperta em vez de quebrar no meio de "SÓ LUGAR". */
@media(max-width:520px){
.entrada-marca .assinatura{letter-spacing:1.4px;font-size:10px}
}
.entrada-marca h1{font-family:var(--fonte-titulo);
font-size:var(--t-display);line-height:var(--ent-display);
margin:0 0 16px;letter-spacing:var(--letra-display);color:#fff;
text-wrap:balance;font-weight:700}
/* A segunda linha do título fica no azul da marca. Uma chamada de 40px em
   branco chapado é um cartaz; quebrada em duas cores ela tem hierarquia
   dentro de si mesma, e a cor que carrega o sentido é a da empresa. */
.entrada-marca h1 em{font-style:normal;
background:linear-gradient(92deg,#9cc2ff,#5d97ff 62%);
-webkit-background-clip:text;background-clip:text;color:transparent}
.entrada-marca p{margin:0;max-width:44ch;font-size:var(--t-m);
line-height:var(--ent);color:rgba(255,255,255,.7);text-wrap:pretty}

/* ---- a rota ----
   Não é enfeite: é o que o sistema FAZ, desenhado. Uma carga entra, as
   automáticas cotam, sai o melhor preço. O número de paradas do meio sai de
   `len(AUTOMATICAS)`, passado por quem chama — escrito à mão, a tela passaria
   a mentir sobre o tamanho do sistema na primeira transportadora que
   entrasse.

   Faixa própria embaixo do texto, e não um traçado atrás dele: fundo que
   cruza o parágrafo briga com a leitura em alguma largura de tela, sempre. */
/* A rota ganha CAIXA: um painel de vidro sobre o fundo escuro, com a linha
   dentro. Solta sobre o gradiente ela se confundia com a malha do hero — as
   duas são pontos e linhas azuis, e o olho não sabia qual das duas ler. */
.entrada-marca .rota{display:flex;align-items:flex-start;gap:0;
margin:0;padding:18px 20px 16px;border-radius:var(--raio);
background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);
backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}
.entrada-marca .rota .parada{display:flex;flex-direction:column;gap:11px;
flex:0 0 auto;max-width:14ch}
.entrada-marca .rota .ponto{width:12px;height:12px;border-radius:50%;
background:#5d97ff;box-shadow:0 0 0 5px rgba(93,151,255,.16);
animation:parada-acende .45s var(--mola) both}
@keyframes parada-acende{from{opacity:0;transform:scale(.3)}
to{opacity:1;transform:none}}
.entrada-marca .rota .parada:nth-child(3) .ponto{animation-delay:.5s}
.entrada-marca .rota .parada:nth-child(5) .ponto{animation-delay:1s}
.entrada-marca .rota .parada:last-child .ponto{background:transparent;
border:2px solid rgba(255,255,255,.45);box-shadow:none}
.entrada-marca .rota .parada span{font-size:10.5px;line-height:var(--ent-curta);
text-transform:uppercase;letter-spacing:.11em;color:rgba(255,255,255,.66);
font-weight:600}
/* O trecho percorrido é sólido no azul; o que falta é pontilhado. A carga
   ainda não chegou — a linha inteira sólida diria que sim. O sólido cresce
   da esquerda, uma vez, no ritmo em que as paradas acendem. */
.entrada-marca .rota .trecho{flex:1 1 auto;height:2px;margin:5px 14px 0;
border-radius:2px;
background:linear-gradient(90deg,#5d97ff,rgba(93,151,255,.4));
transform-origin:left;animation:trecho-corre .55s var(--lento) .25s both}
@keyframes trecho-corre{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.entrada-marca .rota .trecho.falta{background:none;
border-top:2px dashed rgba(255,255,255,.24);height:0;margin-top:4px;
animation-delay:.75s}

/* ---- o lado do formulário ---- */
.entrada-form{display:flex;align-items:center;justify-content:center;
padding:48px 32px;background:#050c1a;position:relative}
/* Um filete vertical de luz na emenda das duas colunas. Sem ele o corte
   entre o hero e o formulário é uma linha de nada: dois escuros diferentes
   encostados, que numa tela fraca some e faz o hero parecer vazar. */
.entrada-form::before{content:"";position:absolute;left:0;top:14%;bottom:14%;
width:1px;background:linear-gradient(180deg,transparent,
rgba(93,151,255,.35),transparent)}
.entrada-form .cartao{width:100%;max-width:404px;margin:0;padding:34px 32px;
background:#101b30;border:1px solid rgba(255,255,255,.08);
border-radius:var(--raio-g);
box-shadow:0 30px 70px -26px rgba(0,0,0,.85)}
.entrada-form h1{color:#fff;font-size:26px;margin-bottom:6px}
.entrada-form .sub{color:#97a3b9;font-size:13.5px;margin-bottom:22px}
.entrada-form label{color:#97a3b9}
.entrada-form input{background:#08121f;border-color:rgba(255,255,255,.14);
color:#e8ebf2;padding:13px 14px}
.entrada-form input::placeholder{color:#7f8ea8}
.entrada-form input:hover{border-color:rgba(255,255,255,.26)}
.entrada-form input:focus{border-color:var(--realce-claro);
box-shadow:0 0 0 3px rgba(93,151,255,.3)}
/* Azul claro com tinta escura: o botão vira a coisa mais clara da tela, que é
   exatamente onde o olho deve parar. Índigo sobre fundo índigo sumiria. */
.entrada-form button{background:var(--realce-claro);color:#061021;
padding:14px 26px;font-size:var(--t-m);
box-shadow:0 14px 32px -12px rgba(93,151,255,.6)}
.entrada-form button:hover{background:#8ab6ff;
box-shadow:0 18px 40px -12px rgba(93,151,255,.72)}
.entrada-form .rodape{margin:18px 0 0;font-size:11.5px;color:#7f8ea8;
text-wrap:pretty;line-height:var(--ent);
padding-top:16px;border-top:1px solid rgba(255,255,255,.07)}
.entrada-form .alerta{background:rgba(191,51,32,.18);
border-color:rgba(255,146,121,.4);border-left-color:#ff9279;color:#ffb4a4;
font-size:var(--t-p);margin-bottom:var(--e3)}
.entrada-form a{color:var(--realce-claro)}

/* Numa tela estreita a coluna da marca vira uma faixa curta em cima: some o
   texto longo e a rota, fica a logo e a chamada. Empilhar tudo empurraria o
   campo de digitar para fora da tela — a única coisa que a pessoa veio
   fazer. */
@media(max-width:860px){
.entrada{grid-template-columns:1fr;min-height:0}
.entrada-marca{padding:28px 22px 30px;gap:18px}
.entrada-marca h1{font-size:24px;margin:0}
/* A ROTA sai, o parágrafo fica. Empilhar os dois empurra o campo de digitar
   para fora da tela — a única coisa que a pessoa veio fazer. Mas sumir com
   os dois deixava uma faixa com logo e título e nada explicando o sistema,
   que é justamente o que o celular mais precisa ler. */
.entrada-marca .rota{display:none}
.entrada-marca p{font-size:13.5px;max-width:none}
.entrada-marca .tarja{margin-bottom:10px}
/* A malha desbota: na faixa curta ela vira risco atrás do título. */
.tecido{opacity:.5}
.entrada-marca .logo{height:44px}
.entrada-form{padding:26px 18px 40px}
.entrada-form::before{display:none}
.entrada-form .cartao{padding:26px 22px}}
/* ================================ a marca ==================================
   Tres pecas, tres trabalhos — ver web/layout.py, MARCA_*.

   Todas tem fundo VAZADO e letras prateadas, feitas para fundo escuro. No
   escuro elas se apoiam direto na pagina: sem retangulo, sem diferenca de
   tom. No CLARO as letras prateadas somem — medido, o lockup sobre #f3f6fb
   fica ilegivel — e por isso vem a PLACA.

   A placa nao e curativo: o arquivo original ja vinha com esse marinho
   cravado. A diferenca e que agora ele e escolha de quem desenha a tela, e
   nao efeito colateral do PNG. */
.marca-placa{display:inline-flex;align-items:center;flex:none}
/* A peça entra como BACKGROUND, e não como <img>: são duas artes — prateada
   para fundo escuro, tinta escura para fundo claro — e o navegador baixa só
   a da regra que vale. Com duas <img> e uma escondida ele baixaria as duas,
   90 KB que nunca aparecem na tela. O nome acessível vem do aria-label no
   elemento, que é como se faz quando a imagem é desenhada pelo CSS. */
.marca-peca{display:block;background-repeat:no-repeat;
background-position:left center;background-size:contain}
.marca-lockup{height:38px;aspect-ratio:469/120;
background-image:url({MARCA_COMPACTA_CLARA})}
[data-tema="escuro"] .marca-lockup{background-image:url({MARCA_COMPACTA})}

/* ---- rodape ----
   Nao existia rodape em tela nenhuma do vendedor. Ele fecha a pagina e e o
   lugar natural da assinatura da marca, que no cabecalho nao cabe legivel. */
/* O rodape encosta no fim da JANELA quando a pagina e curta, e no fim do
   CONTEUDO quando e longa. Sem isto o historico com tres linhas deixava o
   rodape boiando no meio da tela, com 300px de vazio embaixo dele. */
body{min-height:100vh;display:flex;flex-direction:column}
body>.wrap{flex:1 0 auto}
.rodape-site{border-top:1px solid var(--borda);margin-top:var(--e8);
background:var(--papel);flex:none;position:relative}
/* O mesmo filete da marca, agora fechando a página por baixo. O topo abria
   com ele e o rodapé acabava numa linha cinza — a assinatura valia só para
   metade do documento. */
.rodape-site::before{content:"";position:absolute;left:0;right:0;top:-1px;
height:2px;background:var(--marca-grad);opacity:.7}
.rodape-site .dentro{max-width:var(--coluna);margin:0 auto;
padding:var(--e6) var(--e5);
display:flex;align-items:center;gap:var(--e5);flex-wrap:wrap}
.rodape-site .marca-lockup{height:26px}
.rodape-site .diz{font-size:11.5px;color:var(--fraco);line-height:var(--ent)}
.rodape-site .diz b{display:block;font-size:11px;color:var(--tinta2);
letter-spacing:var(--letra-rotulo);text-transform:uppercase;font-weight:700;
margin-bottom:2px}
.rodape-site .links{margin-left:auto;display:flex;gap:var(--e5);
font-size:var(--t-p);flex-wrap:wrap}
.rodape-site .links a{text-decoration:none;color:var(--tinta2);
font-weight:500}
.rodape-site .links a:hover{color:var(--marca);text-decoration:underline}
@media(max-width:620px){
.rodape-site .links{margin-left:0;width:100%}
}

/* ---- a faixa da pagina inicial ----
   O lockup INTEIRO, com a assinatura, que o cabecalho nao consegue mostrar.
   Ela e a unica tela onde a marca ganha area de proposito: e a primeira
   coisa que o vendedor ve ao entrar para trabalhar.

   Contida a 92px de altura: a pagina inicial e onde se trabalha o dia
   inteiro, e faixa alta empurra o formulario para fora da dobra. */
/* No claro a faixa é CLARA. Ela era um painel quase preto no alto de uma
   página branca: cortava a tela ao meio e não combinava com nada em volta.
   Agora é um cartão da casa, com a lavagem da marca subindo da esquerda —
   presença de marca sem brigar com o formulário logo abaixo, que é onde a
   pessoa veio trabalhar. */
.faixa-marca{display:flex;align-items:center;gap:var(--e5);flex-wrap:wrap;
background:linear-gradient(110deg,var(--lavagem) 0%,var(--papel) 62%);
border:1px solid var(--borda);border-radius:var(--raio-g);
padding:var(--e5) var(--e6);
margin:0 0 var(--e6);position:relative;overflow:hidden;
box-shadow:var(--sombra-1)}
/* A malha de corredores do hero, reduzida e quase apagada, no canto direito
   da faixa. É o mesmo desenho da tela de entrada — o que amarra a porta de
   entrada e a tela de trabalho como um sistema só, sem gastar altura: a
   página inicial é onde se trabalha o dia inteiro, e faixa alta empurra o
   formulário para fora da dobra. Zero animação aqui: é tela de trabalho. */
.faixa-marca .tecido{left:auto;right:0;width:min(46%,420px);opacity:.5}
.faixa-marca .tecido *{animation:none !important}
.faixa-marca .tecido .via{stroke-dashoffset:0}
.faixa-marca .tecido .destino,.faixa-marca .tecido .destino-anel{opacity:1}
.faixa-marca .tecido .pulso{display:none}
.faixa-marca>:not(.tecido){position:relative;z-index:1}
/* No CLARO o traço da malha é azul da marca a baixa opacidade: o
   rgba(126,170,255) do hero foi escolhido contra um marinho quase preto e
   aqui ficaria branco sobre branco. */
.faixa-marca .tecido .malha{stroke:rgba(0,63,176,.1)}
.faixa-marca .tecido .via{stroke:rgba(0,63,176,.22)}
.faixa-marca .tecido .via.principal{stroke:rgba(0,63,176,.4)}
.faixa-marca .tecido .destino,.faixa-marca .tecido .origem{fill:var(--marca)}
.faixa-marca .tecido .destino-anel{stroke:rgba(0,63,176,.34)}
@media(max-width:760px){.faixa-marca .tecido{display:none}}
/* No escuro ela continua sendo o painel fundo: ali o cartão claro é que
   seria o corpo estranho. */
[data-tema="escuro"] .faixa-marca{background:#0a1020;
border-color:transparent}
/* O filete da marca no alto, o mesmo da faixa do vendedor e da lateral do
   painel: e o que amarra as tres telas como um sistema so. */
.faixa-marca::before{content:"";position:absolute;left:0;right:0;top:0;
height:3px;background:var(--marca-grad)}
.faixa-marca .marca-lockup{height:52px}
.faixa-marca .diz{color:var(--tinta2);font-size:12.5px;line-height:1.55;
max-width:42ch}
.faixa-marca .diz b{display:block;color:var(--tinta);font-size:15px;
margin-bottom:2px}
[data-tema="escuro"] .faixa-marca .diz{color:#c8d2e8}
[data-tema="escuro"] .faixa-marca .diz b{color:#fff}
@media(max-width:620px){
.faixa-marca{padding:16px}
.faixa-marca .marca-lockup{height:40px}
}

/* ============================== acabamento =================================
   Detalhes pequenos que somam. Cada um tem motivo; nenhum é enfeite solto. */

/* Título e texto curto não podem quebrar deixando uma palavra órfã na última
   linha. `balance` nos títulos, `pretty` no texto de apoio. */
h1,h2,.cartao-cab h2,.res .nome{text-wrap:balance}
.sub,.nota,.res .nota,.entrada-marca p{text-wrap:pretty}

/* Logo de transportadora vem de vinte sites diferentes, e várias têm fundo
   branco: sem contorno, a borda da imagem se dissolve no cartão branco e o
   logo parece flutuar torto. Preto transparente, nunca a cor da marca — o
   contorno é para separar da superfície, não para tingir a imagem alheia. */
.zap .marca,.tr img,.resposta img,.print{outline:1px solid rgba(0,0,0,.09);
outline-offset:-1px}

/* Botão afunda de verdade no clique. `translateY` sozinho lê como o cartão
   subindo; `scale` lê como dedo apertando, que é o que o gesto é. */
button:active{transform:scale(.97);box-shadow:var(--sombra-1)}

/* Alvo de toque. A pastilha de período tinha 12px de altura de texto e quase
   nada em volta: no monitor da empresa, com o mouse na mão o dia inteiro,
   errar a pastilha e recarregar o painel no período errado é atrito real. */
.periodo{min-height:40px;display:inline-flex;align-items:center}
.menu a{display:inline-flex;align-items:center;min-height:40px}
.lateral a{min-height:40px}

/* ================== resultado da cotação: a tabela de comparação ==========
   Direção A. Era um cartão por transportadora, com o print em tamanho real
   dentro: 300px de altura cada, e os dois preços que se comparam ficavam com
   meia tela de distância um do outro. Pior no celular, onde o PRIMEIRO preço
   visível era o mais caro, só por estar antes na ordem.

   Agora é uma linha por transportadora. Comparar vira ler uma coluna. */
.r-cab{display:flex;align-items:center;gap:14px;margin-bottom:12px}
.r-cab h2{font-size:15px;margin:0}
.r-cab .botao2{margin:0 0 0 auto}
/* Só a tabela rola, nunca a página. */
.rolagem-r{overflow-x:auto}
/* `table-layout:fixed` e as larguras nas celulas do CABECALHO. Duas coisas
   que so se descobrem medindo:

   - sem layout fixo o navegador soma o conteudo de cada celula e a tabela
     estoura o container (medido em 10/09/2026: 1323px dentro de 990px);
   - com layout fixo quem define as colunas e a PRIMEIRA linha, que e o
     `<thead>`. Larguras so nas celulas do corpo deixavam cabecalho e corpo
     fora de registro, cada um pedindo um conjunto de colunas.

   Somam exatamente 100%: sobrando, a tabela cresce e a rolagem volta. */
table.resultados{width:100%;border-collapse:collapse;font-size:13.5px;
table-layout:fixed}
table.resultados .r-nome{width:20%}
table.resultados .r-preco{width:13%}
table.resultados .r-prazo{width:8%}
table.resultados .r-nota{width:21%}
table.resultados .r-validade{width:13%}
table.resultados .r-estado{width:13%}
table.resultados .r-print{width:12%}
table.resultados th{font-size:var(--t-micro);
letter-spacing:var(--letra-rotulo);
text-transform:uppercase;color:var(--fraco);font-weight:700;text-align:left;
padding:0 var(--e4);height:40px;background:var(--cova);
border-bottom:1px solid var(--borda-forte);white-space:nowrap}
table.resultados th.r-preco,table.resultados th.r-prazo,
table.resultados th.r-print{text-align:right}
table.resultados td{padding:0 var(--e4);height:62px;
border-bottom:1px solid var(--borda);vertical-align:middle}
tr.r:hover td{background:var(--lavagem)}
.r-nome{font-weight:500}
.r-preco{text-align:right;white-space:nowrap}
.r-prazo{text-align:right;color:var(--tinta2);white-space:nowrap}
/* A unica coluna que QUEBRA. As outras sao numero ou rotulo curto; esta e
   frase, e e ela que deve ceder quando a tela aperta. */
.r-nota{color:var(--fraco);font-size:12.5px;line-height:1.35;
text-wrap:pretty}
.r-print{text-align:right;width:1%}

/* Até quando o preço ainda fecha negócio. A vencida fica apagada e riscada:
   o preço continua na tela porque é histórico, mas não serve mais para
   fechar — e a linha precisa dizer isso antes de ser lida. */
.r-validade{white-space:nowrap;font-size:12.5px}
.validade-ok{color:var(--tinta2)}
.validade-vencida{color:var(--fraco);text-decoration:line-through}

/* O botão de aceitar mora na MESMA célula da validade, logo abaixo dela: é a
   validade que decide se ainda vale a pena aceitar, e separar as duas faria
   o vendedor ler "vence hoje" num canto da linha e clicar no outro. */
.r-validade>span{display:block}
/* `--marca` e não `--tinta`: no tema escuro a tinta INVERTE (vira clara) e o
   botão ficaria com texto branco sobre fundo branco. A marca é a mesma
   família de azul do <button> comum, que já vive bem nos dois temas. */
.aceite-botao{display:inline-block;margin-top:5px;padding:5px 12px;
border-radius:7px;background:var(--marca);color:var(--sobre-marca);font-size:12px;
font-weight:700;text-decoration:none;white-space:nowrap}
.aceite-botao:hover{background:var(--marca-forte)}
/* Pedida e confirmada. Sem botão nenhum — botão apagado ainda parece que um
   dia funciona, e convida ao clique. */
.aceite-feito{display:block;margin-top:5px;color:var(--ok);font-weight:700;
font-size:12px}
.aceite-indo{display:block;margin-top:5px;color:var(--tinta2);font-size:12px}
.aceite-refazer{display:inline-block;margin-top:5px;color:var(--erro);
font-size:12px;font-weight:600}

/* A tela de aceite: o que está sendo aceito, em quatro números, acima do
   formulário. Quem confirma precisa ver isso sem voltar uma página. */
.resumo-aceite{display:flex;flex-wrap:wrap;gap:22px}
.resumo-aceite>div{display:flex;flex-direction:column;gap:2px}
.resumo-aceite .rot{font-size:10.5px;letter-spacing:1px;
text-transform:uppercase;color:var(--fraco);font-weight:700}
.resumo-aceite b{font-size:17px}
.campo{display:block;margin:14px 0}
.campo>span{display:block;font-size:12.5px;font-weight:600;margin-bottom:5px}
.campo small{display:block;color:var(--fraco);font-size:11.5px;margin-top:4px}
.campo input[type=date],.campo select,.campo textarea{width:100%;
padding:9px 11px;border:1px solid var(--borda);border-radius:8px;
font:inherit;font-size:14px;background:#fff}
.campo.linha{display:flex;align-items:center;gap:8px}
.campo.linha>span{margin:0;font-weight:500}
.campo.linha input{width:auto}
.campo.duplo{display:flex;gap:12px}
.campo.duplo>label{flex:1}
.campo.duplo span{display:block;font-size:12.5px;font-weight:600;
margin-bottom:5px}

/* A vencedora. Fundo mais filete à esquerda, e não só borda: numa tabela a
   borda de uma linha se confunde com a divisória da linha de cima. */
tr.r.melhor td{background:var(--ok-fraco)}
tr.r.melhor:hover td{background:#e0efe9}
tr.r.melhor .r-nome{font-weight:700;box-shadow:inset 3px 0 0 var(--ok)}
tr.r.melhor .preco{font-size:21px}

/* O preço na MONOESPAÇADA da casa. É a mudança que mais se nota na tela que
   mais importa: numa coluna de sete fretes, "R$ 1.204,90" e "R$ 69,91" com
   largura de dígito e de vírgula iguais viram uma coluna que se lê de cima
   para baixo sem o olho procurar onde cada número começa. */
.resultados .preco{font-family:var(--fonte-num);font-size:17px;
font-weight:700;color:var(--ok);letter-spacing:-.02em}
/* Preço que não é da carga toda não pode usar o verde de "bom preço": o olho
   compara os números grandes antes de ler qualquer aviso, e era exatamente
   assim que R$ 33,29 por volume parecia mais barato que R$ 69,91 pela carga. */
.resultados .preco.incerto{color:var(--fraco)}
.resultados .sem{color:var(--fraco);font-size:13px}
.resultados .cotando{font-size:12.5px}

/* Pílula de estado. Cor semântica, separada da cor da marca: verde é "veio
   preço", âmbar é "a transportadora disse não", vermelho é "não sabemos". */
/* Pílula com PONTO à esquerda, e não só cor de fundo. Cor sozinha é o jeito
   de dizer o estado só para quem enxerga cor; o ponto dá forma ao mesmo
   recado e não custa marcação nenhuma (`::before`). */
.estado-ok,.estado-aguardando,.estado-recusa,.estado-falha,.estado-cotando{
display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;
border-radius:99px;font-size:var(--t-micro);font-weight:700;
letter-spacing:var(--letra-rotulo);text-transform:uppercase;
white-space:nowrap;border:1px solid transparent}
.estado-ok::before,.estado-aguardando::before,.estado-recusa::before,
.estado-falha::before,.estado-cotando::before{content:"";width:6px;height:6px;
border-radius:50%;background:currentColor;flex:none}
.estado-ok{background:var(--ok-fraco);color:var(--ok);
border-color:color-mix(in srgb,var(--ok) 26%,transparent)}
.estado-aguardando{background:var(--lavagem);color:var(--marca);
border-color:color-mix(in srgb,var(--marca) 22%,transparent)}
.estado-recusa{background:var(--atencao-fraco);color:var(--atencao);
border-color:color-mix(in srgb,var(--atencao) 26%,transparent)}
.estado-falha{background:var(--erro-fraco);color:var(--erro);
border-color:color-mix(in srgb,var(--erro) 26%,transparent)}
.estado-cotando{background:var(--fundo);color:var(--fraco);
border-color:var(--borda)}

/* A MINIATURA do print, em toda transportadora que tenha — não só na mais
   barata. O print é a prova de que aquele preço veio do site, e prova que só
   a vencedora tem não prova nada sobre as outras. `object-position:top`
   porque print de site é pesado em cima: o cabeçalho da transportadora é o
   que identifica a imagem de relance. Clicar abre a lupa. */
.mini{display:inline-block;line-height:0}
.mini .print{width:76px;height:44px;margin:0;object-fit:cover;
object-position:top center;border-radius:6px;cursor:zoom-in;
transition:transform .16s var(--suave),box-shadow .16s var(--suave)}
.mini .print:hover{transform:scale(1.06);box-shadow:var(--sombra-2)}
.sem-print{color:var(--fraco)}

/* ---- histórico do vendedor ----
   A mesma tabela do painel, num corpo menor: aqui é a lista de UMA pessoa,
   e ela abre a tela para conferir um preço que já cotou. */
.hora{color:var(--fraco);font-variant-numeric:tabular-nums;white-space:nowrap;
width:1%}
/* O preço é o número que a linha existe para mostrar: alinhado à direita,
   todas as vírgulas na mesma coluna. */
.melhor{text-align:right;font-weight:700;color:var(--ok);white-space:nowrap;
font-variant-numeric:tabular-nums}
/* O travessão de "nenhuma transportadora cotou" NÃO herda o verde: não ter
   preço não é um preço bom, e uma coluna toda verde faz o olho passar
   direto pela linha que precisava de atenção. A classe vem do app, que é
   quem sabe se houve preço — CSS não consegue perguntar isso. */
.melhor.vazio{color:var(--fraco);font-weight:400;font-size:inherit;
text-align:right;padding:0}

/* A linha de detalhe: só existe quando há o que avisar, e atravessa a tabela
   inteira. Aviso solto numa célula estreita vira duas palavras por linha. */
tr.r-extra td{height:auto;padding:0 14px 12px;background:#fbfcfe;
border-bottom:1px solid var(--borda)}
tr.r-extra .alerta,tr.r-extra .nota{margin:0 0 6px}
tr.r-extra>td>*:last-child{margin-bottom:0}

/* Celular: some o que é explicação e fica o que é comparação. A coluna "o
   que inclui" é a primeira a sair — é longa, e é justamente a que o vendedor
   já sabe de cor. */
@media(max-width:720px){
  table.resultados .r-nota,table.resultados th:nth-child(4){display:none}
  table.resultados td,table.resultados th{padding:0 10px}
  .mini .print{width:56px;height:36px}
}

/* ========================= o cabeçalho das telas de trabalho ================
   Toda tela do vendedor abria com um <h1> solto e um <p class="sub"> embaixo.
   Funciona, e não diz de onde a pessoa veio nem o que ela pode fazer ali: os
   botões ficavam espalhados pelo fim da página, e o contexto da cotação
   (rota, peso, valor) era uma frase corrida de seis campos separados por
   pontos médios.

   `.cab-pagina` é o mesmo componente em todas elas: tarja (onde estou),
   título, uma linha de CONTEXTO em pastilhas e as ações à direita. Compacto
   de propósito — hero é a porta de entrada, não a mesa de trabalho. O
   enunciado do rebranding pede exatamente isso: cabeçalho compacto na tela
   operacional, apresentação na tela que é vista uma vez por sessão. */
.cab-pagina{display:flex;align-items:flex-start;gap:var(--e4);
flex-wrap:wrap;margin:0 0 var(--e5);padding-bottom:var(--e4);
border-bottom:1px solid var(--borda)}
.cab-pagina>.diz{min-width:0;flex:1 1 320px}
.cab-pagina h1{margin:0}
.cab-pagina .sub{margin:var(--e2) 0 0}
/* A tarja: versalete curto com um filete da marca na frente. Mesma gramática
   da tarja do hero — é o que faz a tela de dentro parecer da mesma casa que
   a porta da frente. */
.tarja{display:inline-flex;align-items:center;gap:var(--e2);
font-size:var(--t-micro);letter-spacing:.14em;text-transform:uppercase;
font-weight:700;color:var(--marca);margin:0 0 var(--e2)}
.tarja::before{content:"";width:22px;height:2px;border-radius:2px;
background:var(--marca-grad)}
.cab-pagina .acoes{margin-left:auto;display:flex;align-items:center;
gap:var(--e2);flex-wrap:wrap}
/* A linha de contexto. Cada dado numa pastilha, com o rótulo em versalete e
   o valor na monoespaçada: era uma frase de 120 caracteres com seis números
   dentro, e achar o peso no meio dela exigia ler a frase inteira. */
.contexto{display:flex;flex-wrap:wrap;gap:var(--e2);margin:var(--e3) 0 0;
padding:0;list-style:none}
.contexto li{display:inline-flex;align-items:baseline;gap:6px;
background:var(--cova);border:1px solid var(--borda);border-radius:99px;
padding:5px 12px;font-size:var(--t-p);color:var(--tinta2);max-width:100%}
.contexto li b{font-family:var(--fonte-num);font-weight:600;
font-size:12px;color:var(--tinta);overflow:hidden;text-overflow:ellipsis;
white-space:nowrap}
.contexto li span{font-size:var(--t-micro);text-transform:uppercase;
letter-spacing:var(--letra-rotulo);color:var(--fraco);font-weight:700;
flex:none}
/* A rota é o dado que identifica a cotação: ganha a cor da marca e fica na
   frente das outras pastilhas. */
.contexto li.ctx-rota{background:var(--lavagem);border-color:transparent}
.contexto li.ctx-rota b{color:var(--marca-forte)}

/* ======================= números onde número é o assunto ===================
   A monoespaçada não é enfeite: ela separa o RÓTULO do VALOR. Onde entra é
   onde o olho compara — coluna de preço, hora, peso, campo da ficha. */
.hora,.melhor,.ficha .val{font-family:var(--fonte-num)}
/* A linha do histórico do vendedor. O número é um <a> de verdade (é ele que
   atende o teclado), e a linha inteira é o alvo do mouse. */
tr[data-abrir]{cursor:pointer}
.id-l{width:1%;white-space:nowrap}
.id-l a{font-family:var(--fonte-num);color:var(--fraco);font-weight:700;
text-decoration:none;font-size:12px}
tr[data-abrir]:hover .id-l a{color:var(--marca);text-decoration:underline}
.melhor{font-size:13.5px;letter-spacing:-.02em}
.melhor.vazio{font-family:var(--fonte)}
.hora{font-size:12px}
.ficha .val{font-size:13.5px}
.ficha .pouco{font-family:var(--fonte)}

/* ---- o filtro de transportadoras, mais leve -------------------------------
   Ele abre logo acima do botão Cotar e é o último bloco que a pessoa lê. */
.filtro{border-radius:var(--raio);box-shadow:var(--sombra-1)}
.filtro>summary{padding:14px 16px;font-size:var(--t-base)}
.filtro>summary .abrir{font-size:var(--t-p)}
.grupo-cab{font-size:var(--t-micro);letter-spacing:var(--letra-rotulo)}
.tr{padding:7px var(--e2);border-radius:var(--raio-pp)}
.selo-zap{letter-spacing:.04em;text-transform:uppercase;font-size:9.5px;
padding:2px 8px}

/* ---- as duas opções de tipo de frete -------------------------------------- */
.opcao{border-radius:var(--raio-p);padding:13px 15px;gap:var(--e3)}
.opcao b{font-size:var(--t-m)}
.opcao span{font-size:var(--t-mini);color:var(--fraco)}
/* A escolhida ganha um anel em vez de dois contornos empilhados: o
   `box-shadow:0 0 0 1px` sobre a borda fazia 2px de azul irregular. */
.opcao:has(input:checked){border-color:var(--marca);background:var(--lavagem);
box-shadow:0 0 0 2px color-mix(in srgb,var(--marca) 28%,transparent)}

/* ---- a cotação pronta para copiar ---------------------------------------- */
.pronto{font-family:var(--fonte-num);font-size:12.5px;
border-radius:var(--raio-p);padding:16px;background:var(--cova);
color:var(--tinta)}

/* ---- o passo a passo assistido (Della Volpe) ------------------------------
   Eram quatro parágrafos que começavam com "Passo N:" em negrito, no meio de
   prints e avisos amarelos: numa tela de rolagem longa, achar de onde
   recomeçar depois de mudar de aba era reler tudo. Agora cada passo é um
   bloco com o número em medalhão e um filete ligando um ao outro — a pessoa
   volta do navegador e acha o lugar de relance. */
.passo-n{position:relative;padding:2px 0 var(--e5) 46px;font-size:var(--t-base);
line-height:var(--ent);margin:var(--e5) 0 0}
.passo-n::before{content:attr(data-n);position:absolute;left:0;top:-4px;
width:30px;height:30px;border-radius:50%;display:grid;place-items:center;
font-family:var(--fonte-num);font-size:13px;font-weight:700;
background:var(--marca);color:var(--sobre-marca);
box-shadow:0 0 0 4px color-mix(in srgb,var(--marca) 14%,transparent)}
/* O filete que liga um passo ao próximo. O último não tem para onde ligar. */
.passo-n::after{content:"";position:absolute;left:15px;top:30px;bottom:0;
width:2px;background:linear-gradient(180deg,var(--borda-forte),
color-mix(in srgb,var(--borda) 40%,transparent))}
.passo-n:last-of-type::after{display:none}
/* O que vem DEPOIS do passo (print, legenda, aviso) entra alinhado com o
   texto dele, e não volta para a margem do cartão. */
.passo-n+p,.passo-n+img,.passo-n+.alerta{margin-left:46px}

/* ---- documentação: texto corrido, que o resto do sistema quase não tem ---- */
.doc{max-width:74ch}
.doc h2{font-size:var(--t-g);margin:var(--e6) 0 var(--e2);
font-family:var(--fonte-titulo);letter-spacing:-.018em}
.doc p,.doc ul,.doc .passo{font-size:var(--t-base);line-height:var(--ent)}
.doc table{font-size:var(--t-p)}

/* ---- o giro de espera, no traço da marca --------------------------------- */
.girando{border-width:2px;border-color:var(--borda);
border-top-color:var(--marca)}
.cotando{font-size:var(--t-p)}

/* ============================ nada de rolagem lateral ======================
   `overflow-x:clip` e não `hidden`: `hidden` num ancestral cria contexto de
   rolagem e quebra `position:sticky` dos filhos — que é exatamente o que a
   faixa do topo e os cabeçalhos das tabelas do painel usam. */
html,body{overflow-x:clip;max-width:100%}
/* Imagem e tabela são as duas coisas que estouram a coluna sozinhas. */
img{max-width:100%}

@media(max-width:620px){
.wrap{padding:0 var(--e4);margin-top:var(--e4)}
.cartao{padding:var(--e4)}
.cab-pagina{gap:var(--e3);margin-bottom:var(--e4)}
.cab-pagina .acoes{margin-left:0;width:100%}
.topo{padding:10px var(--e4);gap:var(--e3)}
/* No celular o menu do topo rola de lado em vez de quebrar em duas linhas e
   empurrar o conteúdo: são quatro links curtos, e uma faixa de duas alturas
   custa 40px de dobra em toda tela. */
.topo .quem{width:100%;margin-left:0;order:3;overflow-x:auto;
scrollbar-width:none}
.topo .quem::-webkit-scrollbar{display:none}
.menu{flex:none}
.opcoes{grid-template-columns:1fr}
}
"""

# O endereço das peças da marca entra AQUI, e não por f-string lá em cima:
# `CSS` é cheio de chaves — cada regra é um `{...}` — e transformá-lo em
# f-string obrigaria a dobrar todas elas, estragando o arquivo inteiro para
# resolver dois endereços. Duas linhas de `replace` custam menos e deixam os
# caminhos numa fonte só, no topo do módulo.
CSS = (CSS.replace("{MARCA_COMPACTA_CLARA}", MARCA_COMPACTA_CLARA)
          .replace("{MARCA_COMPACTA}", MARCA_COMPACTA))


def e(v) -> str:
    """Escapa para HTML. O material vem do usuário e vai para a tela."""
    return html.escape(str(v if v is not None else ""))


def moeda(v: Decimal | None) -> str:
    """Preço em português: milhar com ponto, decimal com vírgula. None vira
    travessão, nunca "0,00" — zero seria um preço, e não ter preço é outra
    coisa.

    Vive aqui, e não em web/app.py, porque web/adm.py tinha a própria versão
    (`_moeda`, sem separador de milhar) — a mesma moeda escrita como
    "R$ 12345,67" numa tela e "R$ 12.345,67" na outra, no mesmo sistema."""
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------- a malha do hero
#
# O desenho de fundo da tela de entrada, e o mesmo em miniatura na faixa da
# página inicial. Original, feito à mão em SVG: quatro corredores saindo de
# uma origem para destinos diferentes — que é literalmente o que uma cotação
# é. Nada de arquivo de imagem e nada de biblioteca de animação; CSS e SVG
# dão conta, e o sistema roda em rede interna onde o que não chegou é buraco
# na tela.
#
# A referência é de DIREÇÃO, não de código: os sites de logística que
# funcionam mostram a carga se movendo em vez de uma foto de contêiner
# (project44, Uber Freight), sobre uma malha discreta num marinho escuro
# (ArcBest). Os links estão em docs/rebranding/IMPLEMENTACAO.md. Nenhum
# traçado, nenhuma cor e nenhum arquivo veio de lá.
#
# `--comp` é o comprimento de cada traçado, medido no desenho e escrito no
# elemento: é o que faz `stroke-dasharray`/`dashoffset` desenharem a linha do
# começo ao fim em vez de piscarem inteira. `--atraso` escalona as chegadas.
#
# `aria-hidden` porque é decoração: quem usa leitor de tela já recebe a
# chamada, o apoio e a rota em texto, logo acima.
MALHA_CORREDORES = """<svg class="tecido" viewBox="0 0 520 420"
 preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
<g class="malha">
<path d="M0 84h520M0 168h520M0 252h520M0 336h520"/>
<path d="M104 0v420M208 0v420M312 0v420M416 0v420"/>
</g>
<path class="via" style="--comp:300;--atraso:.15s"
 d="M96 300C170 300 186 214 258 206"/>
<path class="via" style="--comp:330;--atraso:.35s"
 d="M96 300C168 300 196 128 300 112"/>
<path class="via" style="--comp:290;--atraso:.55s"
 d="M96 300C182 300 214 330 286 340"/>
<path class="via principal" style="--comp:430;--atraso:0s"
 d="M96 300C204 300 250 176 340 168 404 162 430 206 470 214"/>
<path class="pulso" style="--comp:430"
 d="M96 300C204 300 250 176 340 168 404 162 430 206 470 214"/>
<circle class="destino-anel" cx="258" cy="206" r="11" style="--atraso:.7s"/>
<circle class="destino" cx="258" cy="206" r="4.5" style="--atraso:.7s"/>
<circle class="destino-anel" cx="300" cy="112" r="11" style="--atraso:.9s"/>
<circle class="destino" cx="300" cy="112" r="4.5" style="--atraso:.9s"/>
<circle class="destino-anel" cx="286" cy="340" r="11" style="--atraso:1.1s"/>
<circle class="destino" cx="286" cy="340" r="4.5" style="--atraso:1.1s"/>
<circle class="destino-anel" cx="470" cy="214" r="15" style="--atraso:1.3s"/>
<circle class="destino" cx="470" cy="214" r="6" style="--atraso:1.3s"/>
<circle class="origem" cx="96" cy="300" r="7"/>
</svg>"""


# ------------------------------------------------------------------- lupa
#
# O comprovante ampliado. Vive aqui porque as QUATRO telas que mostram print
# precisam dele: a cotação do vendedor, a do adm, a do bookmarklet da Della
# Volpe e o e-mail pronto. Antes eram três cópias do mesmo `onclick`, e a
# correção de uma não chegava nas outras.
#
# `<dialog>` aberto com `showModal()`, e não uma `<img>` com `position:fixed`:
# é a única forma que NÃO quebra. `position:fixed` se ancora no ancestral mais
# próximo que tenha `transform` — é a regra do CSS, não bug de navegador — e
# TODO cartão do sistema carrega um. Não pelo `:hover`: a animação de entrada
# usa `fill-mode:both`, então o `transform` da última keyframe fica resolvido
# no elemento para sempre. `getComputedStyle` devolve `matrix(1,0,0,1,0,0)`
# em vez de `none`, e identidade cria containing block igual.
#
# Medido em 09/09/2026, com a janela em 1400x900: o print de 1100x1700 abria
# em 1102x1702 na posição (258, 281) — ou seja, dentro do cartão, no tamanho
# natural, por cima do texto da página e por baixo do que viesse depois. Um
# `:has(.print.zoom){transform:none}` no cartão consertaria ESTE caso e
# voltaria a quebrar no próximo ancestral que ganhasse `transform`, `filter`
# ou `will-change`.
#
# Diálogo modal vai para a CAMADA DE TOPO do navegador: acima de todo o
# documento, sem z-index, imune a transform de ancestral. De brinde vêm o
# `::backdrop` que escurece a página, o Esc que fecha e o foco preso dentro.
LUPA = """<dialog class="lupa" aria-label="Comprovante ampliado">
<img alt="Comprovante da cotação, ampliado"></dialog>
<script>
(() => {
  const lupa = document.querySelector('.lupa');
  if (!lupa) return;
  const img = lupa.querySelector('img');

  // Delegação no documento, e não um ouvinte por imagem: na tela do adm os
  // cartões de resposta são trocados sozinhos conforme as transportadoras
  // respondem, e ouvinte preso a uma imagem morre junto com ela.
  document.addEventListener('click', ev => {
    const print = ev.target.closest('.print');
    if (!print) return;
    img.src = print.src;
    lupa.showModal();
  });

  // Clique em qualquer lugar fecha — na imagem ou no fundo escuro. O Esc já
  // vem de graça com o showModal().
  lupa.addEventListener('click', () => lupa.close());
  // Devolve a rolagem ao topo entre um print e outro: sem isto, abrir o
  // segundo comprovante mostra o meio dele.
  lupa.addEventListener('close', () => { lupa.scrollTop = 0; });
})();
</script>"""


# ------------------------------------------------------------------- tema

def cabeca_do_tema(padrao: str) -> str:
    """O <script> que decide o tema ANTES da primeira pintura.

    É o único script do sistema que precisa estar no <head> e ser síncrono.
    No fim do <body> ele também funcionaria, mas quem escolheu escuro veria a
    página inteira clara por um quadro antes de escurecer — e essa piscada
    branca na cara de quem pediu tela escura é pior do que não ter o botão.

    `padrao` é o que a tela mostra para quem NUNCA mexeu no botão: claro no
    vendedor, escuro no painel. É o que cada uma já era antes de existir
    escolha, então ninguém chega amanhã numa tela diferente da de ontem.

    O `try` não é cerimônia: `localStorage` LEVANTA exceção — não devolve
    null — quando o navegador está com armazenamento bloqueado, e uma exceção
    aqui, no <head>, antes de tudo, mataria a página inteira em vez de só o
    botão.
    """
    return ("<script>try{document.documentElement.dataset.tema="
            "localStorage.getItem('tema')||'" + padrao + "'}"
            "catch(e){document.documentElement.dataset.tema='"
            + padrao + "'}</script>")


# Sol e lua no MESMO botão: cada tema mostra o ícone do que a pessoa vai
# receber, e não do que já tem. Um sol numa tela que já está clara não diz o
# que o botão faz.
BOTAO_TEMA = """<button type="button" class="tema" data-tema-troca
 title="Alternar entre tema claro e escuro"
 aria-label="Alternar entre tema claro e escuro">
<svg class="p-lua" viewBox="0 0 24 24" fill="none" stroke="currentColor"
 stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
 aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>
</svg>
<svg class="p-sol" viewBox="0 0 24 24" fill="none" stroke="currentColor"
 stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
 aria-hidden="true"><circle cx="12" cy="12" r="4"/>
<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>
</svg></button>"""

SCRIPT_TEMA = """<script>
(() => {
  // Delegação no documento: o painel troca pedaços da tela sozinho a cada
  // 10s, e um ouvinte preso ao botão morre junto com o pedaço que o continha.
  document.addEventListener('click', ev => {
    if (!ev.target.closest('[data-tema-troca]')) return;
    const raiz = document.documentElement;
    const novo = raiz.dataset.tema === 'escuro' ? 'claro' : 'escuro';
    raiz.dataset.tema = novo;
    // Guardar pode falhar (navegador restrito). A troca na tela já
    // aconteceu — o que se perde é só a memória. Engolir aqui é o certo:
    // vale mais um tema que não lembra do que um botão que não faz nada.
    try { localStorage.setItem('tema', novo); } catch (e) {}
  });
})();
</script>"""


def e_pdf(caminho: str | None) -> bool:
    """A evidência é um PDF (proposta por e-mail) e não um print?"""
    return str(caminho or "").lower().endswith(".pdf")


def print_embutido(caminho: str | None) -> str:
    """Embute o print da transportadora na página, em base64.

    Base64 em vez de servir o arquivo: teste_real/ tem CNPJ e valor de nota
    fiscal, e abrir a pasta como estatica exporia todas as cotacoes de todo
    mundo. Provisorio — a ideia e passar a so guardar em pasta.

    Vive aqui porque as DUAS telas que mostram uma cotação precisam dele: a
    do vendedor e a do adm. Ler arquivo é a única coisa não-pura deste
    arquivo, e é o mesmo tipo de leitura que a LOGO lá em cima já faz.

    Caminho vazio ou arquivo que sumiu devolve string vazia: print é prova,
    não obrigação, e uma cotação antiga cujo `runs/` foi apagado precisa
    continuar abrindo."""
    if not caminho or e_pdf(caminho) or not Path(caminho).exists():
        # PDF (a proposta da Della Volpe) não é imagem: embutido num <img>
        # vira ícone quebrado. Quem sabe mostrá-lo é a tela, com um link.
        return ""
    dados = base64.b64encode(Path(caminho).read_bytes()).decode()
    return (f'<img class="print" src="data:image/png;base64,{dados}" '
            f'alt="comprovante da cotacao">')


def entrada(titulo: str, cartao: str, *, chamada: str, apoio: str,
            paradas: tuple[str, ...] = (), rodape: str = "",
            tarja: str = "Cotação de frete") -> str:
    """O casco das telas de entrada: a do vendedor e a do painel.

    Casco próprio, e não `pagina()`, por dois motivos. A faixa do topo existe
    para navegar, e quem ainda não entrou não tem para onde ir — ela aparecia
    ali só mostrando a logo, e o cartão logo abaixo mostrava a MESMA logo de
    novo, uma embaixo da outra. E é a única tela do sistema onde vale gastar
    área com apresentação: vista uma vez por sessão, sem trabalho para
    atrapalhar.

    `paradas` desenha a rota: os pontos por onde a carga passa dentro do
    sistema, do primeiro ao último. Vêm de quem chama porque o número do meio
    é do SISTEMA — `len(AUTOMATICAS)`. Fixo aqui, envelheceria na primeira
    transportadora que entrasse, e uma tela de entrada mentindo sobre o
    tamanho do próprio sistema é pior do que uma sem número nenhum.
    `layout.py` também não pode importar `web.transportadoras` sem correr
    atrás de import circular, e passar por parâmetro custa uma linha.

    O último ponto fica em aberto (só o contorno, e o trecho até ele
    pontilhado): é o preço que ainda não chegou. Linha inteira sólida diria
    que a cotação já acabou.

    `cartao` entra CRU: é HTML montado por quem chama, com o formulário. Tudo
    que vem de fora — chamada, apoio, provas, rodapé — passa por `e()`.
    """
    pontos = []
    for n, parada in enumerate(paradas):
        if n:
            # O trecho até o ÚLTIMO ponto é o que falta percorrer.
            falta = " falta" if n == len(paradas) - 1 else ""
            pontos.append(f'<i class="trecho{falta}"></i>')
        pontos.append('<div class="parada"><i class="ponto"></i>'
                      f"<span>{e(parada)}</span></div>")
    lista = f'<div class="rota">{"".join(pontos)}</div>' if pontos else ""
    fim = f'<p class="rodape">{e(rodape)}</p>' if rodape else ""
    # A chamada quebra em duas linhas, e a SEGUNDA sai no azul da marca. O
    # ponto final é o corte: "Uma carga. Todas as transportadoras." vira
    # branco + azul sem quem escreve precisar saber de HTML. Sem ponto no
    # meio, sai inteira em branco, que é o comportamento de antes.
    titulo_html = e(chamada)
    if ". " in titulo_html:
        antes, _, depois = titulo_html.partition(". ")
        titulo_html = f"{antes}.<br><em>{depois}</em>"
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title>{ICONE_ABA}
<style>{CSS}</style></head><body>
<div class="entrada">
  <aside class="entrada-marca">
    {MALHA_CORREDORES}
    <div class="marca-entrada">
      <span class="logo marca-peca" role="img"
          aria-label="Ventura Comércio"></span>
      <p class="assinatura">{ASSINATURA}</p>
    </div>
    <div>
      <p class="tarja">{e(tarja)}</p>
      <h1>{titulo_html}</h1>
      <p>{e(apoio)}</p>
    </div>
    {lista}
  </aside>
  <main class="entrada-form">
    <div>{cartao}{fim}</div>
  </main>
</div>
</body></html>"""


# O rodapé. Não existia em tela nenhuma do vendedor — a página simplesmente
# acabava. Ele fecha o documento e é o lugar natural da assinatura da marca,
# que no cabeçalho não caberia legível: no lockup ela tem 6px de 120, e numa
# barra de 36px isso vira 1.8px.
#
# `/documentacao` está aqui além do menu do topo de propósito: quem trava no
# meio de uma cotação rola a página atrás de ajuda, e não volta ao topo.
def rodape_do_site(usuario: str | None = None) -> str:
    """O rodapé. Não existia em tela nenhuma do vendedor — a página
    simplesmente acabava.

    Ele fecha o documento e é o lugar natural da ASSINATURA da marca, que no
    cabeçalho não cabe legível: no lockup ela tem 6px de 120, e numa barra de
    36px isso vira 1.8px.

    Os links só existem com sessão, pela mesma regra do menu do topo — e não
    por simetria: `/documentacao` e `/historico` redirecionam para `/login`
    sem cookie, então oferecê-los a quem não entrou é oferecer um caminho que
    devolve a pessoa para onde ela já estava."""
    links = ""
    if usuario:
        links = ('<span class="links">'
                 '<a href="/documentacao">Como usar</a>'
                 '<a href="/historico">Histórico</a></span>')
    return f"""<footer class="rodape-site"><div class="dentro">
  <span class="marca-placa"><span class="marca-peca marca-lockup"
        role="img" aria-label="Ventura Comércio"></span></span>
  <span class="diz"><b>{ASSINATURA}</b>
  Cotafrete — sistema interno de cotação de frete.</span>
  {links}
</div></footer>"""


def cabecalho(titulo: str, *, tarja: str = "", sub: str = "",
              contexto: tuple[tuple[str, str], ...] = (),
              acoes: str = "") -> str:
    """O cabeçalho compacto das telas de trabalho.

    UM componente para as sete telas do vendedor, em vez de um `<h1>` solto e
    um `<p class="sub">` repetidos com espaçamento diferente em cada uma. A
    hierarquia fica: onde estou (tarja), o que é isto (título), o que é esta
    cotação (contexto), o que posso fazer (ações).

    `contexto` são pares (rótulo, valor) — a rota, o peso, a nota fiscal. Eles
    viviam numa frase corrida de seis campos separados por pontos médios, e
    achar o peso ali exigia ler a frase inteira. Em pastilha, com o rótulo em
    versalete e o valor na monoespaçada, o olho vai direto.

    `acoes` e `sub` entram CRUS: são HTML montado por quem chama (botões, um
    `<b>` no meio da frase). Título, tarja e contexto são texto e passam por
    `e()` — é por ali que entra o que o usuário digitou."""
    linha = ""
    if contexto:
        itens = ""
        for n, (rotulo, valor) in enumerate(contexto):
            # A primeira pastilha é a rota, e ela identifica a cotação: ganha
            # a lavagem da marca para o olho achá-la antes das outras cinco.
            classe = ' class="ctx-rota"' if n == 0 else ""
            itens += (f"<li{classe}><span>{e(rotulo)}</span>"
                      f"<b>{e(valor)}</b></li>")
        linha = f'<ul class="contexto">{itens}</ul>'
    return (f'<header class="cab-pagina"><div class="diz">'
            + (f'<p class="tarja">{e(tarja)}</p>' if tarja else "")
            + f"<h1>{e(titulo)}</h1>"
            + (f'<p class="sub">{sub}</p>' if sub else "")
            + linha + "</div>"
            + (f'<div class="acoes">{acoes}</div>' if acoes else "")
            + "</header>")


def pagina(titulo: str, corpo: str, usuario: str | None = None) -> str:
    quem = ""
    if usuario:
        # `<nav>` de verdade, e não um <span> com links dentro: é a navegação
        # principal do sistema, e um leitor de tela precisa poder saltar para
        # ela. `aria-label` porque a página tem duas (esta e a do rodapé).
        quem = ('<span class="quem"><nav class="menu" '
                'aria-label="Navegação principal">'
                '<a href="/">Nova cotação</a><a href="/historico">Histórico</a>'
                '<a href="/me">Mercado Eletrônico</a>'
                '<a href="/documentacao">Documentação</a>'
                f'<a href="/sair">Sair</a></nav> <b>{e(usuario)}</b></span>')
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title>{ICONE_ABA}{cabeca_do_tema("claro")}
<style>{CSS}</style></head><body>
<a class="pular" href="#conteudo">Pular para o conteúdo</a>
<div class="topo"><a class="marca-placa" href="/" aria-label="Ventura Comércio — início"><span class="marca-peca marca-lockup" role="img"></span></a>
{quem}{BOTAO_TEMA}</div>
<main class="wrap" id="conteudo">{corpo}</main>
{rodape_do_site(usuario)}{LUPA}{SCRIPT_TEMA}</body></html>"""
