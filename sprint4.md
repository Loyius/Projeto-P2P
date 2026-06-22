## SPRINT 4 - APRESENTAÇÃO FINAL
APRESENTAÇÃO MATUTINO E NOTURNO: 15/06/2026 (TURMA B e
## UN)
## APRESENTAÇÃO MATUTINO: 11/06/2025 (TURMA A)

PROVA MATUTINO E NOTURNO: 22/06/2026 (TURMA B e UN)
## PROVA MATUTINO: 18/06/2026 (TURMA A)

## SCHEDULE DA SIMULAÇÃO:

ATENÇÃO: A SIMULAÇÃO CONSIDERA QUE AS RNs ESTÃO DE ACORDO COM O
## ESPECIFICADO NO PROJETO E DEVEM ESTAR EM PLENO FUNCIONAMENTO.

A comunicação com o supervisor será por socket TCP na porta 443 a cada 10s
Os SERVERS não devem aguardar mensagem (RECV) com retorno, apenas
executar o SEND.
## DASHBOARD PARA TESTE ABAIXO

## PAYLOAD:
## {
## "server_uuid": "master_1",
## "hostname": "master_1.A.farm.local",
## "role": "master",
## "task": "performance_report",
"timestamp": "2026-06-08T12:34:56Z",
## "message_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
## "payload_version": "sprint4-monitor",

## "performance": {
## "system": {
## "uptime_seconds": 12345,
## "load_average_1m": 3.20,
## "load_average_5m": 2.50,
## "cpu": {
## "usage_percent": 85.42,
## "count_logical": 8,
## "count_physical": 4
## },
## "memory": {
## "total_mb": 16384,
## "available_mb": 8192,
## "percent_used": 62.18,
## "memory_used": 8000
## },



## "disk": {
## "total_gb": 512.0,
## "free_gb": 250.0,
## "percent_used": 45.0
## }
## },

## "farm_state": {
## "workers": {
## "total_registered": 6,
## "workers_utilization": 4,
## "workers_alive": 6,
## "workers_idle": 2,
## "workers_borrowed": 1,
## "workers_received": 1,
## "workers_failed": 0,
## "workers_home": 5,
## "workers_available_capacity": 2,

## "borrowed_workers": [
## { "direction": "out", "peer_uuid": "michel_2" },
## { "direction": "in",  "peer_uuid": "michel_2" }
## ]
## },
## "tasks": {
## "tasks_pending": 42,
## "tasks_running": 4,
## "tasks_completed": 150,
## "tasks_failed": 3,
## "oldest_task_age_s": 312
## }
## },

## "config_thresholds": {
## "max_task": 100,
## "warn_cpu_percent": 85,
## "warn_memory_percent": 85,
## "release_task": 60
## },

## "neighbors": [
## {
## "server_uuid": "michel_2",
## "status": "available",
"last_heartbeat": "2026-06-08T12:34:56Z"
## }
## ]
## }
## }




Uso do Supervisor de Métricas do Cluster
Foi implementado um Supervisor de Métricas para monitorar, em tempo real, os projetos
desenvolvidos na disciplina. Esse supervisor recebe relatórios de desempenho via TCP e
apresenta as informações em um dashboard web acessível pelo navegador.

Descrição dos itens do payload:
## Campo Tipo Descrição
server_uuid string Identificador único do servidor no cluster (ex:
## "master_1")
hostname string Nome DNS do nó (ex: "master_1.A.farm.local")
role string Papel do nó no cluster ("master")
task string Tipo de relatório enviado ("performance_report")
timestamp string
## (ISO-8601)
Momento da coleta no formato
## YYYY-MM-DDTHH:MM:SSZ
message_id string
## (UUID)
Identificador único da mensagem
payload_version string Versão do schema do payload (ex:
## "sprint4-monitor-v2")
performance.system
## Campo Tipo Descrição
uptime_seconds int Tempo de atividade do nó em segundos
load_average_1m float Média de load da CPU nos últimos 1 minuto
load_average_5m float Média de load da CPU nos últimos 5 minutos
cpu.usage_percent float Percentual de uso da CPU (0–100)



cpu.count_logical int Número de CPUs lógicas (threads)
cpu.count_physical int Número de CPUs físicas (cores)
memory.total_mb int Memória RAM total em MB
memory.available_mb int Memória RAM disponível em MB
memory.percent_used float Percentual de uso da memória (0–100)
memory.memory_used int Memória RAM utilizada em MB
disk.total_gb float Espaço em disco total em GB
disk.free_gb float Espaço em disco livre em GB
disk.percent_used float Percentual de uso do disco (0–100)
performance.farm_state.workers
## Campo Tipo Descrição
total_registered int Total de workers atualmente registrados no nó
workers_utilization int Workers ocupados no momento (executando
tarefas)
workers_alive int Workers considerados vivos/respondendo
workers_idle int Workers ociosos disponíveis para novas tarefas
workers_borrowed int Workers que este nó emprestou para outros nós
workers_received int Workers que este nó recebeu emprestados de
outros nós



workers_failed int Workers que falharam
workers_home int Workers nativos do servidor (sem empréstimos)
workers_available_capa
city
int Capacidade ociosa total (= workers_idle)
borrowed_workers array Lista de workers emprestados com
origem/destino
borrowed_workers[]
## Campo Tipo Descrição
direction string Direção do empréstimo: "out" (emprestou para
outro) ou "in" (recebeu de outro)
peer_uuid string server_uuid do nó na outra ponta do empréstimo
performance.farm_state.tasks
## Campo Tipo Descrição
tasks_pending int Tarefas aguardando execução
tasks_running int Tarefas em execução no momento
tasks_completed int Total de tarefas concluídas
tasks_failed int Total de tarefas com falha
oldest_task_age_s int Idade da tarefa pendente mais antiga (segundos)
performance.config_thresholds
## Campo Tipo Descrição
max_task int Número máximo de tarefas antes de considerar o
nó saturado



warn_cpu_percent int Percentual de CPU para disparar alerta (ex: 85)
warn_memory_percent int Percentual de memória para disparar alerta (ex:
## 85)
release_task int Threshold para liberar workers emprestados
performance.neighbors[]
## Campo Tipo Descrição
server_uuid string Identificador do nó vizinho
status string Status do vizinho: "available" ou "unavailable"
last_heartbeat string
## (ISO-8601)
Timestamp do último heartbeat recebido do vizinho
Como enviar dados para o Supervisor
Para testar o seu projeto, você deve:
- Enviar os dados de métricas em formato JSON, seguindo o template definido acima.
- Abrir uma conexão TLS sobre TCP com o supervisor.
- Enviar o JSON pela conexão estabelecida.
- Não utilizar HTTP para esse envio.
- Não aguardar resposta da aplicação após o envio. O cliente deve apenas conectar,
enviar os dados e encerrar a conexão.
Parâmetros da conexão:
● Host: nuted-ia.dev
## ● Porta: 443
● Protocolo: TLS sobre TCP
● SNI: nuted-ia.dev
Exemplo de configuração no código:
TCP_SOCKET_HOST = "nuted-ia.dev"
## TCP_SOCKET_PORT = 443
TCP_SOCKET_TLS = True
TCP_SOCKET_SNI = "nuted-ia.dev"



## Importante:
● Não use caminhos como /supervisor/colector ou /supervisor no socket TCP.
● Em conexões TCP, o endpoint é definido apenas por host e porta.
● Não use bibliotecas HTTP para enviar o payload.
● O cliente deve apenas abrir a conexão, enviar o JSON e finalizar.
● Os servers não devem aguardar mensagem de retorno com recv.
Como visualizar o Dashboard
Todas as métricas enviadas pelos projetos são agregadas e exibidas em um painel visual
interativo.
Para acompanhar o comportamento do cluster, acesse:
## ●
URL do Dashboard: https://nuted-ia.dev/supervisor/dashboard/
Ao abrir esse endereço no navegador, você poderá:
● Visualizar a topologia dos nós, servers e workers;
● Acompanhar o consumo de CPU, memória, disco e filas de tarefas por servidor;
● Ver o estado dos workers, incluindo ativos, ociosos, emprestados e com falha;
● Identificar gargalos e nós sobrecarregados em tempo real.
Cada vez que seu projeto enviar novas métricas pela conexão TLS/TCP configurada, o
dashboard será atualizado automaticamente, permitindo a validação e depuração do
comportamento distribuído da sua aplicação.
Observação sobre os identificadores dos nós
Os valores michel_1 e michel_2 representam identificadores de farms em execução no
ambiente do professor e devem ser usados no campo server_uuid do payload. Esses valores
não fazem parte do endereço de conexão com o supervisor.
## EXEMPLO DO DASHBOARD




