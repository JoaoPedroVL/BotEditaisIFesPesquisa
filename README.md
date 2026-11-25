# Monitor de Editais para ONGs

Robô em Python que varre diariamente sites de órgãos de fomento, identifica
editais abertos, usa IA para ler/resumir e verificar se ONGs podem participar e
envia o resultado por mensagem. A entrega pode ser feita por **Telegram**
(chat privado com o bot) ou **e-mail** (SMTP), sem depender de API de WhatsApp.

```
config.yaml ──> scrapers ──> extractor ──> database (SQLite)
                                              │
                                              ▼
                                         llm_client (NVIDIA + fallback)
                                              │
                                              ▼
                                         notifier (e-mail/Telegram/WhatsApp)
```

## Status

| Etapa | Situação |
|---|---|
| Estrutura, configuração e logs | ✅ |
| Scrapers CNPq, FAPES, CAPES e Sebrae | ✅ testados ao vivo em 24/11/2026 |
| Extração HTML + PDF (`pdfplumber`) | ✅ |
| Deduplicação por link e hash (SQLite) | ✅ |
| Análise por IA com fallback entre modelos | ✅ |
| Filtro final (`sim`/`incerto`) e mensagens | ✅ |
| Telegram funcional / e-mail funcional / WhatsApp preparado | ✅ |
| `--dry-run`, `--teste-fonte`, `--agendar`, `--somente-envio` | ✅ |
| Testes automatizados | ✅ 36 testes |

O primeiro teste real em `--dry-run` rodou as quatro fontes e produziu JSON
válido em todas. O edital do Sebrae foi classificado como `nao` e corretamente
**não** enviado.

## Requisitos

- Python 3.11+ (testado com 3.12)
- Chave da NVIDIA: <https://build.nvidia.com> → *Get API Key*
- Um canal de entrega: bot do Telegram **ou** conta de e-mail com SMTP

## Instalação

```bash
cd /home/joao/projeto-editais
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Só é necessário instalar o navegador do Playwright se alguma fonte passar a
carregar o conteúdo via JavaScript:

```bash
playwright install chromium
```

## Configurar segredos

O `.env` já existe (permissão `600`) e está no `.gitignore`. Preencha:

```dotenv
NVIDIA_API_KEY=nvapi-...

# Canal Telegram (opcional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Canal e-mail (opcional)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=
EMAIL_PASSWORD=
EMAIL_DESTINO=
EMAIL_REMETENTE=
EMAIL_SSL=0
EMAIL_TLS=1

# WhatsApp Cloud API oficial (opcional)
WHATSAPP_TOKEN=
WHATSAPP_PHONE_ID=
WHATSAPP_DESTINO=
```

Nunca coloque chaves no `config.yaml`, no código ou no Git.

## Canais de entrega

Você escolhe **um** canal em `config.yaml`:

```yaml
notificacao:
  canal: "email"    # "email", "telegram" ou "whatsapp"
  formato: "resumo" # "resumo" = um envio/dia; "por_edital" = um por edital
```

Com `formato: "resumo"`, todos os editais elegíveis da execução viram **uma
única mensagem** (ou um único e-mail), com cabeçalho de contagem e um bloco por
edital. Se nenhum edital for elegível, **nada é enviado**. Se o envio do resumo
falhar, todos os editais continuam pendentes para a próxima execução.

Com `formato: "por_edital"`, cada edital gera uma mensagem separada (útil no
Telegram, onde cada edital aparece como conversa própria).

### E-mail (recomendado para "só para mim", sem API de WhatsApp)

Entrega na sua própria caixa de entrada, com histórico e assunto pelo título do
edital. Não depende de aprovação da Meta.

**Gmail** (passo a passo):

1. Ative a verificação em duas etapas na conta Google.
2. Acesse <https://myaccount.google.com/apppasswords> e crie uma **senha de app**.
3. Preencha o `.env`:

```dotenv
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=seuemail@gmail.com
EMAIL_PASSWORD=abcd efgh ijkl mnop   # senha de app (16 letras)
EMAIL_DESTINO=seuemail@gmail.com
EMAIL_DESTINO_IFES=outro@gmail.com
EMAIL_REMETENTE=seuemail@gmail.com
EMAIL_SSL=0
EMAIL_TLS=1
```

- Porta `587` + `EMAIL_TLS=1` (STARTTLS) é o padrão.
- Para porta `465`, use `EMAIL_SSL=1`.
- `EMAIL_DESTINO` recebe o resumo de ONGs; `EMAIL_DESTINO_IFES`, o de IFES.
- Cada variável aceita **vários destinatários** separados por vírgula, por exemplo:
  `EMAIL_DESTINO=wizardbr41@gmail.com,homgomes@gmail.com`.
- Outlook/Zoho/outros: troque `EMAIL_HOST`/`EMAIL_PORT` conforme o provedor.
- A **senha normal do Gmail não funciona**; é obrigatório usar a senha de app.

### Telegram (instantâneo, chat privado)

1. Crie o bot com o `@BotFather` e copie o token.
2. Envie `/start` para o seu próprio bot (isso abre o chat privado).
3. Pegue seu `chat_id` com o `@userinfobot` ou em
   `https://api.telegram.org/bot<TOKEN>/getUpdates`.
4. Preencha `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` no `.env`.

As mensagens chegam na conversa privada entre você e o bot — nada é publicado.

### WhatsApp

O canal `whatsapp` usa a **Cloud API oficial** da Meta e exige conta business,
número verificado e (fora da janela de 24h) templates aprovados.

> ⚠️ **Não use automação não oficial** (WhatsApp Web, Baileys, Evolution API
> etc.) para o número pessoal. Isso viola os Termos do WhatsApp e pode resultar
> em **banimento do número**. Para uso pessoal, prefira Telegram ou e-mail.

### Testar o canal escolhido

```bash
.venv/bin/python testar_notificacao.py              # canal do config.yaml
.venv/bin/python testar_notificacao.py --canal email
```

O script envia uma mensagem de exemplo e informa se o canal confirmou a entrega.
Ele não faz coleta nem altera o banco. Se as credenciais estiverem ausentes, a
mensagem de erro indica qual variável falta.

## Configuração (`config.yaml`)

| Seção | Para que serve |
|---|---|
| `ia.modelos` | ordem de fallback dos modelos |
| `ia.max_tokens` | espaço para o JSON (modelos de raciocínio gastam tokens pensando) |
| `ia.pausa_entre_chamadas` | limite de requisições (1,6 s ≈ 37 req/min) |
| `coleta.fontes` | fontes ativas, classe e URL |
| `coleta.palavras_chave` | pré-filtro de títulos |
| `coleta.max_itens_por_fonte` | teto por fonte em cada execução |
| `extracao.limite_caracteres` | tamanho do texto enviado à IA |
| `notificacao.canal` | `email`, `telegram` ou `whatsapp` |
| `notificacao.formato` | `resumo` (um envio por execução) ou `por_edital` |
| `agendamento.cron` | expressão cron do modo `--agendar` (ex.: `0 6 * * 1,4`) |
| `agendamento.horario` | horário do modo `--agendar` (usado se `cron` não existir) |

### Quanto é lido e quanto é enviado

- Até `coleta.max_itens_por_fonte` (padrão **50**) por fonte, em 4 fontes.
- O pré-filtro por palavras-chave e a deduplicação reduzem bastante esse número.
- Só são enviados editais com `ong_pode_participar` = `sim` ou `incerto`.
- No formato `resumo`, isso vira **no máximo um e-mail por execução**.

### Modelos validados no catálogo (24/11/2026)

1. `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` — melhor custo/qualidade;
2. `nvidia/nemotron-3.5-super-vl-120b-a12b` — reserva mais forte;
3. `nvidia/nemotron-3.5-bolt-e4b` — rápido, sem raciocínio oculto.

Os nomes do catálogo mudam. Para conferir:

```bash
.venv/bin/python testar_llm.py --listar-modelos
```

O script marca `NÃO ENCONTRADO` se algum modelo do `config.yaml` saiu do ar.

## Uso

Sempre a partir da raiz do projeto:

```bash
# testa a IA isoladamente (não envia nada)
.venv/bin/python testar_llm.py

# testa o canal de entrega (e-mail/Telegram) com uma mensagem de exemplo
.venv/bin/python testar_notificacao.py

# coleta e analisa uma única fonte, imprimindo as mensagens
.venv/bin/python main.py --dry-run --teste-fonte cnpq --limite-itens 1

# testa várias fontes
.venv/bin/python main.py --dry-run --teste-fonte cnpq --teste-fonte fapes --limite-itens 2

# simulação completa (pode demorar: baixa páginas/PDFs e chama a IA)
.venv/bin/python main.py --dry-run

# execução real (envia pelo canal configurado)
.venv/bin/python main.py

# reenvia o que já está analisado no banco (sem coletar nem chamar a IA)
.venv/bin/python main.py --somente-envio

# executa nos dias/horários do agendamento.cron e fica em primeiro plano
.venv/bin/python main.py --agendar
```

O `--somente-envio` é útil depois de corrigir `EMAIL_DESTINO`/`EMAIL_DESTINO_IFES`:
ele monta os resumos com as análises já salvas e dispara os e-mails pendentes.

### O que o `--dry-run` faz

Faz coleta, extração, deduplicação e análise, mas **imprime** a mensagem em vez
de enviar. As análises ficam salvas no banco; o envio permanece pendente. Se
quiser começar do zero depois dos testes:

```bash
rm data/editais.db
```

## Agendamento

### Opção A: cron (recomendado em servidor)

```bash
crontab -e
```

```cron
0 7 * * * cd /home/joao/projeto-editais && .venv/bin/python main.py >> logs/cron.log 2>&1
```

### Opção B: APScheduler embutido

```bash
.venv/bin/python main.py --agendar
```

O horário vem de `agendamento.horario`. Use **uma** das opções; rodar cron e
`--agendar` ao mesmo tempo pode duplicar execuções.

## Como funciona a deduplicação

- O link é único no SQLite.
- `hash_conteudo` é o SHA-256 do texto limpo do edital.
- Link novo → analisa e envia (se `sim`/`incerto`).
- Link já visto e mesmo hash → ignora.
- Link já visto com hash diferente → reanalisa e envia como
  `🔄 EDITAL ATUALIZADO`.
- Falha na IA → `analisado = 0`; nova tentativa na próxima execução.
- Falha no envio → `enviado = 0`; nova tentativa na próxima execução.

## Análise por IA

- Temperatura `0.15`; resposta somente em JSON.
- Validação de todos os campos; JSON inválido → pedido de correção (1x).
- 429/5xx/timeout/falha de conexão → espera 2 s, tenta de novo, depois passa ao
  próximo modelo.
- Todos os modelos falham → edital fica na fila.
- O log registra o modelo que respondeu cada edital.
- O prompt proíbe inventar dados e manda usar `"não informado"`.
- Texto do edital é tratado como dado; instruções dentro dele são ignoradas.

## Filtro final

- `ong_pode_participar = "sim"` → envia.
- `"incerto"` → envia com `⚠️ Conferir elegibilidade no edital`.
- `"nao"` → salva no banco, não envia.

Toda mensagem termina com o aviso de que o resumo foi gerado por IA.

## Filtro de prazos (editais abertos)

O sistema evita que editais já encerrados cheguem até você, em duas camadas:

| Camada | Onde | Como |
|---|---|---|
| Determinística | Coleta (antes da IA) | Se o scraper extraiu prazo e ele já passou → encerrado = 1, ignora. |
| IA | Análise | A IA lê o texto completo e preenche inscricoes_abertas (sim/nao/incerto). Se nao → encerrado = 1. |

A IA também entende expressões como fluxo contínuo, em fluxo, encerrado, só homologação.

O campo encerrado fica no banco; a consulta de envio (pendentes_envio) já filtra encerrado = 0.


## Testes

```bash
.venv/bin/python -m unittest discover -s testes -t . -v
```

Cobrem fallback/retry da IA, validação de JSON, deduplicação e detecção de
alteração, filtro de envio, limpeza/priorização de texto, parsing dos quatro
scrapers, formatação e divisão de mensagens, e o envio por e-mail com SMTP
simulado. Não usam rede nem a chave real.

## Estrutura

```
projeto-editais/
├── .env / .env.example / .gitignore
├── config.yaml
├── main.py               # orquestra tudo + CLI + agendador
├── database.py           # SQLite, hash e filas
├── extractor.py          # HTML/PDF, limpeza e priorização
├── llm_client.py         # NVIDIA, fallback, retry e rate limit
├── prompts.py            # prompt e validação do JSON
├── logging_setup.py      # logs/app.log + console
├── testar_llm.py         # teste isolado da IA
├── testar_notificacao.py # teste do canal de entrega
├── scrapers/
│   ├── base.py           # robots.txt, pausa, filtro, User-Agent
│   ├── cnpq.py
│   ├── fapes.py
│   ├── capes.py
│   └── sebrae.py
├── notifier/
│   ├── base.py           # contrato + formatação
│   ├── telegram.py
│   ├── email.py
│   └── whatsapp.py
├── testes/
├── logs/
└── data/
```

## Pontos que podem quebrar (e como ajustar)

| Risco | Sintoma | Como ajustar |
|---|---|---|
| Layout do site muda | fonte retorna 0 itens | rode `--teste-fonte NOME --dry-run`; ajuste os seletores no arquivo `scrapers/<fonte>.py` |
| URL sai do ar | HTTP 404/redirect genérico | atualize `coleta.fontes[].url` no `config.yaml` |
| robots.txt bloqueia | log “acesso proibido pelo robots.txt” | remova/desative a fonte; não contorne o bloqueio |
| PDF só com imagem (escaneado) | texto vazio ou muito curto | precisa de OCR (ex.: `ocrmypdf` + Tesseract), não implementado |
| Modelo removido/renomeado | HTTP 404/400 no log | `python testar_llm.py --listar-modelos` e atualize a lista |
| Limite gratuito (429) | fallback e espera | aumente `ia.pausa_entre_chamadas` |
| Timeout da NVIDIA | fallback | aumente `ia.timeout_segundos` |
| JSON cortado | “esgotou os tokens de saída” | aumente `ia.max_tokens` |
| IA erra elegibilidade | status `incerto`/`nao` duvidoso | revise o edital; o aviso na mensagem é obrigatório |
| CAPES muda a lista | 0 itens ou programas estranhos | a página lista programas com edital aberto (não PDFs); ajuste o seletor |
| Sebrae muda por UF | 0 itens | cada unidade tem layout próprio; troque a URL da fonte |
| Telegram não entrega | HTTP 400/403 | confira `TELEGRAM_CHAT_ID` e envie `/start` ao bot |
| E-mail não entrega | erro de login/SSL no log | use senha de app (Gmail) e confira host/porta/TLS/SSL |
| E-mail cai no spam | mensagem não aparece na caixa de entrada | marque como “não é spam” e crie filtro pelo remetente |
| WhatsApp não entrega | HTTP 400/401 | confira token, phone id, número e versão da Graph API |
| Banco some | editais repetidos | mantenha `data/editais.db` em volume persistente/backup |
| Duas execuções simultâneas | envios duplicados | use só cron **ou** `--agendar`; o agendador usa `max_instances=1` |
| Site lento/instável | coleta parcial | aumente `coleta.timeout_segundos`; as demais fontes continuam |

Ajuste fino útil:

- `coleta.pausa_minima_segundos` / `pausa_maxima_segundos`: educação com os sites.
- `coleta.max_itens_por_fonte`: quantidade por execução.
- `extracao.limite_caracteres` / `ia.limite_caracteres_texto`: mais contexto ou
  mais velocidade/custo.
- `extracao.max_pdfs`: quantos anexos baixar por edital.

## Segurança e privacidade

- Chaves somente no `.env` (ignorado pelo Git, permissão `600`).
- A chave nunca é impressa em log; só vai no header `Authorization`.
- Logs em `logs/app.log` (rotação de 2 MB, 5 backups).
- Editais com `nao` não são enviados.
- O resumo é apoio, não substitui a leitura do edital oficial.

## Solução de problemas

1. **`NVIDIA_API_KEY não configurada`** → preencha o `.env` e rode de novo.
2. **`pdfplumber`/`APScheduler` ausentes** → ative o venv e
   `pip install -r requirements.txt`.
3. **Fonte sem itens** → veja `logs/app.log`; teste com
   `--teste-fonte <nome> --limite-itens 1 --debug`.
4. **Quer ver o que será enviado sem enviar** → `--dry-run`; as mensagens saem
   no terminal.
5. **Quer reprocessar um edital** → apague a linha correspondente em
   `data/editais.db` (ou o banco inteiro) e rode novamente.
