# Cotafrete — Ventura

Cotação de frete em várias transportadoras a partir de **um formulário só**.

O problema que resolve: para saber quem leva mais barato, alguém abria sete
sites, redigitava os mesmos dados em cada um, anotava num papel e comparava.
Aqui se preenche uma vez e o sistema faz o resto.

```
Cotafrete.bat        <- duplo clique, abre em http://localhost:8001
Servidor.bat         <- publica na rede da empresa, na porta 8000
```

Para instalar no servidor da empresa: [docs/DEPLOY_SERVIDOR.md](docs/DEPLOY_SERVIDOR.md).
O Server 2012 R2 não roda o Chromium das transportadoras — o guia explica por
que, e como subir numa VM dentro do próprio servidor.

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

Python **3.13 ou 3.14** (o 3.14 está em produção e é o da máquina de
desenvolvimento):

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
```

Copie o `.env` (nunca vai pelo Git — tem senhas) para a raiz do projeto.

⚠ **Rode esses comandos na máquina onde o sistema vai rodar — não copie a
`.venv` pronta de outro lugar.** Ela guarda o caminho absoluto do Python que
a criou (`.venv\pyvenv.cfg`), e numa máquina diferente o `Servidor.bat` morre
com *"did not find executable at ..."*, citando um usuário que nem existe ali.
O mesmo vale para os navegadores: o `playwright install` grava em
`%USERPROFILE%`, ou seja, **por usuário do Windows**.

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
| `/adm` | painel da empresa inteira — senha própria, no `.env` |
| `/adm/cotacao/N` | a cotação de **qualquer** vendedor, inteira |

**Separação por usuário:** cada um vê só as suas. Trocar o número na URL não
abre a cotação alheia — o usuário entra na consulta ao banco.

### Painel do administrador

`COTAFRETE_ADM_SENHA` no `.env`. **Sem essa linha, `/adm` responde 404** — a
tela não passa a existir "aberta por engano" numa pasta onde ninguém
configurou nada. O cookie guarda um HMAC derivado da senha, e trocar a senha
derruba todas as sessões sozinha.

O painel mostra a empresa inteira no período escolhido (24 h / 7 / 30 dias /
tudo): faixa ao vivo de hoje, **alerta de falhas seguidas** a partir de 3,
movimento por dia, aproveitamento de cada transportadora, quem mais cotou,
rotas mais cotadas e o histórico de todo mundo — filtrável por vendedor e por
"só com falha".

Clicar numa linha do histórico abre **`/adm/cotacao/N`**: o que cada
transportadora respondeu, com preço, prazo, protocolo, o texto técnico do erro
**inteiro** (a tela do vendedor corta em 400 caracteres), o print de cada uma,
quanto tempo cada uma levou, a ficha da carga e quais conversas de WhatsApp o
vendedor chegou a abrir.

Essa é uma rota **própria** do adm: `/cotacao/N` continua exigindo o cookie do
vendedor e filtrando por dono. Duas portas separadas, em vez de uma porta com
um `if adm` no meio — e a garantia da tela do vendedor fica intacta, com teste
provando as duas coisas juntas.

A tela é **só leitura**: daqui não se apaga cotação, não se abre WhatsApp e
não se repete cotação. O adm entra para entender o que aconteceu; as ações
continuam sendo de quem cotou.

⚠ O painel junta CNPJ, razão social e valor de nota de todos os clientes num
lugar só. O `Servidor.bat` avisa que `0.0.0.0` inclui o Wi-Fi: numa rede com
visitantes, a senha do `.env` é a única barreira.

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
python -m pytest tests\ -q      # 777 testes, nenhum usa internet
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
TRANSLOVATO_CNPJ / _USUARIO / _SENHA       Translovato
GENEROSO_USUARIO / GENEROSO_SENHA          Transporte Generoso
DV_ENVIO_REAL_AUTORIZADO                   trava do envio real da Della Volpe
DV_AUTOMATICA_DESDE                        liga a Della Volpe como automática
DV_IMAP_HOST / _USUARIO / _SENHA           caixa do suporte (ingestor de e-mail)
COTAFRETE_ADM_SENHA                        senha do painel /adm
```

### Della Volpe: automática e ingestor de e-mail

Ela não mostra preço no site: responde por e-mail com uma proposta em PDF.
Duas chaves independentes no `.env`:

**Caixa do suporte** — liga o ingestor (`carriers/dellavolpe/ingestor.py`),
uma thread que sobe com o servidor e lê a caixa a cada minuto:

```
DV_IMAP_HOST=imap.exemplo.com.br
DV_IMAP_USUARIO=suporte@ventura.com.br
DV_IMAP_SENHA=...
# opcionais: DV_IMAP_PORTA=993  DV_IMAP_PASTA=INBOX  DV_IMAP_INTERVALO_S=60
#            DV_IMAP_DIAS=3  DV_EMAIL_RESPOSTA (se o usuário não for e-mail)
```

Com a caixa configurada, o formulário deles (automático **e** assistido)
passa a mandar a resposta para o suporte, com o carimbo `(cot. N)` no nome.
O ingestor acha o PDF, confere carimbo e rota e grava preço, prazo, validade
e o PDF na cotação. Ele só busca e-mail de `dellavolpe.com.br`, nunca apaga
nem move nada, e só marca como lido o que gravou. Sem a caixa, a resposta
continua indo para o e-mail do vendedor, como antes.

Conferir à mão, sem gravar nada:

```
.venv\Scripts\python.exe -m carriers.dellavolpe.ingestor            # só lê
.venv\Scripts\python.exe -m carriers.dellavolpe.ingestor --pdf x.pdf  # um PDF
.venv\Scripts\python.exe -m carriers.dellavolpe.ingestor --gravar   # grava
```

**Automática** — `DV_AUTOMATICA_DESDE` com a data e hora em que ela é ligada
**neste servidor** (ex.: `2026-09-23T09:00:00`), junto de
`DV_ENVIO_REAL_AUTORIZADO=sim`. A data impede a varredura de cotações
interrompidas de carimbar o histórico antigo (as 118 linhas fantasma da
Braspress). Se o site pedir a caixinha "confirme que é humano", nada é
enviado e a cotação cai no cartão **Semiautomática**.

**`GENEROSO_USUARIO`** é o "E-mail corporativo" da tela de login deles. Sem
essas duas linhas a Generoso nem tenta: deslogada ela não mostra preço, só
confirma o recebimento e responde por e-mail horas depois.

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

**Fase 3 — em andamento.** Ingestor IMAP da Della Volpe pronto (ver
"Della Volpe: automática e ingestor de e-mail"); a Generoso ainda não.

### Onde rodar

Desde **14/09/2026** o sistema roda numa **máquina virtual Windows 10 dentro
do servidor da empresa**, publicada na internet por um túnel da Cloudflare em
`cotafrete.ventura.inf.br`.

A VM existe porque o servidor é **Windows Server 2012 R2**, e o Chromium
parou de suportar esse sistema na versão 110 (fev/2023) — as páginas
simplesmente não carregam. Como cinco das seis transportadoras cotam abrindo
navegador de verdade (e duas exigem **janela**, por causa do checkpoint da
Vercel na Generoso e do reCAPTCHA da Della Volpe), Chromium atual é
requisito — e Chromium atual pede Windows 10 ou mais novo.

| | |
|---|---|
| VM | Windows 10, **4 vCPU**, 8 GB — pasta `C:\enzo\cotafrete-producao` |
| Host | Xeon E3-1270 v2 (4 núcleos / 8 lógicos), 32 GB |
| Python | **3.14** em produção; 3.13 também serve |
| Acesso | túnel da Cloudflare + **Cloudflare Access** (código por e-mail) |
| Tempo de resposta | ~135 s com um vendedor; ~180 s com dois ao mesmo tempo |

Os **4 vCPU** não são luxo: com 1 vCPU a hidratação do SPA da Generoso
chegava depois do preenchimento e apagava os campos de login, derrubando
cotações (as #75, #76 e #77). O código hoje tolera isso, mas a máquina era a
causa.

Dois roteiros cobrem a instalação, nesta ordem:

- [`docs/DEPLOY_SERVIDOR.md`](docs/DEPLOY_SERVIDOR.md) — criar a VM e
  instalar o Cotafrete nela.
- [`docs/CONFIGURAR_NA_EMPRESA.md`](docs/CONFIGURAR_NA_EMPRESA.md) — deixar
  tudo subindo sozinho e publicar na internet.

**O vendedor entra com senha** desde 16/09/2026. A conta é criada pelo
administrador em `/adm/contas`; a senha quem escolhe é a própria pessoa, no
primeiro acesso, e nem o administrador consegue vê-la (fica como hash scrypt,
ver `core/sessao.py`). Antes disso a tela aceitava qualquer nome digitado —
e o cookie guardava esse nome puro, então trocá-lo no navegador era virar
outra pessoa.

> **Ao subir esta versão, crie as contas antes de avisar a equipe.** Quem não
> tem conta não entra, e o histórico anterior não vira conta sozinho. A tela
> `/adm/contas` lista quem já cotou e cria cada um com um clique.

O backup do banco é o `Backup.bat`, agendado na VM para rodar todo dia — ver
[`docs/CONFIGURAR_NA_EMPRESA.md`](docs/CONFIGURAR_NA_EMPRESA.md), passo 8.
Ele **não** copia o arquivo: o banco roda em WAL, e nesse modo o `.db` sozinho
está atrasado — uma cópia crua sai sem as cotações mais recentes, sem erro
nenhum. O `core/backup.py` usa a API de backup online do SQLite, que lê
através do WAL com o servidor no ar, e confere a cópia depois de gravar.

---

## O que já foi confirmado contra os sites reais

- **Fator de cubagem 300** na Della Volpe, por quatro propostas em PDF que
  declaram o peso cubado calculado por eles. Era suposição desde o início.
- **R$ 69,91** na Camilo, o mesmo valor da cotação feita à mão — prova de que
  o adapter reproduz o que uma pessoa faria.
- **5 cotações reais** na Della Volpe (4 propostas recebidas por e-mail) e
  **5 no Generoso**, todas confirmadas pelo site.
