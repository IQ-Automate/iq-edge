# IQ Edge

O IQ Edge conecta esta casa à plataforma IQ Autom8. Com ele, a IQ cuida das automações da casa sem Nabu Casa e sem abrir porta
na internet: o add-on chama a plataforma por HTTPS e busca o que ela pede. A aba **IQ** do Home Assistant traz o **Bom dia**, que
você edita.

## O que o add-on faz

- Lê a casa para a IQ: versão do Home Assistant, entidades, automações, scripts e cenas.
- Aplica na casa só as propostas que a IQ aprovou na plataforma (automações, scripts e cenas), com backup e reversão na plataforma.
- Nunca liga, desliga ou abre nada a pedido da plataforma: ele não chama serviços do Home Assistant para ela.
- Fala o Bom dia no alto-falante que você escolher, no horário e nos dias que você escolher.

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
- **Falar agora** fala o Bom dia salvo no alto-falante escolhido.

## Problemas comuns

- **"A plataforma recusou o código"**: o código está errado, venceu ou já foi usado. Peça outro.
- **"Sem contato com a plataforma"**: confira a internet da casa. O add-on tenta de novo sozinho.
- **"A plataforma desconectou esta casa"**: a casa foi despareada. Peça um código novo.
- **Falar agora não fala**: escolha o alto-falante e o motor de voz e toque em **Salvar** antes.

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

Tipos de tarefa: `ha` (`{method, path, body?}`, só a lista abaixo), `prefs` (`{version, prefs}`), `preview` (`{prefs, language}`) e
`ping`. Lista permitida para `ha`, conferida de novo no add-on: `GET /api/config`, `GET /api/states`, `GET /api/states/<entidade>`,
`GET /api/services`, `GET/POST/DELETE /api/config/{automation,script,scene}/config/<id>` e `POST /api/config/core/check_config`.
Qualquer outra resposta é `forbidden`. Tarefa vencida (`deadline`) nunca roda. Erros: 401 credencial desconhecida ou revogada (o
add-on esquece a credencial), 429 limite (`Retry-After`), 413 corpo grande demais. As preferências seguem o formato v1 da
plataforma mais `schedule` `{time: "HH:MM", days: [0..6]}` (0 = segunda).

## English

IQ Edge connects this home to the IQ Autom8 platform (no Nabu Casa, no open port: the add-on calls the platform over HTTPS). Install
it from the repository `https://github.com/IQ-Automate/iq-edge`, then type the 6-digit pairing code from IQ in the **IQ** tab →
**Status** (or in the add-on's options). The **Good morning** page edits the spoken morning summary, its speaker and its schedule.
The platform can read the home and apply only approved automations, scripts and scenes; it never calls a service.
