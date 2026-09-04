# Subir o Cotafrete no servidor da empresa

O servidor é um **Windows Server 2012 R2**. O Cotafrete **não roda direto
nele** — roda numa máquina virtual Windows dentro dele, no mesmo hardware.

Este documento é o passo a passo dessa instalação.

---

## Por que a máquina virtual, e não direto no servidor

Cinco das seis transportadoras cotam abrindo um navegador de verdade —
inclusive a Jadlog, que apesar de ter API usa o painel (`web/app.py:49`
importa `JadlogPainelAdapter`, não o adapter de API).

O Chromium **110**, de fevereiro de 2023, encerrou o suporte a Windows 7,
8.1, Server 2012 e Server 2012 R2. Não é "sem suporte, mas funciona": o
Google avisou que as páginas simplesmente não carregam. O `requirements.txt`
pede `playwright>=1.45`, que traz Chromium 126.

Voltar o Playwright para a versão 1.29 (dezembro de 2022, último com Chromium
109) faria o navegador abrir — e não resolveria nada:

- A **Generoso** só passa pelo checkpoint da Vercel porque parece um navegador
  atual. A matriz medida em `carriers/base.py:29-36` mostra que qualquer sinal
  de robô devolve "Código 21" ou "Código 29". Um Chromium de quatro anos atrás
  é *mais* suspeito, não menos.
- A **Della Volpe** tem reCAPTCHA v3, com o mesmo problema
  (`carriers/dellavolpe/adapter.py:338-346`).

Ou seja: manter as seis transportadoras exige um Chromium atual, e um Chromium
atual exige Windows 10 ou mais novo. A VM é a forma de ter isso **sem trocar o
servidor da empresa**.

Dois bloqueios menores, na mesma direção: o Python para no 3.12 no Server 2012
R2 (PEP 11), e o `pydantic` 2.x é extensão Rust — o Rust 1.78 também deixou o
Windows 8.1 para trás.

---

## O que é preciso ter antes

| item | por quê |
|---|---|
| Hyper-V habilitado no servidor | é o que roda a VM. Já vem no Server 2012 R2, só ativar a função |
| ~4 GB de RAM e ~60 GB de disco livres | para a VM. Cinco Chromium simultâneos comem memória |
| Licença de Windows para a VM | **Server 2019 ou 2022** se a empresa tiver — é o que o Playwright suporta oficialmente. **Windows 10** também serve: o Chrome mantém suporte a ele até ~2028 |
| O arquivo `.env` de produção | tem as senhas das transportadoras. Não está no Git, tem que ser copiado à mão |

**Windows 11 não dá.** Ele exige TPM virtual, que só existe no Hyper-V a
partir do Server 2016.

---

## 1. Criar o switch de rede — antes da VM

Este é o passo que, se sair errado, deixa tudo instalado e **ninguém consegue
acessar**. A VM precisa de um IP na rede da empresa, e para isso o switch tem
que ser do tipo *externo*, ligado à placa de rede física.

No servidor, Hyper-V Manager → **Virtual Switch Manager** → New → **External**:

- marque a placa de rede que está no cabo da empresa (não o Wi-Fi);
- deixe marcado *"Allow management operating system to share this network
  adapter"* — sem isso o próprio servidor perde a rede.

Switch **Internal** ou **Private** faz a VM enxergar só o servidor. O sistema
sobe, o `Servidor.bat` mostra um IP, e nenhuma máquina da empresa alcança.

---

## 2. Criar a VM

Hyper-V Manager → New → Virtual Machine:

- **Geração 2**;
- 4096 MB de memória, com *Dynamic Memory* desligado (o Chromium oscila muito,
  e a memória dinâmica devolve RAM no meio de uma cotação);
- 2 ou mais processadores virtuais;
- disco de 60 GB;
- conectada ao switch externo do passo 1;
- ISO do Windows escolhido.

Instale o Windows normalmente e aplique as atualizações.

---

## 3. Desligar o modo de sessão avançada

Ainda no Hyper-V Manager, com a VM selecionada: **View → Enhanced Session** →
desmarcado. Nas configurações do host, em *Hyper-V Settings → Enhanced Session
Mode Policy*, desmarque também.

Com a sessão avançada ligada, a janela de conexão é um RDP disfarçado: fechar
a janela **desconecta a sessão**. Com ela desligada, você está olhando para o
console de vídeo da VM — fechar a janela não muda nada do lado de dentro, a
área de trabalho continua viva.

Isso importa porque a Generoso e a Della Volpe exigem navegador **com janela**
(`headless=False`), e janela precisa de área de trabalho. É o mesmo motivo
pelo qual o Cotafrete não pode virar um serviço do Windows: serviço roda na
Sessão 0, que não tem área de trabalho nenhuma.

---

## 4. Instalar o Cotafrete dentro da VM

Dentro da VM, com o Python 3.12 ou 3.13 instalado (marque *"Add Python to
PATH"* no instalador):

```
git clone <url-do-repositorio> C:\cotafrete-producao
cd C:\cotafrete-producao
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
```

Não tem `.venv\Scripts\activate` de propósito. No Windows o `activate` é um
script do PowerShell, e a política de execução padrão recusa scripts —
"running scripts is disabled on this system". Chamar o `python.exe` da venv
direto passa por cima disso sem mexer em política de segurança do servidor, e
é exatamente o que o `Servidor.bat` faz para subir o uvicorn.

**A pasta precisa se chamar `cotafrete-producao`.** O `Servidor.bat` se recusa
a subir de qualquer outra — é a trava que existe desde 25/08/2026, quando
quatro cotações reais foram parar no banco de desenvolvimento.

Depois copie o `.env` de produção para dentro de `C:\cotafrete-producao`. Ele
não vem no Git. As chaves esperadas:

```
BRASPRESS_USUARIO      BRASPRESS_SENHA
GENEROSO_USUARIO       GENEROSO_SENHA
JADLOG_PAINEL_USUARIO  JADLOG_PAINEL_SENHA
JADLOG_TOKEN           JADLOG_CONTA        JADLOG_CONTRATO
SSW_DOMINIO            SSW_CPF             SSW_USUARIO   SSW_SENHA
TRANSLOVATO_CNPJ       TRANSLOVATO_USUARIO TRANSLOVATO_SENHA
COTAFRETE_ADM_SENHA
```

Teste antes de seguir: rode `Servidor.bat` e abra `http://localhost:8000`
dentro da própria VM. Faça uma cotação real e confira que as cinco
automáticas respondem.

---

## 5. Liberar a porta 8000 no firewall da VM

Sem isto o sistema funciona dentro da VM e mais em lugar nenhum. Num
PowerShell como administrador, dentro da VM:

```powershell
New-NetFirewallRule -DisplayName "Cotafrete 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Domain,Private
```

`-Profile Domain,Private` de propósito: não abre a porta se a VM cair numa
rede pública.

---

## 6. Login automático e início automático

O Cotafrete precisa de uma sessão **logada** para ter área de trabalho. Se a
VM reiniciar e parar na tela de login, o sistema fica fora do ar até alguém
digitar a senha.

Dentro da VM, PowerShell como administrador — trocando usuário, senha e
domínio pelos reais:

```powershell
$k = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
Set-ItemProperty $k AutoAdminLogon  "1"
Set-ItemProperty $k DefaultUserName "cotafrete"
Set-ItemProperty $k DefaultPassword "a-senha-real"
Set-ItemProperty $k DefaultDomainName "NOME-DA-VM"
```

A senha fica **em texto puro no registro**. É o preço do login automático.
Por isso: use uma conta local criada só para isso, sem acesso a mais nada da
rede, e não reaproveite uma senha usada em outro lugar.

Depois, coloque um atalho do `Servidor.bat` na pasta de inicialização:

```
C:\Users\cotafrete\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup
```

E no servidor (host), nas configurações da VM → **Automatic Start Action** →
*Always start this virtual machine automatically*. Assim, quando o servidor
liga: sobe a VM, a VM loga sozinha, o `Servidor.bat` abre.

---

## 7. Descobrir o endereço e avisar a equipe

Com o `Servidor.bat` aberto, a janela mostra o IP. É o endereço que a equipe
digita:

```
http://<ip-da-vm>:8000
```

Peça ao pessoal de rede um **IP fixo** (ou uma reserva no DHCP) para a VM. Se
o IP mudar, o endereço quebra para todo mundo de uma vez.

---

## Operação do dia a dia

| situação | o que fazer |
|---|---|
| Sistema fora do ar | abra a VM pelo Hyper-V Manager e veja se o `Servidor.bat` está aberto. Se não, dê duplo clique nele |
| Reiniciar o sistema | feche a janela do `Servidor.bat` e abra de novo |
| Atualizar o código | dentro da VM: feche o `Servidor.bat`, `git pull`, `pip install -r requirements.txt`, abra de novo. Fora do horário de expediente |
| Ver quem está cotando | `Monitor.bat`, dentro da VM. Abre o banco em somente leitura, pode ficar aberto o dia todo |

**Nunca feche a janela do `Servidor.bat` durante o expediente** — ela é o
sistema. Fechar desliga para a empresa inteira.

---

## O que ainda está em aberto

- **Não existe backup do banco.** Todo o histórico de cotações vive em
  `C:\cotafrete-producao\cotafrete.db`, dentro da VM. Antes de considerar a
  instalação concluída, defina uma cópia periódica desse arquivo (e da pasta
  `runs\`, que guarda as evidências) para fora da VM.
- **A VM não recebe atualização de segurança** se for Windows 10 — o suporte
  terminou em outubro de 2025. O Chrome continua funcionando até ~2028. Se a
  empresa tiver licença de Server 2019 ou 2022, prefira, que continua
  recebendo correções.
