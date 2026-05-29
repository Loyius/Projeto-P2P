# Guia de Testes Práticos e Manuais — Sprint 03 (Nativo)

Este guia ensina a validar a **Sprint 03** utilizando **apenas** o `servidor.py` e o `client.py` originais, configurados via variáveis de ambiente no **PowerShell (Windows)**. Não há necessidade de rodar scripts de teste mock adicionais!

---

## 📌 Convenções e Arquitetura Local

Ao rodar tudo em uma única máquina, simulamos o ecossistema Master-Worker distribuído usando portas diferentes:

| Nome do Nó | Endereço | UUID / Identificador | Função |
| :--- | :--- | :--- | :--- |
| **Master A** (Saturado) | `127.0.0.1:5000` | `MASTER_A` | Requisita ajuda |
| **Master B** (Doador) | `127.0.0.1:6001` | `MASTER_B` | Empresta Workers |
| **Master C** (Auxiliar) | `127.0.0.1:6002` | `MASTER_C` | Auxilia na concorrência |
| **Worker B1** | Conecta em `6001` | `WORKER_B1` | Worker nativo de B |

---

## ⚡ CT01, CT04 e CT05 — Ciclo Completo de Empréstimo e Execução

**Objetivo:** Ver o Master A saturar, pedir ajuda ao Master B, redirecionar o Worker B1 e executar uma tarefa nele identificando-o como `[EMPRESTADO]`.

### Passo 1: Iniciar o Master B (Doador)
No **Terminal 1**, configure e inicie o Master B na porta `6001`.
```powershell
$env:P2P_SERVER_UUID = "MASTER_B"
$env:P2P_PORT = "6001"
$env:P2P_SATURATION_THRESHOLD = "100" # Impede que B tente pedir ajuda
python servidor.py
```

### Passo 2: Conectar o Worker B1 a B
No **Terminal 2**, conecte o Worker ao Master B.
```powershell
$env:P2P_PORT = "6001"
$env:P2P_WORKER_UUID = "WORKER_B1"
$env:P2P_NO_TASK_SLEEP_SEC = "30" # Tempo padrão de NO_TASK
python client.py
```
> 💡 *Nota: O Worker B1 consumirá rapidamente a fila de tarefas inicial do Master B. Quando a fila zerar, ele começará a emitir heartbeats ALIVE a cada 30 segundos, ficando "ocioso".*

### Passo 3: Iniciar o Master A (Saturado)
No **Terminal 3**, configure o Master A para saturar muito rápido (threshold de 2 tarefas pendentes na fila) e aponte para o Master B como vizinho.
```powershell
$env:P2P_SERVER_UUID = "MASTER_A"
$env:P2P_PORT = "5000"
$env:P2P_NEIGHBOR_MASTERS = "MASTER_B=127.0.0.1:6001"
$env:P2P_SATURATION_THRESHOLD = "2" # Satura se tiver mais de 2 tarefas
$env:P2P_RELEASE_THRESHOLD = "1"
python servidor.py
```

### 🔍 O que observar nos logs:
1. **Master A** inicia com 30 tarefas na fila. Como $30 > 2$, ele detecta saturação e envia imediatamente um `request_help` para `MASTER_B` (127.0.0.1:6001).
2. **Master B** recebe a requisição, vê que tem `WORKER_B1` ocioso, responde com `response_accepted` e envia um `command_redirect` para o **Worker B1**.
3. No **Terminal 2 (Worker B1)**, você verá instantaneamente:
   ```text
   [WORKER] command_redirect recebido — redirecionando para 127.0.0.1:5000
   [WORKER] register_temporary_worker enviado ao novo Master
   ```
4. No **Terminal 3 (Master A)**, você verá o Worker B1 registrando-se e executando as tarefas pendentes de A:
   ```text
   [MASTER] Worker WORKER_B1 registrado como temporário (origem: MASTER_B)
   [MASTER] [EMPRESTADO] Status worker=WORKER_B1 ... STATUS=OK
   ```

---

## ⚡ CT06 — Devolução Consensual do Worker

**Objetivo:** Ver o Worker B1 retornar ao Master B de origem quando as tarefas do Master A forem concluídas.

### Passo Único: Acompanhar a Conclusão de Tarefas
Continue observando os mesmos terminais do teste anterior:
1. Como o Worker B1 está processando as tarefas de A a cada ciclo, a fila de tarefas do Master A irá baixar.
2. Assim que o tamanho da fila do Master A cair abaixo do threshold de liberação ($< 1$ tarefa), o monitor de saturação do Master A é acionado.
3. **Master A** envia um `command_release` para `WORKER_B1` e notifica o `MASTER_B` via `notify_worker_returned`.
4. No **Terminal 2 (Worker B1)**, você verá:
   ```text
   [WORKER] command_release recebido — voltando ao Master original
   [WORKER] UUID=WORKER_B1 a ligar a 127.0.0.1:6001
   ```
5. O Worker reconecta graciosamente no **Master B** de origem e volta a escutar na porta `6001`!

---

## ⚡ CT02 — Pedido de Ajuda Recusado (Carga Alta ou Sem Workers)

**Objetivo:** Ver o Master A pedir ajuda e o Master B recusar por não ter Workers disponíveis.

### Passo 1: Iniciar o Master B sem Workers
No **Terminal 1**, inicie o Master B na porta `6001` e **não conecte nenhum worker** nele.
```powershell
$env:P2P_SERVER_UUID = "MASTER_B"
$env:P2P_PORT = "6001"
python servidor.py
```

### Passo 2: Iniciar o Master A
No **Terminal 3**, inicie o Master A configurado para saturar.
```powershell
$env:P2P_SERVER_UUID = "MASTER_A"
$env:P2P_PORT = "5000"
$env:P2P_NEIGHBOR_MASTERS = "MASTER_B=127.0.0.1:6001"
$env:P2P_SATURATION_THRESHOLD = "2"
python servidor.py
```

### 🔍 O que observar nos logs:
- **Master A** envia `request_help` para B.
- **Master B** recebe e, por não ter workers ociosos, responde com `response_rejected` e `reason: "high_load"`.
- O log do **Master A** registrará que o pedido foi recusado e o fluxo continuará sem redirecionamentos.

---

## ⚡ CT08 — Tolerância a Falhas (Master A cai durante Empréstimo)

**Objetivo:** Mostrar que, se o Master tomador (Master A) cair repentinamente, o Worker emprestado retorna de forma autônoma para o seu Master de origem.

### Passo 1: Executar o Ciclo de Empréstimo (conforme CT01)
Certifique-se de que o **Worker B1** já está redirecionado e processando tarefas no **Master A**.

### Passo 2: Derrubar o Master A
No **Terminal 3 (Master A)**, pressione `Ctrl+C` para encerrar o processo abruptamente.

### 🔍 O que observar nos logs:
No **Terminal 2 (Worker B1)**, você verá:
1. O socket detecta perda de conexão com o Master A.
2. O Worker identifica que era um Worker emprestado e aciona a recuperação:
   ```text
   [WORKER] Conexão perdida com Master atual. Recuperando Master de origem...
   [WORKER] UUID=WORKER_B1 a ligar a 127.0.0.1:6001
   ```
3. O Worker reconecta com sucesso no **Master B** e continua operacional!

---

## ⚡ CT07 — Timeout de Negociação

**Objetivo:** Ver o Master A tratar de forma robusta e registrar em log a falha/timeout ao tentar falar com um vizinho offline.

### Passo 1: Iniciar Master A apontando para um Vizinho Inexistente
No **Terminal 3**, inicie o Master A apontando para um endereço inativo (`127.0.0.1:9999`) e com timeout curto.
```powershell
$env:P2P_SERVER_UUID = "MASTER_A"
$env:P2P_PORT = "5000"
$env:P2P_NEIGHBOR_MASTERS = "OFFLINE_MASTER=127.0.0.1:9999"
$env:P2P_SATURATION_THRESHOLD = "2"
$env:P2P_M2M_TIMEOUT_SEC = "3"
python servidor.py
```

### 🔍 O que observar nos logs:
No terminal do **Master A**, você verá a tentativa de conexão falhar ou dar timeout de forma elegante, sem crashar o servidor:
```text
[MASTER] Falha ao conectar/enviar request_help para OFFLINE_MASTER: [WinError 10061] ...
```

---

## ⚡ CT09 — Parsing Tolerante (Tipo Desconhecido ou Malformatado)

**Objetivo:** Garantir que o protocolo seja extensível e tolerante a ruído ou campos desconhecidos.

### Passo 1: Iniciar Master A normalmente
```powershell
$env:P2P_SERVER_UUID = "MASTER_A"
$env:P2P_PORT = "5000"
python servidor.py
```

### Passo 2: Enviar Mensagem Inválida ou Desconhecida usando PowerShell
Abra uma janela normal do PowerShell e envie uma mensagem JSON com tipo desconhecido diretamente no socket da porta 5000:
```powershell
$tcp = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 5000)
$stream = $tcp.GetStream()
$writer = New-Object System.IO.StreamWriter($stream)
$writer.WriteLine('{"type": "op_futura_secreta", "request_id": "123", "payload": {"foo": "bar"}}')
$writer.Flush()
$tcp.Close()
```

### 🔍 O que observar nos logs:
No terminal do **Master A**, você verá a mensagem sendo recebida, logada como aviso e ignorada perfeitamente:
```text
WARNING | [MASTER] type='op_futura_secreta' desconhecido de ... — ignorando
```
O Master continuará escutando e aceitando conexões de Workers normalmente!

---

💡 *Dica extra: Você sempre pode rodar a suíte automática de validação usando o comando `python -m pytest tests/ -v` para ter certeza absoluta de que tudo está em conformidade com as regras do projeto.*
