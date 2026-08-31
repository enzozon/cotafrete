"""O casco visual compartilhado: logo, CSS, escape e a moldura da página.

Vive fora de web/app.py porque web/adm.py precisa das mesmas peças, e
web/app.py registra as rotas do adm — um importar o outro seria circular.

Nada aqui conhece banco, cotação ou transportadora. É só desenho."""

from __future__ import annotations

import html
from decimal import Decimal
from pathlib import Path

LOGO = (Path(__file__).parent / "logo_b64.txt").read_text(encoding="utf-8").strip()


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
/* Aba de Documentacao. Escopo proprio: o resto do sistema quase nao usa
   texto corrido, e soltar estilo de <h2>/<ul> no global mexeria nas telas
   de cotacao. */
.doc h2{font-size:15px;margin:22px 0 6px;color:var(--marca)}
.doc h2:first-child{margin-top:0}
.doc p{margin:0 0 10px;font-size:14px}
.doc ul{margin:0 0 12px;padding-left:20px;font-size:14px}
.doc li{margin-bottom:6px}
.doc table{margin-bottom:12px}
.doc td{vertical-align:top}
.doc .errado{color:var(--erro);font-weight:600}
.doc .certo{color:var(--ok);font-weight:600}
.doc .passo{font-size:14px;margin:0 0 10px;padding-left:20px}
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
.faixa{display:flex;gap:18px;flex-wrap:wrap;margin:16px 0}
.numero{background:#f4f4f6;border-radius:10px;padding:12px 18px;min-width:120px}
.numero b{display:block;font-size:28px;line-height:1.1}
.numero span{font-size:12px;color:#666}
.numero.ruim b{color:#b00020}
.barra{display:inline-block;width:90px;height:9px;background:#e6e6ea;
       border-radius:5px;vertical-align:middle;overflow:hidden}
.barra i{display:block;height:100%;background:#1f9d55}
.sem-dado{color:#888;font-size:12px}
.periodo{text-decoration:none;color:#555}
.periodo.atual{font-weight:700;color:#111;text-decoration:underline}
"""


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


def pagina(titulo: str, corpo: str, usuario: str | None = None) -> str:
    quem = ""
    if usuario:
        quem = ('<span class="quem"><span class="menu">'
                '<a href="/">Nova cotação</a><a href="/historico">Histórico</a>'
                '<a href="/documentacao">Documentação</a>'
                f'<a href="/sair">Sair</a></span> <b>{e(usuario)}</b></span>')
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titulo)} — Cotafrete</title><style>{CSS}</style></head><body>
<div class="topo"><img src="data:image/png;base64,{LOGO}" alt="Ventura">
{quem}</div>
<div class="wrap">{corpo}</div></body></html>"""
