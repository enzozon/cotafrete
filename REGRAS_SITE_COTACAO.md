# Regras do site de cotação

Decisões de interface, tiradas do que quebrou nos testes reais com Jadlog,
Della Volpe e Generoso. Não é opinião solta: cada regra tem um caso que a
gerou.

## A tela

**Um formulário só, com os campos que todas as transportadoras pedem.** Botão
único: **Cotar fretes**. Nada de escolher transportadora antes.

**Por quê:** ninguém quer "cotar na Generoso" — quer saber quem leva mais
barato. Se o usuário escolhe primeiro, ele vira o orquestrador: abre cinco
vezes, anota num papel, compara. É o trabalho manual que estamos eliminando,
com uma tela na frente.

**Checkbox, não dropdown**, se ele quiser escolher: `☑ Jadlog ☑ Della Volpe
☑ Generoso`, todas marcadas. Dropdown obriga a escolher uma; checkbox deixa
desmarcar a que não atende aquela rota.

## Onde cada campo mora

A pergunta que decide:

> O usuário precisa **olhar para a carga** para responder? Fica na tela.
> Precisa **saber como a transportadora funciona**? Vai para configuração.

| Fica sempre visível | Vai para configuração |
|---|---|
| Embalagem (caixa, fardo, engradado…) | Modalidade Jadlog |
| Material / descrição da carga | Tipo de pagador padrão |
| Medidas, peso, quantidade, valor da NF | Dados do solicitante |
| CEPs e CNPJs | |

**Embalagem parece detalhe técnico mas muda o preço** — caixa e engradado têm
perfis diferentes. Escondida em configurações, o usuário cota caixa e despacha
engradado.

## Tradução de formato: sempre no adapter, nunca no formulário

O usuário digita `30` e `1`. Quem sabe que uma vira `30,0` e a outra `1,00` é
o código.

| Site | Medida | Peso |
|---|---|---|
| Della Volpe | `30,0` — 1 casa obrigatória | livre |
| Jadlog painel | `30` — inteiro | `1,00` — 2 casas |
| Generoso | `30` — inteiro | `1,00` — 2 casas |

Errar isso não dá erro na tela: cota carga 10x ou 100x menor e o frete parece
certo. Aconteceu duas vezes neste projeto.

## Resultados

**Cada cartão diz o que o preço inclui.** R$ 33,35 da Jadlog e R$ 235,45 da
Della Volpe lado a lado, sem contexto, levam à decisão errada — um é etiqueta
que você leva ao balcão, o outro é coleta na porta com CT-e e ICMS.

**Cartões aparecem conforme chegam.** A Jadlog responde em ~15s com preço; a
Della Volpe e a Generoso levam ~2 min e só confirmam recebimento, com o preço
vindo por e-mail depois. Não trave a tela esperando a mais lenta.

**Quem falhou aparece com o erro.** Sumir com a transportadora que deu
problema é como o bug que custou horas aqui: cinco cotações "enviadas" que
nunca saíram, porque o clique caía num botão oculto e o detector de sucesso
dava positivo em qualquer página.

**Status otimista é proibido.** Só marque "enviado" com prova: a frase de
confirmação do próprio site. Na dúvida, é erro.

## Limites que precisam aparecer ANTES de cotar

- Della Volpe: 1 a 34.000 kg — abaixo de 1 kg ela recusa
- Generoso: embalagem é obrigatória
- Jadlog painel: cota **um volume por vez**; N volumes = N cálculos somados

Validar na tela evita mandar o usuário esperar 2 minutos para receber "peso
inválido".

## Transportadoras que só atendem por WhatsApp

Movvi e Translovato não têm formulário: a cotação vai por mensagem. Elas
entram na mesma tela, mas o botão **abre o WhatsApp com o texto pronto** em
vez de preencher site.

Consequência de projeto: o resultado delas **nunca** é automático. Não invente
status "aguardando retorno" para elas — o máximo que o sistema sabe é que a
mensagem foi aberta para envio. Quem confirma é a pessoa.

## Segurança e dados

- CNPJ e valor de NF **nunca** em log, URL ou nome de arquivo
- Evidências (prints) ficam fora do git: `runs/`, `teste_real/`, `recon_out/`
- Credenciais só no `.env`
- Envio real de formulário que gera cotação na fila de um vendedor precisa de
  confirmação explícita — não é ação de teste

## Uma armadilha de automação

A Della Volpe **recusa envio de navegador headless**: o reCAPTCHA v3 pontua
como robô e o formulário responde "A submissão mencionou-se como spam", sem
gerar e-mail nenhum. Envio real dela roda com janela visível.

Se o site rodar num servidor, isso precisa de solução — provavelmente pedir
API ou liberação à transportadora, em vez de brigar com o antibot.
