# Cotafrete — Ventura

Cotação de frete em várias transportadoras a partir de **um formulário só**.

O problema que resolve: para saber quem leva mais barato, alguém abria sete
sites, redigitava os mesmos dados em cada um, anotava num papel e comparava.
Aqui se preenche uma vez e o sistema faz o resto.

```
Cotafrete.bat        <- duplo clique, abre em http://localhost:8001
Servidor.bat         <- publica na rede da empresa, na porta 8000
```

---

## As sete transportadoras, e por que não são iguais

A diferença que define a interface inteira: **nem todas devolvem preço**.

| transportadora | como cota | tempo | o que devolve |
|---|---|---|---|
| **Camilo dos Santos** (SSW) | login + formulário | ~25 s | **preço + composição completa** |
| **Jadlog Entregas** (painel) | login + formulário | ~15 s | preço de varejo (balcão) |
| **Generoso** | formulário em 5 etapas | ~50 s | só confirmação; preço por e-mail |
| **Della Volpe** | formulário único | ~110 s | só confirmação; preço por e-mail |
| **Movvi** | WhatsApp | — | pessoa responde |
| **Translovato** | WhatsApp | — | pessoa responde |
| **Continental** | WhatsApp | — | pessoa responde |

Três consequências de projeto:

1. **Os resultados aparecem conforme chegam.** A Jadlog responde em 15 s; a
   Della Volpe em 110 s. Esperar a mais lenta seria dois minutos de tela
   branca.
2. **Cada preço diz o que inclui.** R$ 33,35 da Jadlog (você leva ao balcão)
   ao lado de R$ 69,91 da Camilo (coleta na porta, com CT-e e ICMS) leva à
   decisão errada sem contexto.
3. **WhatsApp nunca é automático.** O sistema prepara a mensagem; quem aperta
   enviar é a pessoa. Não existe status "aguardando retorno" para elas.

---

## A armadilha central: o mesmo número, quatro formatos

Você digita `30`. Cada site quer isso escrito de um jeito, e **errar não dá
erro** — cota a carga errada e o preço parece certo.

| site | medida | peso |
|---|---|---|
| Della Volpe | `30,0` — 1 casa obrigatória | livre |
| Jadlog painel | `30` — inteiro | `1,00` — 2 casas |
| Generoso | `30` — inteiro | `1,00` — 2 casas |
| Camilo (SSW) | **`0,300` — METROS** | `1,000` |

Isso já quebrou três vezes neste projeto: a Della Volpe cotou carga 10× menor,
a Jadlog 100× menor, e a Camilo cotaria uma caixa de 30 metros.

**A tradução mora no adapter, nunca no formulário.** O usuário digita
centímetros; quem sabe o resto é o código, e cada regra tem teste.

---

## Como usar

### Primeira vez

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Copie o `.env` (nunca vai pelo Git — tem senhas) para a raiz do projeto.

### No dia a dia

Duplo clique em **`Cotafrete.bat`**. Ele sobe o servidor e abre o navegador.

**Fechar a janela desliga o sistema** — é de propósito. Em segundo plano ele
seguraria a porta 8000 e o próximo duplo clique falharia sem explicar. Se a
porta já estiver ocupada, o `.bat` detecta e pergunta se pode encerrar.

⚠ Cotação em andamento **não sobrevive** ao fechamento: as transportadoras
rodam em threads dentro do processo. Se a tela ainda mostra "cotando…",
espere os ~25 s. O que ficar pendente é marcado como *interrompido* na
próxima subida.

---

## As telas

| rota | o que faz |
|---|---|
| `/login` | digitou o nome, entrou — **placeholder, sem senha** |
| `/` | formulário único |
| `/cotar` | dispara e redireciona na hora |
| `/cotacao/N` | resultados, com selo no mais barato e print de cada uma |
| `/historico` | as cotações **da pessoa**, com o melhor preço de cada |

**Separação por usuário:** cada um vê só as suas. Trocar o número na URL não
abre a cotação alheia — o usuário entra na consulta ao banco.

**Cidade e estado não são campos**: saem do CEP via ViaCEP. Foi digitar
cidade à mão que gerou uma ficha dizendo "São José dos Campos" com CEP de São
Bernardo do Campo — e como a Jadlog cota por CEP e a Della Volpe por cidade,
a mesma ficha cotava duas rotas diferentes.

**Razão social vem do CNPJ** (BrasilAPI), para a mensagem de WhatsApp dizer
quem envia, quem recebe e quem paga.

### Página de WhatsApp

`web/cotacao_whatsapp.html` — arquivo único, autocontido, abre com dois
cliques. Gera a mensagem no padrão da empresa e abre o WhatsApp das três
transportadoras com o texto pronto. Tem 24 checagens que rodam no
carregamento (`window.autoteste()` no console).

---

## Arquitetura

Separação **pura / IO**, que é o que torna o projeto testável:

```
core/
  models.py    modelo central — não conhece transportadora nenhuma
  ficha.py     texto "Chave: valor" -> modelo (puro; a busca de CEP é injetada)
  cep.py       CEP -> cidade/UF/IBGE (ViaCEP, com cache)
  cnpj.py      CNPJ -> razão social (BrasilAPI, com cache)
  banco.py     histórico em SQLite

carriers/
  base.py      contrato comum + utilitários de screenshot
  <nome>/
    mapping.py   camada PURA: modelo -> campos daquele site
    adapter.py   camada de BROWSER: Playwright

web/
  app.py                 interface FastAPI
  cotacao_whatsapp.html  página de WhatsApp, independente
```

**O que é puro roda sem internet e tem teste.** O que é browser é fino de
propósito: só localizar campo e digitar.

**Seletores por rótulo, nunca por posição.** É o que faz a automação
sobreviver a mudança de layout — e na Camilo a ordem dos campos de medida é
Altura/Largura/Comprimento, invertida em relação aos outros.

---

## Formato de entrada

Ver **`REGRAS_FICHA.md`** — as 7 regras do arquivo de texto:

```
Nome Completo: Enzo Zon
email: vendas2@venturainformatica.com.br
WhatsApp: +55 (27) 3339-1891
CEP ORIGEM: 09895-003
CEP DESTINO: 29105-770
CNPJ Remetente: 60.042.686/0001-05
Peso Total (kg): 12          <- peso de UM volume
Quantidade de Volumes: 3     <- carga total = 36 kg
Comprimento (cm): 30
Valor Total Nota Fiscal: 568,77
Material: LUVA DE BOMBEIRO
```

Decisões de interface do site: **`REGRAS_SITE_COTACAO.md`**.

---

## Testes

```bash
python -m pytest tests\ -q      # 223 testes, nenhum usa internet
```

Cada teste tem o caso real que o gerou no docstring. Não são testes de
fachada: todos foram escritos **antes** do fix, e cada um falhou primeiro.

Scripts de verificação contra os sites reais:

| script | o que faz |
|---|---|
| `tests/manuais/testar_tudo.py` | 3 cargas em cada transportadora, dry-run |
| `tests/manuais/testar_teste_real.py` | ficha real na Jadlog e Della Volpe |
| `tests/manuais/testar_generoso_real.py` | 5 envios reais no Generoso |
| `recon/recon_*.py` | mapeamento read-only de cada site |

Todos rodam **a partir da raiz do projeto**. `recon/` mapeia site novo (lê, não
envia); `tests/manuais/` são os que se roda a mão contra os sites reais — ficam
dentro de `tests/` mas o `pytest` não os coleta, porque `testar_*` não casa com
o padrão `test_*` que ele procura.

---

## Credenciais e dados sensíveis

Tudo no **`.env`**, que nunca vai para o Git:

```
SSW_DOMINIO / SSW_USUARIO / SSW_SENHA      Camilo dos Santos
JADLOG_PAINEL_USUARIO / _SENHA             Jadlog Entregas
DV_ENVIO_REAL_AUTORIZADO                   trava do envio real da Della Volpe
```

Fora do Git também: `cotafrete.db`, `runs/`, `teste_real/`, `recon_out/`,
`.cache/` — todos têm CNPJ de cliente e valor de nota fiscal.

**`DV_ENVIO_REAL_AUTORIZADO`** é a trava do envio real da Della Volpe: cada
submissão vira uma cotação na fila de um vendedor. O código nunca liga isso
sozinho.

---

## Estado

**Fase 1 — pronta e em uso.** Camilo, Jadlog e os três cartões de WhatsApp,
com login, histórico por usuário, repetir cotação, máscaras de CNPJ e CEP,
validação antes de cotar e resultados aparecendo conforme chegam.

**Fase 2 — pendente.** Generoso e Della Volpe. Os adapters estão prontos e
validados; falta somá-los em `AUTOMATICAS` no `web/app.py`.

> **Decisão a tomar antes:** a Della Volpe só envia com **janela de navegador
> visível** — o reCAPTCHA v3 barra headless e responde "A submissão
> mencionou-se como spam", sem gerar e-mail. Medido: 5 envios headless não
> geraram nada; com janela real, passaram. Ou se aceita a janela abrindo a
> cada cotação, ou ela fica fora da automação.

**Fase 3 — depois.** Ingestor IMAP para ler as propostas em PDF e preencher
o preço que a Generoso e a Della Volpe mandam por e-mail.

### Onde rodar

Hoje roda na máquina do Enzo. O servidor da empresa é **Windows 8.1**, onde
o Python 3.12 funciona mas o Chromium do Playwright **não** — o Chrome 109,
de janeiro de 2023, foi o último a suportar esse sistema. Guia de
verificação em `TESTE_NO_SERVIDOR.txt`.

---

## O que já foi confirmado contra os sites reais

- **Fator de cubagem 300** na Della Volpe, por quatro propostas em PDF que
  declaram o peso cubado calculado por eles. Era suposição desde o início.
- **R$ 69,91** na Camilo, o mesmo valor da cotação feita à mão — prova de que
  o adapter reproduz o que uma pessoa faria.
- **5 cotações reais** na Della Volpe (4 propostas recebidas por e-mail) e
  **5 no Generoso**, todas confirmadas pelo site.
