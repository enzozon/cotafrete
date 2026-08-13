# Regras da ficha de cotação

Formato para passar os dados de um frete. Uma linha por campo, `Chave: valor`.
O mesmo arquivo serve para todas as transportadoras — cada site recebe os
dados no formato que ele exige, e isso é trabalho do código, não seu.

## Modelo pronto para copiar

```
Nome Completo: Enzo Zon
email: vendas2@venturainformatica.com.br
WhatsApp: +55 (27) 3063-1564
CEP ORIGEM: 09895-003
CEP DESTINO: 29105-770
CNPJ Remetente: 60.042.686/0001-05
CNPJ Destinatario: 05.954.058/0001-98
CNPJ Pagador: 05.954.058/0001-98
Peso Total (kg): 12
Quantidade de Volumes: 3
Comprimento (cm): 30
Largura (cm): 30
Altura (cm): 30
Valor Total Nota Fiscal: 568,77
Material: LUVA DE BOMBEIRO
Tipo de Serviço: Fracionado -LTL
Modalidade: Expresso
```

---

## As 7 regras

### 1. O CEP manda. Não escreva cidade nem estado.

Cidade e UF são **calculadas a partir do CEP**, via ViaCEP. Se você escrever
cidade na ficha, ela é ignorada.

**Por quê:** uma ficha real dizia `São José dos Campos` com o CEP `09895-003`,
que é São Bernardo do Campo. A Jadlog cota **por CEP** e a Della Volpe cota
**por cidade num dropdown** — a mesma ficha cotava duas rotas diferentes, e
comparar os dois preços não queria dizer nada. Uma fonte de verdade só.

CEP que não existe **para o processo**, em vez de seguir com cidade errada.

### 2. WhatsApp é obrigatório.

A Della Volpe exige no formulário. Sem ele a ficha é recusada antes de abrir o
navegador. Pode escrever de qualquer jeito: `27999887766`, `(27) 99988-7766`
ou `+55 (27) 3063-1564`.

### 3. Modalidade define o preço na Jadlog.

`Modalidade: Expresso`. Se omitir, assume Expresso.

Válidas: `expresso`, `package`, `rodoviario`, `economico`, `doc`, `com`,
`cargo`. Modalidade escrita errado **para o processo** e lista as válidas —
o código não escolhe uma por conta própria, porque cada uma tem preço bem
diferente.

### 4. Peso é o de UM volume.

`Peso Total (kg): 12` + `Quantidade de Volumes: 3` = **36 kg de carga**.

3 caixas de 12 kg → escreva `12` e `3`. Não escreva 36.

### 5. Um produto por ficha, caixas idênticas.

O formato tem **um** conjunto de medidas, então todos os volumes têm o mesmo
tamanho. Para despachar caixas de tamanhos diferentes, faça uma ficha por
tamanho.

### 6. Vírgula para decimal. Sempre.

`568,77` — não `568.77`.

O leitor ainda aceita ponto por tolerância, mas `1.568` é genuinamente
ambíguo: mil quinhentos e sessenta e oito, ou um e meio? Com vírgula não há
dúvida: `1.568,77` são mil quinhentos e sessenta e oito reais e setenta e sete.

### 7. Medida em centímetros, número inteiro.

`Comprimento (cm): 30`. Você escreve `30` para todos os sites; o código
converte para o formato de cada um:

| Site | Recebe | Por quê |
|---|---|---|
| Della Volpe | `30,0` | O campo tem máscara de uma casa decimal. Digitar `30` vira `3,0` e a carga é cotada **10x menor**, sem nenhum aviso. |
| Jadlog | `30` | Campo sem máscara. |

Isso é a coisa mais perigosa do projeto, porque erra calado — o frete sai
barato e parece certo.

---

## Detalhes que evitam retrabalho

**Linhas extras são ignoradas.** Pode deixar observação, assinatura de e-mail
ou anotação no fim do arquivo.

**Acento e maiúscula não importam.** `Tipo de Serviço`, `TIPO DE SERVICO` e
`tipo de servico` são a mesma coisa.

**Campo faltando diz qual é**, pelo nome — não precisa conferir as 17 linhas
na mão:

```
core.ficha.CamposFaltando: Faltam campos na ficha: WhatsApp
```

---

## Como rodar

```bash
# Jadlog + Della Volpe em dry-run (preenche, printa, NÃO envia)
python testar_teste_real.py teste1.txt

# Della Volpe com ENVIO REAL — vira cotação na fila de um vendedor
$env:DV_ENVIO_REAL_AUTORIZADO = "sim"
python testar_teste_real.py teste1.txt --dellavolpe
```

Evidências ficam em `teste_real/jadlog/` e `teste_real/dellavolpe/`, uma pasta
por execução, com o print da tela. Essas pastas estão no `.gitignore`: contêm
CNPJ real e valor de nota fiscal.

## Credenciais

Ficam no `.env`, que nunca vai para o git.

`DV_ENVIO_REAL_AUTORIZADO` é a trava do envio real da Della Volpe. Quem define
é você — o código nunca liga isso sozinho.
