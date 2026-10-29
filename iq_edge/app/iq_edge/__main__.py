"""python -m iq_edge: the tab (ingress, port 8099), the platform loop (pairing, long-poll, heartbeat, rotation) and the Bom dia's
automatic speech, until the Supervisor stops the container (SIGTERM)."""
import logging
import signal
import threading

from . import briefing, settings, web
from .center import Center
from .schedule import Scheduler, ha_time_zone


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    log = logging.getLogger('iq_edge')
    center = Center()
    briefing.usar_centro(center)  # the Bom dia's text by the center's AI (lote A5); the rule text when not paired
    scheduler = Scheduler(zone_name=lambda: center.time_zone or ha_time_zone())
    server = web.start(web.App(center))
    log.info('IQ Edge %s (%s): aba na porta %s; plataforma %s; %s.', settings.VERSION, settings.arch(), settings.ingress_port(),
             settings.center_url(), 'pareado' if center.paired() else 'aguardando o código de pareamento')
    stopped = threading.Event()

    def stop(*_):
        center.stop.set()
        scheduler.stop.set()
        stopped.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threads = [threading.Thread(target=center.run, name='iq-edge-center', daemon=True),
               threading.Thread(target=scheduler.run, name='iq-edge-schedule', daemon=True)]
    for thread in threads:
        thread.start()
    stopped.wait()
    server.shutdown()
    log.info('IQ Edge parado.')


if __name__ == '__main__':
    main()
