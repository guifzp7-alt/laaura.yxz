# Sistema de Vendas VIP para Telegram com PIX SigilioPay

Projeto Python para vender assinaturas VIP pelo Telegram, gerar cobrancas PIX, receber webhook de confirmacao e liberar acesso automaticamente a um canal privado.

## Recursos

- Bot Telegram com `/start`, menu inline, verificacao de maioridade e selecao de planos.
- Planos VIP mensal, trimestral e anual criados automaticamente na primeira execucao.
- Geracao de pedido, QR Code e codigo PIX copia e cola.
- Webhook `POST /webhook/sigiliopay`.
- Protecao contra webhooks duplicados e pagamentos duplicados.
- Liberacao automatica por link de convite do Telegram.
- Scheduler diario para expirar assinaturas e remover acesso ao canal.
- Painel administrativo por comandos restritos a `ADMIN_IDS`.
- SQLAlchemy ORM com SQLite.
- Docker e Docker Compose.

## Estrutura

```text
project/
|-- bot.py
|-- webhook.py
|-- sigiliopay_client.py
|-- database.py
|-- models.py
|-- repositories.py
|-- telegram_service.py
|-- scheduler.py
|-- config.py
|-- logging_config.py
|-- requirements.txt
|-- Dockerfile
|-- docker-compose.yml
|-- .env.example
`-- logs/
```

## Variaveis de Ambiente

| Variavel | Descricao |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token do bot criado no BotFather. |
| `TELEGRAM_PRIVATE_CHANNEL_ID` | ID do canal privado, normalmente comecando com `-100`. |
| `ADMIN_IDS` | IDs Telegram autorizados a usar comandos administrativos, separados por virgula. |
| `DATABASE_URL` | URL do banco. Padrao: `sqlite:///database.sqlite3`. |
| `PAYMENT_PROVIDER` | Deve ficar como `sigiliopay`. |
| `SIGILIOPAY_API_BASE_URL` | URL base da API SigilioPay. |
| `SIGILIOPAY_API_KEY` | Chave/token da SigilioPay. |
| `SIGILIOPAY_WEBHOOK_SECRET` | Segredo de validacao do webhook, se a SigilioPay fornecer. |
| `SIGILIOPAY_WEBHOOK_HEADER` | Header onde a assinatura chega. Padrao: `X-SigilioPay-Signature`. |
| `PUBLIC_BASE_URL` | URL publica do servidor, usada para formar o webhook. |
| `WEBHOOK_PORT` | Porta do Flask/Gunicorn. |
| `PIX_EXPIRATION_MINUTES` | Expiracao da cobranca PIX. |
| `INVITE_LINK_EXPIRE_HOURS` | Validade do link de convite gerado. |
| `INVITE_LINK_MEMBER_LIMIT` | Limite de uso do link de convite. |
| `LOG_LEVEL` | Nivel de log. |

## SigilioPay

O arquivo `sigiliopay_client.py` e o ponto unico da integracao de pagamento.

Para finalizar o PIX da SigilioPay, preencha `create_pix_charge()` com o endpoint e payload oficiais da SigilioPay. O webhook esperado no servidor e:

```text
https://seu-dominio.com/webhook/sigiliopay
```

## Execucao Local

Em tres terminais separados:

```powershell
.\.venv\Scripts\python.exe webhook.py
```

```powershell
.\.venv\Scripts\python.exe bot.py
```

```powershell
.\.venv\Scripts\python.exe scheduler.py
```

## Comandos Administrativos

Somente usuarios em `ADMIN_IDS` podem usar:

- `/admin`
- `/clientes`
- `/pedidos`
- `/assinaturas`
- `/receita`
- `/addplano Nome | descricao | preco | dias`
- `/removerplano ID`
