# Changelog

## 0.2.5

- Roteador de voz (lote J1b): o add-on recebe os pedidos do assistente de voz da casa (pela integração Webhook Conversation),
  pergunta à plataforma para onde cada um vai e manda ao assistente local do Home Assistant (pedidos simples) ou ao assistente
  que a casa já usava (os outros). Quem decide é a plataforma. O add-on nunca troca "assistente" por "local": pedido sensível
  (tranca, alarme, garagem, apagar tudo) vai sempre ao assistente.
- A casa nunca fica sem assistente: sem pareamento, sem plataforma, com a plataforma lenta (2 segundos no máximo), com erro ou
  com resposta fora do formato, o pedido vai ao assistente. Se o assistente local não entender, o pedido também vai ao
  assistente. Sem assistente escolhido, o roteador responde em voz que não há assistente configurado.
- Porta nova 8098, só na rede interna do Home Assistant (o Supervisor não a publica no aparelho), com usuário `iq` e uma senha
  que o add-on cria na primeira partida (`/data/voice.json`, só o add-on lê). Só aceita `POST /v1/conversation` com essa senha.
- Duas opções novas, ambas opcionais: `voice_agent` (a entidade `conversation.*` que recebe os pedidos que não são simples) e
  `voice_route` (`on`, `observe` ou `off`; vazio = `on`). Em `observe`, tudo vai ao assistente e a decisão da plataforma só é contada.
- Aba nova **Assistente**: o endereço, o usuário e a senha (só depois do botão) para criar a entrada na integração, o modo, o
  assistente escolhido e os números desde que o add-on iniciou (local, assistente, plano B, sem resposta e o tempo médio da
  consulta à plataforma).
- O texto dos pedidos nunca é guardado: nem no registro, nem na aba, nem na memória depois da resposta.
- **O que muda ao atualizar:** nada do que a casa usa hoje. O add-on abre a porta 8098 e cria a senha, mas só recebe pedidos
  depois que alguém cria a entrada na integração (veja o DOCS). Com as duas opções vazias, o Bom dia e tudo o que já existia ficam
  exatamente como eram.

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
