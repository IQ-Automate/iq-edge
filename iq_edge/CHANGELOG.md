# Changelog

## 0.2.7

- Opção nova `voice_chat_agent` (opcional): uma segunda entidade `conversation.*` do Home Assistant, **só para conversa e perguntas
  gerais**. Só as palavras do pedido, o idioma e o número da conversa chegam a ela (como em `voice_agent`). Vazia (padrão), tudo
  continua como na 0.2.6.
- Com `voice_chat_agent` preenchida e `voice_route` em `on`, o que a plataforma classifica como conversa vai a esse agente de
  conversa. O pedido simples continua indo direto ao assistente local do Home Assistant. Todo o resto vai ao assistente
  principal, como antes: pedido composto, de configuração, pergunta sobre a casa que depende de histórico ou de câmeras e
  qualquer tipo que a plataforma ainda não classifica. **Pedido sensível (tranca, alarme, garagem, apagar tudo) nunca vai ao
  agente de conversa**: vai sempre ao assistente principal.
- A casa nunca fica sem resposta: se o agente de conversa não responder (fora do ar, erro, mais de 30 segundos) ou for o próprio
  roteador, o pedido vai ao assistente principal na mesma hora, e a aba conta isso.
- Modo `observe`: nada é desviado (tudo vai ao assistente principal, como antes) e a aba conta quantos pedidos **iriam** ao agente
  de conversa. Modo `off`: nada muda, a plataforma nunca é consultada. Sem `voice_agent` nem `voice_agent_url`, o roteador continua
  desligado: `voice_chat_agent` sozinha não liga nada.
- Aba **Assistente**: mostra o agente de conversa escolhido (ou "nenhum") e três números novos: quantos pedidos foram ao agente de
  conversa, quantos ele não respondeu (e foram ao assistente principal) e, no modo `observe`, quantos iriam a ele.
- O registro da partida cita o agente de conversa quando há um (a opção e a entidade, nunca senha nem endereço). O texto dos
  pedidos continua nunca indo ao registro, à aba nem à memória.
- Cuidado: o agente de conversa **não deve poder controlar a casa**. Crie-o sem a opção de controlar o Home Assistant e sem
  entidades expostas. A plataforma pode errar uma classificação, e o que protege a casa é o agente de conversa não ter controle.
- **O que muda ao atualizar:** nada, enquanto `voice_chat_agent` ficar vazia.

## 0.2.6

- Botão novo **Repetir o último**, na aba **Bom dia**, ao lado de **Falar agora**: toca de novo o Bom dia que acabou de ser
  falado (por exemplo, para ouvir as notícias do dia outra vez). É o **mesmo áudio**: o add-on não gera a voz de novo e, por isso,
  a repetição **não gasta** a ElevenLabs.
- Evento novo `iq_bom_dia_repeat`: uma automação ou um script do Home Assistant dispara a mesma repetição (`- event:
  iq_bom_dia_repeat`). Dois eventos com menos de 1 minuto de diferença tocam uma vez só. O pedido é ignorado enquanto um Bom dia
  está falando. A repetição não dispara `iq_bom_dia_done`.
- Depois de cada Bom dia falado no alto-falante, o add-on guarda o áudio do que foi falado na pasta de mídia do Home Assistant
  (`iq-edge/bom-dia.mp3`) e os dados em `/data/briefing-last.json` (só o add-on lê): idioma, alto-falante, volume, hora, tamanho,
  um resumo do arquivo e a duração estimada. **O texto da fala não é guardado.** O áudio vem do próprio Home Assistant, com o mesmo
  pedido que o Bom dia preparado já usa, depois que a fala terminou: ele responde do cache dele.
- Só o último Bom dia fica guardado, por 20 horas. Se guardar o áudio de hoje falhar, o de antes é apagado: a repetição nunca toca
  um Bom dia mais velho. O mesmo vale quando o Bom dia saiu só pelo aparelho de voz de reserva.
- A repetição usa `media_player.play_media` (com `announce`) no alto-falante escolhido **agora**, com o volume do Bom dia (depois o
  volume volta). Nunca chama `tts.speak`, `tts_get_url` nem o aparelho de voz. Quando não há o que repetir (nada guardado, mais de 20
  horas, arquivo sumido) ou um Bom dia está falando, nada toca. Sem áudio para repetir, a aba deixa o botão desligado e diz o
  motivo.
- O add-on ganha acesso de leitura e escrita à pasta de mídia (`map: media:rw`). Só a pasta `iq-edge` dentro dela é usada.
- **O que muda ao atualizar:** nada no Bom dia: mesma fala, mesmos eventos, mesmo horário. A repetição só passa a existir depois do
  primeiro Bom dia falado na 0.2.6.

## 0.2.5

- Roteador de voz (lote J1b): o add-on recebe os pedidos do assistente de voz da casa (pela integração Webhook Conversation),
  pergunta à plataforma para onde cada um vai e manda ao assistente local do Home Assistant (pedidos simples) ou ao assistente
  que a casa já usava (os outros). Quem decide é a plataforma. O add-on nunca troca "assistente" por "local": pedido sensível
  (tranca, alarme, garagem, apagar tudo) vai sempre ao assistente.
- A casa nunca fica sem assistente: sem pareamento, sem plataforma, com a plataforma lenta (2 segundos no máximo), com erro ou
  com resposta fora do formato, o pedido vai ao assistente. Se o assistente local não entender, o pedido também vai ao
  assistente. Sem assistente escolhido, o roteador responde em voz que não há assistente configurado.
- Entrega fiel por endereço: três opções novas, `voice_agent_url` (o endereço do webhook do assistente antigo),
  `voice_agent_user` e `voice_agent_password`. Com o endereço preenchido, o pedido vai ao assistente exatamente como o Home
  Assistant o enviou (mesmos bytes, com `user_id`, `device_id`, `device_info` e as entidades expostas), com autenticação Basic só
  quando há usuário e 90 segundos de limite. A resposta do assistente volta ao Home Assistant sem mudar (código, tipo e corpo).
  Vale para todo caminho do assistente: modo `off`, modo `observe`, plataforma mandando ao assistente, plataforma sem resposta,
  texto com mais de 500 caracteres e plano B do assistente local. O endereço vale mais que `voice_agent`.
- O endereço só vale se for `http` ou `https`, sem usuário nem senha dentro e sem apontar para o próprio roteador. Endereço
  recusado, assistente fora do ar, tempo esgotado ou erro 5xx viram uma frase falada e contam como falha. O endereço, o usuário, a
  senha e o texto dos pedidos nunca vão ao registro.
- Porta nova 8098, só na rede interna do Home Assistant (o Supervisor não a publica no aparelho), com usuário `iq` e uma senha
  que o add-on cria na primeira partida (`/data/voice.json`, só o add-on lê). Só aceita `POST /v1/conversation` com essa senha.
  **A porta só abre, e o arquivo só nasce, quando `voice_agent` ou `voice_agent_url` está preenchida.**
- Cinco opções novas, todas opcionais: `voice_agent` (a entidade `conversation.*` que recebe os pedidos que não são simples; só as
  palavras chegam a ela, sem saber quem fala nem o aparelho), `voice_route` (`on`, `observe` ou `off`; vazio = `on`; sozinha, não
  liga o roteador), `voice_agent_url`, `voice_agent_user` e `voice_agent_password`. Em `observe`, tudo vai ao assistente e a
  decisão da plataforma só é contada.
- Aba nova **Assistente**: com o roteador desligado, diz isso e quais opções da aba Configuração ligam. Com o roteador ligado,
  mostra o endereço, o usuário e a senha (só depois do botão) para criar a entrada na integração, o modo, o tipo de assistente
  (a entidade, ou só "agente por endereço", nunca o endereço) e os números desde que o add-on iniciou (local, assistente, plano B,
  sem resposta e o tempo médio da consulta à plataforma).
- O texto dos pedidos nunca é guardado: nem no registro, nem na aba, nem na memória depois da resposta.
- Limite conhecido: o caminho local não sabe de qual aparelho nem de qual cômodo veio a frase; um pedido que depende de "este
  cômodo" cai no assistente.
- **O que muda ao atualizar:** com as cinco opções de voz vazias, nada muda: o add-on não abre a porta 8098, não cria
  `/data/voice.json` e se comporta como a 0.2.4 (a aba só ganha a seção Assistente, que diz que o roteador está desligado). Para
  ligar numa casa que já usa a integração, veja os passos no DOCS (**Casa que já usa a integração**).

## 0.2.4

- Duas opções novas, `trash_organic_days` e `trash_recycling_days`: os dias da semana do lixo orgânico e do lixo reciclável
  (escritos em inglês: `monday` a `sunday`). Nos dias marcados, todo Bom dia termina com uma frase fixa de lembrete, por
  exemplo "E não esqueça: hoje é dia do lixo orgânico. Coloque o lixo orgânico para fora." (em inglês: "And don't forget:
  today is trash day. Take the trash out."). Se os dois lixos caem no mesmo dia, a frase fala dos dois.
- O dia vale no fuso da casa (o do Home Assistant). A frase vem depois do limite de tamanho da fala, não vai à plataforma e não
  é escrita pela IA. O botão Testar também mostra o lembrete, e o áudio preparado antes já leva a frase.
- **O que muda ao atualizar:** nada. Com as duas opções vazias, o Bom dia fica exatamente como era.

## 0.2.3

- Padrão IQ: o que ficava vazio na aba Configuração agora vale o comportamento da empresa, sem preencher nada em cada casa.
  Os campos continuam existindo para trocar numa casa.
- **O que muda ao atualizar, para quem deixou os campos vazios:**
  - `speaker_busy` vazio: com o alto-falante tocando (TV ou música), o Bom dia **fala por cima**. Antes falava no aparelho de
    voz de reserva, sem interromper.
  - `greet_names` vazio: o Bom dia **não fala nomes** (só "Bom dia."; também sem a linha "Em casa" no cartão Casa). Antes
    falava os nomes de quem estava em casa.
  - `tts_voice` vazio **com a ElevenLabs**: usa a **voz padrão da IQ**, em português e em inglês. Antes usava a voz do motor.
    Com outro motor de voz, nada muda. Se a fala com a voz padrão falhar, o add-on tenta uma vez sem escolher a voz.
- **Para voltar ao que era:** `speaker_busy: voice`, `greet_names: true` e, em `tts_voice`, o id de outra voz (a voz que a
  casa usava). Um valor escrito sempre vale mais que o padrão.

## 0.2.2

- Opção nova `greet_names`: com `false`, o Bom dia fala só "Bom dia." e não usa o nome de ninguém (nem na fala, nem no cartão
  Casa, nem no pedido à IA). Sem a opção, nada muda.
- Evento novo `iq_bom_dia_done`: o add-on avisa o Home Assistant quando o Bom dia termina de falar (`spoken`: `true` ou
  `false`, e `language`). Uma automação pode esperar por ele, por exemplo para começar a música depois da fala.

## 0.2.1

- Correção: falar o Bom dia não estoura mais aos 30 s. `tts.speak` e o anúncio no aparelho de voz só respondem depois da fala;
  a espera agora é a duração estimada do texto + 30 s (no máximo 240 s). Se mesmo assim o Home Assistant não responder a tempo,
  o registro tem uma linha de aviso (a fala pode ter sido tocada), sem o rastro de erro.
- Correção: o motor de voz que o centro manda como nome curto (ex.: `elevenlabs`) vira a entidade `tts.*` real do Home Assistant
  (ex.: `tts.elevenlabs_text_to_speech`), em vez de `tts.elevenlabs`, que não existe. A lista de entidades fica guardada por
  10 minutos; sem achar (ou com o Home Assistant fora do ar), vale o comportamento antigo.

## 0.2.0

- Bom dia com IA pela plataforma (lote A5): a casa manda só os dados do resumo (`POST briefing-compose`, contrato v2) e usa o
  texto e as manchetes escolhidas. A chave da IA fica só na plataforma. Sem plataforma ou sem resposta, vale o texto por regra.
- Evento `iq_bom_dia` do Home Assistant: uma automação dispara o Bom dia na hora (websocket do Core pelo Supervisor, sem porta
  nova; `language` opcional). Dois eventos em menos de 1 minuto falam uma vez.
- Bom dia preparado antes: uma vez, 30 minutos antes do horário (ou a partir das 06:00 numa casa que usa o evento); renovado
  só depois de 90 minutos, no máximo 2 vezes, até ser falado. Quem está em casa e o que está aberto entram na hora da fala.
  O áudio da voz fica em cache no Home Assistant antes da hora, só quando o texto muda (melhor esforço).
- Opções novas (todas opcionais): `weather_entity`, `temp_sensor`, `satellite`, `tts_voice`, `tts_voice_en`, `speaker_delay`,
  `speaker_wait`, `speaker_busy`, `card_seconds`, `prepare_minutes`, `prepare_at`.
- Aba Estado: "IA pelo centro" (ok ou sem resposta, com a hora), "Bom dia preparado às hh:mm" e o estado do evento.
- **Falar agora** sem alto-falante fala no aparelho de voz de reserva (`satellite`).
- Correção: limpar o código de pareamento das opções não apaga mais as outras opções (e, sem ler as opções, nada é gravado).

## 0.1.0

- Primeira versão (lote A4 da plataforma IQ).
- Pareamento com a plataforma por código de 6 dígitos (opções ou aba IQ); credencial própria em `/data`, trocada a cada 30 dias.
- Agente da casa pelo contrato v2: busca as tarefas na plataforma (long-poll HTTPS de saída), lê a casa e aplica só propostas aprovadas
  (automações, scripts e cenas); nunca chama serviço a pedido da plataforma.
- Saúde a cada 5 minutos (versão do Home Assistant, contagem de automações, scripts e cenas).
- Aba IQ (ingress): Estado e Bom dia editável (fontes, quantidades, palavras, regras, alto-falante, volume, voz, idioma, unidade,
  horário e dias da fala automática), Testar, Salvar e Falar agora.
