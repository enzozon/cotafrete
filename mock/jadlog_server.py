"""Mock da API Jadlog. Permite testar o adapter inteiro sem contrato e sem token.

    uvicorn mock.jadlog_server:app --port 8098

Valida token, CEP e peso como a API real faria, e devolve o mesmo formato de
resposta. Assim que você tiver o token de verdade, basta trocar a URL.
"""

from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock Jadlog Embarcador API")

TOKEN_FAKE = "Bearer TOKEN-DE-TESTE"
ULTIMO_PAYLOAD: dict = {}


@app.post("/embarcador/api/frete/valor")
async def frete_valor(request: Request,
                      authorization: str = Header(default="")) -> JSONResponse:
    if authorization != TOKEN_FAKE:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    corpo = await request.json()
    ULTIMO_PAYLOAD.clear()
    ULTIMO_PAYLOAD.update(corpo)

    saida = []
    for item in corpo.get("frete", []):
        cepori = str(item.get("cepori", ""))
        cepdes = str(item.get("cepdes", ""))
        peso = float(item.get("peso") or 0)

        if len(cepori) != 8 or len(cepdes) != 8:
            saida.append({**_eco(item), "erro": {
                "id": "1", "descricao": "CEP inválido"}})
            continue
        if peso <= 0:
            saida.append({**_eco(item), "erro": {
                "id": "2", "descricao": "Peso inválido"}})
            continue
        if peso > 120:
            saida.append({**_eco(item), "erro": {
                "id": "3", "descricao": "Peso acima do permitido"}})
            continue

        # tabela fictícia determinística: base + por kg + % do declarado
        declarado = float(item.get("vldeclarado") or 0)
        frete = round(18.90 + peso * 2.35 + declarado * 0.004, 2)
        interestadual = cepori[:1] != cepdes[:1]
        saida.append({
            **_eco(item),
            "vlfrete": frete,
            "vltotal": round(frete * 1.12, 2),   # com tributos
            "prazo": 5 if interestadual else 2,
        })

    return JSONResponse({"frete": saida})


def _eco(item: dict) -> dict:
    return {
        "id": 1,
        "cnpj": item.get("cnpj"),
        "cepori": item.get("cepori"),
        "cepdes": item.get("cepdes"),
    }


@app.get("/ultimo-payload")
def ultimo_payload() -> JSONResponse:
    return JSONResponse(ULTIMO_PAYLOAD)
