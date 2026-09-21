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
--marca:#0042b5;--marca-forte:#00328a;--marca-viva:#0450d2;
--realce:#004bcc;--realce-claro:#317bfc;--lavagem:#eaf1fd;
--marca-grad:linear-gradient(135deg,#317bfc 0%,#0450d2 45%,#0042b5 100%);
/* neutros com viés azul */
--tinta:#0f1724;--tinta2:#3c485d;--fraco:#5e6b82;
--borda:#dee3ed;--borda-forte:#c1cbdc;--fundo:#f5f7fb;--papel:#fff;
/* semânticos: sentido, não marca — mudar estes muda o que a tela AFIRMA */
--ok:#00785a;--erro:#c0341d;--atencao:#a15c00;--zap:#25d366;
--ok-fraco:#e6f4ef;--erro-fraco:#fdece9;--atencao-fraco:#fffae6;
--atencao-borda:#ffe380;--atencao-tinta:var(--tinta);
--sobre-marca:#fff;--cova:#f7f9fc;
--brilho-marca:rgba(0,66,181,.45);
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
/* elevação: três degraus, e não sombra solta por regra. Borda de 1px em tudo
   achata a hierarquia — quem precisa se destacar sobe, o resto fica no plano */
--sombra-1:0 1px 2px rgba(20,32,66,.05),0 1px 3px rgba(20,32,66,.04);
--sombra-2:0 2px 4px rgba(20,32,66,.04),0 10px 22px -8px rgba(20,32,66,.14);
--sombra-3:0 18px 44px -12px rgba(20,32,66,.28);
--raio:12px;--raio-p:8px;--raio-g:16px;
--suave:cubic-bezier(.2,.6,.3,1);--mola:cubic-bezier(.34,1.32,.46,1)}
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
--marca:#5291ff;--marca-forte:#85b1ff;--marca-viva:#0450d2;
--realce:#5291ff;--realce-claro:#70a5ff;--lavagem:#1c2940;
/* O que se escreve EM CIMA de um preenchimento da marca. Herdar o #fff do
   claro daria 2.6:1 sobre o azul claro: o botão sumiria por dentro. */
--sobre-marca:#061021;
/* neutros: 13.9:1, 9.1:1 e 6.7:1 sobre o cartão */
--tinta:#e6e9ef;--tinta2:#bcc4d2;--fraco:#99a4b8;
--borda:#2d3f5c;--borda-forte:#475e85;--fundo:#061021;--papel:#111e34;
/* Um degrau ABAIXO do papel, para o que é buraco e não cartão: campo de
   digitar, caixa de texto técnico, ficha dentro do cartão. No claro esse
   papel é o próprio branco e o buraco se faz com borda; no escuro é a
   luminância que separa, então o buraco precisa existir como cor. */
--cova:#0a1426;
/* Semânticos: o SENTIDO é o mesmo, só a luminância sobe. Verde 8.4:1, âmbar
   7.8:1, vermelho 7.5:1 sobre o cartão — contra 3.7, 5.2 e 2.8 que as cores
   claras dariam aqui. O vermelho de falha, no escuro, era ilegível. */
--ok:#3ecf8e;--erro:#ff8f75;--atencao:#e5a54a;
/* As lavagens de cada semântico: o fundo das pílulas e dos avisos. */
--ok-fraco:#142b26;--erro-fraco:#2d201f;--atencao-fraco:#2c2413;
--atencao-borda:#5c4a1c;--atencao-tinta:#e8cf9a;
--brilho-marca:rgba(82,145,255,.55);
/* Os mesmos tons, com a luminância que o fundo escuro exige. O pior é
   o roxo, com 6.1:1 sobre o cartão; no claro o vermelho de falha dava
   2.8:1 aqui e não passava nem como gráfico (SC 1.4.11). */
--tom-marca:#5291ff;--tom-marca-fraco:#18263f;
--tom-ok:#3ecf8e;--tom-ok-fraco:#142b26;
--tom-atencao:#e5a54a;--tom-atencao-fraco:#2b2618;
--tom-erro:#ff8f75;--tom-erro-fraco:#2d201f;
--tom-neutro:#98a1b8;--tom-neutro-fraco:#1f2740;
--tom-roxo:#a78bfa;--tom-roxo-fraco:#242847;
--alerta-fundo:#2a1a17;--alerta-borda:#5c3128;--alerta-tinta:#e0ab9c;
/* No escuro sombra não separa nada: quem separa é o degrau de luminância
   entre #0b0f1c e #161d33. A sombra fica só para dizer o que está POR CIMA
   quando o cursor levanta um cartão. */
--sombra-1:0 1px 2px rgba(0,0,0,.4);
--sombra-2:0 10px 28px -8px rgba(0,0,0,.6);
--sombra-3:0 20px 48px -12px rgba(0,0,0,.75);
/* Diz ao NAVEGADOR que a página é escura, para ele pintar de escuro o que
   desenha sozinho: barra de rolagem, cursor de texto, caixa de seleção. Sem
   isto a barra de rolagem branca era a coisa mais clara da tela. */
color-scheme:dark}

/* ---- o que ficou cravado em claro quando o sistema só tinha um tema -------
   Token nenhum alcança um `#fffae6` escrito dentro de uma regra. São estes,
   e ficam juntos para quem for mexer no tema achar num lugar só, em vez de
   caçar um fundo branco perdido no meio do arquivo. */
[data-tema="escuro"] fieldset{background:#12182b}
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
[data-tema="escuro"] button:not(.tema){color:var(--sobre-marca)}
[data-tema="escuro"] .selo-zap{background:var(--ok-fraco)}
[data-tema="escuro"] .zap.aberta{background:#131a2e;border-color:#25503a}

/* A tabela do resultado. O verde da linha vencedora vira um verde de FUNDO
   escuro: no claro ele é uma lavagem, e lavagem clara no escuro é um rasgo
   branco no meio da tabela. */
[data-tema="escuro"] table.resultados th{background:#12182b}
[data-tema="escuro"] tr.r.melhor td{background:#132a24}
[data-tema="escuro"] tr.r.melhor:hover td{background:#17332b}
[data-tema="escuro"] tr.r-extra td{background:#12182b}
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
body{margin:0;background:var(--fundo);color:var(--tinta);line-height:1.45;
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
-webkit-font-smoothing:antialiased;
/* O sistema é uma tela de números: peso, cubagem, preço. Dígito de largura
   fixa faz as colunas de dinheiro alinharem sem tabela e sem monoespaçada. */
font-variant-numeric:tabular-nums}
a{color:var(--marca)}

/* Movimento é enfeite até virar obstáculo. Quem pediu para o sistema parar de
   se mexer não pode receber um formulário que entra deslizando. Uma regra, no
   topo, valendo para todas as telas — inclusive as do painel, que empilha
   o seu CSS depois deste. */
@media(prefers-reduced-motion:reduce){
*,*::before,*::after{animation-duration:.01ms !important;
animation-iteration-count:1 !important;transition-duration:.01ms !important;
scroll-behavior:auto !important}}

/* ---- faixa do topo ---- */
.topo{background:var(--papel);border-bottom:1px solid var(--borda);
padding:12px 24px;display:flex;align-items:center;gap:16px;position:relative}
/* O filete do gradiente da logo, atravessando a tela inteira. É a assinatura
   da marca no lugar mais barato possível: 3px que nenhuma outra tela de
   sistema interno tem, e que ninguém precisa ler para reconhecer. */
.topo::before{content:"";position:absolute;left:0;right:0;top:0;height:3px;
background:var(--marca-grad)}
.topo img{height:38px}
.topo .quem{margin-left:auto;font-size:13px;color:var(--fraco)}
.wrap{max-width:1080px;margin:24px auto;padding:0 24px}

/* Entrada em cascata. O formulário tem cinco blocos; todos aparecendo no
   mesmo quadro é um susto, escalonados o olho acompanha de cima para baixo. */
/* Nome com sufixo: web/painel_ui.py empilha o CSS dele depois
   deste e ja tem um @keyframes `sobe` proprio, das barras do
   grafico. Dois com o mesmo nome na mesma folha e o de baixo
   ganha em silencio. */
@keyframes sobe-bloco{from{opacity:0;transform:translateY(10px)}
to{opacity:1;transform:none}}
.cartao{background:var(--papel);border:1px solid var(--borda);
border-radius:var(--raio);padding:20px;margin-bottom:16px;
box-shadow:var(--sombra-1);animation:sobe-bloco .42s var(--suave) both}
h1{font-size:24px;margin:0 0 4px;letter-spacing:-.5px;font-weight:700}
.sub{color:var(--fraco);font-size:13px;margin:0 0 18px}
fieldset{border:1px solid var(--borda);border-radius:var(--raio-p);
margin:0 0 14px;padding:14px 16px;background:#fcfdff}
legend{font-size:10.5px;font-weight:700;color:var(--marca);padding:0 7px;
text-transform:uppercase;letter-spacing:1px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
label{display:block;font-size:11px;color:var(--fraco);margin-bottom:4px;
font-weight:500}
input{width:100%;padding:10px 12px;border:1px solid var(--borda-forte);
border-radius:var(--raio-p);font-size:14px;font-family:inherit;
background:var(--papel);color:var(--tinta);
transition:border-color .16s var(--suave),box-shadow .16s var(--suave)}
input:hover{border-color:#b6c2d6}
/* O azul de realce da marca: o anel de foco é a peça que mais aparece
   num sistema onde se digita o dia inteiro, e era o contorno cinza do
   navegador. */
input:focus{outline:0;border-color:var(--realce);
box-shadow:0 0 0 3px rgba(82,145,255,.35)}
button{font:inherit;cursor:pointer;border:0;border-radius:var(--raio-p);
background:var(--marca);color:#fff;padding:13px 26px;font-weight:600;
font-size:15px;box-shadow:var(--sombra-2);
transition:transform .16s var(--mola),box-shadow .16s var(--suave),
background .16s var(--suave)}
button:hover{background:var(--marca-forte);transform:translateY(-1px);
box-shadow:var(--sombra-3)}
/* Afunda no clique. Num formulário que dispara cinco navegadores e leva dois
   minutos, o retorno imediato do botão é o que diz "recebi" antes de a
   primeira transportadora responder. */
button:active{transform:translateY(1px);box-shadow:var(--sombra-1)}
button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid
var(--realce);outline-offset:2px}

.falhou{color:var(--erro);font-size:13px;font-weight:600}
/* "Enviada" NAO pode usar o vermelho de falha nem o verde de preco: nao deu
   errado e nao ha numero para comparar. Fica na cor da marca, no tamanho que
   ocupa o lugar do preco - o olho passa pelos cartoes procurando o numero
   grande, e precisa parar aqui em vez de saltar. */
.enviada{color:var(--marca);font-size:20px;font-weight:700;margin:6px 0 2px}
.selo{display:inline-block;font-size:10px;font-weight:700;color:#fff;
background:var(--ok);border-radius:99px;padding:3px 9px;letter-spacing:.4px}
.zap{display:flex;align-items:center;gap:10px;border:1px solid var(--borda);
border-radius:var(--raio-p);padding:11px 13px;text-decoration:none;
color:inherit;margin-bottom:8px;background:var(--papel);
transition:border-color .16s var(--suave),transform .16s var(--suave),
box-shadow .16s var(--suave)}
.zap:hover{border-color:var(--zap);transform:translateX(2px);
box-shadow:var(--sombra-1)}
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
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:10.5px;color:var(--fraco);text-transform:uppercase;
letter-spacing:.8px;padding:8px;border-bottom:1px solid var(--borda);
font-weight:700}
td{padding:9px 8px;border-bottom:1px solid #f0f3f8}
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
.aviso{background:#fffae6;border:1px solid #ffe380;border-radius:var(--raio-p);
padding:11px 13px;font-size:13px;margin-bottom:14px}
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
.botao2{display:inline-block;background:var(--papel);color:var(--marca);
border:1px solid var(--borda-forte);border-radius:var(--raio-p);
padding:10px 17px;font-size:14px;font-weight:600;text-decoration:none;
transition:border-color .16s var(--suave),background .16s var(--suave)}
.botao2:hover{border-color:var(--marca);background:var(--lavagem)}
.login{max-width:380px;margin:70px auto;text-align:center;
animation:sobe-bloco .5s var(--suave) both}
.login img{height:64px;margin-bottom:18px}
.menu a{margin-right:14px;font-size:13px;text-decoration:none;
position:relative;padding-bottom:2px}
/* Sublinhado que cresce do centro. É a única decoração de navegação do
   sistema, e cabe em duas linhas. */
.menu a::after{content:"";position:absolute;left:50%;right:50%;bottom:0;
height:2px;background:var(--marca-grad);border-radius:2px;
transition:left .2s var(--suave),right .2s var(--suave)}
.menu a:hover::after{left:0;right:0}
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
.alerta{background:#fffae6;border:1px solid #ffe380;border-radius:var(--raio-p);
padding:9px 11px;font-size:12px;margin:6px 0 2px;line-height:1.35}
/* Amarelo e para "cuidado, esse numero engana". Aqui nao ha erro nenhum: e
   instrucao de onde olhar. Azul separa os dois recados. */
.alerta.email{background:var(--lavagem);border-color:#c7d6f5}
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
.entrada{min-height:100vh;display:grid;grid-template-columns:1.04fr .96fr;
background:#061021;color:#e6e9ef}
.entrada-marca{position:relative;overflow:hidden;
padding:clamp(32px,4vw,56px);display:flex;flex-direction:column;
justify-content:center;gap:clamp(26px,3.4vw,40px);
background:linear-gradient(158deg,#112039 0%,#0a162b 55%,#050d1d 100%)}
/* Dois clarões fora de eixo. O índigo chapado é uma parede; os halos dão
   profundidade sem desenhar nada e sem depender de arquivo de imagem — o
   sistema roda em rede interna, e imagem que não chegou é buraco na tela. */
.entrada-marca::before,.entrada-marca::after{content:"";position:absolute;
border-radius:50%;pointer-events:none}
.entrada-marca::before{inset:-26% auto auto -16%;width:52%;aspect-ratio:1;
background:radial-gradient(circle,rgba(112,200,224,.22),transparent 66%)}
.entrada-marca::after{inset:auto -18% -32% auto;width:56%;aspect-ratio:1;
background:radial-gradient(circle,rgba(64,88,160,.38),transparent 68%)}
.entrada-marca>*{position:relative;z-index:1}
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
.entrada-marca .assinatura{margin:9px 0 0;font-size:11px;letter-spacing:2.4px;
text-transform:uppercase;color:rgba(255,255,255,.62);font-weight:600;
white-space:nowrap}
/* Numa tela estreita a entrelinha larga faria a frase estourar a coluna:
   ela aperta em vez de quebrar no meio de "SÓ LUGAR". */
@media(max-width:520px){
.entrada-marca .assinatura{letter-spacing:1.4px;font-size:10px}
}
.entrada-marca h1{font-size:clamp(28px,3.5vw,42px);line-height:1.1;
margin:0 0 14px;letter-spacing:-.9px;color:#fff;text-wrap:balance}
.entrada-marca p{margin:0;max-width:40ch;font-size:15px;line-height:1.55;
color:rgba(255,255,255,.72);text-wrap:pretty}

/* ---- a rota ----
   Não é enfeite: é o que o sistema FAZ, desenhado. Uma carga entra, as
   automáticas cotam, sai o melhor preço. O número de paradas do meio sai de
   `len(AUTOMATICAS)`, passado por quem chama — escrito à mão, a tela passaria
   a mentir sobre o tamanho do sistema na primeira transportadora que
   entrasse.

   Faixa própria embaixo do texto, e não um traçado atrás dele: fundo que
   cruza o parágrafo briga com a leitura em alguma largura de tela, sempre. */
.entrada-marca .rota{display:flex;align-items:flex-start;gap:0;margin:0;padding-top:4px}
.entrada-marca .rota .parada{display:flex;flex-direction:column;gap:9px;flex:0 0 auto;
max-width:14ch}
.entrada-marca .rota .ponto{width:13px;height:13px;border-radius:50%;background:#5291ff;
box-shadow:0 0 0 5px rgba(82,145,255,.18)}
.entrada-marca .rota .parada:last-child .ponto{background:transparent;
border:2px solid rgba(255,255,255,.5);box-shadow:none}
.entrada-marca .rota .parada span{font-size:11.5px;line-height:1.35;
text-transform:uppercase;letter-spacing:.9px;color:rgba(255,255,255,.72)}
/* O trecho percorrido é sólido no azul; o que falta é pontilhado. A carga
   ainda não chegou — a linha inteira sólida diria que sim. */
.entrada-marca .rota .trecho{flex:1 1 auto;height:2px;margin:6px 12px 0;
background:linear-gradient(90deg,#5291ff,rgba(82,145,255,.45))}
.entrada-marca .rota .trecho.falta{background:none;
border-top:2px dashed rgba(255,255,255,.26);height:0;margin-top:5px}

/* ---- o lado do formulário ---- */
.entrada-form{display:flex;align-items:center;justify-content:center;
padding:40px 28px;background:#061021}
.entrada-form .cartao{width:100%;max-width:392px;margin:0;padding:30px;
background:#111e34;border:1px solid rgba(255,255,255,.09);
box-shadow:0 26px 60px -24px rgba(0,0,0,.8)}
.entrada-form h1{color:#fff;font-size:23px}
.entrada-form .sub{color:#99a4b8}
.entrada-form label{color:#99a4b8}
.entrada-form input{background:#0a1426;border-color:rgba(255,255,255,.16);
color:#e6e9ef}
.entrada-form input::placeholder{color:#8594ad}
.entrada-form input:hover{border-color:rgba(255,255,255,.28)}
.entrada-form input:focus{border-color:var(--realce-claro);
box-shadow:0 0 0 3px rgba(112,200,224,.24)}
/* Ciano com tinta escura: o botão vira a coisa mais clara da tela, que é
   exatamente onde o olho deve parar. Índigo sobre fundo índigo sumiria. */
.entrada-form button{background:var(--realce-claro);color:#0d1120;
box-shadow:0 12px 30px -12px rgba(82,145,255,.65)}
.entrada-form button:hover{background:#85b1ff;
box-shadow:0 16px 38px -12px rgba(82,145,255,.75)}
.entrada-form .rodape{margin:14px 0 0;font-size:12px;color:#8594ad;
text-wrap:pretty}
.entrada-form .alerta{background:rgba(192,52,29,.16);
border-color:rgba(255,138,116,.42);color:#ffb4a4}
.entrada-form a{color:var(--realce-claro)}

/* Numa tela estreita a coluna da marca vira uma faixa curta em cima: some o
   texto longo e a rota, fica a logo e a chamada. Empilhar tudo empurraria o
   campo de digitar para fora da tela — a única coisa que a pessoa veio
   fazer. */
@media(max-width:860px){
.entrada{grid-template-columns:1fr;min-height:0}
.entrada-marca{padding:26px 22px;gap:16px}
.entrada-marca h1{font-size:22px;margin:0}
.entrada-marca p,.entrada-marca .rota{display:none}
.entrada-marca .logo{height:48px}
.entrada-form{padding:30px 20px}}
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
.rodape-site{border-top:1px solid var(--borda);margin-top:40px;
background:var(--papel);flex:none}
.rodape-site .dentro{max-width:1080px;margin:0 auto;padding:22px 20px 26px;
display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.rodape-site .marca-lockup{height:28px}
.rodape-site .diz{font-size:11.5px;color:var(--fraco);line-height:1.5}
.rodape-site .diz b{display:block;font-size:12px;color:var(--tinta2);
letter-spacing:.6px;text-transform:uppercase;font-weight:700}
.rodape-site .links{margin-left:auto;display:flex;gap:16px;font-size:12.5px;
flex-wrap:wrap}
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
.faixa-marca{display:flex;align-items:center;gap:20px;flex-wrap:wrap;
background:linear-gradient(110deg,var(--lavagem) 0%,var(--papel) 62%);
border:1px solid var(--borda);border-radius:var(--raio-g);padding:20px 24px;
margin:0 0 20px;position:relative;overflow:hidden}
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
table.resultados th{font-size:10.5px;letter-spacing:1px;
text-transform:uppercase;color:var(--fraco);font-weight:700;text-align:left;
padding:0 14px;height:34px;background:#f8fafd;
border-bottom:1px solid var(--borda);white-space:nowrap}
table.resultados th.r-preco,table.resultados th.r-prazo,
table.resultados th.r-print{text-align:right}
table.resultados td{padding:0 14px;height:56px;
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

/* A vencedora. Fundo mais filete à esquerda, e não só borda: numa tabela a
   borda de uma linha se confunde com a divisória da linha de cima. */
tr.r.melhor td{background:#f2f8f5}
tr.r.melhor:hover td{background:#eaf4ef}
tr.r.melhor .r-nome{font-weight:700;box-shadow:inset 3px 0 0 var(--ok)}
tr.r.melhor .preco{font-size:19px}

.resultados .preco{font-size:16px;font-weight:700;color:var(--ok)}
/* Preço que não é da carga toda não pode usar o verde de "bom preço": o olho
   compara os números grandes antes de ler qualquer aviso, e era exatamente
   assim que R$ 33,29 por volume parecia mais barato que R$ 69,91 pela carga. */
.resultados .preco.incerto{color:var(--fraco)}
.resultados .sem{color:var(--fraco);font-size:13px}
.resultados .cotando{font-size:12.5px}

/* Pílula de estado. Cor semântica, separada da cor da marca: verde é "veio
   preço", âmbar é "a transportadora disse não", vermelho é "não sabemos". */
.estado-ok,.estado-aguardando,.estado-recusa,.estado-falha,.estado-cotando{
display:inline-flex;align-items:center;height:22px;padding:0 9px;
border-radius:99px;font-size:10.5px;font-weight:700;letter-spacing:.4px;
white-space:nowrap}
.estado-ok{background:#e6f4ef;color:var(--ok)}
.estado-aguardando{background:var(--lavagem);color:var(--marca)}
.estado-recusa{background:#fff4e2;color:var(--atencao)}
.estado-falha{background:#fdece9;color:var(--erro)}
.estado-cotando{background:var(--fundo);color:var(--fraco)}

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
            paradas: tuple[str, ...] = (), rodape: str = "") -> str:
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
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title>{ICONE_ABA}
<style>{CSS}</style></head><body>
<div class="entrada">
  <aside class="entrada-marca">
    <div class="marca-entrada">
      <span class="logo marca-peca" role="img"
          aria-label="Ventura Comércio"></span>
      <p class="assinatura">{ASSINATURA}</p>
    </div>
    <div>
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


def pagina(titulo: str, corpo: str, usuario: str | None = None) -> str:
    quem = ""
    if usuario:
        quem = ('<span class="quem"><span class="menu">'
                '<a href="/">Nova cotação</a><a href="/historico">Histórico</a>'
                '<a href="/documentacao">Documentação</a>'
                f'<a href="/sair">Sair</a></span> <b>{e(usuario)}</b></span>')
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title>{ICONE_ABA}{cabeca_do_tema("claro")}
<style>{CSS}</style></head><body>
<div class="topo"><a class="marca-placa" href="/" aria-label="Ventura Comércio — início"><span class="marca-peca marca-lockup" role="img"></span></a>
{quem}{BOTAO_TEMA}</div>
<div class="wrap">{corpo}</div>
{rodape_do_site(usuario)}{LUPA}{SCRIPT_TEMA}</body></html>"""
