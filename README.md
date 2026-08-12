# Cotação de Fretes — plataforma multi-transportadora

Cadastra a carga uma vez, cota em várias transportadoras, compara e envia por e-mail.

## Estado atual

| Transportadora | Integração | Modo | Precisa de credencial | Testável agora |
|---|---|---|---|---|
| Della Volpe | Playwright (formulário) | assíncrono ~15 min | não | ✅ mock + dry-run |
| Jadlog | API REST oficial | **síncrono** | ✅ token de contrato | ✅ só via mock |

## Instalar
```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env    # preencha; .env está no .gitignore
```

## Testes (44, nenhum toca a internet)
```bash
pytest tests/ -v
```

## Della Volpe

```bash
# 1. mock local — pode usar valores fictícios à vontade
uvicorn mock.server:app --port 8099
python testar_local.py --headed

# 2. dry-run no site real: preenche, tira print, NÃO envia
python -c "from carriers.dellavolpe.adapter import DellavolpeAdapter; ..."
#    -> runs/<timestamp>/preenchido.png

# 3. envio real: só com carga que você precisa cotar de fato
DV_ENVIO_REAL_AUTORIZADO=sim ...   # com confirmar_envio=True
```

## Jadlog

```bash
# sem token — mock replica a API inteira
uvicorn mock.jadlog_server:app --port 8098
JADLOG_TOKEN="TOKEN-DE-TESTE" \
JADLOG_URL="http://localhost:8098/embarcador/api/frete/valor" python ...

# com token real, só troque as variáveis no .env
```

O token vem da **franquia Jadlog que atende seu CNPJ**, via contrato.
Não existe cotação Jadlog por API sem ele.

## Arquitetura

```
core/models.py               modelo central (Pydantic v2) — não conhece transportadora
carriers/base.py             Protocol CarrierAdapter
carriers/registry.py         fan-out isolado + comparativo
carriers/dellavolpe/
  mapping.py                 PURO: modelo -> campos do formulário
  adapter.py                 BROWSER: Playwright
  planilha.py                gera o .xlsx de volumes
carriers/jadlog/
  mapping.py                 PURO: modelo -> JSON da API
  adapter.py                 HTTP: POST autenticado
mock/                        réplicas locais para teste sem tocar em produção
```

Toda transportadora tem `mapping.py` (puro, testável em qualquer máquina) e um
adapter (browser ou HTTP). O orquestrador só chama `cotar()` — não sabe qual é qual.

## Adicionar transportadora nova
1. `carriers/<slug>/mapping.py` — payload + validações, funções puras
2. `carriers/<slug>/adapter.py` — implementa o Protocol
3. `mock/<slug>_server.py` — réplica para teste
4. `tests/test_<slug>.py`
5. registrar em `carriers/registry.py`

Nenhum arquivo de `core/` é tocado.

## Pendências
- [ ] ingestor IMAP: fecha o ciclo da Della Volpe (aguardando_retorno -> cotado)
- [ ] confirmar fator de cubagem e códigos de modalidade Jadlog no contrato
- [ ] rodar `recon_dellavolpe.py` e ajustar seletores
- [ ] persistência (SQLAlchemy) + histórico
- [ ] interface web
