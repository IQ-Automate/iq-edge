# Changelog

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
