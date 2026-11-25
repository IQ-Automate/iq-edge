"""python -m iq_edge: the tab (ingress, port 8099), the platform loop (pairing, long-poll, heartbeat, rotation), the Bom dia's
automatic speech and Home Assistant's event iq_bom_dia (websocket, lote A5) and, only when voice_agent or voice_agent_url is set, the
voice router's door (port 8098, lote J1b), until the Supervisor stops the container (SIGTERM)."""
import logging
import signal
import threading

from . import briefing, settings, voice_http, web
from .center import Center
from .events import Listener
from .schedule import Preparer, Scheduler, ha_time_zone
from .voice import Router


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    log = logging.getLogger('iq_edge')
    applied = settings.apply_briefing_options()  # the Bom dia's options -> IQ_BRIEFING_* before anything reads them
    if applied:
        log.info('Opções do Bom dia: %s.', ', '.join(applied))
    applied = settings.apply_voice_options()  # the voice router's (voice_agent, voice_route, voice_agent_url...) -> IQ_VOICE_*
    if applied:
        log.info('Opções do roteador de voz: %s.', ', '.join(applied))  # (only the names: voice_chat_agent is there when it is set)
    center = Center()
    briefing.usar_centro(center)  # the Bom dia's text by the center's AI (lote A5); the rule text when not paired
    scheduler = Scheduler(zone_name=lambda: center.time_zone or ha_time_zone(), preparer=Preparer())  # + the Bom dia prepared ahead
    listener = Listener() if settings.ha_token() else None  # outside Home Assistant (no token) there is no event to hear
    router, voice_server = None, None
    if settings.voice_enabled():  # an agent is set; with no voice option the add-on is what 0.2.4 was: no door, no /data/voice.json
        if settings.voice_agent_kind() == 'refused':  # (the address itself is never logged)
            log.warning('O endereço do assistente (voice_agent_url) foi recusado: use http ou https, sem usuário nem senha dentro, '
                        'e não o endereço do próprio roteador.')
        router = Router(center)
        try:
            voice_server = voice_http.start(router)  # for Home Assistant Core's integration; the tab shows its address and password
        except OSError:  # the port is taken or /data cannot be written: the rest of the add-on works as before, without the router
            router = None
            log.warning('Não consegui abrir o roteador de voz (porta %s).', settings.voice_port())
    server = web.start(web.App(center, listener, router))
    log.info('IQ Edge %s (%s): aba na porta %s; plataforma %s; %s.', settings.VERSION, settings.arch(), settings.ingress_port(),
             settings.center_url(), 'pareado' if center.paired() else 'aguardando o código de pareamento')
    if voice_server:
        chat_agent = settings.voice_chat_agent()  # 0.2.7: the entity that only chats (its id is no secret); empty = the center's Claude
        log.info('Roteador de voz na porta %s; modo %s; %s; conversa geral %s.', settings.voice_port(), settings.voice_route_mode(),
                 {'url': 'assistente por endereço', 'refused': 'endereço do assistente recusado', 'entity': 'assistente escolhido'}[
                     settings.voice_agent_kind()], f'pelo agente de conversa {chat_agent}' if chat_agent else 'pelo centro')
    stopped = threading.Event()

    def stop(*_):
        center.stop.set()
        scheduler.stop.set()
        if listener:
            listener.close()
        stopped.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threads = [threading.Thread(target=center.run, name='iq-edge-center', daemon=True),
               threading.Thread(target=scheduler.run, name='iq-edge-schedule', daemon=True)]
    if listener:
        threads.append(threading.Thread(target=listener.run, name='iq-edge-events', daemon=True))
    for thread in threads:
        thread.start()
    stopped.wait()
    server.shutdown()
    if voice_server:
        voice_server.shutdown()
        voice_server.server_close()
    log.info('IQ Edge parado.')


if __name__ == '__main__':
    main()
