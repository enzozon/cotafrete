# Mapa do sistema: o que é difícil e onde mexer

Leia este arquivo **antes** de abrir código. Ele existe para que uma mudança
comece no arquivo certo, sem varrer o repositório. Cada seção diz o que quebra
fácil, por que quebra e o que conferir depois de mexer.

Atualize este mapa no mesmo PR quando mudar uma das partes descritas aqui.
Mapa desatualizado custa mais que mapa nenhum.

---

## 1. A empresa e os sistemas

A Ventura Informática vende para grandes compradores, como Vale, Petrobras e
Samarco, por portais de compra: Mercado Eletrônico (ME), Coupa, Ariba, Findes
e o portal da Vale. Quase tudo que se automatiza aqui serve a três
trabalhos: **cotar o frete**, **responder cotações dos portais** e
**acompanhar pedido → nota fiscal**.

| sistema | repositório / local | o que faz | roda onde |
|---|---|---|---|
| **Cotafrete** | este repo, `web/` + `core/` + `carriers/` | um formulário e cotação em várias transportadoras | VM Windows 10 no servidor, `cotafrete.ventura.inf.br` |
| **Mercado Eletrônico** | este repo, `mercado_eletronico/` + `web/me_ui.py` | lê cotações do ME, calcula impostos e prazos, preenche rascunho | VM, junto do Cotafrete |
| **Gerar DAV** | este repo, `orcamento/` + `web/dav_ui.py` | vendedor envia a PLANILHA-BASE v3, confere, e o robô gera o orçamento (DAV) no HSE; PDF e histórico por vendedor | VM, junto do Cotafrete |
| **Serviço de NF** | este repo, `cruzar_nf/` | busca NFs no ERP HSE e preenche nos pedidos do Maestro | SERVIDOR2 (Server 2012 R2) |
| **Cadastro de pedidos** | `cruzar_nf/cadastro_pedidos.py` | leva a planilha dos estagiários para o PEDIDOS.json | SERVIDOR2, a cada 10 min |
| **Portal Maestro** | `allan-max/portaismaestro` (`server.js` + `public/*.html`) | painel web com socket.io, onde ficam os robôs dos portais, a fila, os pedidos e a planilha Vale | pm2 "Site-Maestro" + Cloudflare Tunnel, `maestro.ventura.inf.br` |
| **Gerenciador Maestro** | só no servidor: `\\SERVIDOR2\Publico\ALLAN\NUVEM\server2012\novo maestro` (`gerenciador.py`, `planilha_manager.py`, bots) | robôs dos portais e dono do PEDIDOS.json | SERVIDOR2 |

**O gerenciador não está no git.** Outras pessoas o alteram direto no
servidor. Antes de mexer em qualquer integração com ele, compare os arquivos
(data, tamanho e hash) com a última versão vista.

---

## 2. Cotafrete: as quatro armadilhas

### 2.1 O mesmo número em formatos diferentes

O usuário digita centímetros e quilos. Cada site quer um formato, e **errar
não dá erro**: o site cota a carga errada com um preço que parece certo.
A Camilo (SSW) recebe as medidas em **metros**; a Della Volpe exige uma casa
decimal. A tabela completa está no README, seção "A armadilha central".

- **Onde:** em `carriers/<slug>/mapping.py`, que é puro e testado. Nunca no
  formulário nem em `web/`. **Exceção: Jadlog.** Produção usa o painel
  (`carriers/jadlog/painel.py`, `JadlogPainelAdapter`), que formata o peso no
  próprio adapter. O `jadlog/mapping.py` serve a API com token, e o
  `simulador.py` está aposentado. Para saber quem cota de verdade, veja
  `FABRICAS` em `web/app.py`.
- **Depois de mexer:** `pytest tests -k <slug>` e um dry-run com print
  (`teste_real/<slug>/<data>/preenchido.png`).

### 2.2 Seletores

Seletor deduzido de print já quebrou duas vezes sem aviso. Use rótulo ou
placeholder. Use o `name=` medido no recon (`recon/recon_<slug>.py`) só como
último recurso. Nunca use posição.

### 2.3 Preço atrás de um aviso

O site pode mostrar um preço calculado **atrás** de um popup de recusa
("cidade não atendida", "CNPJ não cadastrado"). Esse preço é fantasma. Todo
adapter confere o popup antes de aceitar o preço.

### 2.4 Concorrência e tempo

- `core/retentativa.py`: `NAVEGADORES_SIMULTANEOS = 2` e
  `ESPERA_MAXIMA_S = 300`. Esses números foram medidos na VM com 4 vCPU (veja
  `docs/SERVIDOR.md`). Só mude depois que um vendedor vir o aviso "não
  responderam em 5 minutos".
- Generoso, Favorita e Della Volpe só passam com **janela visível** (Vercel e
  reCAPTCHA). Headless "funciona" e não envia nada.

### Generoso e Favorita: um portal, duas contas

A Favorita (`carriers/favorita/adapter.py`) é o mesmo portal da Generoso e
herda o `GenerosoAdapter` inteiro. Só mudam os atributos de conta
(`url_base`, `prefixo_env`, `empresas`, `trava_conta`, `nome_curto`). Mexeu na
mecânica da Generoso? Rode também `pytest tests -k favorita`. A conta da
Favorita tem as três do grupo no "Alterar empresa" desde 03/11/2026 (antes só
a Ventura) e troca pelo CNPJ como a Generoso; o agendamento de coleta dela
não foi levantado (levanta `NotImplementedError`). CNPJ "nao cadastrado" na
ponta digitada é recusa na Generoso, mas na Favorita não
(`cota_sem_cadastro`): o robô digita o CEP e, se for CEP geral de cidade,
completa rua e bairro pela Receita (`core/cnpj.endereco`). Cliente
cadastrado com bairro "." e campo travado (#466) é recusa
(`recusa_cadastro_sem_bairro`), não erro: só a transportadora corrige.

A Della Volpe escolhe a cidade sem diferenciar maiúscula nem acento
(`mapping.opcao_da_cidade`, e o mesmo no bookmarklet): o site lista "Santa
Bárbara d'Oeste", e o texto exato derrubava a cotação (#472).
Os `<select>` dela vão por `select_option(valor)`, que casa value **ou**
label de uma vez. `label=` com `value=` no `except` esperava o tempo limite
(45s) a cada UF, porque a UF vai como sigla e o site mostra o nome: ~90s
parados em toda cotação até 03/11/2026.

"Ainda não atendemos essa origem" (embaixo do CEP) pode aparecer só **depois**
do Próximo: `_conferir_cobertura` roda antes e depois dele. Na Favorita a
mesma recusa também vem na tela de resultado ("Cidade destino não atendida",
`mapping.cidade_nao_atendida`). As duas viram RECUSADO com a cidade da tela.
Na Favorita, remetente sem cadastro num FOB (com coleta) é recusa: o CEP da
coleta vem travado e só a equipe dela cadastra endereço novo
(`recusa_coleta_sem_cadastro`). No destino ela deixa digitar.
O CNPJ do lado livre preenche o endereço **cadastrado** dele, que pode não ser
o da cotação. `_usar_cep_da_cotacao` digita o CEP da ficha por cima; se não
der, recusa nomeando a cidade do cadastro. Nunca cotar o endereço do cadastro.

### Jadlog: oferta na frente do botão

O site abre ofertas por cima do painel (a "11.11" custou 45 s e uma falha na
cotação #630). O seletor muda a cada campanha, então `_clicar_calcular` esconde
qualquer camada `position: fixed` sobre o centro do botão, antes do clique e de
novo se ele não passar em 10 s. Só cobre o "Calcular Envio".

### Braspress: recusa antes do preço

`normalizar_resposta` confere a caixa de recusa (`alert-danger`) antes do
sucesso. Sucesso sem valor de frete vira ERRO, não COTADO.

### Braspress: CNPJ sem cadastro

O site escreve "não cadastrado, para prosseguir informe o CEP de Destino". O
robô digita o CEP da cotação no lado livre (`_endereco_pelo_cep`) e segue.

### "Não se aplica", conferência e alertas

- `StatusCotacao.NAO_SE_APLICA`: regra fixa da transportadora que exclui a
  carga (Jadlog só CIF, Translovato só saindo da Ventura, Generoso/Favorita
  com a ponta travada fora do grupo). Nasce em `recusa_por_validacao` quando todos os erros têm
  `nao_se_aplica=True`. Não abre navegador e fica fora do aproveitamento
  (`core/painel.categoria` → "nao_aplica", `resumo_semana`). CNPJ novo da
  Ventura na Translovato entra em `CNPJS_REMETENTE_ACEITOS`.
- `core/conferencia.py`: antes de cotar, avisa CIF/FOB trocado com o grupo e
  medida improvável (menor que 3 cm, ou mais denso que aço). A rota `/cotar`
  mostra `tela_conferencia`; o vendedor corrige com um clique ou confirma.
- `painel.falhas_repetidas`: o mesmo erro (sem números) 3× em 24 h vira
  alerta no /adm, mesmo com sucesso no meio.

### IA na tela do vendedor

Toda IA nova segue a regra: a IA sugere, o código confere contra os dados
reais. `core/explicar_erro.py` (frase do erro, sem número),
`core/resposta_cliente.py` (cada preço igual ao do banco) e
`core/busca_historico.py` (só filtros da lista fechada). Nos testes, o que
chama a IA sozinho fica desligado em `tests/conftest.py`.
Quem tem gente esperando passa `limite_s=ia.LIMITE_TELA_S` (40 s no pedido
inteiro). Formulário que espera a IA leva `data-ia-espera` (`JS_ESPERA_IA` em
`web/app.py`). A cotação recarrega de 10 em 10 s enquanto
`explicar_erro.pendente` diz que a frase do erro está sendo escrita.

### Para ligar uma transportadora nova

Siga o roteiro: recon → `mapping.py` → `adapter.py` → fixture tirada do HTML
real → dry-run → envio real com cliente real → ligação em `web/app.py`.
`web/app.py` é a ligação e não a lógica. Ele tem perto de 3.000 linhas.
Procure nele por `AUTOMATICAS`, `FABRICAS`, `NOMES` e `NOTAS`. As listas vêm
de `web/transportadoras.py`. Os testes de consistência travam fábrica e lista
juntas. O `monitorar.py` se atualiza sozinho.

---

## 3. Mercado Eletrônico: nunca salvar sem querer

- **Travas:** `mercado_eletronico/trava.py` intercepta POST, postback e anexo
  e bloqueia o que não for um salvamento pedido. Nada que escreve no ME pode
  passar por fora dela.
- **Rascunho de outra pessoa é intocável.** Em 28/09/2026 um teste apagou o
  rascunho de um colega, e não havia como recuperar. Toda escrita, de salvar
  ou de limpar, confere antes se a cotação tem rascunho alheio. Não encadeie
  duas escritas no mesmo comando.
- A parte pura fica em `regras.py`, `feriados.py`, `mapa.py`, `painel.py`,
  `lista.py` e `pagina.py`, e tem testes. A parte de browser fica em
  `robo.py` e `ponte.py` e é fina de propósito.
- `revisao.py` usa IA (`core/ia.py`) só para gerar **alertas** e
  **exigências do comprador** (cada uma com o trecho conferido no texto) e
  nunca escreve no formulário. `core/resumo_erros.py` só aceita um número como fato
  se ele aparece fora da data.
- **Nunca preso em "salvando".** O robô roda numa thread. Na subida,
  `banco.me_soltar_salvando` troca `salvando` por `erro` com o motivo, e
  exceção fora do previsto no robô vira `erro` (`me_ui._nunca_preso`). O
  `/_ocupado` soma `me_ui.robos_em_curso()`, para o `atualizar.py` não
  reiniciar no meio de um Salvar.
- **Limpar exclui só o anexo que o robô subiu** (evento "anexado no ME" no
  histórico, `me_ui.anexos_subidos_pelo_robo`), nunca o de mesmo nome que
  um colega pôs direto no site.
- **Preço**: `regras.validar_item` recusa "1.234" sem vírgula (ambíguo) e
  mais de 2 casas. Aviso de frete com sigla negada ("não aceitamos FOB")
  não decide por ela (`regras._frete_do_aviso`).
- **Pendente:** Salvar e Limpar ainda **não** conferem se há rascunho de
  outra pessoa nos campos de item. Ver a auditoria de 21/10/2026.
- **Leitura automática dos itens** (`web/me_ui.ler_itens_novos`): `Sessao.abrir`
  espera só o formulário (o "load" completo da página é opcional). Na falha,
  o erro diz a tela e o print vai para "Prints do robô". As tentativas contam
  pelo histórico no banco (1 h, depois 4 h, para na 3ª falha) e cedem a vez
  enquanto houver frete em curso (`retentativa.fretes_em_curso`).
- Guia completo: `docs/MERCADO_ELETRONICO.md`.

---

## 3b. Gerar DAV: nunca gerar duas vezes

Código em `orcamento/` (leitura da planilha `planilha.py`, robô do HSE,
`fila.py`) e a tela em `web/dav_ui.py` (`/dav`; lista do admin em `/adm/dav`).
O estado fica na tabela `dav` do `cotafrete.db`; a planilha enviada e os PDFs
ficam em `davs/entrada/<id>.xlsx` e `davs/pdf/` (fora do git). A cada volta, o
`atualizar.py` copia o que é novo ou mudou em `davs/` para
`//SERVIDOR2/Publico/ENZO/davs` (`espelhar_davs`). Só acrescenta, nunca apaga.

- A mesma planilha (hash) do mesmo vendedor não gera outro orçamento: a tela
  diz "já gerou o orçamento N". Servidor reiniciado com DAV "gerando" vira
  "confira no HSE", nunca roda de novo sozinho.
- O HSE é produção. Só o `DAV_DRY_RUN=0` salva de verdade.
- **Teste de fumaça:** `orcamento/fumaca.py` roda às 8h05 pelo `atualizar.py`
  (`fumaca_do_dia`, uma tentativa por dia, só seg–sex antes das 18h: fora disso
  o usuário do HSE não loga). Confere um DAV de mentira com
  `HseSoLeitura`, sem IA, e só manda e-mail quando falha. Sem `FUMACA_CLIENTE`,
  `FUMACA_VENDEDOR` e `FUMACA_CODIGO` no `.env`, não roda e só diz no
  `log\atualizar.log`. Vendedor que sai da empresa vira alarme até trocar.
- Conferência de itens (`processador.py`): tabela até R$ 0,05 (`TABELA_MINIMA`) só gera aviso,
  porque quem decide é o HSE (ele aceitou 0,01 no orçamento 16600); código cuja descrição no HSE não tem nenhuma
  palavra em comum com a da planilha gera aviso (`aviso_codigo_de_outro_produto`).
  B30 que não casa: só escolhe sozinho quando o cliente tem um endereço e ele é parecido
  (`hse.PARECIDO`), com aviso "Local de entrega ... confira"; com dois ou mais, só sugere.
  Vendedor (B33) com erro de digitação sugere o nome parecido da lista do HSE. CNPJ (B31)
  com dígito verificador errado: o HSE só acha CNPJ inteiro, então a conferência procura os
  CNPJs válidos a um dígito de distância (`cnpjs_vizinhos`) e sugere se achar um só. Nunca escolhe.
- `.env` do Cotafrete: `HSE_USUARIO`, `HSE_SENHA`, `HSE_CLIENT_ID`,
  `DAV_DRY_RUN`, `DAV_HEADLESS`, `IA`, `IA_MODELO`, `ANTHROPIC_API_KEY`,
  `IA_LIMITE_DIA_USD` (padrão 0,30), `SMTP_USER` e `SMTP_PASSWORD` (resumo diário de erros por e-mail, `core/resumo_email.py`, às 19h pelo `atualizar.py`; destino em `RESUMO_EMAIL_PARA`). Senha e chave nunca em log, banco,
  relatório ou tela. `GITHUB_TOKEN_ISSUES` (opcional): token fine-grained só com
  Issues read/write no `enzozon/cotafrete`; com ele, diagnóstico com culpa robo e
  confiança alta ou média abre issue sozinho (`orcamento/issue_robo.py`, etiqueta `robo-dav`,
  no máximo 5 novas por dia, o mesmo erro vira comentário; registro em
  `davs/issues_robo.json`). O repositório é público: a issue não leva cliente,
  produto, preço nem números; os detalhes ficam no `/adm/dav/<id>`.
  O mesmo token liga a issue dos erros de cotação (`core/issue_cotacao.py`,
  chamado no `_rodar` do `web/app.py`): erro final sem frase em
  `MENSAGENS_DE_ERRO` vai uma vez por tipo para a IA (veredito em
  `davs/erros_cotacao.json`, menos confiança baixa, que pergunta de novo na próxima
  ocorrência; a IA vê o erro inteiro, com o call log do Playwright, e a assinatura
  segue sendo só a 1ª linha); só bug com confiança alta ou média abre issue com a
  etiqueta `robo-cotacao`, no mesmo limite diário. O botão "Abrir issue no GitHub"
  do `/adm/dav/<id>` só aparece quando a issue não abriu sozinha (confiança baixa,
  sem token ou limite do dia).
- IA do produto novo (`orcamento/ia.py`): NCM primeiro de memória e só com
  busca na web (US$ 0,01 por busca, entra no custo) quando o HSE não tem o
  NCM. GRUPO com o guia `orcamento/guia_grupos.txt` (o PDF "Cadastro de
  produto por grupo"). Gasto do dia em `davs/ia_uso.csv`; chegou ao limite,
  a IA para até o dia seguinte. O `/adm/dav` mostra o gasto do dia e do mês.
- Modelo v3 (`orcamento/modelo/PLANILHA-BASE-v3.xlsx`): FRETE na B38 (lista
  CIF/FOB na aba LISTAS, coluna H) e DESCRIÇÃO NO DAV na coluna R. O frete vira
  a linha `FRETE CIF, PRAZO DE ENTREGA 30 DIAS` abaixo das observações (exige o
  prazo da B32). A descrição vai para o `#dsObsItem_<cdItem>` do item no HSE,
  que só existe depois do Incluir; se não gravar, o DAV sai e o relatório avisa.
  Planilha do modelo anterior (A38 = "ITEM 1", sem a linha "Frete") ignora a B38.
- Tamanho do modelo: o vendedor escolhe de 1 a 1000 itens em `/dav/modelo?itens=N`
  (padrão 24 = o arquivo fixo). `orcamento/modelo_itens.py` monta o arquivo
  editando o XML (openpyxl apagaria as listas x14): repete a linha de item,
  desce o rodapé e ajusta mesclagens, validações, TOTAL e comentários; a
  proteção da aba fica igual. Coluna S = Nº do item (travada). O leitor
  (`planilha.linha_rodape`) acha "OBSERVAÇÕES:" na coluna A: itens até a linha
  antes, rodapé por deslocamento (B30, B31... são os endereços do modelo de 24
  itens; `celula_real` traduz). As mensagens de erro citam a célula real.
- Local de entrega (B30): texto do endereço ou só o número dele ("2" casa com a
  opção "2 - ..."). Sem endereço correspondente, o erro lista os do cliente;
  se um só for bem parecido (erro de digitação, `erro_local_entrega`), o erro diz o número dele.
- Conferência com o HSE antes do Gerar (`orcamento/conferencia.py`,
  `processador.conferir`): ao enviar, o rascunho nasce `conferencia="conferindo"`
  e uma fila própria (uma thread, uma vaga de `VAGA_NAVEGADOR`, até 120 s) roda a
  simulação num `HseSoLeitura`, que aborta todo POST de gravação. O resultado
  (`ok`, `erros`, `nao_conferido`) e o JSON do que o HSE achou ficam em
  `dav.conferencia` / `dav.conferencia_relatorio`. Com `erros` o Gerar some e o
  POST de gerar é recusado; `nao_conferido` (HSE lento, fora ou servidor
  reiniciado) só avisa e libera. Preço acima de 2x a tabela é aviso amarelo.
  Rascunho antigo (`conferencia` nula) segue o fluxo de antes. A geração confere
  tudo de novo antes de salvar.
- `planilha.ler_planilha` recusa, antes do HSE, o mesmo CÓDIGO HSE em duas linhas com
  valor diferente: o HSE junta as linhas e recusa o preço da segunda (envio #149).
  Com o mesmo valor passa.
- Diagnóstico do DAV (`orcamento/agente.py`, `provas.py`, `fila_diagnostico.py`):
  quando um envio vira `erro`, `incerto`, `rejeitado` ou rascunho com
  conferência `erros`, a fila própria (uma thread, uma por vez) junta as
  provas e a IA explica a culpa (vendedor, planilha, robô, HSE...), a causa e a
  ação. Dispara sozinho ao terminar a fila do DAV ou da conferência, ou pelo
  botão do admin. O resultado fica nas colunas novas `dav.diagnostico` (JSON)
  e `dav.diagnostico_estado` (`pendente`, `feito`, `falhou`); pendente é
  retomado ao subir o servidor.
  - Rotas do admin: `POST /adm/dav/{id}/diagnosticar` (roda de novo),
    `POST /adm/dav/{id}/corrigir` (aprova as correções e cria um envio novo do
    mesmo vendedor, para conferir), `GET /adm/dav/{id}/hse/{nome}` (print ou
    resposta do HSE gravados para o envio) e `GET /adm/dav/{id}/planilha`.
  - Pastas em `davs/`: `prints_hse/` (print da tela quando o robô falha) e
    `respostas_hse/` (resposta inteira do HSE a cada gravação), fora do git.
  - Custo: mesmo teto e mesmo `davs/ia_uso.csv` da IA do produto novo
    (`IA_LIMITE_DIA_USD`). Chegou ao limite, o diagnóstico sai sem IA e diz o
    motivo.
  - Segurança: o HSE só é aberto em leitura (`HseSoLeitura` aborta todo POST;
    se algo tentar gravar, o diagnóstico falha com alarme). Se o HSE não
    responde, os pedidos ficam "não verificados". Quem decide `criados_no_hse`
    é o código (`provas.coletar`), nunca a IA. As correções passam por lista
    branca: só B30, B31, B33, K2:K25 e O2:O25 (endereços do modelo de 24
    itens; `correcao` grava na célula real); preço, quantidade, custo e NCM
    nunca. Corrigir só cria um envio para conferir: nunca gera no HSE.
  - Avaliação com envios reais (dados fora do git):
    `python scripts/avaliar_agente.py <pasta_dados> [--ia arquivo|api]`.
    A pasta tem `envios.json`, `gabarito.json`, `pedidos.jsonl` e `vm/<id>.xlsx`. `--ia arquivo`
    (padrão) lê respostas gravadas em `aval/ia/<id>.json`; `--ia api` chama a IA de verdade,
    com cache em `aval/cache_ia/` e uso em `aval/programa/` (não mexe no `ia_uso.csv` de
    produção) e para em `--max-usd` (padrão 1,00). Nunca abre o HSE: o buscador lê o
    `pedidos.jsonl`. Sai com 1 se culpa de confiança alta < 90% ou se houver caso perigoso.
- O modelo tem 2 cópias que precisam ficar iguais: esta e o `public/PLANILHA
  BASE.xlsx` + `public/vendor/template_planilha_base.js` (base64) do Maestro. A
  pasta pública `ORCAMENTO` saiu de uso em 06/11/2026. Grave o modelo pelo XML
  (o openpyxl apaga as listas suspensas x14) e mantenha a aba protegida com as
  células de digitação desbloqueadas. As regras de digitação ficam em
  `scripts/validacoes_modelo.py`: barra o que o robô recusaria e só avisa no que
  vem do HSE (vendedor, parcelamento, grupo, marca). Colar por cima passa pela
  validação do Excel; quem pega é a conferência do robô.

---

## 4. NF e pedidos: escritores concorrentes no JSON e no Excel

O ponto mais frágil da empresa é o **PEDIDOS.json**, porque vários processos
escrevem nele:

```
gerenciador.py / planilha_manager.py   (dono; fora do git)
cruzar_nf/servico.py → sincronizar.py  (preenche NF vazia)
cruzar_nf/cadastro_pedidos.py          (acrescenta pedido novo da planilha)
cruzar_nf/sync_planilha_portal.py     (sincronização diária de campos e novos itens)
```

**Por que não se corrompe:** `cruzar_nf/arquivo_pedidos.py` grava só se a data
e o tamanho não mudaram desde a leitura. Ele escreve num temporário e troca o
arquivo com `os.replace`, depois relê. Se o gerenciador gravou por cima, ele
grava de novo. A conferência final e a troca acontecem segurando
`PEDIDOS.json.lock` (1 byte com `msvcrt.locking`, até 30 s), a trava combinada
com o gerenciador em 21/10/2026; a janela só fecha quando o gerenciador
também a usar. Isso **depende** de o `planilha_manager.py` recarregar o JSON
quando a data de modificação muda. Se alguém tirar essa recarga do servidor,
o gerenciador volta a sobrescrever as NFs. Confira essa recarga antes de
qualquer mudança no fluxo, pelo hash do arquivo no servidor.

### Peças

| arquivo | papel | o que quebra |
|---|---|---|
| `servico.py` | conecta no portal com `sou_o_sync_nf` + `SYNC_NF_TOKEN` e roda a rodada diária | **uma instância só**, pela trava `servico_nf.instancia`. Desde a #49 a segunda fica de reserva em vez de sair |
| `ServicoNF.bat` | sobe e reinicia o serviço | roda pela tarefa "Maestro NF Servico" (ONSTART, Administrator). `schtasks /End` **não** mata o python |
| `ReiniciarServicoNF.bat` | encerra os que sobraram e sobe de novo | não reinicia enquanto `nf_planilha` grava (trava própria) |
| `hse_robo.py` | Selenium no ERP HSE, com login em duas etapas e um Excel por mês | usa Chrome 109, o último que roda no Server 2012 R2 |
| `sincronizar.py` | exporta, monta a base, cruza, grava e escreve o `sync_nf.json` | base acumulada desde 01/01/2025 em `vendas_hse.json`. Data final no futuro é recusada. A trava leva uma ficha e só a dona a apaga. Exportação vazia com vendas na janela é recusada (`base_vendas.mesclar`), nada é apagado |
| `cruzar.py` | casa pedido com NF | regra de casamento documentada em `cruzar_nf/README.md` |
| `cadastro_pedidos.py` | planilha → PEDIDOS.json | chave = PEDIDO + RFQ + começo do PRODUTO (30 caracteres). **O que já foi visto não volta**, mesmo se apagado no portal. Linha incompleta fica esperando. Gêmeo (PEDIDO e RFQ diferentes, mesma CIDADE+VALOR) não conta como já cadastrado (`_gemeo`) |
| `nf_planilha.py` | escreve a NF na coluna "NF (MAESTRO)" da planilha | edita o XML do .xlsx de forma cirúrgica. **Planilha aberta = não grava**. Par só aproximado (sem mesmo PEDIDO) precisa ser exclusivo, e gêmeo nunca empresta a NF; senão vai para `ambiguas` |
| `planilha_portal.py` | confere planilha × portal todo dia | linhas canceladas ficam em `conferencia_ignorar.json` |
| `sync_planilha_portal.py` | merge de três pontas, prévia padrão; tarefa própria às 12:30 | primeira gravação só inicializa a foto; conflitos, exclusões e histórico antigo não são sobrescritos. PEDIDO/RFQ/PRODUTO exigem revisão |
| `planilha_edicao.py` | atualiza células e acrescenta linhas no XML do Excel | compartilha `nf_planilha.trava` com o gravador de NF; fórmulas e estruturas não suportadas bloqueiam a operação |

Cadastro, NF e sincronização bidirecional compartilham `sync_nf.trava`.
A sincronização adquire depois `nf_planilha.trava`, sempre nessa ordem; não
segura travas entre tentativas do Agendador. O gerenciador externo não usa
essas travas: continua necessária a verificação otimista e a recarga dele.
Os temporários do JSON têm nomes exclusivos. Uma edição concorrente de um
campo não é sobrescrita por uma repetição cega.

A foto (`sync_planilha_portal.json`) guarda a base comum por campo, as duas
pontas observadas, chaves conhecidas, exclusões e operações pendentes antes
da escrita. Não apagar nem reinicializar esse arquivo para resolver erro.
O relatório próprio é entregue pelo evento de estado existente; o portal
precisa também do PR do painel. NF continua com os escritores antigos.
Datas americanas do JSON legado são identificadas por comparação com o
Excel e o formato fica guardado por item; dados inválidos são pendências.

Painel (`sync.html` no portal, só admin): o serviço de NF responde
`comando_sync_planilha_painel` com `painel_para_tela()`: listas completas do
relatório, conflitos com os valores do Excel/portal/base, pendências com
linha e lado, e `sync_planilha_portal_historico.json` (uma linha por rodada,
7 dias). Alerta quando fica mais de 1 h adiada/com erro. Rodada com erro
mantém as listas da última rodada boa.

Dashboards de NFs e Atividade (`nfs.html` e `atividade.html` no portal, só
admin): `painel_nf.py` só **lê**. `comando_nf_painel` devolve indicadores do
`sync_nf.json`, pedidos sem NF (do `RELATORIO_NF_ultimo.json`, mais antigos
primeiro, com RFQ e entrega), divergências, "NF no portal com a coluna vazia"
(`nf_so_no_portal_lista` da conferência), rodadas (com `inicio`) e o cadastro.
`comando_eventos_nf` devolve a linha do tempo de 7 dias montada **na leitura**
a partir de `sync_nf.json`, `cadastro_pedidos.json` e
`sync_planilha_portal_historico.json`. Não existe `eventos_nf.jsonl`: são
processos diferentes (serviço, SincronizarNF.bat, CadastrarPedidos.bat, tarefa
da sync) e cada um já grava só o próprio histórico. Parte que não lê vem como
`{"erro": ...}`, nunca como zero.

### Configuração (o `.env` fica na pasta `sync_nf`, não no repo)

`SYNC_NF_DADOS=\\SERVIDOR2\Publico\ALLAN\database\sync_nf` guarda o
`vendas_hse.json`, o `sync_nf.json`, o `cadastro_pedidos.json` e o estado da
conferência. **Nunca aponte para outra pasta**: ela já foi trocada por engano
uma vez, ao suspeitarem que causava um erro.

### Sintomas já vistos

| sintoma | causa real |
|---|---|
| "cadastro parou" | planilha aberta no Excel sem salvar. O `~$` pode ser velho, não confie nele |
| linha apagada e redigitada não entra | a deduplicação do `cadastro_pedidos.json` já a marcou como vista |
| serviço "rodando" em loop | processo órfão segurando a trava, e o código de saída 3 se perdia na tarefa |
| "Consultando o robô..." infinito no portal | serviço desconectado ou recusado pelo token |

---

## 5. Portal Maestro: contrato de eventos

O `server.js` só repassa eventos socket.io entre o navegador (`sou_frontend`),
os robôs (`sou_o_robo`) e o serviço de NF (`sou_o_sync_nf`). **O contrato é o
nome do evento**, uma string que liga JS e Python sem import nenhum. Renomear
de um lado quebra o outro sem aviso.

Eventos da integração de NF e cadastro:

- portal → serviço: `solicitar_sync_nf*`, aceitos só de socket logado;
- serviço ↔ `maestro.py`: `comando_sync_nf_estado` e `comando_sync_nf`;
- dashboards (só leitura): `comando_sync_planilha_painel`, `comando_nf_painel`
  e `comando_eventos_nf` (`{limite, desde, clientId}`), com resposta
  `retorno_*` e o mesmo `clientId`;
- serviço/robô → portal: progresso, resultado e `planilha_atualizada`;
- token comparado em tempo constante. Token errado ou ausente faz o portal
  recusar e desconectar.

Para mudar um evento: `grep -n "<nome>"` em `server.js`, `public/*.html`,
`cruzar_nf/` **e** no `gerenciador.py` do servidor.

O `server.js` **não lê `.env`**: o dotenv foi tirado em 02/10. O token vem de
`setx /M`, depois `pm2 restart --update-env` e `pm2 save`.

---

## 6. Onde ficam os dados (não leia inteiro, filtre)

São arquivos grandes de dados e não de código. Abrir inteiro gasta contexto à
toa. Use `python -c`, `jq` ou `grep` para extrair o pedido ou a linha que
interessa.

| arquivo | o que é |
|---|---|
| `cotafrete.db` | SQLite em WAL. Backup só por `core/backup.py`, nunca por cópia crua |
| `PEDIDOS.json` | pedidos do Maestro (servidor, `Banco-de-dados\`) |
| `vendas_hse.json` | base de vendas do HSE desde 2025 |
| `logs\servico_nf.log`, `logs\diag_nf.txt` | leia só o final: `tail -n 200` ou `Get-Content -Tail 200` |
| `tests/fixtures/*.html` | HTML real dos sites. Não abra para entender código |
| `runs/`, `recon_out/`, `teste_real/` | saídas de execução. Ignore |

## 7. Orçamentos DAV: resultado, avisos e correções

- `web/dav_ui.py`: envio e conferência do vendedor, histórico pessoal, detalhe,
  PDF e componentes compartilhados. `web/adm_dav.py`: painel e detalhe próprios
  de administração; aparece na sidebar de `web/painel_ui.py`. O `/adm` mostra
  um resumo DAV separado dos números de frete.
  A barra compacta usa menus `details` com links GET; período, resultado,
  vendedor (só ADM), busca e categoria continuam nos links e na paginação.
  `/adm/dav/erros` e `/adm/dav/erros/agora` mostram o resumo com a mesma porta
  administrativa, orientações e detalhes originais escapados.
- `orcamento/diagnostico.py`: interpreta `erro` **e** a seção de erros do
  relatório. Aviso financeiro pode coexistir com DAV pronto e não significa
  falha de criação. Texto livre do relatório só é entregue ao administrador;
  o vendedor recebe projeção permitida, inclusive no pulso e na cópia de
  diagnóstico. Formato desconhecido é omitido com orientação, não exposto por
  uma tentativa de retirar números. Valores comerciais da conferência e o
  acesso aos PDFs existentes permanecem como antes.
  Origem, onde conferir, como corrigir e células confirmadas são projeções
  seguras. Padrões de campo são ancorados na estrutura da mensagem: texto
  digitado dentro do valor inválido não pode virar evidência de outra célula
  ou defeito da automação. Endereço divergente exige comparar B30 e cadastro,
  sem atribuir culpa. Automação/acesso orientam procurar Enzo, Allan ou Lucas.
  Resultado sem confirmação sempre prevalece sobre instrução de correção.
- `core/painel_dav.py`: consultas completas por período, filtragem e paginação
  de 25 registros. Contagem usa o período inteiro pela data de submissão em
  Brasília; rejeições, conferências e simulações não são tentativas de geração.
  Ausência de informação de aviso não equivale a zero avisos.
  `ocorrencias` agrupa o recorte filtrado completo antes da paginação,
  separando falha, rejeição, conferência inválida, confirmação e avisos.
  O grupo é a causa (tipo, origem, motivo, orientação); as células ficam em
  cada envio, não em "Onde conferir". Erro já resolvido por novo envio pronto
  sai das ocorrências (`corrigidas` conta quantos). O cartão do painel ADM
  soma as mesmas ocorrências por origem, para os números baterem com o resumo.
  Telas no modelo B: `consultar` devolve `quadro` (precisa/andamento/prontos)
  do período inteiro, sem o filtro de resultado; só a tabela do histórico segue
  os filtros. Vendedor: banner com o envio + colunas Precisa de você / Em
  andamento / Prontos. ADM: indicadores + colunas por quem resolve (planilha e
  cadastro, automação e acesso, conferir no HSE e avisos). O pulso atualiza
  `dav-quadro` junto com o histórico.
  Sem linha ERRO: do robô, o motivo vem da origem reconhecida (nunca do texto
  livre do erro). No detalhe, a orientação fica dentro da caixa do resultado.
  Espera e duração na UI vêm das datas reais (Brasília), omitidas se inválidas
  ou negativas. A cópia para suporte inclui contexto do envio sem ampliar a
  exposição do relatório ao vendedor.
- `dav.estado`: `rascunho`, `fila`, `gerando`, `pronto`, `erro`, `incerto`,
  `simulado` e `rejeitado`. Rejeição guarda metadados/motivo, hash vazio e não
  mantém arquivo nem entra no robô. Estados desconhecidos continuam visíveis.
- `dav_correcao`: relações explícitas entre envios do mesmo proprietário;
  validação transacional impede origem incerta e ciclos. Um descendente pronto
  resolve a pendência visual, preservando o erro e a contagem originais. Não
  inferir vínculos antigos por nome de arquivo ou cliente.
- **Correção automática da IA** (`dav_ui.corrigir_sozinho`, ligada no `ao_terminar`
  da `FilaDiagnostico`): só culpa `planilha`, confiança alta, `criados_no_hse == []`
  e todas as correções em B30/B33 (`correcao.automaticas`). CNPJ e código de produto
  continuam no "Aprovar correção": um dígito errado vira outro cliente ou produto que
  passa na conferência. Cria o mesmo envio do Aprovar (`criar_envio_corrigido`), passa
  pela conferência e espera o vendedor clicar em Gerar. Nunca gera no HSE. A coluna
  `dav.correcao_ia` guarda campo, valor antigo e novo para o aviso ao vendedor (sem o
  motivo, que é texto livre da IA) e impede uma segunda rodada sobre o mesmo envio.
- **Duplicidade:** `incerto`, evidência de salvamento ou erro com número HSE
  exigem conferência antes de reenviar. A deduplicação protege também erro com
  número já persistido. Nada aqui repete geração automaticamente. O ADM consulta
  todos os envios, mas não assume o usuário de um vendedor para gerar.
- GETs de acompanhamento: `/dav/agora`, `/dav/{id}/agora`, `/adm/dav/agora` e
  `/adm/dav/{id}/agora`. Mesmas permissões das páginas; 401 se a sessão expirou,
  204 se o conteúdo do recorte não mudou e respostas privadas sem cache. Pulso
  de 5 s preserva filtros/foco/detalhes abertos; falha de consulta mantém os dados
  anteriores e exibe aviso. Não adicionar progresso percentual fictício.

Depois de mexer: `python -m pytest tests -k dav -q`, regressão de
`tests/orcamento/test_fila.py` e conferência visual claro/escuro e celular.
Arquivos produtivos e robô HSE não são necessários para esses testes.

## 8. Testes: rápido no dia a dia, inteiro em segundo plano

`tests/test_dav_apresentacao.py` usa `bs4` para conferir o HTML. A distribuição
é `beautifulsoup4`, declarada em `requirements.txt`, que a CI instala antes dos
testes. Não depender apenas dos pacotes já instalados no PC de desenvolvimento.

`tests/conftest.py` marca `navegador` sozinho todo teste de arquivo que
importa playwright ou uvicorn (31 arquivos, ~435 testes, dois terços do
tempo). A marcação é pelo import: teste novo de navegador cai nela sem
decorar nada.

- **Dia a dia:** `python -m pytest tests -q -m "not navegador"`. Mexeu numa
  transportadora: isso e `python -m pytest tests -q -k <slug>`, que inclui
  os testes de navegador dela.
- **Suíte inteira:** sempre em segundo plano e nunca dividida. Em paralelo:
  `-n 4` (pytest-xdist), que é como a CI roda. Em série é o padrão local.
  Na CI a suíte vai em 4 máquinas ao mesmo tempo (`PARTE_DA_SUITE=1/4`…`4/4`,
  divisão por arquivo no `tests/conftest.py`), e o check `cotafrete` junta
  as quatro.
- **Espera fixa do site** (`wait_for_timeout`, `ESPERA_*`): no teste, troque a
  constante por `monkeypatch` (ver `ESPERA_AJAX_TESTE_MS` em
  `tests/test_translovato_cnpj.py`). Produção não muda.
- **Teste esperando tempo limite** costuma ser defeito do adapter, não do
  teste: foi assim que a UF da Della Volpe apareceu (seção 2).
- **Banco nos testes:** `with closing(banco._conectar()) as con, con:`, como
  o `core/banco.py`. Sem o `closing` o arquivo fica aberto.
- **Prints de `docs/rebranding/`:** `python scripts/gerar_prints_rebranding.py`,
  fora da suíte e da CI.
