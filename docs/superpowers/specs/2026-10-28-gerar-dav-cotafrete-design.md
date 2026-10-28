# Gerar DAV no Cotafrete — design

Data: 28/10/2026. Aprovado pelo Enzo no chat (rodadas Q1–Q11).

## 1. Intenção

O vendedor preenche a planilha base, manda o arquivo e recebe o DAV (orçamento do HSE)
em PDF, sem digitar mais nada. Hoje isso já funciona pelo **RoboOrcamento**
(`C:\RoboOrcamento`, repositório `enzozon/robo-orcamento-hse`), que lê planilhas soltas em
`\\SERVIDOR2\Publico\ENZO\ORCAMENTO`. Ele gerou DAVs reais (16295 a 16368) e cadastrou
produto novo (76627). O que falta é uma **tela**: enviar a planilha, ver o andamento,
baixar o PDF e ter o histórico de cada vendedor.

A tela fica no **Cotafrete** (`cotafrete.ventura.inf.br`), numa aba nova "Gerar DAV".
O portal Maestro só ganha um botão que abre essa aba.

Por que no Cotafrete: ele roda na **VM Windows 10** do SERVIDOR2, onde Playwright e Python
novos funcionam (o 2012 R2 não passa do Chrome 109). Ele também já tem conta por vendedor,
com cada um vendo só o que é seu. Assim o código do RoboOrcamento entra quase sem mudança.

## 2. Objetivos

- Aba **Gerar DAV** no Cotafrete: enviar planilha v3 → conferir o resumo → Gerar →
  andamento → número do orçamento, PDF para baixar e o relatório item por item.
- Histórico: cada vendedor vê os próprios DAVs; o admin vê todos.
- Botão **GERAR DAV** em `minhas_cotacoes.html` do portal Maestro, abrindo a aba do Cotafrete.
- O "Exportar planilha base" de Minhas Cotações passa a sair no modelo **v3**.
- O mesmo comportamento do RoboOrcamento: produto pelo código HSE, senão pela descrição,
  senão cadastro de produto novo; recusa de desconto do HSE; confirmação do salvamento
  reabrindo o pedido; "salvo incerto" nunca cancela nem repete.

## 3. Fora do escopo (agora)

- Login único portal → Cotafrete (link assinado). O vendedor usa a conta do Cotafrete.
- Vendedor travado pelo login. O vendedor do DAV continua sendo a célula **B33**.
- Responder a cotação Coupa/Vale com o DAV, e-mail do DAV, duplicar DAV
  (ver `docs/implementacoes-futuras-gerar-dav.txt` no portal).
- Conferência no HSE antes de gerar (cliente/produtos). Os erros do HSE voltam no relatório.
- As branches `feat/gerar-dav` dos dois repositórios (robô em Selenium no serviço de NF e
  formulário no portal) **não vão para produção**: ficam como referência. O serviço de NF não muda.

## 4. Anti-objetivos

- Orçamento repetido no HSE. Qualquer dúvida sobre o Salvar vira "confira no HSE o
  orçamento N e não gere de novo", nunca uma nova tentativa automática.
- Um vendedor vendo ou baixando o DAV de outro.
- Senha do HSE ou chave de IA em tela, log, banco ou relatório.
- Derrubar cotações de frete: a VM tem CPU apertada.

## 5. Decisões do Enzo

| # | Decisão |
|---|---|
| Q1 | Tela e robô no Cotafrete (VM Win10). Portal só com o botão |
| Q2 | Sem formulário: envia, confere o resumo (só leitura), clica Gerar. Planilha com erro não gera |
| Q3 | A `PLANILHA-BASE-v3` é o modelo único, inclusive no export de Minhas Cotações |
| Q4 | Vendedor = B33; o histórico é de quem enviou (conta do Cotafrete) |
| Q5 | Cadastro automático de produto novo já na 1ª versão |
| Q6 | IA só por chave de API (`IA=api`), desligada por padrão. Desligada: produto novo exige NCM, grupo e marca, descrição até 100 caracteres |
| Q7 | A pasta `ENZO\ORCAMENTO` segue até o portal estar em produção; depois o modo pasta é desligado |
| Q8 | Login do HSE = usuário próprio do Enzo, **sem** permissão de excluir rascunho |
| Q9 | Login com a conta do Cotafrete; quem não está logado cai no login |
| Q10 | Vendedor vê os seus; admin vê todos |
| Q11 | Partes A/B antigas ficam só como referência |

## 6. Como funciona

### 6.1 Planilha v3 (do RoboOrcamento, sem mudança)

Aba `ORÇAMENTO`. Itens nas linhas 2–25 (a linha conta se A ou K estiver preenchida):
A produto, B quantidade, C custo, D–F fretes/madeira, G margem, J valor unitário (preço do DAV),
K código HSE, L NCM, M origem, N ICMS, O descrição p/ cadastro, P grupo, Q marca.
Cabeçalho: B26 observações, B30 local de entrega, **B31 cliente** (obrigatório), B32 prazo (dias),
**B33 vendedor** (obrigatório), B34 forma de pagamento, B35 parcelamento, B36 ordem de compra,
B37 filial (vazio = 1). Aba oculta `LISTAS` com as listas suspensas.
A leitura é `ler_planilha` do RoboOrcamento, que já valida tudo isso.

### 6.2 Tela (aba "Gerar DAV", rota `/dav`)

1. **Enviar**: um campo de arquivo `.xlsx` (até 5 MB) e o link para baixar o modelo v3.
2. **Conferir** (só leitura): cliente, vendedor, filial, pagamento, prazo, OC, observações e a
   tabela dos itens (produto, qtd, valor unitário, código HSE ou "procurar pela descrição /
   cadastrar se não existir"). Os erros de `ler_planilha` aparecem aqui e o botão Gerar não aparece.
   Avisos (ex.: "valor recalculado") aparecem sem bloquear.
3. **Gerar** → entra na fila. A página do DAV mostra o estado (na fila / gerando / pronto /
   erro / confira no HSE) e atualiza sozinha enquanto não termina.
4. **Pronto**: número do orçamento, botão "Baixar PDF" e o relatório (`.txt` do RoboOrcamento)
   na tela.
5. **Histórico** na mesma aba: os DAVs do vendedor, mais novos primeiro (data, arquivo, cliente,
   número, estado, PDF).

Visual: o do Cotafrete (`web/layout.py`), como as telas do ME. Link "Gerar DAV" no menu.

### 6.3 Fila e robô

- Um DAV por vez (uma thread trabalhadora). O robô pega uma vaga de `VAGA_NAVEGADOR`
  (`core/retentativa.py`), como as transportadoras, para não passar de 2 navegadores na VM.
- DAVs na fila ou rodando contam no `/_ocupado`: o `atualizar.py` não reinicia o servidor
  no meio de um DAV.
- Reinício com um DAV "gerando": ao subir, ele vira **"confira no HSE"** (nunca repete).
  Os que estavam "na fila" voltam para a fila.
- O robô é o RoboOrcamento: `processar_arquivo` decide e o `Hse` (Playwright) executa.
  `DRY_RUN=1` continua valendo para teste (preenche sem Incluir/Salvar).

### 6.4 Dados

- Tabela `dav` no `cotafrete.db`: dono (conta), arquivo original, quando, estado, número,
  cliente, relatório (texto), caminho do PDF, erro.
- Arquivos em `davs/` (fora do git): a planilha enviada e o PDF.
- Download do PDF só pelo dono ou pelo admin.

### 6.5 Configuração (`.env` do Cotafrete na VM)

`HSE_USUARIO`, `HSE_SENHA`, `HSE_CLIENT_ID=ventura`, `DAV_DRY_RUN`, `DAV_HEADLESS=1`,
`IA=desligada|api`, `IA_MODELO`, `ANTHROPIC_API_KEY`. A senha e a chave nunca saem em log,
banco ou relatório.

### 6.6 Portal Maestro

- Botão **GERAR DAV** em `minhas_cotacoes.html` → `https://cotafrete.ventura.inf.br/dav`
  (nova aba).
- Export da planilha base passa a usar o modelo v3 (mesmas colunas A–J e linhas 2–25;
  observações em B26).

## 7. Comportamentos do HSE que valem (conferidos pelo RoboOrcamento)

- Filial vem do login; o robô loga na filial da planilha.
- Recusa de desconto ("Desconto máximo 15%…") vira erro do item com o motivo.
- Falha depois do 1º item: fica um rascunho/incompleto. O usuário do robô não pode excluir,
  então o relatório e a tela mostram o número para a gestora excluir.
- Salvar sem confirmação = "PODE ter sido salvo: confira no HSE e não reenvie".
- Produto novo é cadastrado na filial da planilha; nas outras fica com preço 0 (combinado).

## 8. O que fica para o construtor decidir

- Nomes de módulos, rotas internas e colunas da tabela, seguindo o padrão do `me_ui.py`.
- Texto exato dos estados e mensagens (português simples, como o resto do Cotafrete).

## 9. Chamadas minhas (para o Enzo conferir)

- O código do RoboOrcamento entra no Cotafrete como pacote `orcamento/`, e os testes vão junto.
  O RoboOrcamento continua no repositório dele até o modo pasta ser desligado (Q7).
- IA: fica o `ia.py` do RoboOrcamento só com o modo `api` (o `claude_cli` sai: o servidor
  não tem o Claude Code). O pacote `anthropic` entra no `requirements.txt` do Cotafrete.
- Sem conferência prévia no HSE no envio: abrir navegador a cada upload pesaria a VM.
- O admin vê todos os DAVs numa lista no painel do admin.
