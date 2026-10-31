# Colosys Lamp Server

Back-end do **Colosys Sentinel**, implementado com FastAPI. A API fornece autenticação e gerenciamento de usuários, cadastro e gerenciamento de dispositivos, leitura do contexto FIWARE, histórico de medições, eventos em tempo real e automação relacionada aos limites configurados.

## Componentes

O `docker-compose.yml` da branch `master` define os seguintes serviços:

- **API:** aplicação FastAPI/Uvicorn, publicada na porta `8000`.
- **Keyrock:** gerenciamento de identidade, publicado na porta `3005`.
- **MySQL 5.7:** banco utilizado pelo Keyrock.
- **Volumes Docker:** persistência dos dados MySQL e das credenciais OAuth geradas pela API.
- **Rede externa FIWARE:** ligação com Orion, IoT Agent e STH-Comet já executados pelo ambiente FIWARE.

A API utiliza variáveis de ambiente para configurar Keyrock, FIWARE, MQTT, CORS, cookies, notificações e histórico.

## Requisitos

- Docker Engine e Docker Compose v2.
- A stack FIWARE executada antes da API.
- Acesso à rede Docker FIWARE (branch `master`) ou acesso de rede aos serviços FIWARE publicados (branch `deploy-local`).
- Endereços e portas liberados conforme a topologia escolhida.

## Escolha da branch

### `master` — API e FIWARE no mesmo servidor/rede Docker

Use esta branch quando o back-end deve se conectar aos serviços FIWARE pela rede Docker externa compartilhada. O `docker-compose.yml` utiliza por padrão a rede externa `fiware_default` e nomes de serviço como `orion`, `iot-agent` e `fiware-sth-comet`.

### `deploy-local` — FIWARE em outro servidor

Use esta branch quando o back-end é executado em uma máquina e a stack FIWARE está em outro servidor. A configuração utiliza `FIWARE_HOST` para alcançar as portas publicadas do FIWARE e exige `NOTIFY_URL`, que precisa ser acessível **a partir do servidor FIWARE** para que Orion envie notificações à API.

A branch `deploy-local` também configura o acesso a `host.docker.internal` para cenários em que a API precisa alcançar serviços publicados no próprio host. Consulte o `docker-compose.yml` dessa branch antes de aplicar as variáveis no seu ambiente.

## Instalação — branch `master`

### 1. Inicie a stack FIWARE

Na pasta do projeto FIWARE, inicie os serviços usando o arquivo Compose correspondente ao seu ambiente. Por exemplo, se a stack já estiver configurada nessa pasta:

```bash
docker compose up -d
```

Confira os nomes das redes:

```bash
docker network ls
```

O arquivo da branch `master` espera por padrão a rede externa `fiware_default`. Se a rede tiver outro nome, ele pode ser configurado com `FIWARE_NETWORK` no `.env`.

### 2. Configure as variáveis de ambiente

Clone o repositório:

```bash
git clone https://github.com/MurilloFonseca/colosys-lamp-server.git
cd colosys-lamp-server
cp .env.example .env
```

Edite `.env`. No mínimo, substitua as senhas de exemplo e confira `FIWARE_NETWORK`, `CORS_ORIGINS`, `MQTT_HOST` e `MQTT_PORT`.

Exemplo de parâmetros relevantes:

```dotenv
MYSQL_ROOT_PASSWORD=troque-esta-senha
KEYROCK_ADMIN_EMAIL=admin@seu-dominio.com
KEYROCK_ADMIN_PASSWORD=troque-esta-senha
CORS_ORIGINS=http://localhost:5173
COOKIE_SECURE=false
FIWARE_NETWORK=fiware_default
MQTT_HOST=localhost
MQTT_PORT=1883
```

Os valores acima são exemplos de formato. Ajuste-os à rede, ao endereço do broker MQTT e à origem real do front-end. Não use as senhas de exemplo em produção.

### 3. Inicie o back-end

```bash
docker compose up -d --build
```

Acompanhe os logs:

```bash
docker compose logs -f api
```

A API publica a documentação interativa em `http://localhost:8000/docs` e o endpoint de saúde em `http://localhost:8000/health`, quando acessados a partir do host onde o serviço está disponível.

## Configuração — branch `deploy-local`

Selecione a branch antes de iniciar:

```bash
git switch deploy-local
cp .env.example .env
```

Configure no `.env` os endereços corretos para o ambiente distribuído:

```dotenv
FIWARE_HOST=ENDERECO_DO_SERVIDOR_FIWARE
NOTIFY_URL=http://ENDERECO_ACESSIVEL_PARA_FIWARE:8000/internal/orion/notify
CORS_ORIGINS=https://SEU-FRONTEND-VERCEL
COOKIE_SECURE=true
MQTT_HOST=ENDERECO_DO_BROKER_MQTT
MQTT_PORT=1883
```

Substitua todos os valores de exemplo por endereços reais. `FIWARE_HOST` deve permitir que a API alcance as portas publicadas do Orion (`1026`), IoT Agent (`4041`), STH-Comet (`8666`) e broker MQTT conforme o ambiente. `NOTIFY_URL` deve ser acessível do lado do servidor FIWARE; se a API estiver atrás de NAT, pode ser necessário VPN ou túnel. Não exponha a API de notificação sem avaliar a segurança e manter o token de notificação protegido.

Depois de configurar o `.env`:

```bash
docker compose up -d --build
docker compose logs -f api
```

Confirme também no ambiente FIWARE que o callback de notificação configurado pelo back-end pode ser alcançado pelo Orion.

## Variáveis de ambiente importantes

As variáveis disponíveis dependem da branch. Consulte o `.env.example` e o `docker-compose.yml` da branch escolhida.

| Variável | Finalidade |
|---|---|
| `MYSQL_ROOT_PASSWORD` | Senha do usuário root do MySQL usado pelo Keyrock. |
| `KEYROCK_ADMIN_EMAIL` / `KEYROCK_ADMIN_PASSWORD` | Credenciais administrativas iniciais do Keyrock. |
| `CORS_ORIGINS` | Origens de navegador autorizadas a chamar a API com credenciais. |
| `COOKIE_SECURE` | Define se o cookie de autenticação exige HTTPS. |
| `FIWARE_NETWORK` | Nome da rede Docker externa FIWARE, na branch `master`. |
| `FIWARE_HOST` | Host do servidor FIWARE, na branch `deploy-local`. |
| `ORION_URL` / `IOTA_URL` | Endereços do Orion e do IoT Agent. |
| `STH_URL` | Endereço do STH-Comet usado para consultar histórico. |
| `NOTIFY_URL` / `NOTIFY_TOKEN` | Callback de notificações do Orion e segredo compartilhado. |
| `FIWARE_SERVICE` / `FIWARE_SERVICEPATH` | Serviço e caminho de serviço usados no contexto FIWARE. |
| `IOTA_API_KEY` | Chave usada nos tópicos MQTT do IoT Agent; o padrão do projeto é `TEF`. |
| `MQTT_HOST` / `MQTT_PORT` | Endereço do broker informado ao dispositivo. |
| `AUTOMATION_RETRY_SECONDS` | Intervalo para repetir comandos de automação. |

Não publique o arquivo `.env`, tokens ou senhas. As credenciais de administrador do Keyrock e a senha do MySQL são aplicadas quando os respectivos dados persistentes são criados inicialmente. Alterar as variáveis depois não altera automaticamente as credenciais existentes.

## API e rotas principais

As rotas identificadas no código incluem:

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/health` | Estado da API e disponibilidade de FIWARE/histórico. |
| `POST` | `/api/users` | Cadastro de usuário. |
| `POST` | `/api/auth/login` | Autenticação e criação de cookie de sessão. |
| `POST` | `/api/auth/logout` | Encerramento da sessão. |
| `GET` | `/api/me` | Retorna o usuário autenticado. |
| `POST` | `/api/lamps` | Cadastra uma lâmpada/dispositivo. |
| `GET` | `/api/lamps` | Lista os dispositivos do usuário autenticado. |
| `GET` | `/api/lamps/stream` | Fluxo de eventos em tempo real (Server-Sent Events). |
| `GET` | `/api/lamps/{device_id}` | Consulta um dispositivo. |
| `DELETE` | `/api/lamps/{device_id}` | Exclui o dispositivo e tenta remover seu histórico. |
| `GET` | `/api/lamps/{device_id}/history` | Consulta medições históricas. |
| `GET` | `/api/lamps/{device_id}/thresholds` | Consulta os limites configurados. |
| `PUT` | `/api/lamps/{device_id}/thresholds` | Atualiza os limites e aplica a lógica de automação. |

A rota interna `/internal/orion/notify` recebe notificações do Orion e é protegida por token. Ela não deve ser tratada como uma rota pública comum.

A documentação OpenAPI pode ser acessada em `/docs` quando a API está em execução.

## Integração e funcionamento

- A aplicação usa Keyrock para identidade e autenticação.
- A API configura o contexto e as assinaturas necessárias no FIWARE durante a inicialização.
- As leituras atuais são distribuídas ao front-end por Server-Sent Events.
- O histórico é consultado no STH-Comet.
- A automação avalia as leituras e os limites configurados, podendo enviar comandos ao dispositivo.

## Diagnóstico

Verifique os logs da API:

```bash
docker compose logs -f api
```

Confira o estado dos containers:

```bash
docker compose ps
```

Se o serviço não ficar pronto, confirme:

1. Keyrock e MySQL estão saudáveis.
2. A stack FIWARE está ativa e os endereços configurados são acessíveis a partir do container da API.
3. Na branch `master`, a rede Docker externa informada em `FIWARE_NETWORK` existe.
4. Na branch `deploy-local`, `FIWARE_HOST` está correto e `NOTIFY_URL` é acessível a partir do servidor FIWARE.
5. `CORS_ORIGINS` contém a origem real do front-end e o uso de cookies está compatível com HTTPS.

## Repositórios relacionados

- **Projeto principal e diagrama de arquitetura:** https://github.com/MurilloFonseca/colosys-sentinel
- **Front-end:** https://github.com/MurilloFonseca/colosys-lamp-client
- **Simulação Wokwi:** https://wokwi.com/projects/465199340265498625
