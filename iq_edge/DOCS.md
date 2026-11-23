# IQ Edge

O IQ Edge conecta esta casa à plataforma IQ Autom8. Com ele, a IQ cuida das automações da casa sem Nabu Casa e sem abrir porta
na internet: o add-on chama a plataforma por HTTPS e busca o que ela pede. A aba **IQ** do Home Assistant traz o **Bom dia**, que
você edita.

## O que o add-on faz

- Lê a casa para a IQ: versão do Home Assistant, entidades, automações, scripts e cenas.
- Aplica na casa só as propostas que a IQ aprovou na plataforma (automações, scripts e cenas), com backup e reversão na plataforma.
- Nunca liga, desliga ou abre nada a pedido da plataforma: ele não chama serviços do Home Assistant para ela.
- Fala o Bom dia no alto-falante que você escolher, no horário e nos dias que você escolher, ou quando uma automação do Home
  Assistant dispara o evento `iq_bom_dia`.
- Pede à plataforma o texto do Bom dia escrito por IA. A chave da IA fica só na plataforma: a casa manda só os dados do resumo
  (nomes de quem está em casa, clima, o que está aberto, alarme e as manchetes candidatas). Sem plataforma ou sem resposta, o
  texto é montado por regra, como antes.
- Prepara o Bom dia antes do horário, para a fala sair na hora.
- Roteia a voz do assistente da casa (0.2.5): recebe os pedidos do assistente de voz, pergunta à plataforma para onde cada
  um vai e manda ao assistente local do Home Assistant ou ao assistente que a casa já usava. Veja **Roteador de voz**.

## Instalar

1. Abra **Configurações → Apps → Instalar app**.
2. No menu do canto (⋮), toque em **Repositórios**.
3. Cole `https://github.com/IQ-Automate/iq-edge` e toque em **Adicionar**.
4. Feche a janela. Procure **IQ Edge** e toque em **Instalar**. A instalação monta o add-on neste aparelho e leva alguns minutos.
5. Ative **Mostrar na barra lateral**.

## Parear com a plataforma

1. Peça à IQ o código de pareamento desta casa. O código tem 6 dígitos e vale 15 minutos.
2. Digite o código de um destes dois jeitos:
   - Na aba **IQ** → **Estado**, no campo **Código de pareamento**. Toque em **Parear**.
   - Ou em **Configuração** do add-on, no campo **Código de pareamento**. Salve e reinicie o add-on.
3. Confira que a aba **Estado** mostra **Pareado** e o nome da casa.

O código vale uma vez e por 15 minutos; vencido, usado ou cancelado na plataforma, peça outro. Depois do pareamento o add-on apaga o código
das opções. Ele guarda a credencial própria em `/data` (só o add-on lê) e troca a credencial a cada 30 dias.

### Desparear

1. Abra a aba **IQ** → **Estado**.
2. Toque em **Desparear** e confirme.

A plataforma deixa de alcançar a casa. Para voltar, peça um código novo e pareie de novo. A IQ também pode desparear pela plataforma.

## Bom dia

Na aba **IQ** → **Bom dia** você escolhe:

- **Ler o estado da casa** (portas, janelas e alarme) e **Falar o clima**.
- **Fontes**: uma por linha, no formato `Nome = endereço RSS`. Fontes com o mesmo nome se juntam.
- **Quantas de cada fonte** (0 a 6), no formato `Nome = 2`. Sem linha, vale 1.
- **Total** de notícias (mínimo e máximo), **Máximo de palavras** e **Regras de relevância**.
- **Alto-falante** (um `media_player` da casa), **Volume**, **Motor de voz**, **Idioma** e **Unidade**.
- **Fala automática**: horário e dias. Sem dias marcados, ela fica desligada.

Botões:

- **Testar** mostra o texto com os valores da tela. Nada é falado e nada é salvo.
- **Salvar** guarda nesta casa e envia à plataforma. Sem internet, a plataforma recebe quando a conexão voltar.
- **Falar agora** fala o Bom dia salvo no alto-falante escolhido. Sem alto-falante, fala no aparelho de voz de reserva (opção
  `satellite`).

### Bom dia preparado antes

O add-on lê as notícias, o clima e pede o texto à IA antes da hora. Assim a fala sai na hora.

- Com **Fala automática** ligada: ele prepara 30 minutos antes do horário (opção `prepare_minutes`).
- Sem **Fala automática**, numa casa que usa o evento `iq_bom_dia`: ele prepara a partir das 06:00 (opção `prepare_at`). Ele só
  faz isso depois que o evento chegou uma vez nos últimos 14 dias.
- Ele prepara uma vez no começo. Até o Bom dia ser falado, ele prepara de novo só quando o texto passa de 90 minutos, no
  máximo 2 vezes. Ele para 4 horas depois do horário e apaga o texto preparado.
- Um horário logo depois da meia-noite (por exemplo, 00:10) é preparado na noite anterior.
- Quem está em casa e o que está aberto (portas, janelas e alarme) não entram no texto preparado. Eles entram na hora da fala,
  com frases fixas, para nunca ficarem velhos.
- Um texto preparado vale por 2 horas. Depois disso, ou se você mudou o Bom dia, o add-on monta o texto na hora, como antes.
- Quando o texto preparado muda, o add-on pede ao Home Assistant para gerar o áudio da voz e guardar em cache. Nada toca
  nessa hora. Se a casa não mudou até a fala, o áudio já está pronto.
- `prepare_minutes: 0` desliga a preparação.

## Bom dia por uma automação do Home Assistant (evento `iq_bom_dia`)

O add-on escuta o evento `iq_bom_dia` do Home Assistant. Quando o evento chega, ele fala o Bom dia na hora, como **Falar agora**.
Ele não abre porta nova: o add-on conecta no Home Assistant pelo Supervisor.

Para disparar o Bom dia por uma automação:

1. Abra **Configurações → Automações e cenas → Criar automação → ⋮ → Editar em YAML**.
2. Cole o exemplo abaixo. Troque `binary_sensor.porta_do_quarto` pelo sensor que marca o começo do dia na sua casa.
3. Toque em **Salvar**.
4. Na aba **IQ** → **Bom dia**, deixe os dias da **Fala automática** desmarcados. Assim o Bom dia não fala duas vezes.

```yaml
alias: Bom dia IQ
mode: single
triggers:
  - trigger: state
    entity_id: binary_sensor.porta_do_quarto
    to: "on"
conditions:
  - condition: time
    after: "05:30:00"
    before: "11:00:00"
  # uma vez por dia
  - condition: template
    value_template: >
      {{ this.attributes.last_triggered is none
         or as_local(this.attributes.last_triggered).date() != now().date() }}
actions:
  - event: iq_bom_dia
    event_data:
      language: pt   # opcional: pt ou en; sem ele, vale o idioma salvo
```

Dois eventos com menos de 1 minuto de diferença falam uma vez só.

### Depois da fala

Quando o Bom dia termina de falar, o add-on dispara o evento `iq_bom_dia_done` no Home Assistant. Isso vale para **Falar agora**, para o
horário e para o evento `iq_bom_dia`. O evento leva `spoken` (`true` se o Bom dia foi falado) e `language` (`pt` ou `en`). Se nada foi
falado (sem alto-falante nem aparelho de reserva, falha na voz ou alto-falante ocupado), o evento sai na hora com `spoken: false`: a
automação que espera não fica presa. Se o alto-falante responde antes de a fala acabar (como o Sonos), o add-on espera o tempo
estimado da fala. Use o evento para começar a música ambiente só depois da fala:

```yaml
- event: iq_bom_dia
- wait_for_trigger:
    - trigger: event
      event_type: iq_bom_dia_done
  timeout: "00:03:00"
  continue_on_timeout: true
```

## Opções do Bom dia (aba Configuração do add-on)

Todas são opcionais. Toque em **Mostrar opções não usadas** para ver. Depois de mudar, reinicie o add-on.

Deixar uma opção vazia usa o **padrão IQ** (coluna da direita). Escreva um valor só quando uma casa precisar de outro
comportamento.

| Opção | O que faz | Vazio (padrão IQ) |
| --- | --- | --- |
| `weather_entity` | A entidade `weather.*` da previsão. | a primeira da casa |
| `temp_sensor` | Um `sensor.*` que dá a temperatura agora (por exemplo, o de fora). | o `weather.*` |
| `satellite` | Um `assist_satellite.*` de reserva: fala quando o alto-falante ou a voz falham, ou quando não há alto-falante. | nenhum |
| `tts_voice` | O id da voz em português no motor de voz (por exemplo, ElevenLabs). | com a ElevenLabs, a voz padrão da IQ; com outro motor, a voz do motor |
| `tts_voice_en` | O id da voz em inglês. | a voz de `tts_voice` (que, vazio, segue a regra da linha acima) |
| `speaker_delay` | Segundos de espera antes de tocar (0 a 15). A fala automática não espera. | 2 |
| `speaker_wait` | Segundos que espera um alto-falante indisponível voltar (0 a 30). | 8 |
| `speaker_busy` | Alto-falante tocando (TV ou música): `interrupt` fala por cima; `voice` fala no aparelho de reserva, sem interromper. | `interrupt` (fala por cima) |
| `card_seconds` | Segundos que os cartões ficam no painel (10 a 300). | 40 |
| `prepare_minutes` | Minutos antes do horário para preparar o Bom dia (0 a 180; 0 desliga). | 30 |
| `prepare_at` | Hora de começar a preparar numa casa sem horário que usa o evento (`HH:MM`). | 06:00 |
| `greet_names` | Cumprimenta pelo nome de quem está em casa. Com `true`, fala os nomes. Sem nomes (vazio ou `false`), fala só "Bom dia." e os nomes também saem do cartão Casa e do pedido à plataforma. | sem nomes |
| `trash_organic_days` | Os dias da semana do lixo orgânico. Escreva-os em inglês: `monday` = segunda, `tuesday` = terça, `wednesday` = quarta, `thursday` = quinta, `friday` = sexta, `saturday` = sábado, `sunday` = domingo. Nos dias marcados, todo Bom dia termina com um lembrete para colocar o lixo para fora. | sem lembrete |
| `trash_recycling_days` | Os dias da semana do lixo reciclável, escritos do mesmo jeito. Se os dois lixos caem no mesmo dia, o lembrete fala dos dois. | sem lembrete |

**Lembrete do lixo (0.2.4).** O lembrete é uma frase fixa, no fim da fala. Por exemplo: "E não esqueça: hoje é dia do lixo orgânico.
Coloque o lixo orgânico para fora." O dia vale no fuso da casa (o do Home Assistant). A IA não escreve a frase e a plataforma não
a recebe. O botão **Testar** também mostra o lembrete.

## Roteador de voz (aba Assistente, 0.2.5)

O roteador recebe cada frase do assistente de voz da casa e pergunta à plataforma para onde ela vai:

- **Pedido simples** (por exemplo, acender uma luz): vai ao assistente local do Home Assistant. Se ele não entender, o pedido vai
  ao assistente.
- **Qualquer outro pedido**: vai ao **assistente** que você escolheu na opção `voice_agent` (o que a casa já usava).
- **Pedido sensível** (tranca, alarme, garagem, apagar tudo): vai sempre ao assistente. O add-on nunca troca isso.

A casa nunca fica sem assistente. Sem pareamento, sem internet, com a plataforma lenta (mais de 2 segundos), com erro ou com
resposta estranha, o pedido vai ao assistente. Sem assistente escolhido, o roteador responde em voz que não há assistente
configurado.

O roteador não guarda o texto dos pedidos: nem no registro, nem na aba, nem na memória depois da resposta. Ele guarda só os números
de conversa, por 30 minutos, para a frase seguinte continuar a mesma conversa.

### Opções do roteador

Todas são opcionais. Depois de mudar, reinicie o add-on. A coluna da direita diz o que vale quando a opção fica vazia.

| Opção | O que faz | Vazio |
| --- | --- | --- |
| `voice_agent` | A entidade `conversation.*` que recebe os pedidos que não são simples (o assistente que a casa já usava). Nunca escolha o agente do próprio roteador. | nenhum: o roteador avisa que não há assistente |
| `voice_route` | `on`: a plataforma decide para onde vai cada pedido. `observe`: tudo vai ao assistente, mas a plataforma ainda é consultada e a decisão é contada na aba. `off`: tudo vai ao assistente e a plataforma nunca é consultada. | `on` |

Para começar com segurança, use `observe`: a casa fala como antes e a aba **Assistente** mostra quantos pedidos a plataforma teria
mandado ao assistente local. Quando os números parecerem bons, deixe o modo vazio (ou `on`).

### Criar a entrada na integração (uma vez)

Antes, a casa precisa da integração **Webhook Conversation** (no Marketplace do Home Assistant). A casa que já a usa tem tudo pronto.

1. Abra a aba **IQ** → **Assistente**. Anote o **Endereço** e o **Usuário**. Toque em **Mostrar a senha** e depois em **Copiar**.
2. No Home Assistant, abra **Configurações → Dispositivos e serviços → Webhook Conversation**.
3. Adicione um agente de conversa novo (o nome do botão muda com a versão da integração). Preencha:
   - **Nome**: `IQ Roteador`.
   - **URL do webhook**: o **Endereço** da aba, no formato `http://<nome do add-on>:8098/v1/conversation`.
   - **Tempo limite**: 90 segundos (o padrão, 30, é curto para o assistente de IA).
   - **Tipo de autenticação**: `basic_auth`. Usuário `iq` e a senha que você copiou.
   - **Campo de saída**: `output` (o padrão). O roteador responde bem com a resposta em fluxo ligada ou desligada.
4. Salve. O agente novo aparece como uma entidade `conversation.*` (por exemplo, `conversation.iq_roteador`).
5. Abra **Configurações → Assistentes de voz**, escolha o assistente que vai usar o roteador e, em **Agente de conversa**, escolha
   o agente novo. Fale uma frase para testar.
6. Nas opções do add-on, escreva em `voice_agent` o agente que a casa usava antes (a entrada antiga do Webhook Conversation, por
   exemplo `conversation.webhook_conversation`). **Não** escreva o agente novo: o roteador chamaria a si mesmo. Se isso
   acontecer, ele avisa em voz e não chama ninguém.
7. Reinicie o add-on e abra a aba **Assistente** para ver o modo, o assistente escolhido e os números.

A porta 8098 fica só na rede interna do Home Assistant: o Supervisor não a publica no aparelho (em **Configuração → Rede** ela
aparece desligada; deixe assim). O Home Assistant chega nela pelo nome do add-on. Toda chamada pede usuário e senha. A senha nasce
na primeira partida e fica em `/data` (só o add-on lê).

A aba **Assistente** mostra os números desde que o add-on iniciou: quantos pedidos foram ao assistente local, quantos ao assistente,
quantos foram pelo plano B (a plataforma ou o assistente local não responderam), quantos ninguém respondeu e o tempo médio da
consulta à plataforma. Nunca mostra o texto de um pedido.

## Problemas comuns

- **"A plataforma recusou o código"**: o código está errado, venceu ou já foi usado. Peça outro.
- **"Sem contato com a plataforma"**: confira a internet da casa. O add-on tenta de novo sozinho.
- **"A plataforma desconectou esta casa"**: a casa foi despareada. Peça um código novo.
- **Falar agora não fala**: escolha o alto-falante e o motor de voz e toque em **Salvar** antes.
- **"IA pelo centro: sem resposta"** na aba **Estado**: o Bom dia saiu com o texto por regra. Confira a internet da casa e o
  pareamento. A plataforma aceita 6 pedidos por hora e 30 por dia de cada casa.
- **"Evento iq_bom_dia: sem conexão com o Home Assistant"**: o add-on tenta de novo sozinho. Se continuar, reinicie o add-on.
- **Voz: "Error contacting webhook: HTTP 401"**: o usuário ou a senha da entrada estão errados. Copie de novo na aba **Assistente**.
- **Voz: "Cannot connect to host"**: o endereço está errado ou o add-on está parado. O nome do add-on também aparece na página
  **Informações** dele.
- **Voz: tempo esgotado**: aumente o **Tempo limite** da entrada (90 segundos ou mais).
- **O roteador fala que não há assistente configurado**: preencha `voice_agent` e reinicie o add-on.
- **"Plano B" alto na aba Assistente**: a plataforma está lenta ou fora, ou o assistente local não entendeu os pedidos simples.

## Contrato v2 (para a equipe técnica)

Todas as chamadas vão do add-on para `{center_url}/api/edge/v1/` por HTTPS, com o cabeçalho `X-IQ-Edge-Contract: 2`. Depois do
pareamento: `Authorization: Bearer <credencial>` e `X-IQ-Edge-Home: <id da casa>`.

| Rota | Corpo | Resposta |
| --- | --- | --- |
| `POST pair` | `{code, hostname, addon_version, arch, ha_version}` | `{home_id, home_name, credential, poll_wait: 25, heartbeat_every: 300, contract: 2}` · 400/403 `code` |
| `GET jobs?wait=25` | — | 200 `{id, kind, request, deadline, contract}` ou 204 (sem tarefa; `Retry-After` quando o centro está cheio) |
| `POST jobs/<id>/result` | `{ok: true, status, data}` ou `{ok: false, error, detail}` | 200 · 404 tarefa desconhecida · 409 vencida ou já respondida |
| `POST heartbeat` | `{ha_version, addon_version, health: ok\|ha_unreachable, programs}` | 200 `{ok, heartbeat_every}` |
| `POST prefs` | `{prefs, user: {id, name}}` | 200 `{ok, version}` · 422 preferências inválidas |
| `POST rotate` | `{}` | 200 `{credential, previous_valid_until}` (a anterior vale mais 5 min) |
| `POST unpair` | `{user: {name}}` | 200 `{ok}` |
| `POST briefing-compose` | `{language, max_words, rules, house_state, facts: {names, weather, open, alarm}, candidates: [{source, limit, titles}], total_min?, total_max?}` (≤ 64 KiB) | 200 `{text, picks: [{source, indices}], model, words}` · 401/410 · 422 `invalid` · 429 `rate` · 502 `ai_failed` · 503 `no_key` |
| `POST voice-route` | `{text (1 a 500 caracteres), language}` | 200 `{route: local\|agent, category: simple\|compound\|config\|chat\|unknown, sensitive, confidence, engine: jev\|simulated\|none, reason, ms}` · 401/410/413/422/429/5xx |

Tipos de tarefa: `ha` (`{method, path, body?}`, só a lista abaixo), `prefs` (`{version, prefs}`), `preview` (`{prefs, language}`) e
`ping`. Lista permitida para `ha`, conferida de novo no add-on: `GET /api/config`, `GET /api/states`, `GET /api/states/<entidade>`,
`GET /api/services`, `GET/POST/DELETE /api/config/{automation,script,scene}/config/<id>` e `POST /api/config/core/check_config`.
Qualquer outra resposta é `forbidden`. Tarefa vencida (`deadline`) nunca roda. Erros: 401 credencial desconhecida ou revogada (o
add-on esquece a credencial), 429 limite (`Retry-After`), 413 corpo grande demais. As preferências seguem o formato v1 da
plataforma mais `schedule` `{time: "HH:MM", days: [0..6]}` (0 = segunda).

`briefing-compose` (0.2.0): uma tentativa, até 45 s (dentro de uma tarefa `preview`, termina antes do prazo dela). Qualquer erro
vira o texto por regra; o log guarda só o motivo curto (`rate`, `no_key`...), nunca o corpo. O add-on corta os campos nos
limites do centro antes de enviar (20 fontes, 30 títulos de 300 caracteres, 20 nomes de 80, 60 itens abertos de 120, clima e
alarme de 40, unidade só `C`/`F`) e manda `total_min`/`total_max` quando o Bom dia tem total de notícias. Em `facts.weather`
vão também `say_unit` (`false` no modo de unidade pelo idioma: a fala diz só "graus") e, com as duas unidades, `high2`/`low2`.
Fontes com o mesmo nome vão juntas, como uma fonte só. O Bom dia preparado manda `names`
vazio e `house_state: false`: o cumprimento e a casa entram na hora da fala.

`voice-route` (0.2.5): uma tentativa e cerca de 2 s no total; depois disso o pedido segue para o assistente. Qualquer erro (401, 410,
413, 422, 429, 5xx, tempo esgotado, resposta fora do formato) vira "assistente". Texto com mais de 500 caracteres nem vai à
plataforma. `sensitive: true` nunca fica local, e o add-on nunca troca `agent` por `local`. O texto vai só no corpo da chamada:
nunca no registro, em contador ou em erro.

## English

IQ Edge connects this home to the IQ Autom8 platform (no Nabu Casa, no open port: the add-on calls the platform over HTTPS). Install
it from the repository `https://github.com/IQ-Automate/iq-edge`, then type the 6-digit pairing code from IQ in the **IQ** tab →
**Status** (or in the add-on's options). The **Good morning** page edits the spoken morning summary, its speaker and its schedule.
The platform can read the home and apply only approved automations, scripts and scenes; it never calls a service.
Since 0.2.0 the good morning text is written by the platform's AI (the key stays on the platform; the home sends only the
summary's data) and falls back to the rule text; it is prepared ahead so it is spoken at once; and an automation can trigger it
with the event `iq_bom_dia` (optional `event_data: {language: en}`). When the speech ends, the add-on fires the event
`iq_bom_dia_done` (`spoken`: true or false, `language`), so an automation can wait for it, for example to start the background
music. The good morning options (`weather_entity`, `temp_sensor`, `satellite`, voices, waits, `card_seconds`, `prepare_minutes`,
`prepare_at`, `greet_names`, `trash_organic_days`, `trash_recycling_days`) are in the add-on's configuration. Since 0.2.4, on the
weekdays marked in `trash_organic_days` and `trash_recycling_days` (written in English: `monday` to `sunday`), every good
morning ends with a fixed reminder to take the trash out (in the home's time zone); empty means no reminder. Since 0.2.3 an empty option means the IQ default: the speech
plays over the TV or music (`speaker_busy: interrupt`), says only "Good morning." with no names (in the speech, on the Home card
or in the request to the platform), and, with ElevenLabs, uses the IQ voice. `speaker_busy: voice`, `greet_names: true` and a
voice id in `tts_voice` bring back the old behavior.

Since 0.2.5 the add-on is also a voice router. It listens on port 8098 (only on Home Assistant's internal network; the Supervisor
does not publish it on the host) for the community integration Webhook Conversation, with Basic authentication (user `iq`, a
password made on the first start and shown in the **Assistant** tab). For each spoken request it asks the platform (`voice-route`,
about 2 s at most) where it goes: simple requests go to Home Assistant's local assistant, the others (and every sensitive one: lock,
alarm, garage, turn everything off) go to the agent chosen in `voice_agent`. If the platform cannot answer, or the local assistant
does not understand, the request goes to the agent: the home never loses its assistant. `voice_route` is `on` (default), `observe`
(always the agent, the platform's decision is only counted) or `off` (the platform is never asked). The text of a request is never
logged, shown or kept. Create the entry in Webhook Conversation with the address, user and password from the **Assistant** tab
(timeout 90 s), pick it in the voice assistant's conversation agent, and set `voice_agent` to the agent the home used before.
