# Dashboard administrativo do Cotafrete

**Data:** 28/08/2026
**Estado:** desenho aprovado; falta o plano de implementação.

## Por que

O `monitorar.py` mostra o que está acontecendo AGORA, num terminal, e faz isso
bem. O que ninguém consegue hoje é enxergar o conjunto: quais erros mais se
repetem, se uma transportadora está degradando, o que já foi cotado pela
empresa inteira. Essa informação existe no banco e só sai de lá com consulta
SQL escrita à mão.

O custo disso é concreto e recente. A Jadlog falhou no login em **5 tentativas
seguidas**, da cotação #49 (27/08 16:13) até a #56 (28/08 09:22), e o problema
só foi notado quando um vendedor reclamou — quase um dia depois. Uma tela que
dissesse "a Jadlog falhou nas últimas 5 tentativas" teria antecipado isso.

## Decisões tomadas

| Decisão | Escolha |
|---|---|
| Acesso | Senha única de adm no `.env` |
| Formato | Uma tela: faixa ao vivo no topo, análise embaixo |
| Erros | Defeitos e recusas **separados** |
| Onde mora | `core/painel.py` + `web/adm.py` + `web/graficos.py` |
| `monitorar.py` | Fica como está, sem mexer |
| Hora da resposta | Coluna nova `respondido_em`, agora |

## Segurança

**A senha vive só em `COTAFRETE_ADM_SENHA`, no `.env` de cada pasta.**

- **Sem a variável, `/adm` responde 404.** A rota não passa a existir "aberta
  por engano" numa pasta onde ninguém configurou nada. Mesmo espírito do aviso
  de arranque da Della Volpe.
- O cookie **não** pode ser `adm=sim`: qualquer um que soubesse o nome entraria
  digitando no navegador. Guarda
  `hmac.new(senha, b"cotafrete-adm", "sha256").hexdigest()`. Quem tem a senha
  produz esse valor — que é exatamente a permissão concedida. Sem segredo extra
  para administrar, e **trocar a senha invalida todas as sessões**.
- Comparação com `hmac.compare_digest` (não vaza tempo).
- Cookie `httponly`, `samesite=lax`, **12 horas** — acesso mais poderoso que o
  do vendedor (30 dias) dura menos.
- Senha errada dorme **1 segundo** antes de responder. Não é bloqueio; é o
  suficiente para inviabilizar tentativa em massa numa rede local. Se um dia a
  tela for para a internet, isto precisa virar bloqueio de verdade.
- A senha nunca vai para log, HTML ou URL. Só POST.

**O que NÃO muda:** `banco.buscar_cotacao` e `banco.listar_cotacoes` continuam
travados por usuário. A garantia que a tela do vendedor tem hoje — coberta por
`test_cotacao_de_outro_usuario_nao_abre` — fica intacta. O adm ganha funções
**próprias**, que consultam sem o filtro. Duas portas separadas, em vez de uma
porta com um `if adm` no meio.

## Como cada status é classificado

Sem isto, "aproveitamento" fica ambíguo e cada bloco da tela poderia contar
diferente. A tabela é a definição única:

| status | conta como | por quê |
|---|---|---|
| `cotado` | **sucesso** | veio preço |
| `aguardando_retorno` | **sucesso** | a Della Volpe recebeu; o preço vem por e-mail. Não é falha nem recusa |
| `recusado` | **recusa** | a transportadora entendeu e disse não, com o motivo dela |
| `erro` | **falha** | ninguém sabe o que houve — é o que se conserta |
| `intervencao_necessaria` | **falha** | credencial recusada; precisa de uma pessoa |
| `interrompido` | **nossa** | o servidor reiniciou no meio. Não é culpa da transportadora e não entra no aproveitamento dela — vira uma contagem à parte |
| `rascunho` | ignorado | só existe em ensaio (`confirmar_envio=False`); não deveria aparecer em produção. Se aparecer, a tela mostra em "inesperados" em vez de esconder |

**Aproveitamento** = sucesso ÷ (sucesso + recusa + falha). `interrompido` fica
de fora do denominador: punir a transportadora por um restart nosso faria o
número mentir.

## As peças

### `core/painel.py` — as contas (puro)

Recebe conexão, devolve `list[dict]`. Nenhum HTML. Testável sem navegador e sem
servidor, como `carriers/*/mapping.py`.

- `resumo_do_dia()` — cotações, com preço, **sem nenhum preço**, em andamento
- `saude_das_transportadoras(dias)` — cotou / recusou / falhou / aproveitamento
- `falhas_seguidas()` — quantas falhas consecutivas sem sucesso no meio.
  **Alerta a partir de 3.** Duas acontecem por acaso; três seguidas, na
  série medida até aqui, sempre foram problema de verdade
- `falhas_agrupadas(dias)` — defeitos por assinatura
- `recusas_agrupadas(dias)` — motivos de recusa por transportadora
- `serie_por_dia(dias)` — cotações e falhas por dia
- `economia(dias)`, `rotas(dias)`, `whatsapp_por_transportadora(dias)`
- `historico(filtros, pagina)`

**A peça delicada: `assinatura_do_erro(texto)`.** Normaliza números e caminhos
para que `Timeout 45000ms` e `Timeout 30000ms` caiam no mesmo grupo. Se ela
agrupar errado, o ranking inteiro mente — é o risco central da tela. Função
pura, testada contra os textos de erro **reais** que já estão no banco.

### `web/adm.py` — rotas e HTML

Reaproveita `pagina()` e o CSS de `web/app.py`. Fica em arquivo próprio porque
`web/app.py` já tem **1753 linhas**, mais que o dobro do teto de 800 do padrão
do projeto.

### `web/graficos.py` — dados → desenho (puro)

Barras horizontais em CSS, séries temporais em SVG inline gerado em Python.
**Sem biblioteca nova**: funciona sem internet e imprime bem.

### O fluxo do "ao vivo"

A faixa do topo **não** recarrega a página — recarregar perderia a rolagem toda
vez que alguém estivesse lendo a análise embaixo. `/adm/agora` devolve um
fragmento de HTML, e ~10 linhas de JavaScript trocam só aquela faixa a cada
10 segundos.

## A tela, de cima para baixo

1. **Faixa ao vivo** — hoje: quantas cotações, quantas com preço, **quantas
   ficaram sem nenhum preço**; e o que está cotando neste minuto, com há quanto
   tempo.
2. **Alertas** — só aparece quando existe algo, a partir de **3 falhas
   seguidas**. *"A Jadlog falhou nas últimas 5 tentativas de login."* A
   parte mais valiosa da tela.
3. **Saúde das transportadoras** — tabela com barras.
4. **Falhas mais frequentes** — defeitos por assinatura: quantas vezes, quando
   foi a última, links para as cotações afetadas.
5. **Recusas mais frequentes** — motivo × transportadora. Responde uma pergunta
   comercial que hoje ninguém consegue fazer: onde a carga da Ventura não cabe
   no perfil delas.
6. **Dois gráficos** — cotações por dia; falhas por dia empilhadas por
   transportadora. O aproveitamento **não** vira gráfico: já é barra na tabela,
   e gráfico duplicado só ocupa tela.
7. **Números do período** — economia estimada, rotas mais cotadas, WhatsApp por
   transportadora (quais das manuais são tão usadas que valeria automatizar).
8. **Histórico completo** — todo mundo, com filtro por vendedor, período e
   status. Clicar abre a cotação com os prints.

**Período:** hoje / 7 / 30 dias / tudo, padrão 30.

## A conta da economia

É **estimativa**, e a tela diz isso com a fórmula à vista: diferença entre o
mais barato e a média das outras cotadas, somada, contando só cotações com dois
preços ou mais.

**Precisa respeitar a regra que já existe:** a Jadlog cota por volume e está
fora da disputa do "mais barato" quando há mais de uma caixa (`web/app.py`).
Ignorar isso infla o número — seria exatamente o tipo de tela que mente com
confiança.

## A coluna nova

`resultado.respondido_em`, migração **aditiva** via o `_migrar` que já existe.
Não toca nas 325 linhas atuais. O adapter já calcula o valor e o descarta.

A tela mostra **"sem dados ainda"** enquanto estiver vazia, e nunca finge zero.

## Testes

| o quê | como |
|---|---|
| `core/painel.py` | banco temporário semeado com linhas conhecidas; confere cada agregação |
| `assinatura_do_erro` | contra os textos de erro **reais** do banco |
| `web/adm.py` | sem senha no `.env` → 404; sem cookie → login; senha errada → não entra; **cookie forjado → não entra** |
| `web/graficos.py` | puro: dados → SVG, sem navegador |
| isolamento do vendedor | `test_cotacao_de_outro_usuario_nao_abre` continua passando |
| migração | banco antigo, sem a coluna, ganha a coluna sem perder linha |

## Ordem de implementação

Três fases, cada uma entregando algo utilizável sozinho. Se o tempo acabar no
meio, o que existir já vale.

**Fase 1 — poder entrar e ver.** Senha, cookie, 404 sem variável, `/adm` com a
faixa ao vivo, saúde das transportadoras e histórico completo com filtros.
Aqui já substitui o `monitorar.py` para o dia a dia.

**Fase 2 — entender o que quebra.** `assinatura_do_erro`, falhas agrupadas,
recusas agrupadas e os alertas de falhas seguidas. É a fase que responde à
pergunta que motivou o pedido.

**Fase 3 — enxergar o conjunto.** `web/graficos.py`, os dois gráficos, e os
números do período (economia, rotas, WhatsApp).

A coluna `respondido_em` entra na **Fase 1**, mesmo sem tela: cada dia sem ela
é um dia de histórico que não volta.

## Fora de escopo

Exportar CSV, alertas por e-mail/WhatsApp, apagar cotações pela tela, login por
pessoa. Nenhum foi pedido; o de apagar é perigoso demais para existir sem
motivo.

## Riscos declarados

1. **O dashboard lê o mesmo SQLite que o servidor escreve.** Com 325 linhas é
   instantâneo. Na casa das dezenas de milhares, uma agregação pode disputar
   com uma escrita — aí precisa de índice ou cache.
2. **Agrupamento errado mente.** Daí a assinatura ser testada contra dados
   reais, nunca contra exemplos inventados.
3. **O adm vê CNPJ, nome e valor de nota de todos os clientes num lugar só.** O
   `Servidor.bat` avisa que `0.0.0.0` inclui o Wi-Fi. Numa rede com visitantes,
   a senha do `.env` é a única barreira entre eles e o histórico comercial da
   Ventura.

---

## O que existe hoje — 04/09/2026

Registro do que foi de fato entregue, para o desenho acima não descrever um
sistema que não é este.

**Da Fase 1:** tudo. Senha, cookie, 404 sem variável, faixa ao vivo, saúde das
transportadoras, histórico completo e a coluna `respondido_em`.

**Da Fase 2:** o **alerta de 3 falhas seguidas** (`painel.falhas_seguidas`) —
a parte que motivou o pedido. `assinatura_do_erro`, falhas agrupadas e recusas
agrupadas continuam pendentes; o texto de erro inteiro aparece na tela de uma
cotação, o que resolve o caso individual mas ainda não o ranking.

**Da Fase 3:** os gráficos (em `web/painel_ui.py`, não em `web/graficos.py` —
o arquivo virou o desenho inteiro do painel, casco incluído) e as **rotas mais
cotadas**. A economia estimada e o WhatsApp por transportadora continuam
pendentes.

**Fora do desenho original: `/adm/cotacao/{id}`.** A tela de UMA cotação, de
qualquer vendedor — o item 8 do desenho dizia "clicar abre a cotação com os
prints" e não tinha rota para isso: `/cotacao/{id}` é do vendedor e filtra por
dono. Ela usa `painel.cotacao`, que consulta sem o filtro, e
`banco.buscar_cotacao` não mudou — as duas portas separadas que a seção de
segurança pede. É **só leitura**: nada de abrir WhatsApp, repetir ou apagar.

A ficha da carga passou a ser desenhada por `web/ficha_ui.py`, usada pelas
DUAS telas. O cadastro de nome e logo das automáticas foi para
`web/transportadoras.py`, junto com `cota_por_volume` — assim as duas telas
elegem o mesmo "mais barato" e chamam a mesma transportadora pelo mesmo nome.
