"""python -m iq_edge: the tab (ingress, port 8099), the platform loop (pairing, long-poll, heartbeat, rotation), the Bom dia's
automatic speech and Home Assistant's event iq_bom_dia (websocket, lote A5), until the Supervisor stops the container (SIGTERM)."""
import logging
import signal
import threading

from . import briefing, settings, web
from .center import Center
from .events import Listener
from .schedule import Preparer, Scheduler, ha_time_zone


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    log = logging.getLogger('iq_edge')
    center = Center()
    briefing.usar_centro(center)  # the Bom dia's text by the center's AI (lote A5); the rule text when not paired
    scheduler = Scheduler(zone_name=lambda: center.time_zone or ha_time_zone(), preparer=Preparer())  # + the Bom dia prepared ahead
    listener = Listener() if settings.ha_token() else None  # outside Home Assistant (no token) there is no event to hear
    server = web.start(web.App(center, listener))
    log.info('IQ Edge %s (%s): aba na porta %s; plataforma %s; %s.', settings.VERSION, settings.arch(), settings.ingress_port(),
             settings.center_url(), 'pareado' if center.paired() else 'aguardando o código de pareamento')
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
    log.info('IQ Edge parado.')


if __name__ == '__main__':
    main()
