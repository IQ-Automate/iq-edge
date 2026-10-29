# IQ Autom8 — apps for Home Assistant

Repositório de apps (add-ons) da IQ Autom8 para o Home Assistant OS / Supervised.

| App | O que faz |
| --- | --- |
| [IQ Edge](iq_edge/) | Conecta a casa à plataforma IQ (pareamento por código, sem Nabu Casa) e traz o Bom dia editável na aba IQ. |

## Instalar

Em **Configurações → Apps → Instalar app → ⋮ → Repositórios**, adicione:

```
https://github.com/IQ-Automate/iq-edge
```

Depois instale **IQ Edge** e siga a aba **Documentação** do app.

## Desenvolvimento

O pacote Python fica em `iq_edge/app/iq_edge` (só `requests`, `PyYAML` e a biblioteca padrão). Ele roda fora do Home Assistant com
variáveis de ambiente (`HA_URL`, `HA_TOKEN`, `IQ_CENTER_URL`, `IQ_DATA_DIR`, `IQ_PAIRING_CODE`). Testes, com centro e Home Assistant
falsos (nada sai da máquina):

```
cd iq_edge/app
python -m unittest discover -s tests
python -m compileall -q iq_edge
```

A imagem é construída no aparelho pelo Supervisor (`iq_edge/Dockerfile`, amd64 e aarch64); não há registro de imagens.
