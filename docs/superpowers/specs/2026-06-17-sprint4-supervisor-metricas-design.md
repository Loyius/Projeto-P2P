# Sprint 4: Supervisor de Métricas do Cluster — Design (Brainstorming)

**Data:** 2026-06-17
**Estado:** Planeado. Ver plano em `docs/superpowers/plans/2026-06-17-sprint4-supervisor-metricas.md`.

---

## 1. Contexto

Extensão do sistema Master-Worker (Sprints 01, 02 e 03) para reportar métricas de desempenho do cluster a um **Supervisor de Métricas** externo (`nuted-ia.dev`), que agrega os dados e os exibe num dashboard web. Cada Master deve, periodicamente (a cada 10s), abrir uma conexão **TLS sobre TCP** ao Supervisor, enviar um payload JSON com o estado do nó (sistema, farm_state, thresholds, vizinhos) e fechar a conexão **sem aguardar resposta** (apenas `SEND`, nunca `RECV`).

Toda a lógica das Sprints 01/02/03 é **preservada integralmente** — nada é apagado ou sobrescrito. O envio ao Supervisor é um novo "side-channel" independente do protocolo M2M e do protocolo Worker↔Master.

---

## 2. Decisões de desenho

| Decisão | Escolha |
|--------|---------|
| Canal de envio | Conexão **TLS sobre TCP** própria, separada do socket principal do Master. Nunca HTTP. |
| Host/Porta/SNI | `nuted-ia.dev:443`, SNI `nuted-ia.dev` — fixos por configuração (`TCP_SOCKET_HOST`, `TCP_SOCKET_PORT`, `TCP_SOCKET_TLS`, `TCP_SOCKET_SNI`). |
| Periodicidade | Thread daemon dedicada (`_metrics_reporter`), dispara a cada 10s via `threading.Event.wait(10)` — não bloqueia o loop principal do Master. |
| Padrão de envio | **Apenas `SEND`**: abre conexão TLS, envia o JSON + `\n`, fecha a conexão. Nunca chama `RECV`. |
| Formato do payload | JSON conforme `sprint4.md`, com a correção de formato exigida nesta sprint: **todas as chaves do payload em MAIÚSCULAS**, valores inalterados em relação ao documento original (mesmos tipos e mesmo significado). |
| Origem dos dados | `performance.system` vem de `psutil` (cpu, memória, disco, uptime); `performance.farm_state` vem das estruturas já existentes (`local_workers`, `borrowed_workers`, `task_queue`, `pending_by_worker`); `performance.config_thresholds` vem das env vars já existentes (Sprint 03); `performance.neighbors` vem de `NEIGHBOR_MASTERS` + último heartbeat M2M observado. |
| Falha de envio | `socket.timeout`/`OSError`/`ssl.SSLError` ao conectar ou enviar são capturados, logados (`metrics` logger) e ignorados — o relatório seguinte tenta de novo em 10s. Nunca derruba o Master. |
| Tolerância a falhas de Worker | Ver seção 7 — requisito novo desta sprint, ortogonal ao Supervisor de Métricas. |

---

## 3. Payload enviado ao Supervisor

### 3.1 Regra de formatação (correção desta sprint)

O documento `sprint4.md` define o payload com chaves em minúsculas/snake_case (ex.: `server_uuid`, `performance.system.cpu.usage_percent`). **Esta sprint corrige esse formato**: todas as chaves (em todos os níveis de aninhamento) passam a ser enviadas em **MAIÚSCULAS**, mantendo a mesma estrutura, os mesmos tipos e os mesmos valores definidos no documento original. Exemplo de mapeamento (chave original → chave enviada):

| Chave original (sprint4.md) | Chave enviada (Sprint 04) |
|---|---|
| `server_uuid` | `SERVER_UUID` |
| `hostname` | `HOSTNAME` |
| `role` | `ROLE` |
| `task` | `TASK` |
| `timestamp` | `TIMESTAMP` |
| `message_id` | `MESSAGE_ID` |
| `payload_version` | `PAYLOAD_VERSION` |
| `performance` | `PERFORMANCE` |
| `performance.system` | `PERFORMANCE.SYSTEM` |
| `performance.system.uptime_seconds` | `PERFORMANCE.SYSTEM.UPTIME_SECONDS` |
| `performance.system.load_average_1m` | `PERFORMANCE.SYSTEM.LOAD_AVERAGE_1M` |
| `performance.system.load_average_5m` | `PERFORMANCE.SYSTEM.LOAD_AVERAGE_5M` |
| `performance.system.cpu.usage_percent` | `PERFORMANCE.SYSTEM.CPU.USAGE_PERCENT` |
| `performance.system.cpu.count_logical` | `PERFORMANCE.SYSTEM.CPU.COUNT_LOGICAL` |
| `performance.system.cpu.count_physical` | `PERFORMANCE.SYSTEM.CPU.COUNT_PHYSICAL` |
| `performance.system.memory.total_mb` | `PERFORMANCE.SYSTEM.MEMORY.TOTAL_MB` |
| `performance.system.memory.available_mb` | `PERFORMANCE.SYSTEM.MEMORY.AVAILABLE_MB` |
| `performance.system.memory.percent_used` | `PERFORMANCE.SYSTEM.MEMORY.PERCENT_USED` |
| `performance.system.memory.memory_used` | `PERFORMANCE.SYSTEM.MEMORY.MEMORY_USED` |
| `performance.system.disk.total_gb` | `PERFORMANCE.SYSTEM.DISK.TOTAL_GB` |
| `performance.system.disk.free_gb` | `PERFORMANCE.SYSTEM.DISK.FREE_GB` |
| `performance.system.disk.percent_used` | `PERFORMANCE.SYSTEM.DISK.PERCENT_USED` |
| `performance.farm_state` | `PERFORMANCE.FARM_STATE` |
| `performance.farm_state.workers.*` | `PERFORMANCE.FARM_STATE.WORKERS.*` (mesmas sub-chaves, maiúsculas) |
| `performance.farm_state.workers.borrowed_workers[].direction` | `PERFORMANCE.FARM_STATE.WORKERS.BORROWED_WORKERS[].DIRECTION` |
| `performance.farm_state.workers.borrowed_workers[].peer_uuid` | `PERFORMANCE.FARM_STATE.WORKERS.BORROWED_WORKERS[].PEER_UUID` |
| `performance.farm_state.tasks.*` | `PERFORMANCE.FARM_STATE.TASKS.*` (mesmas sub-chaves, maiúsculas) |
| `performance.config_thresholds.*` | `PERFORMANCE.CONFIG_THRESHOLDS.*` (mesmas sub-chaves, maiúsculas) |
| `performance.neighbors[].server_uuid` | `PERFORMANCE.NEIGHBORS[].SERVER_UUID` |
| `performance.neighbors[].status` | `PERFORMANCE.NEIGHBORS[].STATUS` |
| `performance.neighbors[].last_heartbeat` | `PERFORMANCE.NEIGHBORS[].LAST_HEARTBEAT` |

Os **valores** (tipos, formato de timestamp ISO-8601, escala de percentuais 0–100, etc.) seguem exatamente o que está descrito em `sprint4.md` — apenas as chaves mudam de caixa.

> **Nota sobre os valores de workers no exemplo:** os números do payload de exemplo em `sprint4.md` (ex.: `TOTAL_REGISTERED: 6`, `WORKERS_ALIVE: 6`, `WORKERS_IDLE: 2`, etc.) são **meramente ilustrativos**. Todos os campos em `PERFORMANCE.FARM_STATE.WORKERS.*` são **dinâmicos**: refletem, em tempo real, o estado efetivo da farm no momento de cada envio — quantos Workers se registaram, estão vivos, ociosos, emprestados ou falhados naquele instante. Não existe um número fixo de Workers esperado: a farm pode iniciar e operar com qualquer quantidade de Workers, e esses valores devem ser sempre calculados a partir das estruturas internas do Master (`local_workers`, `borrowed_workers`, `pending_by_worker`) no instante da coleta, nunca hardcoded ou assumidos como constantes.

### 3.2 Exemplo de payload final (trecho, chaves em maiúsculas)

> Os valores de `PERFORMANCE.FARM_STATE.WORKERS` abaixo são apenas exemplo de formato — na prática variam a cada envio conforme o número real de Workers conectados naquele momento.

```json
{
  "SERVER_UUID": "master_1",
  "HOSTNAME": "master_1.A.farm.local",
  "ROLE": "master",
  "TASK": "performance_report",
  "TIMESTAMP": "2026-06-08T12:34:56Z",
  "MESSAGE_ID": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "PAYLOAD_VERSION": "sprint4-monitor",
  "PERFORMANCE": {
    "SYSTEM": {
      "UPTIME_SECONDS": 12345,
      "LOAD_AVERAGE_1M": 3.20,
      "LOAD_AVERAGE_5M": 2.50,
      "CPU": { "USAGE_PERCENT": 85.42, "COUNT_LOGICAL": 8, "COUNT_PHYSICAL": 4 },
      "MEMORY": { "TOTAL_MB": 16384, "AVAILABLE_MB": 8192, "PERCENT_USED": 62.18, "MEMORY_USED": 8000 },
      "DISK": { "TOTAL_GB": 512.0, "FREE_GB": 250.0, "PERCENT_USED": 45.0 }
    },
    "FARM_STATE": {
      "WORKERS": {
        "TOTAL_REGISTERED": 6, "WORKERS_UTILIZATION": 4, "WORKERS_ALIVE": 6,
        "WORKERS_IDLE": 2, "WORKERS_BORROWED": 1, "WORKERS_RECEIVED": 1,
        "WORKERS_FAILED": 0, "WORKERS_HOME": 5, "WORKERS_AVAILABLE_CAPACITY": 2,
        "BORROWED_WORKERS": [
          { "DIRECTION": "out", "PEER_UUID": "michel_2" },
          { "DIRECTION": "in",  "PEER_UUID": "michel_2" }
        ]
      },
      "TASKS": {
        "TASKS_PENDING": 42, "TASKS_RUNNING": 4, "TASKS_COMPLETED": 150,
        "TASKS_FAILED": 3, "OLDEST_TASK_AGE_S": 312
      }
    },
    "CONFIG_THRESHOLDS": {
      "MAX_TASK": 100, "WARN_CPU_PERCENT": 85, "WARN_MEMORY_PERCENT": 85, "RELEASE_TASK": 60
    },
    "NEIGHBORS": [
      { "SERVER_UUID": "michel_2", "STATUS": "available", "LAST_HEARTBEAT": "2026-06-08T12:34:56Z" }
    ]
  }
}
```

---

## 3.3 Schema completo do payload

> Convenção de nomes: todos os campos abaixo são listados em **MAIÚSCULAS**, conforme a correção de formato desta sprint (seção 3.1). Os campos de contagem de Workers (`PERFORMANCE.FARM_STATE.WORKERS.*`) são **dinâmicos**: refletem o estado real da farm no momento do envio, calculados a partir das estruturas internas do Master — não há valores fixos ou número fixo de Workers esperado.

### Raiz do payload

| Campo | Tipo | Descrição |
|---|---|---|
| `SERVER_UUID` | string | Identificador único do servidor no cluster (ex.: `"master_1"`) |
| `HOSTNAME` | string | Nome DNS do nó (ex.: `"master_1.A.farm.local"`) |
| `ROLE` | string | Papel do nó no cluster (`"master"`) |
| `TASK` | string | Tipo de relatório enviado (`"performance_report"`) |
| `TIMESTAMP` | string (ISO-8601) | Momento da coleta, formato `YYYY-MM-DDTHH:MM:SSZ` |
| `MESSAGE_ID` | string (UUID) | Identificador único da mensagem |
| `PAYLOAD_VERSION` | string | Versão do schema do payload (ex.: `"sprint4-monitor"`) |

### `PERFORMANCE.SYSTEM`

| Campo | Tipo | Descrição |
|---|---|---|
| `UPTIME_SECONDS` | int | Tempo de atividade do nó em segundos |
| `LOAD_AVERAGE_1M` | float | Média de load da CPU nos últimos 1 minuto |
| `LOAD_AVERAGE_5M` | float | Média de load da CPU nos últimos 5 minutos |
| `CPU.USAGE_PERCENT` | float | Percentual de uso da CPU (0–100) |
| `CPU.COUNT_LOGICAL` | int | Número de CPUs lógicas (threads) |
| `CPU.COUNT_PHYSICAL` | int | Número de CPUs físicas (cores) |
| `MEMORY.TOTAL_MB` | int | Memória RAM total em MB |
| `MEMORY.AVAILABLE_MB` | int | Memória RAM disponível em MB |
| `MEMORY.PERCENT_USED` | float | Percentual de uso da memória (0–100) |
| `MEMORY.MEMORY_USED` | int | Memória RAM utilizada em MB |
| `DISK.TOTAL_GB` | float | Espaço em disco total em GB |
| `DISK.FREE_GB` | float | Espaço em disco livre em GB |
| `DISK.PERCENT_USED` | float | Percentual de uso do disco (0–100) |

### `PERFORMANCE.FARM_STATE.WORKERS`

> Todos os campos abaixo são **dinâmicos** — calculados a partir de `local_workers`/`borrowed_workers`/`pending_by_worker` no instante da coleta. Não há quantidade fixa de Workers: a farm pode operar com qualquer número.

| Campo | Tipo | Descrição |
|---|---|---|
| `TOTAL_REGISTERED` | int | Total de Workers atualmente registados no nó (dinâmico, reflete o estado real no momento) |
| `WORKERS_UTILIZATION` | int | Workers ocupados no momento (executando tarefas) |
| `WORKERS_ALIVE` | int | Workers considerados vivos/respondendo |
| `WORKERS_IDLE` | int | Workers ociosos disponíveis para novas tarefas |
| `WORKERS_BORROWED` | int | Workers que este nó emprestou para outros nós |
| `WORKERS_RECEIVED` | int | Workers que este nó recebeu emprestados de outros nós |
| `WORKERS_FAILED` | int | Workers que falharam |
| `WORKERS_HOME` | int | Workers nativos do servidor (sem empréstimos) |
| `WORKERS_AVAILABLE_CAPACITY` | int | Capacidade ociosa total (= `WORKERS_IDLE`) |
| `BORROWED_WORKERS` | array | Lista de Workers emprestados com origem/destino |
| `BORROWED_WORKERS[].DIRECTION` | string (`"in"` \| `"out"`) | Direção do empréstimo: `"out"` (emprestou para outro) ou `"in"` (recebeu de outro) |
| `BORROWED_WORKERS[].PEER_UUID` | string | `SERVER_UUID` do nó na outra ponta do empréstimo |

### `PERFORMANCE.FARM_STATE.TASKS`

| Campo | Tipo | Descrição |
|---|---|---|
| `TASKS_PENDING` | int | Tarefas aguardando execução |
| `TASKS_RUNNING` | int | Tarefas em execução no momento |
| `TASKS_COMPLETED` | int | Total de tarefas concluídas |
| `TASKS_FAILED` | int | Total de tarefas com falha |
| `OLDEST_TASK_AGE_S` | int | Idade da tarefa pendente mais antiga (segundos) |

### `PERFORMANCE.CONFIG_THRESHOLDS`

| Campo | Tipo | Descrição |
|---|---|---|
| `MAX_TASK` | int | Número máximo de tarefas antes de considerar o nó saturado |
| `WARN_CPU_PERCENT` | int | Percentual de CPU para disparar alerta (ex.: 85) |
| `WARN_MEMORY_PERCENT` | int | Percentual de memória para disparar alerta (ex.: 85) |
| `RELEASE_TASK` | int | Threshold para liberar Workers emprestados |

### `PERFORMANCE.NEIGHBORS[]`

| Campo | Tipo | Descrição |
|---|---|---|
| `SERVER_UUID` | string | Identificador do nó vizinho |
| `STATUS` | string (`"available"` \| `"unavailable"`) | Status do vizinho |
| `LAST_HEARTBEAT` | string (ISO-8601) | Timestamp do último heartbeat recebido do vizinho |

---

## 4. Conexão com o Supervisor

| Parâmetro | Valor |
|---|---|
| Host | `nuted-ia.dev` |
| Porta | `443` |
| Protocolo | TLS sobre TCP (sem HTTP) |
| SNI | `nuted-ia.dev` |
| Periodicidade | a cada 10s |
| Padrão | conecta → envia JSON (`+\n`) → encerra; **nunca chama `RECV`** |

```python
TCP_SOCKET_HOST = "nuted-ia.dev"
TCP_SOCKET_PORT = 443
TCP_SOCKET_TLS = True
TCP_SOCKET_SNI = "nuted-ia.dev"
```

### 4.1 Regras explícitas de envio

- **TLS sobre TCP puro** — nunca HTTP/HTTPS. O envio é feito abrindo um socket TCP e envolvendo-o em TLS (`ssl.wrap_socket`/`SSLContext.wrap_socket`); não se usa nenhuma biblioteca HTTP (`requests`, `urllib`, etc.) para este envio.
- **Sem paths de URL no socket.** O endpoint de um socket TCP é definido **apenas por host e porta** — não existe noção de "caminho" num socket TCP. Caminhos como `/supervisor/colector` ou `/supervisor` **não se aplicam** aqui e não devem ser usados em nenhuma parte da lógica de conexão; eles pertencem apenas à URL do dashboard web (seção 4.3), que é um recurso HTTP separado e não tem relação com o socket de envio de métricas.
- **Apenas `SEND`, nunca `RECV`.** O cliente (Master) deve: (1) abrir a conexão TLS/TCP; (2) enviar o JSON serializado pela conexão estabelecida; (3) encerrar a conexão. Em nenhum momento o Master chama `recv()`/aguarda resposta do Supervisor — isso já está refletido em `_send_metrics_report` (seção 3, Task 3 do plano), que nunca invoca `recv`.
- **Parâmetros fixos da conexão:**

```python
TCP_SOCKET_HOST = "nuted-ia.dev"   # HOST
TCP_SOCKET_PORT = 443              # PORT
TCP_SOCKET_TLS  = True             # TLS = true
TCP_SOCKET_SNI  = "nuted-ia.dev"   # SNI
```

### 4.2 Identificadores dos nós (`SERVER_UUID`)

Valores como `michel_1` e `michel_2` são **identificadores de farms** em execução no ambiente do professor (ou de outros grupos), usados exclusivamente no campo `SERVER_UUID` do payload — são identificadores lógicos do nó **dentro do cluster monitorado**, não fazem parte do endereço de conexão TCP/TLS com o Supervisor (que é sempre `nuted-ia.dev:443`, independentemente do valor de `SERVER_UUID`). Cada Master deste projeto deve usar o seu próprio `SERVER_UUID` (configurável, ex.: via variável de ambiente já existente do projeto) sem confundir esse identificador lógico com host/porta de conexão.

### 4.3 Dashboard de visualização

As métricas enviadas por todos os projetos são agregadas e exibidas em tempo real num painel web acessível em:

`https://nuted-ia.dev/supervisor/dashboard/`

No dashboard é possível:
- Visualizar a topologia dos nós, servers e Workers do cluster;
- Acompanhar o consumo de CPU, memória, disco e filas de tarefas por servidor;
- Ver o estado dos Workers (ativos, ociosos, emprestados, com falha);
- Identificar gargalos e nós sobrecarregados em tempo real.

Cada novo envio via TLS/TCP atualiza automaticamente o dashboard, permitindo validar e depurar o comportamento distribuído do Master sem instrumentação adicional. Esse endereço é apenas para visualização no navegador (HTTP) — **não tem relação com o endpoint TCP/TLS** usado para enviar o payload (seção 4.1).

---

## 5. Estrutura de estado adicional (Master)

| Variável | Tipo | Protecção | Propósito |
|---|---|---|---|
| `_metrics_start_time` | `float` (monotonic) | — | Cálculo de `UPTIME_SECONDS` |
| `_neighbor_last_heartbeat` | `dict[str, str]` | `m2m_pool_lock` (reuso) | Último heartbeat ISO-8601 recebido de cada vizinho M2M, usado em `NEIGHBORS[].LAST_HEARTBEAT` |
| `worker_failure_count` | `int` (já existente, exposto) | `local_workers_lock` (reuso) | Alimenta `WORKERS_FAILED` |

Nenhuma estrutura de Sprint 01/02/03 é alterada de tipo; apenas lidas para compor o relatório.

---

## 6. Configuração via variáveis de ambiente (Sprint 04)

| Variável | Padrão | Descrição |
|---|---|---|
| `P2P_METRICS_ENABLED` | `"1"` | Liga/desliga o reporter de métricas (para testes) |
| `P2P_METRICS_INTERVAL_SEC` | `10` | Periodicidade de envio ao Supervisor |
| `P2P_SUPERVISOR_HOST` | `nuted-ia.dev` | Host do Supervisor |
| `P2P_SUPERVISOR_PORT` | `443` | Porta do Supervisor |
| `P2P_SUPERVISOR_SNI` | `nuted-ia.dev` | SNI da conexão TLS |

---

## 7. Tolerância a falhas do Master (continuidade de tarefas)

Requisito novo desta sprint, independente do Supervisor de Métricas: o Master deve garantir que uma tarefa em execução **nunca fica órfã** por falha do Worker que a executava.

- O Master já monitoriza Workers via heartbeat/handshake (Sprints 01/02). Esta sprint formaliza a reação à falha: se um Worker que tinha uma tarefa **pendente** (`pending_by_worker[wid]`) deixa de responder (timeout de heartbeat, conexão fechada inesperadamente, exceção no `handle_client`), o Master:
  1. Detecta a falha no `finally`/`except` de `handle_client` (ou no monitor de heartbeats).
  2. Recupera a tarefa associada em `pending_by_worker[wid]` (se existir).
  3. Re-enfileira a tarefa no início de `task_queue` (`appendleft`), marcando-a com contagem de re-tentativa.
  4. Remove o Worker falhado de `local_workers`/`worker_connections`/`borrowed_workers` (se aplicável) e incrementa `workers_failed`.
  5. Na próxima rodada de despacho, a tarefa é atribuída a **outro Worker disponível** (ocioso, local ou emprestado) através do mecanismo de despacho já existente — nenhum novo Worker é necessário, apenas a tarefa volta à fila e segue o fluxo normal de atribuição.
- Esta reatribuição é transparente para o cliente que originou a tarefa: do ponto de vista externo, a tarefa apenas demora mais a concluir, mas conclui.
- Métrica `WORKERS_FAILED` e `TASKS_FAILED` no relatório de métricas refletem essas ocorrências (Worker falhado é contado uma vez em `WORKERS_FAILED`; a tarefa, se reatribuída com sucesso, **não** entra em `TASKS_FAILED` — só entra se exceder o número máximo de re-tentativas).

---

## 8. Casos de teste

| ID | Cenário | Resultado Esperado |
|----|---------|-------------------|
| CT01 | `build_metrics_report()` com farm em estado conhecido | JSON com todas as chaves em MAIÚSCULAS, valores idênticos aos das estruturas internas |
| CT02 | `_metrics_reporter` dispara a cada `P2P_METRICS_INTERVAL_SEC` | Pelo menos N envios em N×intervalo segundos (monkeypatch de `_send_metrics_report`) |
| CT03 | Envio com Supervisor inacessível (`OSError`/`ssl.SSLError`) | Erro logado; thread não termina; próximo ciclo tenta de novo |
| CT04 | Envio nunca chama `recv` | Socket mock falha o teste se `recv` for invocado |
| CT05 | `P2P_METRICS_ENABLED=0` | `_metrics_reporter` não inicia thread / não envia nada |
| CT06 | Worker com tarefa pendente falha (conexão cai) | Tarefa volta a `task_queue`; `workers_failed` incrementado; Worker removido de `local_workers` |
| CT07 | Tarefa re-enfileirada após falha de Worker | Outro Worker ocioso disponível recebe a tarefa na rodada seguinte de despacho |
| CT08 | Worker emprestado falha durante execução de tarefa | Tarefa é reatribuída a outro Worker disponível (local ou emprestado); `notify_worker_returned` não é enviado indevidamente |
| CT09 | `NEIGHBORS[].LAST_HEARTBEAT` no relatório | Reflete o último heartbeat M2M observado de cada vizinho configurado em `NEIGHBOR_MASTERS` |

---

## 9. Fora de âmbito (YAGNI)

- Autenticação/handshake com o Supervisor além do TLS padrão, retry com backoff exponencial, dashboard local próprio, persistência histórica das métricas no Master, número máximo de re-tentativas configurável por tarefa (usa-se um valor fixo simples).

---

## Referências no repositório

- `servidor.py` — `build_metrics_report`, `_send_metrics_report`, `_metrics_reporter`, reatribuição de tarefas em falha de Worker
- `protocol.py` — (sem alterações de protocolo M2M/Worker; apenas eventual helper de timestamp ISO-8601 reutilizado)
- `tests/test_sprint4.py` — testes cobrindo CT01–CT09

---

*Documento produzido como especificação da Sprint 04; implementação: `docs/superpowers/plans/2026-06-17-sprint4-supervisor-metricas.md`.*
