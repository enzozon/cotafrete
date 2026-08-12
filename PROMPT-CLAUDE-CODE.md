# Prompt para o Claude Code

Descompacte o zip na raiz do repositório antes de rodar. Depois cole tudo
abaixo da linha no terminal (`claude` na pasta do projeto).

---

Este repositório já contém uma plataforma de cotação de fretes com dois
adapters implementados: Della Volpe (automação de formulário via Playwright) e
Jadlog (API REST oficial). O código existe e tem 47 testes passando.

NÃO reescreva do zero. Sua tarefa é VALIDAR e ENCONTRAR BUGS.

## Passo 1 — Situar-se
Leia, nesta ordem: README.md, core/models.py, carriers/base.py,
carriers/dellavolpe/mapping.py, carriers/jadlog/mapping.py, carriers/registry.py.
Não altere nada ainda. Me diga em até 10 linhas o que o sistema faz e onde estão
as fronteiras entre camada pura e camada de I/O.

## Passo 2 — Ambiente
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```
Se algo falhar, corrija e me diga o quê.

## Passo 3 — Testes puros
```
pytest tests/ -v
```
Esperado: 47 passando. Se algum falhar, me mostre o output antes de mexer.

## Passo 4 — End-to-end Della Volpe (mock local)
Suba `uvicorn mock.server:app --port 8099` em background e rode
`python testar_local.py`. Ele compara campo a campo o que o mock recebeu com o
payload esperado. Todos devem bater e a planilha de volumes deve ser anexada.

## Passo 5 — End-to-end Jadlog (mock local)
Suba `uvicorn mock.jadlog_server:app --port 8098` e escreva um script que use
`JadlogAdapter` apontando para o mock. Confirme: status COTADO, valor > 0,
prazo preenchido, e que o campo `peso` enviado é o MAIOR entre peso real e
cubado (regra explícita da doc da Jadlog).

## Passo 6 — Recon do site real (só leitura)
```
python recon_dellavolpe.py --headed
```
Compare `recon_out/campos.json` com os rótulos usados em
`carriers/dellavolpe/mapping.py`. Me diga quais não batem. Este script NÃO envia
o formulário — não altere isso.

## Passo 7 — Dry-run no site real
`DellavolpeAdapter(headless=False).cotar(req)` com o default
`confirmar_envio=False`: navega, preenche, printa em `runs/<ts>/preenchido.png`,
para antes do submit. Me diga quais campos ficaram vazios ou errados no print.

## Passo 8 — Caça a bugs
Audite com atenção, e desconfie especialmente destes pontos:

- `DellavolpeAdapter._localizar`: o terceiro fallback usa
  `[name*="{rotulo[:14]}" i]`. Truncar em 14 chars pode casar com o campo errado
  quando dois rótulos compartilham prefixo (ex.: os três CNPJs). Verifique.
- `_preencher`: a ordem UF-antes-de-cidade depende de ordenação alfabética
  (`"cidade" in k.lower()`). É frágil. Existe caso em que quebra?
- Selects de cidade: o `wait_for_timeout(1200)` fixo é race condition. Trocar
  por espera do XHR ou por `wait_for_function` no número de options.
- `jadlog/mapping.py::_num` trata `0` como ausente. Verifique se isso pode
  mascarar uma resposta legítima.
- `MODALIDADES` e `FATOR_CUBAGEM` da Jadlog estão marcados como presumidos.
  Não invente valores; apenas sinalize.
- Cubagem com `Decimal`: procure qualquer ponto onde vire `float` e perca
  precisão antes de ir para a API.
- Rode `pytest --cov` e me diga o que NÃO está coberto.

Para cada bug: arquivo, linha, por que quebra, e um teste que falha antes do
fix. Escreva o teste PRIMEIRO, veja ele falhar, depois corrija.

## Regras rígidas
1. NUNCA envie o formulário real da Della Volpe. Cada submit vira uma cotação
   na fila de um vendedor. Só com `DV_ENVIO_REAL_AUTORIZADO=sim`, e só se eu
   pedir explicitamente. Não defina essa variável por conta própria.
2. NÃO temos token Jadlog ainda. Tudo contra o mock.
3. Não commite `.env`, `runs/` ou `recon_out/`.
4. Não altere a camada pura para fazer o browser passar. Se o mapeamento estiver
   certo e o browser errado, o problema é do adapter.
5. Trabalhe em branch: `git checkout -b validacao-adapters`.

Comece pelo Passo 1 e pare para eu confirmar antes do Passo 6.
