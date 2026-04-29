# Sprint 2: Comunicação de Tarefas e Apresentação de Workers — Design (Brainstorming)

**Data:** 2026-04-29  
**Estado:** Especificação aprovada para implementação (ver plano em `docs/superpowers/plans/`).

---

## 1. Contexto

Sistema de balanceamento P2P sobre **TCP** com mensagens **JSON** terminadas obrigatoriamente em **`\n`**. Código atual: `servidor.py` (Master) com ciclo **HEARTBEAT**; `client.py` (Worker) envia heartbeat periódico. Esta sprint substitui ou estende esse fluxo pelo **ciclo completo de tarefa** Master ↔ Worker.

---

## 2. Decisões de desenho (brainstorming)

| Decisão | Escolha |
|--------|---------|
| Modelo de conexão | **B** — **conexões curtas**: 1ª conexão pedido/apresentação + resposta `QUERY` ou `NO_TASK`; 2ª conexão relatório de status + `ACK`. |
| Comportamento `NO_TASK` | **Intervalo fixo de 30 s** antes de nova tentativa (alinhado ao ritmo do worker atual). |
| Arquitetura Master | **Fila FIFO + mapa pendente por `WORKER_UUID`** protegido por lock; ao enviar `QUERY`, regista atribuição até `ACK` / validação de `STATUS`. |
| Concorrência | Manter **thread por conexão** + **`threading.Lock`** na estrutura partilhada (encaixa no `servidor.py` atual). |

---

## 3. Protocolo de mensagens

### 3.1 Regras globais

- **Framing:** uma mensagem = um objeto JSON + `\n`.
- **Parsing estrito (Master):** **ignorar** chaves JSON desconhecidas; **falhar** (fechar conexão ou responder erro de protocolo — ver §5) se **faltar qualquer campo obrigatório** para o tipo de mensagem esperado nesta fase.
- **Case sensitivity:** valores de controlo **somente em maiúsculas:** `ALIVE`, `QUERY`, `NO_TASK`, `OK`, `NOK`, `ACK`.

### 3.2 Worker → Master (1ª conexão — apresentação)

**Obrigatórios:**

- `"WORKER": "ALIVE"`
- `"WORKER_UUID": "<string>"` — identificador estável do worker nesta sessão de vida útil.

**Opcional:**

- `"SERVER_UUID": "<string>"` — quando o worker é “emprestado” de outro Master; o Master pode registar em log e ignorar para a lógica de fila se não for usado na sprint.

**Resposta Master:**

- Se existir tarefa na fila: `{"TASK": "QUERY", "USER": "<string>"}` e **registar pendente** para esse `WORKER_UUID`.
- Se fila vazia: `{"TASK": "NO_TASK"}` (sem registo pendente).

### 3.3 Worker → Master (2ª conexão — resultado)

**Obrigatórios:**

- `"STATUS": "OK"` ou `"STATUS": "NOK"`
- `"TASK": "QUERY"` — deve coincidir com a tarefa atribuída em memória para este `WORKER_UUID`.
- `"WORKER_UUID": "<string>"` — igual ao da apresentação.

**Resposta Master:**

- Se validação OK: **log** (worker, resultado, contexto útil da tarefa) e `{"STATUS": "ACK"}`; **remover** pendente.
- Se validação falhar: ver §5 (não enviar `ACK` de confirmação válida sem critério claro — recomenda-se fechar ou mensagem de erro explícita; implementação deve ser **determinística** e documentada no plano).

### 3.4 Processamento no Worker

- Após receber `QUERY` na 1ª conexão, **fechar conexão**, **simular trabalho** (sleep pseudoaleatório ou cálculo local).
- Abrir **nova conexão** e enviar o JSON de `STATUS`.
- Após `ACK`, considerar ciclo concluído; pode iniciar novo ciclo (1ª conexão) para próxima tarefa.

### 3.5 Timeout (Worker)

- Em **cada** conexão, ao aguardar a **primeira** linha/resposta completa do Master: **máximo 5 s**. Se expirar: tratar como falha, fechar socket e **tentar reconectar** conforme política simples (ex.: retry com backoff leve ou imediato — o plano de implementação fixa o detalhe para evitar loops agressivos).

---

## 4. Master — fila e estado

- **Fila:** estrutura em memória (lista ou `collections.deque`) de itens de tarefa; mínimo para a sprint: campo `USER` (string) por item; fila inicial pode ser preenchida por código de arranque, CLI ou constantes — ver plano.
- **Pendentes:** `dict[WORKER_UUID, { "TASK": "QUERY", "USER": "..." }]` (ou estrutura equivalente).
- **Invariantes:**
  - Só existe entrada pendente se o Master enviou `QUERY` a esse worker e ainda não recebeu `STATUS` válido + processou `ACK`.
  - `NO_TASK` **não** cria pendente.
- **Concorrência:** todo acesso à fila e ao dicionário pendente sob **um lock**.

---

## 5. Tratamento de erros (resumo)

- **JSON inválido** ou linha incompleta além do timeout: descartar ou fechar; Master deve **logar**; Worker usa timeout de 5 s.
- **Campos obrigatórios em falta:** Master **não** tratar como sucesso silencioso.
- **`STATUS` sem pendente correspondente** ou `TASK`/`WORKER_UUID` incoerente: **não** confirmar com `ACK` como sucesso; fechar ou protocolo de erro acordado no plano.
- **`NOK`:** mesmo fluxo de confirmação que `OK` após validação (tarefa considerada “fechada” do ponto de vista do worker; política de re-enfileiramento **fora do âmbito** salvo definição explícita no plano — default: **não** re-enfileirar automaticamente).

---

## 6. Testes e critérios de sucesso

- Teste(s) de integração ou testes com sockets em porta local: ciclo feliz **QUERY → OK/NOK → ACK**.
- `NO_TASK` seguido de comportamento do worker (espera 30 s) pode ser testado com clock fake ou intervalo reduzido em modo teste se o plano introduzir isso.
- Master ignora campos extra no JSON e falha sem campos obrigatórios.
- Valores de controlo recusados se não forem exatamente maiúsculos conforme spec.

---

## 7. Fora de âmbito (YAGNI)

- Persistência da fila, multi-master, criptografia, formato rico de `USER` além de string, reatribuição automática de tarefas falhadas.

---

## Referências no repositório

- `servidor.py` — Master  
- `client.py` — Worker  

---

*Documento produzido pelo fluxo de brainstorming; implementação: `docs/superpowers/plans/2026-04-29-sprint2-comunicacao-tarefas-workers.md`.*
