"""Réplica local do formulário da Della Volpe.

Serve para rodar o Playwright de verdade — preenchimento, selects dependentes,
upload, submit — sem mandar nada para a transportadora. O endpoint devolve em
JSON tudo que recebeu, então dá para conferir campo a campo se o dado certo
chegou no lugar certo.

    pip install fastapi uvicorn python-multipart
    uvicorn mock.server:app --port 8099
    # abre http://localhost:8099

Depois de rodar o recon no site real, substitua os `name=` daqui pelos reais,
e o mock passa a ser um espelho fiel.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Mock Della Volpe")

ULTIMO_ENVIO: dict[str, Any] = {}

UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
       "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
       "SE", "SP", "TO"]

CIDADES = {
    "ES": ["Vitória", "Vila Velha", "Serra", "Cariacica", "Linhares"],
    "SP": ["São Paulo", "Campinas", "Santos", "Guarulhos"],
    "MG": ["Belo Horizonte", "Uberlândia", "Contagem"],
    "RJ": ["Rio de Janeiro", "Niterói", "Duque de Caxias"],
}

VEICULOS = ["Bug 20", "Bug 40", "Carreta LS (até 30.000 kg)",
            "Carreta Simples (até 27.000 kg)", "Fiorino (até 500 kg)",
            "Truck (até 12.500 kg)", "Van (até 1000 kg)",
            "Carreta Vanderleia (até 34.000 kg)"]


def _sel(name: str, label: str, opcoes: list[str], req: bool = True) -> str:
    ops = "".join(f'<option value="{o}">{o}</option>' for o in opcoes)
    return (f'<label for="{name}">{label}{"*" if req else ""}</label>'
            f'<select id="{name}" name="{name}" {"required" if req else ""}>'
            f'<option value="">{label}{"*" if req else ""}</option>{ops}</select>')


def _txt(name: str, label: str, tipo: str = "text", req: bool = True) -> str:
    return (f'<label for="{name}">{label}{"*" if req else ""}</label>'
            f'<input id="{name}" name="{name}" type="{tipo}" '
            f'placeholder="{label}{"*" if req else ""}" {"required" if req else ""}>')


PAGINA = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Mock — Faça uma Cotação</title><style>
body{{font-family:system-ui,sans-serif;background:#f8981d;margin:0;padding:32px}}
form{{max-width:760px;margin:auto;background:#f8981d;border:2px solid #fff;
border-radius:12px;padding:28px;color:#fff}}
h2{{text-align:center;margin:0 0 20px}}
label{{display:block;font-size:12px;margin:14px 0 4px;opacity:.9}}
input,select{{width:100%;padding:11px;border:0;border-radius:6px;font-size:14px;
box-sizing:border-box}}
fieldset{{border:1px dashed #fff;border-radius:8px;margin:18px 0;padding:12px}}
legend{{font-size:13px;padding:0 6px}}
button{{width:100%;margin-top:22px;padding:14px;border:2px solid #fff;
background:transparent;color:#fff;font-weight:700;font-size:15px;
border-radius:8px;cursor:pointer}}
.hint{{font-size:11px;opacity:.85;margin-top:4px}}
#veiculo-bloco{{display:none}}
</style></head><body>
<form id="form-cotacao" method="post" action="/pedir-orcamento"
      enctype="multipart/form-data">
<h2>Preencha os campos abaixo e enviaremos<br>uma cotação para o serviço que necessitar</h2>

{_txt("nome", "Nome completo")}
{_txt("email", "E-mail", "email")}
{_txt("whatsapp", "WhatsApp", "tel")}
{_sel("servico", "Qual o serviço que você procura?", ["Fracionado -LTL", "Lotação/Dedicado-FTL"])}

{_txt("cnpj_remetente", "CNPJ - Remetente")}
{_sel("uf_origem", "Selecione o estado de origem", UFS)}
{_sel("cidade_origem", "Selecione a cidade de origem", [])}

{_txt("cnpj_destinatario", "CNPJ - Destinatário")}
{_sel("uf_destino", "Selecione o estado de destino", UFS)}
{_sel("cidade_destino", "Selecione a cidade de destino", [])}

<div id="veiculo-bloco">{_sel("tipo_veiculo", "Escolha o tipo de veículo", VEICULOS, False)}</div>

{_txt("peso_total", "Peso total (1 ~ 34.000kg)")}
{_txt("quantidade_volumes", "Quantidade de Volumes")}

<fieldset><legend>Medidas dos Volumes (cm)</legend>
{_txt("comprimento", "Comprimento (ex. 12,5m = 1.250,0cm)")}
{_txt("largura", "Largura (ex. 2,5m = 250,0cm)")}
{_txt("altura", "Altura (ex. 2,9m = 290,0cm)")}
<div class="hint">Se houver mais volumes com medidas diferentes,
anexar planilha em Excel</div>
<label for="planilha">Anexar Planilha</label>
<input id="planilha" name="planilha" type="file" multiple>
</fieldset>

{_txt("valor_nf", "Valor total da nota fiscal")}
{_txt("tipo_material", "Tipo de Material que será transportado")}
<div class="hint">(se for produto químico, favor enviar a FISPQ no anexo)</div>
<label for="fispq">Anexar FISPQ / Licença</label>
<input id="fispq" name="fispq" type="file" multiple>

{_txt("cnpj_pagador", "CNPJ da empresa que pagará o frete")}
<button type="submit">Pedir orçamento</button>
</form>

<script>
const CIDADES = {json.dumps(CIDADES, ensure_ascii=False)};
function ligar(ufId, cidadeId) {{
  const uf = document.getElementById(ufId), cid = document.getElementById(cidadeId);
  uf.addEventListener('change', () => {{
    cid.innerHTML = '<option value="">Selecione a cidade*</option>';
    // atraso proposital: simula o XHR do site real
    setTimeout(() => {{
      (CIDADES[uf.value] || ['Cidade não mapeada']).forEach(c => {{
        const o = document.createElement('option'); o.value = c; o.text = c;
        cid.appendChild(o);
      }});
    }}, 400);
  }});
}}
ligar('uf_origem', 'cidade_origem');
ligar('uf_destino', 'cidade_destino');

document.getElementById('servico').addEventListener('change', e => {{
  document.getElementById('veiculo-bloco').style.display =
    e.target.value.includes('FTL') ? 'block' : 'none';
}});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def formulario() -> str:
    return PAGINA


@app.post("/pedir-orcamento", response_class=HTMLResponse)
async def pedir_orcamento(request: Request) -> str:
    form = await request.form()
    recebido: dict[str, Any] = {}
    arquivos: dict[str, list[str]] = {}
    for chave, valor in form.multi_items():
        if isinstance(valor, UploadFile):
            arquivos.setdefault(chave, []).append(valor.filename or "?")
        else:
            recebido[chave] = valor

    ULTIMO_ENVIO.clear()
    ULTIMO_ENVIO.update({"campos": recebido, "arquivos": arquivos})

    print("\n=== RECEBIDO PELO MOCK ===")
    print(json.dumps(ULTIMO_ENVIO, ensure_ascii=False, indent=2))

    faltando = [k for k, v in recebido.items() if not str(v).strip()]
    if faltando:
        return f"<h1>Erro</h1><p>Campos vazios: {', '.join(faltando)}</p>"
    return "<h1>Obrigado!</h1><p>Sua mensagem foi enviada com sucesso.</p>"


@app.get("/ultimo-envio")
def ultimo_envio() -> JSONResponse:
    """Usado pelos testes para conferir o que chegou."""
    return JSONResponse(ULTIMO_ENVIO)
