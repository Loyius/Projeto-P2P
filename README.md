# Projeto P2P — Sistema Distribuído Master-Worker com Federação

---

## Pré-requisitos

- **Python 3.8+** instalado e disponível no PATH.
- **pip** para instalar dependências.

Verifique sua versão:

```bash
python --version
pip --version
```
1. Definir o IP do Master (servidor principal)
No arquivo servidor.py, altere o valor abaixo para o IP da sua máquina (onde o Master estará rodando):

HOST = os.environ.get("P2P_HOST", "192.168.100.87")

2. Definir o IP do(s) nó(s) vizinho(s) (outros Masters na rede)
Ainda em servidor.py, configure os endereços dos outros Masters aos quais sua máquina irá se conectar:

_RAW_NEIGHBORS = os.environ.get("P2P_NEIGHBOR_MASTERS", "192.168.100.97:8000").strip()
NEIGHBOR_MASTERS: list[dict] = []

3. Configurar o Worker local (cliente)
No arquivo client.py, o IP do Worker deve ser o mesmo IP definido para o Master da sua máquina:

HOST = os.environ.get("P2P_HOST", "192.168.100.87")

---

## Instalação

Clone o repositório e instale as dependências:

```bash
git clone <url-do-repositorio>
cd Projeto-P2P
pip install -r requirements.txt
```

As dependências instaladas são:

| Pacote     | Uso                                              |
|------------|--------------------------------------------------|
| `schedule` | Agendamento de tarefas do tipo `SCHEDULE` no Worker |
| `pytest`   | Execução dos testes automatizados                |

Todos os demais módulos usados (`socket`, `threading`, `json`, `uuid`, `logging`, etc.) fazem parte da biblioteca padrão do Python e não precisam ser instalados.

---

## Como Rodar

### Servidor (Master)

Inicia o servidor Master que aguarda conexões de Workers e de outros Masters:

```bash
python servidor.py
```

Por padrão, o servidor escuta em `127.0.0.1:65432`. Para personalizar, use variáveis de ambiente (ver seção [Variáveis de Ambiente](#variáveis-de-ambiente)).

Exemplo com configuração customizada (PowerShell):

```powershell
$env:P2P_HOST = "0.0.0.0"
$env:P2P_PORT = "8000"
$env:P2P_SERVER_UUID = "MASTER_A"
python servidor.py
```

Exemplo com configuração customizada (Linux/macOS):

```bash
P2P_HOST=0.0.0.0 P2P_PORT=8000 P2P_SERVER_UUID=MASTER_A python servidor.py
```

---

### Cliente (Worker)

Inicia um Worker que se conecta ao Master e fica aguardando tarefas:

```bash
python client.py
```

Por padrão conecta em `127.0.0.1:65432`. Para conectar a um Master diferente:

```powershell
$env:P2P_HOST = "192.168.1.10"
$env:P2P_PORT = "8000"
python client.py
```

```bash
P2P_HOST=192.168.1.10 P2P_PORT=8000 python client.py
```

Você pode rodar múltiplos Workers em terminais separados — cada um se registra individualmente no Master.

