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
/* marca — mesma matiz 218, um degrau mais FUNDA que a de antes. O azul
   anterior (#0042b5) era azul de meio-tom: bonito e sem peso. Este é tinta
   de impressão, e é o que faz o prateado do lockup parecer prata em vez de
   cinza. Matiz lida de volta do hexadecimal: 219 graus, dentro da folga. */
--marca:#00379e;--marca-forte:#002a7a;--marca-viva:#0a57d6;
--realce:#0046c8;--realce-claro:#2f7cff;--lavagem:#e8eefc;
--marca-grad:linear-gradient(118deg,#2f7cff 0%,#0a57d6 42%,#00379e 100%);
/* O contraponto QUENTE. A paleta era azul sobre azul sobre azul, e tela sem
   nenhum ponto de calor lê como planilha em vez de produto. O cobre NÃO é
   semântico e nunca diz estado: ele marca a sobrancelha das telas, os pontos
   do corredor e o rastro que atravessa a faixa. Fora da matiz da marca de
   propósito — é o único token que pode estar, e por isso está sozinho. */
--cobre:#9a5216;--cobre-claro:#c4762e;--cobre-lavagem:#fbf1e6;
/* neutros com viés azul, agora mais fundos nas duas pontas: a tinta era
   #0f1724 e o fundo #f5f7fb, e pouca distância entre os extremos empurra
   tudo para o meio — nada parece à frente nem atrás de nada. */
--tinta:#0b1220;--tinta2:#3a4a5f;--fraco:#5a6880;
--borda:#dbe1ec;--borda-forte:#bcc6d8;--fundo:#eef2f9;--papel:#fff;
/* A hairline. Borda cheia de 1px em TUDO achata a hierarquia; esta separa
   sem desenhar — linha de tabela e divisória interna de cartão, onde a
   borda cheia era barulho e não informação. */
--linha:#e7ebf3;
/* semânticos: sentido, não marca — mudar estes muda o que a tela AFIRMA */
--ok:#0a6b4f;--erro:#b52d18;--atencao:#8f5100;--zap:#1fb457;
--ok-fraco:#e4f3ed;--erro-fraco:#fdeae6;--atencao-fraco:#fdf4e3;
--atencao-borda:#f0d49a;--atencao-tinta:var(--tinta);
--sobre-marca:#fff;--cova:#f6f8fc;
--brilho-marca:rgba(0,55,158,.42);
/* Os tons do quadro de instrumentos. Moram aqui, e não no CSS do
   painel, porque quem os ESCREVE é o Python (o número do topo sai com
   `style="--cor:..."`), e hexadecimal escrito pelo servidor não muda
   quando a pessoa clica no botão de tema. Token muda. */
--tom-marca:#00379e;--tom-marca-fraco:#e8eefc;
--tom-ok:#0a6b4f;--tom-ok-fraco:#e4f3ed;
--tom-atencao:#8f5100;--tom-atencao-fraco:#fdf4e3;
--tom-erro:#b52d18;--tom-erro-fraco:#fdeae6;
--tom-neutro:#55607a;--tom-neutro-fraco:#edf0f6;
--tom-roxo:#6d34d6;--tom-roxo-fraco:#efe8fd;
--alerta-fundo:#fdf3f0;--alerta-borda:#f3cdc2;--alerta-tinta:#6e3427;
/* elevação: quatro degraus, e não sombra solta por regra. A rampa antiga
   tinha três e pulava do quase-nada (1px) para o modal (44px); o degrau que
   faltava é justamente o do cartão que está SOB o cursor. Todas com dois
   raios — um curto que cola a peça na superfície e um longo e difuso que
   dá a distância. Tinta de sombra puxada para o azul da marca, e não preta:
   preto sobre papel azulado lê como sujeira. */
--sombra-0:0 1px 1px rgba(11,18,32,.04);
--sombra-1:0 1px 2px rgba(11,18,32,.05),0 2px 6px -2px rgba(11,18,32,.06);
--sombra-2:0 2px 4px rgba(11,18,32,.04),0 12px 26px -10px rgba(11,18,32,.16);
--sombra-3:0 20px 50px -14px rgba(11,18,32,.30);
/* raios um degrau maiores em toda a escala: 8/12/16 lia como painel de
   administração de 2015. A pílula ganhou token — estava escrita `99px` em
   onze lugares, e onze lugares é onde uma escala começa a divergir. */
--raio:14px;--raio-p:10px;--raio-g:22px;--raio-pill:999px;
/* ---- escala de espaço ----
   Não existia: cada regra escolhia 6, 7, 9, 11, 13, 14, 16, 18, 20, 22, 24
   e 26px, e o resultado é uma tela sem ritmo nenhum — nada alinha com nada
   porque não há grade a que alinhar. Base 4, que é o menor passo que a
   tipografia deste sistema ainda percebe. */
--e1:4px;--e2:8px;--e3:12px;--e4:16px;--e5:24px;--e6:32px;--e7:48px;--e8:72px;
/* ---- escala tipográfica ----
   Razão ~1.2 embaixo (onde mora a interface) e aberta no topo (onde mora o
   título). Os dois maiores são fluidos: o display de hero precisa encolher
   num celular de 390px sem virar três linhas órfãs. O TRACKING acompanha o
   tamanho — é o que a tela não tinha: 24px e 42px estavam os dois com
   -.5px, e tracking fixo numa escala larga faz o título grande parecer
   solto e o pequeno parecer apertado. */
--t1:11px;--t2:12.5px;--t3:14px;--t4:15px;--t5:17px;--t6:20px;
--t7:clamp(23px,2.2vw,28px);--t8:clamp(30px,4.4vw,46px);
--tr6:-.2px;--tr7:-.5px;--tr8:-1.4px;
/* A sobrancelha: versalete de 10.5px com 1.6px de entreletra. Um estilo, e
   não onze cópias de `text-transform:uppercase;letter-spacing:1px`. */
--t-olho:10.5px;--tr-olho:1.6px;
--suave:cubic-bezier(.2,.6,.3,1);--mola:cubic-bezier(.34,1.32,.46,1);
--calmo:cubic-bezier(.22,.9,.3,1)}
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
--marca:#6ba2ff;--marca-forte:#9cc0ff;--marca-viva:#0a57d6;
--realce:#6ba2ff;--realce-claro:#8ab5ff;--lavagem:#18243d;
/* O cobre, no escuro, é o mesmo papel com a luminância que o fundo exige:
   #9a5216 sobre o cartão escuro dá 1.6:1 e sumiria. 7.9:1 aqui. */
--cobre:#e8a06a;--cobre-claro:#f0b98c;--cobre-lavagem:#2b1f14;
/* O que se escreve EM CIMA de um preenchimento da marca. Herdar o #fff do
   claro daria 2.6:1 sobre o azul claro: o botão sumiria por dentro. */
--sobre-marca:#061021;
/* neutros: 14.7:1, 10.2:1 e 6.7:1 sobre o cartão */
--tinta:#e9edf5;--tinta2:#bfc8d8;--fraco:#95a2b9;
--borda:#28374f;--borda-forte:#42587c;--fundo:#04101f;--papel:#0e1b30;
/* A hairline do escuro é mais FRACA que a borda, não mais forte: aqui quem
   separa é o degrau de luminância, e a linha só o confirma. */
--linha:#1d2a41;
/* Um degrau ABAIXO do papel, para o que é buraco e não cartão: campo de
   digitar, caixa de texto técnico, ficha dentro do cartão. No claro esse
   papel é o próprio branco e o buraco se faz com borda; no escuro é a
   luminância que separa, então o buraco precisa existir como cor. */
--cova:#081426;
/* Semânticos: o SENTIDO é o mesmo, só a luminância sobe. Verde 9.3:1, âmbar
   8.4:1, vermelho 7.9:1 sobre o cartão — contra 3.7, 5.2 e 2.8 que as cores
   claras dariam aqui. O vermelho de falha, no escuro, era ilegível. */
--ok:#3ed69a;--erro:#ff9179;--atencao:#e8a94e;
/* As lavagens de cada semântico: o fundo das pílulas e dos avisos. */
--ok-fraco:#0f2a22;--erro-fraco:#2c1e1c;--atencao-fraco:#2a2314;
--atencao-borda:#5a4820;--atencao-tinta:#ecd3a2;
--brilho-marca:rgba(107,162,255,.55);
/* Os mesmos tons, com a luminância que o fundo escuro exige. O pior é
   o roxo, com 6.1:1 sobre o cartão; no claro o vermelho de falha dava
   2.8:1 aqui e não passava nem como gráfico (SC 1.4.11). */
--tom-marca:#6ba2ff;--tom-marca-fraco:#16233c;
--tom-ok:#3ed69a;--tom-ok-fraco:#0f2a22;
--tom-atencao:#e8a94e;--tom-atencao-fraco:#2a2314;
--tom-erro:#ff9179;--tom-erro-fraco:#2c1e1c;
--tom-neutro:#95a2b9;--tom-neutro-fraco:#1c2440;
--tom-roxo:#ac92fb;--tom-roxo-fraco:#212645;
--alerta-fundo:#281815;--alerta-borda:#582f26;--alerta-tinta:#e3ae9f;
/* No escuro sombra não separa nada: quem separa é o degrau de luminância
   entre o fundo e o papel. A sombra fica só para dizer o que está POR CIMA
   quando o cursor levanta um cartão. */
--sombra-0:0 1px 1px rgba(0,0,0,.35);
--sombra-1:0 1px 2px rgba(0,0,0,.42);
--sombra-2:0 12px 30px -10px rgba(0,0,0,.62);
--sombra-3:0 22px 52px -14px rgba(0,0,0,.78);
/* Diz ao NAVEGADOR que a página é escura, para ele pintar de escuro o que
   desenha sozinho: barra de rolagem, cursor de texto, caixa de seleção. Sem
   isto a barra de rolagem branca era a coisa mais clara da tela. */
color-scheme:dark}

/* ---- o que ficou cravado em claro quando o sistema só tinha um tema -------
   Token nenhum alcança um `#fffae6` escrito dentro de uma regra. São estes,
   e ficam juntos para quem for mexer no tema achar num lugar só, em vez de
   caçar um fundo branco perdido no meio do arquivo. */
[data-tema="escuro"] fieldset{background:#0b1728}
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
[data-tema="escuro"] .filtro.parcial>summary:hover{background:#352c15}
[data-tema="escuro"] .alerta.email{background:var(--lavagem);
border-color:var(--borda-forte);color:var(--tinta2)}
[data-tema="escuro"] .selo-obs{background:var(--atencao-fraco);
border-color:var(--atencao-borda)}

/* Texto escrito EM CIMA de um preenchimento: o #fff do claro dá 1.7:1 sobre
   o verde e 2.6:1 sobre o azul claro da marca. */
[data-tema="escuro"] .selo{color:#06110d}
/* `:not(.tema)` porque esta regra fala de texto sobre PREENCHIMENTO da
   marca, e o botão de tema não tem preenchimento nenhum — ele é um contorno
   sobre o papel. Sem o `:not`, o seletor com atributo (0,1,1) ganhava do
   `.tema` (0,1,0) e pintava o ícone do sol de #0b0f1c, que é a cor do fundo
   da página: o sol ficava desenhado em preto sobre preto, presente na tela e
   invisível para quem olha. */
[data-tema="escuro"] button:not(.tema){color:var(--sobre-marca)}
[data-tema="escuro"] .selo-zap{background:var(--ok-fraco)}
[data-tema="escuro"] .zap.aberta{background:#0b1728;border-color:#1e4a35}

/* A tabela do resultado. O verde da linha vencedora vira um verde de FUNDO
   escuro: no claro ele é uma lavagem, e lavagem clara no escuro é um rasgo
   branco no meio da tabela. */
[data-tema="escuro"] table.resultados th{background:#0b1728}
[data-tema="escuro"] tr.r.melhor td{background:#102a22}
[data-tema="escuro"] tr.r.melhor:hover td{background:#14332a}
[data-tema="escuro"] tr.r-extra td{background:#0b1728}
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
/* 38px, e não 34: o alvo mínimo confortável de toque num sistema usado
   também no celular. E sem sombra — ele é contorno, não peça elevada. */
.tema{display:inline-flex;align-items:center;justify-content:center;
width:38px;height:38px;padding:0;flex:none;border-radius:var(--raio-pill);
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
/* ---- as duas famílias ----
   Nenhuma fonte baixada: o sistema roda em rede interna e fonte que não
   chegou é texto pulando na cara de quem já começou a ler. O que muda é que
   agora são DUAS pilhas com trabalhos diferentes, e não uma só para tudo.

   A de TÍTULO pede primeiro os cortes de display que o Windows e o macOS já
   têm instalados ("Segoe UI Variable Display", "SF Pro Display"): eles têm
   o desenho mais fechado e a haste mais firme que um título de 46px precisa.
   Onde não existirem, cai na mesma system-ui do corpo — e aí quem separa
   título de texto é o tamanho, o peso e o tracking, que é o grosso do
   trabalho de qualquer jeito. */
:root{
--fonte:system-ui,-apple-system,"Segoe UI Variable Text","Segoe UI",
  Roboto,"Helvetica Neue",sans-serif;
--fonte-titulo:"Segoe UI Variable Display","SF Pro Display",system-ui,
  -apple-system,"Segoe UI",Roboto,sans-serif;
--fonte-num:ui-monospace,"Cascadia Mono",Consolas,"SF Mono",monospace}
body{margin:0;background:var(--fundo);color:var(--tinta);line-height:1.55;
font-family:var(--fonte);font-size:var(--t4);
-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
/* O sistema é uma tela de números: peso, cubagem, preço. Dígito de largura
   fixa faz as colunas de dinheiro alinharem sem tabela e sem monoespaçada. */
font-variant-numeric:tabular-nums}
/* Entrelinha 1.55 no corpo é leitura; num TÍTULO ela vira um buraco entre as
   duas linhas. Cada degrau da escala tem a sua, e a dos grandes é apertada. */
h1,h2,h3{font-family:var(--fonte-titulo);line-height:1.18;margin:0;
font-weight:700}
a{color:var(--marca);text-underline-offset:3px}
a:hover{color:var(--marca-forte)}

/* ---- a sobrancelha ----
   O rótulo curto que vem ACIMA do título e diz de que parte do sistema a
   tela é. Existe porque cada página começava com um <h1> solto e mais nada:
   sem o degrau de cima, o título tem de carregar sozinho o contexto inteiro
   e acaba comprido demais para o tamanho em que está escrito.

   É onde o cobre trabalha. Um traço curto antes do texto, e não uma pílula:
   pílula pesa igual a um selo de estado, e isto não afirma estado nenhum. */
.olho{display:flex;align-items:center;gap:var(--e2);margin:0 0 var(--e2);
font-size:var(--t-olho);letter-spacing:var(--tr-olho);text-transform:uppercase;
font-weight:700;color:var(--cobre);font-family:var(--fonte)}
.olho::before{content:"";width:18px;height:2px;border-radius:2px;
background:currentColor;flex:none}

/* ---- pular para o conteúdo ----
   Quem navega por teclado batia nas quatro abas do topo em TODA página antes
   de chegar na tabela que veio ver. Escondido fora da tela até receber foco,
   e aí ele aparece por cima da barra — que gruda, e taparia o link se ele
   só "voltasse para o fluxo". */
.pular{position:fixed;left:var(--e4);top:-100px;z-index:50;
background:var(--marca);color:#fff;padding:var(--e3) var(--e4);
border-radius:var(--raio-p);font-size:var(--t3);font-weight:600;
text-decoration:none;box-shadow:var(--sombra-3);
transition:top .18s var(--suave)}
.pular:focus{top:var(--e3);color:#fff}
/* A âncora do <main>: sem isto o salto encosta o conteúdo na borda de cima e
   a barra grudada cobre a primeira linha do que a pessoa acabou de pedir. */
#conteudo{scroll-margin-top:84px}

/* Movimento é enfeite até virar obstáculo. Quem pediu para o sistema parar de
   se mexer não pode receber um formulário que entra deslizando. Uma regra, no
   topo, valendo para todas as telas — inclusive as do painel, que empilha
   o seu CSS depois deste. */
@media(prefers-reduced-motion:reduce){
*,*::before,*::after{animation-duration:.01ms !important;
animation-iteration-count:1 !important;transition-duration:.01ms !important;
scroll-behavior:auto !important}}

/* ---- faixa do topo ----
   Passou a GRUDAR. A página da cotação tem sete cartões e o histórico cresce
   sem teto: sair de onde se está para trocar de aba exigia rolar de volta ao
   começo. Grudada, a navegação existe o tempo todo e a tela deixa de ter um
   "topo" ao qual se precisa voltar.

   Fundo translúcido com `backdrop-filter`: por baixo dela passa conteúdo, e
   um branco chapado apagaria a informação de que há mais coisa acima. Onde o
   navegador não tiver o filtro, o `--papel` do fallback cobre — a barra fica
   opaca, que é o pior caso aceitável. */
.topo{background:color-mix(in srgb,var(--papel) 82%,transparent);
backdrop-filter:saturate(1.6) blur(14px);
-webkit-backdrop-filter:saturate(1.6) blur(14px);
border-bottom:1px solid var(--linha);
padding:var(--e3) var(--e5);display:flex;align-items:center;gap:var(--e4);
position:sticky;top:0;z-index:20}
@supports not (backdrop-filter:blur(1px)){.topo{background:var(--papel)}}
/* O filete do gradiente da logo, atravessando a tela inteira. É a assinatura
   da marca no lugar mais barato possível: 3px que nenhuma outra tela de
   sistema interno tem, e que ninguém precisa ler para reconhecer. */
.topo::before{content:"";position:absolute;left:0;right:0;top:0;height:3px;
background:var(--marca-grad)}
.topo img{height:36px}
.topo .quem{margin-left:auto;font-size:var(--t2);color:var(--fraco);
display:flex;align-items:center;gap:var(--e3)}
/* O nome de quem está logado, em pastilha. Solto, ele era texto cinza no
   meio de mais texto cinza — e é a única coisa da barra que responde
   "quem sou eu aqui". */
.topo .quem>b{background:var(--lavagem);color:var(--marca-forte);
border-radius:var(--raio-pill);padding:5px var(--e3);font-size:var(--t2);
font-weight:700;white-space:nowrap}
[data-tema="escuro"] .topo .quem>b{color:var(--marca-forte)}
/* Mais larga (era 1080) e com respiro maior em cima. A tabela de resultados
   tem seis colunas e vivia espremida; 1140 dá a coluna "o que inclui" de
   volta sem que a linha de texto passe do confortável. */
.wrap{width:100%;max-width:1140px;margin:var(--e6) auto var(--e5);
padding:0 var(--e5)}
@media(max-width:620px){
.topo{padding:var(--e2) var(--e4);gap:var(--e2)}
.wrap{margin-top:var(--e5);padding:0 var(--e4)}
}

/* Entrada em cascata. O formulário tem cinco blocos; todos aparecendo no
   mesmo quadro é um susto, escalonados o olho acompanha de cima para baixo. */
/* Nome com sufixo: web/painel_ui.py empilha o CSS dele depois
   deste e ja tem um @keyframes `sobe` proprio, das barras do
   grafico. Dois com o mesmo nome na mesma folha e o de baixo
   ganha em silencio. */
@keyframes sobe-bloco{from{opacity:0;transform:translateY(10px)}
to{opacity:1;transform:none}}
/* O cartão. Mais ar por dentro (era 20px em volta de tudo), raio maior, e a
   sombra rasa do primeiro degrau — a borda continua sendo quem desenha o
   limite, a sombra só o descola do fundo. */
.cartao{background:var(--papel);border:1px solid var(--borda);
border-radius:var(--raio);padding:var(--e5);margin-bottom:var(--e4);
box-shadow:var(--sombra-1);animation:sobe-bloco .42s var(--suave) both}
@media(max-width:620px){.cartao{padding:var(--e4)}}
/* Título maior e com o tracking da própria faixa da escala. Ele era 24px com
   -.5px em toda tela, do login à ficha — um tamanho só para sete telas de
   densidade diferente. */
h1{font-size:var(--t7);margin:0 0 var(--e1);letter-spacing:var(--tr7)}
h2{font-size:var(--t6);letter-spacing:var(--tr6)}
.sub{color:var(--fraco);font-size:var(--t3);margin:0 0 var(--e5);
max-width:72ch}
/* ---- cabeçalho de página ----
   Sobrancelha, título, apoio e ações numa peça só. Existe porque sete telas
   montavam isso à mão, cada uma com a sua margem, e a diferença aparecia ao
   trocar de aba: o título pulava alguns pixels para o lado e para baixo.

   COMPACTO de propósito. O hero grande é da entrada e do início; tela de
   trabalho não pode gastar a primeira dobra se apresentando — quem chega no
   histórico veio ler uma linha da tabela. */
.cabeca{display:flex;align-items:flex-end;gap:var(--e4);flex-wrap:wrap;
margin:0 0 var(--e5);padding-bottom:var(--e4);
border-bottom:1px solid var(--linha)}
.cabeca>div:first-child{min-width:0;flex:1 1 320px}
.cabeca h1{margin:0}
.cabeca .sub{margin:var(--e2) 0 0}
.cabeca .acoes{margin-left:auto;display:flex;align-items:center;
gap:var(--e2);flex-wrap:wrap}
@media(max-width:620px){
.cabeca{gap:var(--e3)}
.cabeca .acoes{margin-left:0;width:100%}
}
fieldset{border:1px solid var(--borda);border-radius:var(--raio-p);
margin:0 0 var(--e4);padding:var(--e4) var(--e4) var(--e4);
background:var(--cova)}
legend{font-size:var(--t-olho);font-weight:700;color:var(--marca);
padding:0 var(--e2);text-transform:uppercase;
letter-spacing:var(--tr-olho)}
.grid{display:grid;gap:var(--e3);
grid-template-columns:repeat(auto-fit,minmax(158px,1fr))}
label{display:block;font-size:var(--t1);color:var(--tinta2);
margin-bottom:var(--e1);font-weight:600;letter-spacing:.2px}
input{width:100%;padding:11px var(--e3);border:1px solid var(--borda-forte);
border-radius:var(--raio-p);font-size:var(--t4);font-family:inherit;
background:var(--papel);color:var(--tinta);
transition:border-color .16s var(--suave),box-shadow .16s var(--suave)}
input:hover{border-color:var(--fraco)}
/* O azul de realce da marca: o anel de foco é a peça que mais aparece
   num sistema onde se digita o dia inteiro, e era o contorno cinza do
   navegador. O anel sai do TOKEN da marca, e não de um rgba escrito à mão —
   era o mesmo `rgba(82,145,255,.35)` em quatro regras, e o azul dele já não
   é o azul da marca desde que a paleta ficou mais funda. */
input:focus{outline:0;border-color:var(--realce);
box-shadow:0 0 0 3px var(--brilho-marca)}
button{font:inherit;cursor:pointer;border:0;border-radius:var(--raio-p);
background:var(--marca);color:#fff;padding:12px var(--e5);font-weight:600;
font-size:var(--t4);letter-spacing:.1px;box-shadow:var(--sombra-1);
transition:transform .16s var(--mola),box-shadow .16s var(--suave),
background .16s var(--suave)}
button:hover{background:var(--marca-forte);transform:translateY(-1px);
box-shadow:var(--sombra-2)}
/* Afunda no clique. Num formulário que dispara cinco navegadores e leva dois
   minutos, o retorno imediato do botão é o que diz "recebi" antes de a
   primeira transportadora responder. */
button:active{transform:translateY(1px);box-shadow:var(--sombra-1)}
/* Anel de foco em DUAS camadas: um vazio da cor da superfície e o traço da
   marca por fora. Um anel só encosta na borda do elemento e, sobre um botão
   preenchido da mesma família de cor, some dentro dele. */
button:focus-visible,a:focus-visible,summary:focus-visible,
input:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--realce);
outline-offset:2px;box-shadow:0 0 0 2px var(--papel)}

.falhou{color:var(--erro);font-size:13px;font-weight:600}
/* "Enviada" NAO pode usar o vermelho de falha nem o verde de preco: nao deu
   errado e nao ha numero para comparar. Fica na cor da marca, no tamanho que
   ocupa o lugar do preco - o olho passa pelos cartoes procurando o numero
   grande, e precisa parar aqui em vez de saltar. */
.enviada{color:var(--marca);font-size:20px;font-weight:700;margin:6px 0 2px}
.selo{display:inline-block;font-size:10px;font-weight:700;color:#fff;
background:var(--ok);border-radius:var(--raio-pill);padding:3px 9px;
letter-spacing:.6px;text-transform:uppercase;vertical-align:middle}
.zap{display:flex;align-items:center;gap:10px;border:1px solid var(--borda);
border-radius:var(--raio-p);padding:11px 13px;text-decoration:none;
color:inherit;margin-bottom:8px;background:var(--papel);
transition:border-color .16s var(--suave),transform .16s var(--suave),
box-shadow .16s var(--suave)}
.zap:hover{border-color:var(--zap);transform:translateX(2px);
box-shadow:var(--sombra-1)}
/* Já aberta: fica apagada para o olho cair na próxima da lista sozinho, sem
   precisar de seta nem de "next". O visto verde diz que passou por ali. */
.zap.aberta{background:var(--cova);border-color:var(--ok-fraco)}
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
color:var(--atencao);background:var(--atencao-fraco);
border:1px solid var(--atencao-borda);
border-radius:var(--raio-pill);padding:2px 9px;letter-spacing:.2px;
margin-left:4px}
/* A Della Volpe fica sozinha no cartão "Semiautomática", e o botão maior é o
   que diz "comece por aqui" sem precisar de mais nenhuma frase. */
.zap-dv{padding:16px 18px;margin-bottom:0;border-color:var(--zap)}
.zap-dv .marca{width:60px;height:60px}
.zap-dv b{font-size:16px}
.zap-dv .ir{font-size:14px;padding:11px 19px}
table{width:100%;border-collapse:collapse;font-size:var(--t3)}
th{text-align:left;font-size:var(--t-olho);color:var(--fraco);
text-transform:uppercase;letter-spacing:var(--tr-olho);
padding:var(--e2) var(--e3);border-bottom:1px solid var(--borda);
font-weight:700;white-space:nowrap}
td{padding:var(--e3);border-bottom:1px solid var(--linha)}
/* A linha sob o cursor ganha um filete da marca à ESQUERDA, além do fundo.
   Só o fundo lavado some numa tabela de dez linhas vistas de relance; o
   filete diz qual linha responde ao clique — e no histórico a linha
   inteira é clicável. `inset` e não borda: borda empurraria a coluna. */
tr:hover td{background:var(--lavagem)}
tr:hover td:first-child{box-shadow:inset 2px 0 0 var(--marca)}
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
/* Aviso e alerta saem dos TOKENS do âmbar, e não de um #fffae6 cravado: era
   por isso que o bloco "o que ficou em claro" lá em cima precisava existir —
   nenhum token alcançava um hexadecimal escrito dentro da regra. */
.aviso{background:var(--atencao-fraco);border:1px solid var(--atencao-borda);
border-left:3px solid var(--atencao);border-radius:var(--raio-p);
padding:var(--e3) var(--e4);font-size:var(--t3);margin-bottom:var(--e4);
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
padding:10px var(--e4);font-size:var(--t3);font-weight:600;
text-decoration:none;box-shadow:var(--sombra-0);
transition:border-color .16s var(--suave),background .16s var(--suave),
transform .16s var(--suave),box-shadow .16s var(--suave)}
.botao2:hover{border-color:var(--marca);background:var(--lavagem);
transform:translateY(-1px);box-shadow:var(--sombra-1);color:var(--marca-forte)}
.botao2:active{transform:translateY(0);box-shadow:none}
.login{max-width:380px;margin:70px auto;text-align:center;
animation:sobe-bloco .5s var(--suave) both}
.login img{height:64px;margin-bottom:18px}
/* ---- o menu do topo, agora em abas ----
   Eram quatro links soltos com um sublinhado que crescia do centro no hover:
   bonito, e sem dizer NUNCA em que aba a pessoa está. Como pastilha, o
   estado de repouso já carrega a informação que o hover carregava — e o
   alvo de clique passa dos 13px de altura da letra para a pastilha inteira.

   Sem `.atual` no HTML: o casco não sabe qual rota está aberta, e inventar
   um parâmetro para isso mudaria a assinatura de `pagina()` em sete telas.
   O que a pastilha resolve é o alvo e o peso; a página já diz onde está pelo
   próprio <h1>. */
.menu{display:flex;align-items:center;gap:var(--e1);flex-wrap:wrap}
.menu a{font-size:var(--t2);text-decoration:none;color:var(--tinta2);
padding:7px var(--e3);border-radius:var(--raio-pill);font-weight:600;
transition:background .16s var(--suave),color .16s var(--suave)}
.menu a:hover{background:var(--lavagem);color:var(--marca-forte)}
@media(max-width:820px){
/* No celular a barra não cabe com quatro pastilhas e o nome: some o texto
   e ficam os dois que a pessoa usa de dentro de uma cotação. */
.menu a:nth-child(3){display:none}
.topo .quem>b{max-width:9ch;overflow:hidden;text-overflow:ellipsis}
}
/* Aviso DENTRO do cartão, colado no preço que ele qualifica. Numa faixa no
   topo da página ele seria lido antes do número e esquecido depois. */
/* Aba de Documentacao. Escopo proprio: o resto do sistema quase nao usa
   texto corrido, e soltar estilo de <h2>/<ul> no global mexeria nas telas
   de cotacao. */
/* Título de seção com um filete da marca à esquerda, e não só cor: numa
   página de texto corrido de 1500px a cor sozinha não marca onde uma seção
   acaba e a outra começa — quem varre a página procura um degrau, não um
   tom. O filete sai para fora do fluxo do texto, no respiro do cartão. */
.doc h2{font-size:var(--t5);margin:var(--e6) 0 var(--e2);color:var(--marca);
letter-spacing:var(--tr6);position:relative;padding-left:var(--e4);
scroll-margin-top:84px}
.doc h2::before{content:"";position:absolute;left:0;top:.18em;bottom:.18em;
width:3px;border-radius:3px;background:var(--marca-grad)}
.doc h2:first-child{margin-top:0}
.doc p{margin:0 0 var(--e3);font-size:var(--t4);max-width:76ch}
.doc ul{margin:0 0 var(--e3);padding-left:var(--e5);font-size:var(--t4);
max-width:76ch}
.doc li{margin-bottom:var(--e2)}
.doc table{margin-bottom:var(--e3)}
.doc td{vertical-align:top}
.doc .errado{color:var(--erro);font-weight:600}
.doc .certo{color:var(--ok);font-weight:600}
.doc .passo{font-size:var(--t4);margin:0 0 var(--e3);padding-left:var(--e5)}

/* ---- o fluxo assistido da Della Volpe ----
   Eram nove parágrafos seguidos, com "Passo 1", "Passo 2" em negrito no meio
   do texto — e quatro prints do mesmo tamanho entre eles. Quem está no passo
   3 com a aba da transportadora aberta ao lado precisa achar o passo 3 de
   relance, e "negrito no meio do parágrafo" não é um degrau que o olho ache
   de relance.

   `<ol>` de verdade: o número sai da LISTA, e não de texto escrito à mão —
   inserir um passo no meio renumerava tudo à mão, e já renumerou errado.
   O contador é desenhado no `::before` porque o marcador nativo não aceita
   nem o disco nem a cor. */
.passos-lista{list-style:none;counter-reset:passo;margin:0;padding:0}
.passos-lista>li{counter-increment:passo;position:relative;
padding:0 0 var(--e5) var(--e7);margin:0}
/* O fio que liga um passo ao seguinte. É o que transforma quatro blocos
   soltos numa sequência — e some no último, que não leva a lugar nenhum. */
.passos-lista>li::after{content:"";position:absolute;left:15px;
top:38px;bottom:var(--e3);width:2px;background:var(--linha)}
.passos-lista>li:last-child{padding-bottom:0}
.passos-lista>li:last-child::after{display:none}
.passos-lista>li::before{content:counter(passo);position:absolute;left:0;
top:0;width:32px;height:32px;border-radius:50%;
display:grid;place-items:center;background:var(--marca);color:#fff;
font-size:var(--t3);font-weight:700;font-variant-numeric:tabular-nums;
box-shadow:0 0 0 4px var(--papel)}
.passos-lista>li>h2{font-size:var(--t5);letter-spacing:var(--tr6);
margin:var(--e1) 0 var(--e2);display:flex;align-items:center;gap:var(--e3);
flex-wrap:wrap}
.passos-lista>li>p{margin:0 0 var(--e3);font-size:var(--t4);max-width:72ch}
.passos-lista .sub{margin:var(--e2) 0 0}
.passos-lista .print{max-width:560px}
/* "só na primeira vez" não é parte do título: é uma ressalva sobre ele, e
   sem separação visual o passo 1 parecia opcional por inteiro. */
.so-uma-vez{font-size:var(--t1);font-weight:700;text-transform:uppercase;
letter-spacing:var(--tr-olho);color:var(--cobre);
background:var(--cobre-lavagem);border-radius:var(--raio-pill);
padding:3px var(--e2);font-family:var(--fonte)}
@media(max-width:620px){
.passos-lista>li{padding-left:var(--e6)}
.passos-lista>li::before{width:26px;height:26px;font-size:var(--t2)}
.passos-lista>li::after{left:12px;top:32px}
}
.alerta{background:var(--atencao-fraco);border:1px solid var(--atencao-borda);
border-left:3px solid var(--atencao);border-radius:var(--raio-p);
padding:var(--e2) var(--e3);font-size:var(--t2);margin:var(--e2) 0 var(--e1);
line-height:1.45;color:var(--atencao-tinta)}
/* Amarelo e para "cuidado, esse numero engana". Aqui nao ha erro nenhum: e
   instrucao de onde olhar. Azul separa os dois recados. */
.alerta.email{background:var(--lavagem);border-color:var(--borda-forte);
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
.filtro.parcial{border-color:var(--atencao-borda);
background:var(--atencao-fraco);box-shadow:inset 3px 0 0 var(--atencao)}
.filtro.parcial>summary{color:var(--atencao);font-weight:700}
.filtro.parcial>summary:hover{background:#faeed5}
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
.selo-zap{font-size:10px;background:var(--ok-fraco);color:var(--ok);
border-radius:var(--raio-pill);padding:2px 8px;font-weight:700;flex:none}
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
.opcao:hover{border-color:var(--fraco);background:var(--cova)}
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
.pronto{width:100%;font-family:var(--fonte-num);font-size:var(--t3);
        line-height:1.6;padding:var(--e4);border:1px solid var(--borda-forte);
        border-radius:var(--raio-p);background:var(--cova);color:var(--tinta);
        resize:vertical}
.pronto:focus{outline:0;border-color:var(--realce);
box-shadow:0 0 0 3px var(--brilho-marca)}
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
.entrada{min-height:100vh;display:grid;grid-template-columns:1.14fr .86fr;
background:var(--noite);color:#e9edf5}
/* A noite da entrada é um token PRÓPRIO, e não o `--fundo` do tema escuro:
   esta tela é escura por desenho nos dois temas, e amarrá-la ao tema faria
   a porta da frente clarear no dia em que alguém mexesse no botão. */
:root{--noite:#04101f;--noite2:#0c1c33;--noite3:#132845}
.entrada-marca{position:relative;overflow:hidden;
padding:clamp(34px,4.6vw,68px);display:flex;flex-direction:column;
justify-content:center;gap:clamp(28px,3.6vw,44px);
background:linear-gradient(152deg,var(--noite3) 0%,var(--noite2) 48%,
var(--noite) 100%)}
/* Dois clarões fora de eixo. O índigo chapado é uma parede; os halos dão
   profundidade sem desenhar nada e sem depender de arquivo de imagem — o
   sistema roda em rede interna, e imagem que não chegou é buraco na tela.
   O de baixo virou COBRE: o azul sobre azul não separava os dois, e o
   quente é o que diz que há mais de uma coisa acontecendo no fundo. */
.entrada-marca::before,.entrada-marca::after{content:"";position:absolute;
border-radius:50%;pointer-events:none}
.entrada-marca::before{inset:-30% auto auto -20%;width:58%;aspect-ratio:1;
background:radial-gradient(circle,rgba(47,124,255,.26),transparent 66%)}
.entrada-marca::after{inset:auto -22% -36% auto;width:60%;aspect-ratio:1;
background:radial-gradient(circle,rgba(154,82,22,.30),transparent 68%)}
.entrada-marca>*{position:relative;z-index:1}

/* ============================ o corredor ==================================
   O desenho animado do hero. Não é enfeite de fundo: é o que o sistema FAZ,
   visto de cima — faixas paralelas de transporte, um nó em cada ponta, e um
   sinal que percorre a faixa do meio da origem até o destino.

   SVG e CSS, sem biblioteca. O sistema não tem framework nenhum e não vai
   ganhar um por causa de uma animação de tela de login; o desenho inteiro
   são doze elementos e quatro @keyframes.

   FINITO de propósito. As faixas se traçam uma vez; os nós acendem uma vez;
   o sinal atravessa TRÊS vezes e para no destino. Uma animação que não
   termina numa tela onde a pessoa está digitando a senha é uma coisa se
   mexendo no canto do olho para sempre — e `prefers-reduced-motion`, lá no
   topo, já corta tudo para quem pediu.

   `aria-hidden` no elemento: não há informação aqui que o texto ao lado já
   não diga. Um leitor de tela lendo "corredor, gráfico" ganharia ruído. */
.corredor{position:absolute;inset:0;width:100%;height:100%;
object-fit:cover;pointer-events:none;z-index:0;opacity:.85}
/* Toda faixa leva `pathLength="100"` no SVG: o comprimento do traçado passa
   a ser 100 unidades para o CSS, qualquer que seja a geometria real. Sem
   isso o tracejado tem de ser calculado por caminho — e basta mexer numa
   curva para a animação parar de cobrir a linha inteira, em silêncio. */
.corredor .faixa-c{fill:none;stroke:rgba(107,162,255,.22);stroke-width:1.5;
stroke-linecap:round;stroke-dasharray:100;stroke-dashoffset:100;
animation:corredor-traca 1.6s var(--calmo) both}
.corredor .faixa-c.viva{stroke:rgba(107,162,255,.55);stroke-width:2.5}
.corredor .faixa-c.quente{stroke:rgba(196,118,46,.34)}
@keyframes corredor-traca{to{stroke-dashoffset:0}}
/* O sinal: um risco curto que corre POR CIMA da faixa viva, usando a mesma
   geometria. Dois dashes — o aceso e o vazio do resto do caminho — e o que
   se anima é o deslocamento. É o truque mais barato que existe para mover
   ao longo de uma curva sem `offset-path` e sem script.

   O vão de 200 contra o risco de 6 não é exagero: com vão curto o padrão se
   repete dentro do próprio caminho e nasce um SEGUNDO risco atrás do
   primeiro, bem quando o primeiro está saindo. */
.corredor .sinal{fill:none;stroke:#8ab5ff;stroke-width:3.5;
stroke-linecap:round;filter:drop-shadow(0 0 7px rgba(138,181,255,.9));
stroke-dasharray:6 200;stroke-dashoffset:6;
animation:corredor-sinal 3.4s var(--suave) 1.1s 3 both}
@keyframes corredor-sinal{to{stroke-dashoffset:-100}}
.corredor .no{fill:var(--noite);stroke:#6ba2ff;stroke-width:2.5;
transform-box:fill-box;transform-origin:center;
animation:corredor-no .5s var(--mola) both}
.corredor .no.fim{stroke:#c4762e}
.corredor .halo{fill:none;stroke:rgba(107,162,255,.30);stroke-width:1.2;
transform-box:fill-box;transform-origin:center;
animation:corredor-halo .8s var(--calmo) both}
@keyframes corredor-no{from{opacity:0;transform:scale(0)}
to{opacity:1;transform:none}}
@keyframes corredor-halo{from{opacity:0;transform:scale(.4)}
to{opacity:1;transform:none}}
/* Em cores naturais, sobre uma pastilha branca. `brightness(0) invert(1)`
   pintaria o desenho inteiro de branco — e o "V" da marca é um RECORTE, já
   branco: some contra a elipse e a logo vira um borrão. Passa despercebido na
   lateral do painel, onde ela tem 30px; aqui é a primeira coisa que se vê. */
/* Sem placa atrás: esta tela é escura por desenho, e a peça da marca tem
   fundo vazado — ela se apoia no próprio fundo da tela. */
.marca-entrada{align-self:flex-start}
/* A entrada é escura por desenho: sempre a peça prateada, sem o par
   claro que o resto do sistema tem. */
.entrada-marca .logo{height:clamp(52px,5.4vw,76px);aspect-ratio:469/120;
background-image:url({MARCA_COMPACTA})}
/* A assinatura da marca, em TEXTO: dentro do lockup ela tem 6px de 120 e só
   se lê a partir de ~180px de altura da peça inteira. Aqui ela acompanha a
   largura da logo e fica legível em qualquer tela. */
.entrada-marca .assinatura{margin:var(--e3) 0 0;font-size:11px;
letter-spacing:2.6px;text-transform:uppercase;color:rgba(255,255,255,.58);
font-weight:600;white-space:nowrap;
display:flex;align-items:center;gap:var(--e3)}
/* O filete que sai da assinatura para a borda do painel. Amarra o bloco da
   marca ao corredor desenhado atrás dele — sem ele a logo fica boiando num
   canto, sem relação nenhuma com o resto da composição. */
.entrada-marca .assinatura::after{content:"";height:1px;flex:1;
background:linear-gradient(90deg,rgba(255,255,255,.28),transparent)}
/* Numa tela estreita a entrelinha larga faria a frase estourar a coluna:
   ela aperta em vez de quebrar no meio de "SÓ LUGAR". */
@media(max-width:520px){
.entrada-marca .assinatura{letter-spacing:1.4px;font-size:10px}
}
/* A sobrancelha do hero, em cobre sobre a noite. É o único lugar onde o
   cobre aparece em cima do azul escuro, e é por isso que ele existe. */
.entrada-marca .olho{color:var(--cobre-claro);margin-bottom:var(--e3)}
.entrada-marca h1{font-size:var(--t8);line-height:1.06;
margin:0 0 var(--e4);letter-spacing:var(--tr8);color:#fff;
font-family:var(--fonte-titulo);text-wrap:balance}
.entrada-marca p{margin:0;max-width:44ch;font-size:var(--t5);line-height:1.6;
color:rgba(255,255,255,.74);text-wrap:pretty;font-weight:400}

/* ---- a rota ----
   Não é enfeite: é o que o sistema FAZ, desenhado. Uma carga entra, as
   automáticas cotam, sai o melhor preço. O número de paradas do meio sai de
   `len(AUTOMATICAS)`, passado por quem chama — escrito à mão, a tela passaria
   a mentir sobre o tamanho do sistema na primeira transportadora que
   entrasse.

   Faixa própria embaixo do texto, e não um traçado atrás dele: fundo que
   cruza o parágrafo briga com a leitura em alguma largura de tela, sempre. */
/* A rota ganhou uma FAIXA por baixo: um retângulo de vidro que a separa do
   parágrafo acima. Solta sobre o gradiente, ela lia como três palavras
   perdidas no rodapé do painel; dentro da faixa, lê como o rodapé de dados
   de um produto — que é o que ela é. */
.entrada-marca .rota{display:flex;align-items:flex-start;gap:0;margin:0;
padding:var(--e4) var(--e5);border-radius:var(--raio-g);
background:rgba(255,255,255,.045);
border:1px solid rgba(255,255,255,.09)}
.entrada-marca .rota .parada{display:flex;flex-direction:column;
gap:var(--e3);flex:0 0 auto;max-width:15ch}
.entrada-marca .rota .ponto{width:12px;height:12px;border-radius:50%;
background:#6ba2ff;box-shadow:0 0 0 5px rgba(107,162,255,.16)}
/* A última parada é o preço que ainda não chegou: contorno em COBRE, e não
   um contorno branco qualquer. O quente é o que diz "é aqui que termina" —
   e é o mesmo cobre do halo de baixo e da sobrancelha lá em cima. */
.entrada-marca .rota .parada:last-child .ponto{background:transparent;
border:2px solid var(--cobre-claro);box-shadow:0 0 0 5px rgba(196,118,46,.14)}
.entrada-marca .rota .parada span{font-size:11px;line-height:1.4;
text-transform:uppercase;letter-spacing:1.1px;color:rgba(255,255,255,.7);
font-weight:600}
/* O trecho percorrido é sólido no azul; o que falta é pontilhado. A carga
   ainda não chegou — a linha inteira sólida diria que sim. */
.entrada-marca .rota .trecho{flex:1 1 auto;height:2px;margin:5px var(--e3) 0;
border-radius:2px;
background:linear-gradient(90deg,#6ba2ff,rgba(107,162,255,.35))}
.entrada-marca .rota .trecho.falta{background:none;
border-top:2px dashed rgba(196,118,46,.45);height:0;margin-top:4px}

/* ---- o lado do formulário ---- */
.entrada-form{display:flex;align-items:center;justify-content:center;
padding:var(--e7) var(--e5);background:var(--noite);position:relative}
/* Um filete de vidro separando as duas colunas. Sem ele os dois azuis
   escuros encostam e a tela vira um retângulo só com texto de um lado. */
.entrada-form::before{content:"";position:absolute;left:0;top:14%;bottom:14%;
width:1px;background:linear-gradient(180deg,transparent,
rgba(255,255,255,.14),transparent)}
.entrada-form .cartao{width:100%;max-width:404px;margin:0;
padding:clamp(26px,3vw,36px);
background:var(--noite2);border:1px solid rgba(255,255,255,.10);
border-radius:var(--raio-g);
box-shadow:0 30px 70px -26px rgba(0,0,0,.85)}
.entrada-form h1{color:#fff;font-size:var(--t7);letter-spacing:var(--tr7)}
.entrada-form .sub{color:#95a2b9;margin-bottom:var(--e5)}
.entrada-form label{color:#95a2b9}
.entrada-form input{background:#081426;border-color:rgba(255,255,255,.18);
color:#e9edf5;padding:13px var(--e3)}
.entrada-form input::placeholder{color:#7d8ca6}
.entrada-form input:hover{border-color:rgba(255,255,255,.3)}
.entrada-form input:focus{border-color:var(--realce-claro);
box-shadow:0 0 0 3px rgba(47,124,255,.32)}
/* Azul claro com tinta escura: o botão vira a coisa mais clara da tela, que
   é exatamente onde o olho deve parar. O azul cheio da marca sobre um fundo
   da mesma família sumiria dentro dele. */
.entrada-form button{background:var(--realce-claro);color:#04101f;
padding:14px var(--e5);font-size:var(--t4);
box-shadow:0 14px 34px -14px rgba(47,124,255,.7)}
.entrada-form button:hover{background:#6ba2ff;
box-shadow:0 18px 42px -14px rgba(47,124,255,.8)}
.entrada-form button:focus-visible{box-shadow:0 0 0 2px var(--noite2)}
.entrada-form .rodape{margin:var(--e4) 0 0;font-size:var(--t2);color:#7d8ca6;
text-wrap:pretty;max-width:44ch}
.entrada-form .alerta{background:rgba(181,45,24,.18);
border-color:rgba(255,145,121,.42);border-left-color:#ff9179;color:#ffb4a4}
.entrada-form a{color:var(--realce-claro)}

/* Numa tela estreita a coluna da marca vira uma faixa curta em cima: some o
   texto longo e a rota, fica a logo e a chamada. Empilhar tudo empurraria o
   campo de digitar para fora da tela — a única coisa que a pessoa veio
   fazer. */
@media(max-width:900px){
.entrada{grid-template-columns:1fr;min-height:0}
.entrada-marca{padding:var(--e5) var(--e4) var(--e6);gap:var(--e4);
justify-content:flex-start}
.entrada-marca h1{font-size:clamp(22px,6vw,28px);margin:0}
/* No estreito some o parágrafo longo e a rota; o CORREDOR fica. Ele é
   desenho de fundo e não custa altura nenhuma — empilhar a rota é que
   empurraria o campo de digitar para fora da tela, que é a única coisa
   que a pessoa veio fazer aqui. */
.entrada-marca p,.entrada-marca .rota{display:none}
.entrada-marca .olho{margin-bottom:var(--e2)}
.corredor{opacity:.5}
.entrada-form{padding:var(--e5) var(--e4) var(--e6)}
.entrada-form::before{display:none}
.entrada-form .cartao{max-width:none}}
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
/* O mesmo filete da marca do topo, aqui virado para baixo e mais fino: a
   página abre e fecha com a mesma assinatura. */
.rodape-site::before{content:"";position:absolute;left:0;right:0;top:0;
height:2px;background:var(--marca-grad);opacity:.5}
.rodape-site .dentro{max-width:1140px;margin:0 auto;
padding:var(--e5) var(--e5) var(--e6);
display:flex;align-items:center;gap:var(--e5);flex-wrap:wrap}
.rodape-site .marca-lockup{height:26px}
.rodape-site .diz{font-size:var(--t2);color:var(--fraco);line-height:1.6;
max-width:46ch}
.rodape-site .diz b{display:block;font-size:var(--t-olho);color:var(--cobre);
letter-spacing:var(--tr-olho);text-transform:uppercase;font-weight:700;
margin-bottom:2px}
.rodape-site .links{margin-left:auto;display:flex;gap:var(--e1);
font-size:var(--t2);flex-wrap:wrap}
.rodape-site .links a{text-decoration:none;color:var(--tinta2);
padding:6px var(--e3);border-radius:var(--raio-pill);font-weight:600}
.rodape-site .links a:hover{background:var(--lavagem);color:var(--marca-forte)}
@media(max-width:620px){
.rodape-site .links{margin-left:0;width:100%}
.rodape-site .dentro{gap:var(--e4)}
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
/* Ela deixou de ser uma tira com logo e frase e passou a ser um HERO
   COMPACTO: marca e texto de um lado, o trilho animado do outro. Compacto é
   a palavra — a home é onde se trabalha o dia inteiro, e o hero de tela
   cheia da entrada aqui seria a primeira dobra gasta com apresentação, todo
   dia, para quem já sabe onde está.

   Grade de duas colunas, e não flex-wrap: o trilho precisa de largura
   previsível para o desenho não esticar, e `flex-wrap` dava a ele o que
   sobrasse — que no meio do caminho era 90px. */
.faixa-marca{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,300px);
align-items:center;gap:var(--e5);
background:linear-gradient(110deg,var(--lavagem) 0%,var(--papel) 62%);
border:1px solid var(--borda);border-radius:var(--raio-g);
padding:var(--e5) var(--e5) var(--e5) var(--e6);
margin:0 0 var(--e6);position:relative;overflow:hidden;
box-shadow:var(--sombra-1)}
/* No escuro ela continua sendo o painel fundo: ali o cartão claro é que
   seria o corpo estranho. */
[data-tema="escuro"] .faixa-marca{background:#0a1020;
border-color:var(--borda)}
/* O filete da marca no alto, o mesmo da faixa do vendedor e da lateral do
   painel: e o que amarra as tres telas como um sistema so. */
.faixa-marca::before{content:"";position:absolute;left:0;right:0;top:0;
height:3px;background:var(--marca-grad)}
/* Um halo de cobre no canto, o mesmo da entrada, em dose muito menor: é o
   que impede a faixa clara de virar um retângulo chapado. */
.faixa-marca::after{content:"";position:absolute;right:-8%;top:-60%;
width:38%;aspect-ratio:1;border-radius:50%;pointer-events:none;
background:radial-gradient(circle,var(--cobre-lavagem),transparent 70%)}
.faixa-marca>*{position:relative;z-index:1}
.faixa-marca .marca-lockup{height:44px;margin-bottom:var(--e3)}
.faixa-marca .diz{color:var(--tinta2);font-size:var(--t3);line-height:1.6;
max-width:52ch;display:block}
.faixa-marca .diz b{display:block;color:var(--tinta);font-size:var(--t6);
letter-spacing:var(--tr6);margin-bottom:var(--e1);
font-family:var(--fonte-titulo);line-height:1.2}
[data-tema="escuro"] .faixa-marca .diz{color:#c8d2e8}
[data-tema="escuro"] .faixa-marca .diz b{color:#fff}

/* ---- o trilho ----
   A versão pequena do corredor da entrada: três nós numa linha, e o sinal
   que vai do primeiro ao último. Mesmo desenho, mesma ideia, tamanho de
   faixa — é o que faz a home e o login parecerem a mesma marca.

   Corre DUAS vezes e para. Na entrada são três porque ali a pessoa fica
   parada olhando; aqui ela veio preencher um formulário. */
.trilho{width:100%;height:auto;display:block;overflow:visible}
.trilho .via{fill:none;stroke:var(--borda-forte);stroke-width:2;
stroke-linecap:round}
.trilho .via.falta{stroke-dasharray:4 6;stroke:var(--cobre-claro);opacity:.6}
.trilho .pulso{fill:none;stroke:var(--marca-viva);stroke-width:3.5;
stroke-linecap:round;stroke-dasharray:10 200;stroke-dashoffset:10;
animation:trilho-corre 2.8s var(--suave) .5s 2 both}
@keyframes trilho-corre{to{stroke-dashoffset:-100}}
.trilho .no-t{fill:var(--papel);stroke:var(--marca);stroke-width:2.5}
.trilho .no-t.fim{stroke:var(--cobre-claro)}
.trilho .rot{font-size:8.5px;font-family:var(--fonte);font-weight:700;
fill:var(--fraco);letter-spacing:.7px;text-transform:uppercase}
@media(max-width:860px){
/* Abaixo disto o trilho fica com menos de 200px e os três rótulos se
   encavalam. Some o desenho e fica o recado — o contrário nunca. */
.faixa-marca{grid-template-columns:1fr;gap:var(--e4)}
.faixa-marca .trilho{display:none}
}
@media(max-width:620px){
.faixa-marca{padding:var(--e4);margin-bottom:var(--e5)}
.faixa-marca .marca-lockup{height:34px}
.faixa-marca .diz b{font-size:var(--t5)}
}

/* ============================== acabamento =================================
   Detalhes pequenos que somam. Cada um tem motivo; nenhum é enfeite solto. */

/* Título e texto curto não podem quebrar deixando uma palavra órfã na última
   linha. `balance` nos títulos, `pretty` no texto de apoio. */
h1,h2,.cartao-cab h2,.res .nome{text-wrap:balance}
.sub,.nota,.res .nota,.entrada-marca p,.faixa-marca .diz{text-wrap:pretty}

/* ---- a rede contra o vazamento horizontal ----
   Duas telas já estouraram de lado: a tabela de resultados (medida em
   10/09/2026, 1323px dentro de 990) e a grade do painel no celular. O
   remédio de cada vez foi local, e o defeito voltou por outro caminho.
   Aqui a regra é do SISTEMA: nada corre para fora da largura da janela, e o
   que for largo demais rola dentro do próprio container. */
   `clip`, e nao `hidden`: `overflow-x:hidden` transforma o elemento em
   container de rolagem, e um container de rolagem no <body> quebra o
   `position:sticky` da barra do topo — a barra para de grudar sem nenhum
   erro no console. `clip` corta sem criar container. */
body{max-width:100%;overflow-x:clip}
img,svg,table{max-width:100%}
/* Palavra sem espaço — CNPJ, endereço de e-mail, mensagem de erro de site
   alheio — é o que estoura a coluna quando a tela aperta. */
.diz,.sub,.nota,td,.alerta,.r-nota{overflow-wrap:anywhere}

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
table.resultados .r-nome{width:22%}
table.resultados .r-preco{width:14%}
table.resultados .r-prazo{width:9%}
table.resultados .r-nota{width:27%}
table.resultados .r-estado{width:14%}
table.resultados .r-print{width:14%}
/* O cabeçalho GRUDA no topo da rolagem. A tabela tem seis colunas e o
   resultado pode ter dezoito linhas: rolando, "Preço" e "Prazo" saem da
   tela e sobram seis colunas de número sem nome em cima. O `top` é a altura
   da barra do site, que também gruda — sem o desconto, o cabeçalho da
   tabela sumiria por baixo dela. */
table.resultados th{font-size:var(--t-olho);letter-spacing:var(--tr-olho);
text-transform:uppercase;color:var(--fraco);font-weight:700;text-align:left;
padding:0 14px;height:38px;background:var(--cova);
border-bottom:1px solid var(--borda);white-space:nowrap;
position:sticky;top:0;z-index:1}
table.resultados th.r-preco,table.resultados th.r-prazo,
table.resultados th.r-print{text-align:right}
table.resultados td{padding:0 14px;height:60px;
border-bottom:1px solid var(--linha);vertical-align:middle}
tr.r:hover td{background:var(--lavagem)}
tr.r:hover td:first-child{box-shadow:inset 2px 0 0 var(--marca)}
.r-nome{font-weight:500}
.r-preco{text-align:right;white-space:nowrap}
.r-prazo{text-align:right;color:var(--tinta2);white-space:nowrap}
/* A unica coluna que QUEBRA. As outras sao numero ou rotulo curto; esta e
   frase, e e ela que deve ceder quando a tela aperta. */
.r-nota{color:var(--fraco);font-size:12.5px;line-height:1.35;
text-wrap:pretty}
.r-print{text-align:right;width:1%}

/* A vencedora. Fundo mais filete à esquerda, e não só borda: numa tabela a
   borda de uma linha se confunde com a divisória da linha de cima. */
tr.r.melhor td{background:var(--ok-fraco)}
tr.r.melhor:hover td{background:#daeee5}
tr.r.melhor .r-nome{font-weight:700;box-shadow:inset 3px 0 0 var(--ok)}
tr.r.melhor:hover .r-nome{box-shadow:inset 3px 0 0 var(--ok)}
tr.r.melhor .preco{font-size:21px;letter-spacing:-.6px}

.resultados .preco{font-size:17px;font-weight:700;color:var(--ok);
letter-spacing:-.3px}
/* Preço que não é da carga toda não pode usar o verde de "bom preço": o olho
   compara os números grandes antes de ler qualquer aviso, e era exatamente
   assim que R$ 33,29 por volume parecia mais barato que R$ 69,91 pela carga. */
.resultados .preco.incerto{color:var(--fraco)}
.resultados .sem{color:var(--fraco);font-size:13px}
.resultados .cotando{font-size:12.5px}

/* Pílula de estado. Cor semântica, separada da cor da marca: verde é "veio
   preço", âmbar é "a transportadora disse não", vermelho é "não sabemos". */
/* A pílula ganhou um PONTO da própria cor à esquerda. Cor sozinha não é
   informação acessível (WCAG 1.4.1): quem não distingue verde de âmbar
   lia cinco pílulas iguais com texto diferente. O ponto não resolve isso
   sozinho — quem resolve é o texto, que sempre esteve lá — mas dá a
   segunda pista que a tabela não tinha, e de graça. */
.estado-ok,.estado-aguardando,.estado-recusa,.estado-falha,.estado-cotando{
display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;
border-radius:var(--raio-pill);font-size:var(--t-olho);font-weight:700;
letter-spacing:.5px;white-space:nowrap;border:1px solid transparent}
.estado-ok::before,.estado-aguardando::before,.estado-recusa::before,
.estado-falha::before,.estado-cotando::before{content:"";width:6px;
height:6px;border-radius:50%;background:currentColor;flex:none}
.estado-ok{background:var(--ok-fraco);color:var(--ok);
border-color:color-mix(in srgb,var(--ok) 22%,transparent)}
.estado-aguardando{background:var(--lavagem);color:var(--marca);
border-color:color-mix(in srgb,var(--marca) 20%,transparent)}
.estado-recusa{background:var(--atencao-fraco);color:var(--atencao);
border-color:var(--atencao-borda)}
.estado-falha{background:var(--erro-fraco);color:var(--erro);
border-color:color-mix(in srgb,var(--erro) 22%,transparent)}
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
/* Coluna de número: o cabeçalho vai para a direita, junto da vírgula que ele
   nomeia. Classe própria porque `.melhor` pinta de verde, e um cabeçalho
   verde diria que o TÍTULO da coluna é um preço bom. */
th.col-num{text-align:right}
.clicavel{cursor:pointer}
/* O número da cotação é o alvo de TECLADO da linha. Fica com a cara do texto
   que era antes — quem usa mouse clica na linha inteira e não precisa saber
   que há um link ali; quem anda de Tab precisa de um alvo, e é este. */
.num-cot{color:var(--tinta2);text-decoration:none;font-weight:600}
.clicavel:hover .num-cot{color:var(--marca)}
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
tr.r-extra td{height:auto;padding:0 14px var(--e3);background:var(--cova);
border-bottom:1px solid var(--borda)}
tr.r-extra:hover td:first-child{box-shadow:none}
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


# --------------------------------------------------------------- corredor
#
# O desenho animado do hero das telas de entrada: as faixas por onde a carga
# corre, vistas de cima, com um nó em cada ponta e um sinal que atravessa.
#
# SVG escrito à mão, e não arquivo: são doze elementos, e um arquivo teria de
# ser servido, versionado e baixado — mais três coisas que podem faltar numa
# rede interna para desenhar o que cabe em vinte linhas aqui. A animação é
# CSS (ver o bloco "o corredor"), então o mesmo desenho já respeita o
# `prefers-reduced-motion` global sem nenhuma regra própria.
#
# `pathLength="100"` em toda faixa: o CSS passa a medir o traçado em
# centésimos, qualquer que seja a curva. Sem isso, mexer numa curva quebra o
# tracejado da animação sem quebrar nada visível no desenho parado.
#
# `aria-hidden` e `focusable="false"`: não há informação aqui que a chamada
# ao lado já não diga, e o `focusable` é o que impede o SVG de virar uma
# parada extra do Tab no Internet Explorer/Edge legado.
CORREDOR = """<svg class="corredor" viewBox="0 0 640 480"
 preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
<path class="faixa-c" pathLength="100"
      d="M-20,322 C150,322 220,252 340,216 S520,150 660,92"
      style="animation-delay:.15s"/>
<path class="faixa-c quente" pathLength="100"
      d="M-20,456 C190,456 244,354 360,320 S540,266 660,212"
      style="animation-delay:.45s"/>
<path class="faixa-c viva" pathLength="100"
      d="M-20,396 C170,396 224,302 334,270 S520,202 660,140"/>
<!-- O sinal repete o `d` da faixa viva em vez de um <use href>: o clone de
     um <use> carrega consigo a CLASSE do original, e o CSS do documento
     alcança o conteúdo clonado — a regra `.faixa-c.viva` venceria a herança
     do `.sinal` e o risco sairia com o traço da faixa, parado. -->
<path class="sinal" pathLength="100"
      d="M-20,396 C170,396 224,302 334,270 S520,202 660,140"/>
<circle class="halo" cx="334" cy="270" r="17" style="animation-delay:.9s"/>
<circle class="halo" cx="604" cy="152" r="21" style="animation-delay:1.3s"/>
<circle class="no" cx="72" cy="396" r="7" style="animation-delay:.7s"/>
<circle class="no" cx="334" cy="270" r="6" style="animation-delay:1s"/>
<circle class="no fim" cx="604" cy="152" r="8" style="animation-delay:1.35s"/>
</svg>"""


# O trilho da faixa do início: o mesmo desenho do corredor, em tamanho de
# tira e com os três nomes escritos. Três paradas fixas porque são as três
# que a home descreve na frase ao lado — a contagem de transportadoras, que
# muda, mora no texto, onde ela é lida e não contada de cabeça.
TRILHO = """<svg class="trilho" viewBox="0 0 300 92" role="img"
 aria-label="O caminho de uma cotação: a carga entra, as transportadoras
 respondem, sai o melhor preço.">
<path class="via" pathLength="100" d="M22,40 H150"/>
<path class="via falta" pathLength="100" d="M150,40 H278"/>
<path class="pulso" pathLength="100" d="M22,40 H278"/>
<circle class="no-t" cx="22" cy="40" r="6"/>
<circle class="no-t" cx="150" cy="40" r="6"/>
<circle class="no-t fim" cx="278" cy="40" r="6"/>
<text class="rot" x="22" y="66" text-anchor="start">a carga</text>
<text class="rot" x="150" y="66" text-anchor="middle">cotação</text>
<text class="rot" x="278" y="66" text-anchor="end">o preço</text>
</svg>"""


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
    if not caminho or not Path(caminho).exists():
        return ""
    dados = base64.b64encode(Path(caminho).read_bytes()).decode()
    return (f'<img class="print" src="data:image/png;base64,{dados}" '
            f'alt="comprovante da cotacao">')


def entrada(titulo: str, cartao: str, *, chamada: str, apoio: str,
            paradas: tuple[str, ...] = (), rodape: str = "",
            olho: str = "Cotafrete") -> str:
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

    `olho` é a sobrancelha acima da chamada: o rótulo curto que diz de que
    parte do sistema a tela é. Tem padrão porque as duas entradas que existem
    hoje ("Cotafrete" no vendedor, "Painel" no adm) não justificam obrigar
    quem chama a decidir — e um argumento obrigatório a mais é um lugar a
    mais para as duas telas divergirem sem motivo.

    `cartao` entra CRU: é HTML montado por quem chama, com o formulário. Tudo
    que vem de fora — chamada, apoio, provas, rodapé, sobrancelha — passa
    por `e()`.
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
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title><style>{CSS}</style></head><body>
<div class="entrada">
  <aside class="entrada-marca">
    {CORREDOR}
    <div class="marca-entrada">
      <span class="logo marca-peca" role="img"
          aria-label="Ventura Comércio"></span>
      <p class="assinatura">{ASSINATURA}</p>
    </div>
    <div>
      <p class="olho">{e(olho)}</p>
      <h1>{e(chamada)}</h1>
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
        links = ('<nav class="links" aria-label="Links do rodapé">'
                 '<a href="/documentacao">Como usar</a>'
                 '<a href="/historico">Histórico</a></nav>')
    return f"""<footer class="rodape-site"><div class="dentro">
  <span class="marca-placa"><span class="marca-peca marca-lockup"
        role="img" aria-label="Ventura Comércio"></span></span>
  <span class="diz"><b>{ASSINATURA}</b>
  Cotafrete — sistema interno de cotação de frete.</span>
  {links}
</div></footer>"""


def pagina(titulo: str, corpo: str, usuario: str | None = None) -> str:
    """O casco das telas de trabalho.

    `<nav>` de verdade em volta do menu, e `<main>` em volta do corpo: eram
    duas <div>, e num leitor de tela a diferença é entre poder pular direto
    para o conteúdo e ter de ouvir as quatro abas em toda página. O
    `aria-label` nomeia a navegação porque a página tem duas — esta e a do
    rodapé —, e "navegação" repetida duas vezes não distingue nenhuma.
    """
    quem = ""
    if usuario:
        quem = ('<span class="quem"><nav class="menu" '
                'aria-label="Navegação principal">'
                '<a href="/">Nova cotação</a><a href="/historico">Histórico</a>'
                '<a href="/documentacao">Documentação</a>'
                f'<a href="/sair">Sair</a></nav> <b>{e(usuario)}</b></span>')
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title>{cabeca_do_tema("claro")}
<style>{CSS}</style></head><body>
<a class="pular" href="#conteudo">Pular para o conteúdo</a>
<div class="topo"><a class="marca-placa" href="/" aria-label="Ventura Comércio — início"><span class="marca-peca marca-lockup" role="img"></span></a>
{quem}{BOTAO_TEMA}</div>
<main class="wrap" id="conteudo">{corpo}</main>
{rodape_do_site(usuario)}{LUPA}{SCRIPT_TEMA}</body></html>"""
