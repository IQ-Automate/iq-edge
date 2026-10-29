# Changelog

## 0.1.0

- Primeira versão (lote A4 da plataforma IQ).
- Pareamento com a plataforma por código de 6 dígitos (opções ou aba IQ); credencial própria em `/data`, trocada a cada 30 dias.
- Agente da casa pelo contrato v2: busca as tarefas na plataforma (long-poll HTTPS de saída), lê a casa e aplica só propostas aprovadas
  (automações, scripts e cenas); nunca chama serviço a pedido da plataforma.
- Saúde a cada 5 minutos (versão do Home Assistant, contagem de automações, scripts e cenas).
- Aba IQ (ingress): Estado e Bom dia editável (fontes, quantidades, palavras, regras, alto-falante, volume, voz, idioma, unidade,
  horário e dias da fala automática), Testar, Salvar e Falar agora.
