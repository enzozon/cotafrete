"""Interface web: um formulário, duas transportadoras.

    uvicorn web.app:app --port 8000
    # abre http://localhost:8000

Preenche o simulador da Jadlog (devolve VALOR + print do resultado) e o
formulário da Della Volpe (dry-run: preenche, printa e PARA antes do submit).

⚠ A Della Volpe é assíncrona: o preço só volta por e-mail depois que a cotação
é realmente enviada. Por enquanto esta tela mostra só o print do formulário
preenchido — nada é enviado para eles.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

from carriers.base import ResultadoCotacao
from carriers.dellavolpe.adapter import DellavolpeAdapter
from carriers.jadlog import mapping as jm
from carriers.jadlog.simulador import JadlogSimuladorAdapter
from core.models import (
    CotacaoRequest, Local, Mercadoria, NotaFiscal, Parte, Servico,
    Solicitante, StatusCotacao, Volume,
)

app = FastAPI(title="Cotação de Fretes")

UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
       "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
       "SE", "SP", "TO"]

CSS = """
*{box-sizing:border-box} body{font-family:system-ui,-apple-system,sans-serif;
margin:0;padding:24px;background:#f4f5f7;color:#1a1a1a}
.wrap{max-width:1000px;margin:auto}
h1{font-size:22px;margin:0 0 4px} .sub{color:#666;font-size:13px;margin-bottom:20px}
form{background:#fff;border:1px solid #dfe1e6;border-radius:10px;padding:20px}
fieldset{border:1px solid #e6e8eb;border-radius:8px;margin:0 0 16px;padding:14px}
legend{font-size:12px;font-weight:600;color:#5e6c84;padding:0 6px;
text-transform:uppercase;letter-spacing:.5px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
label{display:block;font-size:12px;color:#5e6c84;margin-bottom:4px}
input,select{width:100%;padding:8px 10px;border:1px solid #dfe1e6;border-radius:6px;
font-size:14px;background:#fff}
button{background:#0052cc;color:#fff;border:0;border-radius:6px;padding:12px 22px;
font-size:15px;font-weight:600;cursor:pointer;margin-top:6px}
button:hover{background:#0043a6}
.aviso{background:#fffae6;border:1px solid #ffe380;border-radius:6px;padding:10px 12px;
font-size:13px;margin-bottom:16px}
.card{background:#fff;border:1px solid #dfe1e6;border-radius:10px;padding:18px;
margin-bottom:16px}
.valor{font-size:30px;font-weight:700;color:#00875a;margin:6px 0}
.erro{color:#bf2600} .status{font-size:12px;color:#5e6c84;text-transform:uppercase;
letter-spacing:.5px}
img{max-width:100%;border:1px solid #dfe1e6;border-radius:6px;margin-top:10px}
a.voltar{display:inline-block;margin-top:8px;color:#0052cc;font-size:14px}
table{border-collapse:collapse;font-size:13px;margin-top:6px}
td{padding:2px 12px 2px 0;color:#5e6c84}
"""


def _campo(nome: str, rotulo: str, valor: str = "", tipo: str = "text") -> str:
    return (f'<div><label for="{nome}">{rotulo}</label>'
            f'<input id="{nome}" name="{nome}" type="{tipo}" value="{valor}" required></div>')


def _select(nome: str, rotulo: str, opcoes: list[str], atual: str = "") -> str:
    ops = "".join(
        f'<option value="{o}"{" selected" if o == atual else ""}>{o}</option>'
        for o in opcoes)
    return (f'<div><label for="{nome}">{rotulo}</label>'
            f'<select id="{nome}" name="{nome}">{ops}</select></div>')


FORMULARIO = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cotação de Fretes</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Cotação de Fretes</h1>
<div class="sub">Preencha uma vez — cotamos na Jadlog e na Della Volpe.</div>
<div class="aviso"><b>Jadlog:</b> simulador público, devolve o valor na hora.
<b>Della Volpe:</b> só preenche e tira print — <b>nada é enviado</b>, porque cada
envio real vira uma cotação na fila de um vendedor.</div>
<form method="post" action="/cotar">

<fieldset><legend>Quem está cotando</legend><div class="grid">
{_campo("nome", "Nome completo", "Enzo Teste")}
{_campo("email", "E-mail", "enzo@exemplo.com.br", "email")}
{_campo("whatsapp", "WhatsApp", "27999887766", "tel")}
</div></fieldset>

<fieldset><legend>Origem</legend><div class="grid">
{_campo("cep_origem", "CEP de origem", "29065-560")}
{_select("uf_origem", "Estado", UFS, "ES")}
{_campo("cidade_origem", "Cidade", "Vitória")}
{_campo("cnpj_remetente", "CNPJ do remetente", "11.222.333/0001-81")}
</div></fieldset>

<fieldset><legend>Destino</legend><div class="grid">
{_campo("cep_destino", "CEP de destino", "01310-100")}
{_select("uf_destino", "Estado", UFS, "SP")}
{_campo("cidade_destino", "Cidade", "São Paulo")}
{_campo("cnpj_destinatario", "CNPJ do destinatário", "45.723.174/0001-10")}
</div></fieldset>

<fieldset><legend>Produto</legend><div class="grid">
{_campo("qtd", "Quantidade de volumes", "1", "number")}
{_campo("peso", "Peso unitário (kg)", "10")}
{_campo("comprimento", "Comprimento (cm)", "15")}
{_campo("largura", "Largura (cm)", "15")}
{_campo("altura", "Altura (cm)", "15")}
{_campo("valor_nf", "Valor da nota fiscal (R$)", "30")}
{_campo("tipo_material", "Tipo de material", "Peças metálicas")}
{_campo("cnpj_pagador", "CNPJ de quem paga o frete", "61.139.432/0001-72")}
{_select("modalidade", "Modalidade Jadlog", sorted(jm.MODALIDADES), "expresso")}
</div></fieldset>

<button type="submit">Cotar nas duas transportadoras</button>
</form></div></body></html>"""


@app.get("/", response_class=HTMLResponse)
def formulario() -> str:
    return FORMULARIO


def _montar(dados: dict) -> CotacaoRequest:
    """Formulário -> modelo central. Único ponto que conhece o HTML."""
    return CotacaoRequest(
        solicitante=Solicitante(nome=dados["nome"], email=dados["email"],
                                whatsapp=dados["whatsapp"]),
        servico=Servico.FRACIONADO_LTL,
        origem=Local(uf=dados["uf_origem"], cidade=dados["cidade_origem"],
                     cep=dados["cep_origem"]),
        destino=Local(uf=dados["uf_destino"], cidade=dados["cidade_destino"],
                      cep=dados["cep_destino"]),
        remetente=Parte(cnpj=dados["cnpj_remetente"]),
        destinatario=Parte(cnpj=dados["cnpj_destinatario"]),
        pagador_frete=Parte(cnpj=dados["cnpj_pagador"]),
        volumes=[Volume(
            qtd=int(dados["qtd"]),
            comprimento_cm=Decimal(dados["comprimento"].replace(",", ".")),
            largura_cm=Decimal(dados["largura"].replace(",", ".")),
            altura_cm=Decimal(dados["altura"].replace(",", ".")),
            peso_kg=Decimal(dados["peso"].replace(",", ".")))],
        mercadoria=Mercadoria(tipo_material=dados["tipo_material"]),
        nota_fiscal=NotaFiscal(
            valor_total=Decimal(dados["valor_nf"].replace(",", "."))),
    )


def _img(caminho: str | None) -> str:
    """Embute o PNG na página: evita servir runs/ (contém CNPJ e valor de NF)."""
    if not caminho or not Path(caminho).exists():
        return "<p class='status'>sem print</p>"
    dados = base64.b64encode(Path(caminho).read_bytes()).decode()
    return f'<img src="data:image/png;base64,{dados}" alt="print">'


def _cartao(titulo: str, res: ResultadoCotacao, nota: str, print_idx: int) -> str:
    if res.status is StatusCotacao.COTADO and res.valor_frete is not None:
        corpo = f'<div class="valor">R$ {res.valor_frete}</div>'
    elif res.motivo_recusa:
        # recusa da transportadora, não falha nossa: sem vermelho de erro
        corpo = (f'<p><b>Não atende esta rota:</b> {res.motivo_recusa}</p>'
                 f'<p class="status">Tente outra modalidade.</p>')
    elif res.erro:
        corpo = f'<p class="erro"><b>Erro:</b> {res.erro}</p>'
    else:
        corpo = ""
    prazo = (f"<p class='status'>Prazo: {res.prazo_dias} dias</p>"
             if res.prazo_dias is not None else "")
    evid = res.evidencias[print_idx] if len(res.evidencias) > print_idx else None
    return (f'<div class="card"><div class="status">{res.status.value}</div>'
            f'<h2>{titulo}</h2>{corpo}{prazo}'
            f'<p class="status">{nota}</p>{_img(evid)}</div>')


@app.post("/cotar", response_class=HTMLResponse)
def cotar(
    nome: str = Form(...), email: str = Form(...), whatsapp: str = Form(...),
    cep_origem: str = Form(...), uf_origem: str = Form(...),
    cidade_origem: str = Form(...), cnpj_remetente: str = Form(...),
    cep_destino: str = Form(...), uf_destino: str = Form(...),
    cidade_destino: str = Form(...), cnpj_destinatario: str = Form(...),
    qtd: str = Form(...), peso: str = Form(...), comprimento: str = Form(...),
    largura: str = Form(...), altura: str = Form(...), valor_nf: str = Form(...),
    tipo_material: str = Form(...), cnpj_pagador: str = Form(...),
    modalidade: str = Form("expresso"),
) -> str:
    """Endpoint SÍNCRONO de propósito: o FastAPI o roda numa thread do pool, e a
    API sync do Playwright não pode conviver com um event loop na mesma thread."""
    try:
        req = _montar(locals())
    except Exception as exc:
        return (f'<!doctype html><meta charset="utf-8"><style>{CSS}</style>'
                f'<div class="wrap"><div class="card"><h2 class="erro">Dados '
                f'inválidos</h2><p>{exc}</p><a class="voltar" href="/">← voltar'
                f'</a></div></div>')

    jadlog = JadlogSimuladorAdapter(modalidade=modalidade)
    dv = DellavolpeAdapter()

    # as duas em paralelo: cada uma leva ~10-20s de browser
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_jad = pool.submit(jadlog.cotar, req)
        f_dv = pool.submit(dv.cotar, req)     # confirmar_envio=False: dry-run
        res_jad, res_dv = f_jad.result(), f_dv.result()

    resumo = (f"<table>"
              f"<tr><td>Peso total</td><td>{req.peso_total_kg} kg</td></tr>"
              f"<tr><td>Volumes</td><td>{req.quantidade_volumes}</td></tr>"
              f"<tr><td>Cubagem</td><td>{req.cubagem_m3} m³</td></tr>"
              f"<tr><td>Peso cubado (fator {jm.FATOR_CUBAGEM})</td>"
              f"<td>{req.peso_cubado_kg(jm.FATOR_CUBAGEM)} kg</td></tr></table>")

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resultado — Cotação</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Resultado</h1>
<div class="sub">{req.origem.cidade}/{req.origem.uf} → {req.destino.cidade}/{req.destino.uf}</div>
<div class="card"><div class="status">carga</div>{resumo}</div>
{_cartao(f"Jadlog — {modalidade}", res_jad,
         "Simulador público. Preço de tabela, não o contratado; não informa prazo.", 0)}
{_cartao("Della Volpe", res_dv,
         "Dry-run: formulário preenchido, NADA enviado. O preço real chega por "
         "e-mail depois do envio.", 0)}
<a class="voltar" href="/">← nova cotação</a>
</div></body></html>"""
