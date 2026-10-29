"""The add-on's package as the Supervisor reads it: config.yaml (the same version as the code, ingress on 8099, Core API only,
amd64 + aarch64, the two options), the Dockerfile (a fixed base image tag, no build.yaml), repository.yaml and the files a person sees."""
import os
import re
import unittest
from pathlib import Path
from unittest import mock

import yaml

import iq_edge
from iq_edge import settings
from tests.fakes import EdgeCase

ADDON = Path(__file__).resolve().parents[2]
REPO = ADDON.parent


class PackageTests(unittest.TestCase):
    def test_config_yaml(self):
        config = yaml.safe_load((ADDON / 'config.yaml').read_text(encoding='utf-8'))
        self.assertEqual(config['version'], iq_edge.__version__)
        self.assertEqual((config['name'], config['slug'], sorted(config['arch'])), ('IQ Edge', 'iq_edge', ['aarch64', 'amd64']))
        self.assertEqual((config['init'], config['ingress'], config['ingress_port'], config['panel_title'], config['panel_admin']),
                         (False, True, 8099, 'IQ', False))
        self.assertTrue(config['homeassistant_api'])
        for key in ('hassio_api', 'host_network', 'privileged', 'full_access', 'ports', 'docker_api'):
            self.assertNotIn(key, config)  # nothing more than the Core API
        self.assertEqual(config['options'], {'center_url': 'https://business.iqautom8.com', 'pairing_code': ''})
        # lote A5: the Bom dia's options are all optional (out of `options`, so they stay unset until someone fills them in)
        self.assertEqual(set(config['schema']), {'center_url', 'pairing_code'} | set(settings.BRIEFING_OPTIONS))
        for key, kind in config['schema'].items():
            if key != 'center_url':
                self.assertTrue(kind.endswith('?'), key)
            match = re.fullmatch(r'match\((.*)\)\??', kind)
            if match:
                re.compile(match.group(1))
        self.assertTrue(re.fullmatch(config['schema']['prepare_at'][6:-2], '06:00'))
        self.assertIsNone(re.fullmatch(config['schema']['prepare_at'][6:-2], '24:00'))
        self.assertTrue(re.match(config['schema']['satellite'][6:-2], 'assist_satellite.cozinha'))
        for name in ('en', 'pt-BR'):
            translations = yaml.safe_load((ADDON / 'translations' / f'{name}.yaml').read_text(encoding='utf-8'))['configuration']
            self.assertEqual(set(translations), set(config['schema']), name)
            self.assertTrue(all(item.get('name') and item.get('description') for item in translations.values()), name)

    def test_dockerfile_and_repository(self):
        dockerfile = (ADDON / 'Dockerfile').read_text(encoding='utf-8')
        self.assertRegex(dockerfile, r'ARG BUILD_FROM=ghcr\.io/home-assistant/base-python:\d+\.\d+-alpine\d+\.\d+\n')
        self.assertIn('FROM ${BUILD_FROM}', dockerfile)
        self.assertIn('CMD ["python3", "-m", "iq_edge"]', dockerfile)
        self.assertFalse((ADDON / 'build.yaml').exists())
        requirements = (ADDON / 'app' / 'requirements.txt').read_text(encoding='utf-8')
        self.assertEqual(sorted(re.findall(r'^([A-Za-z0-9_-]+)==', requirements, re.M)), ['PyYAML', 'requests'])
        repository = yaml.safe_load((REPO / 'repository.yaml').read_text(encoding='utf-8'))
        self.assertEqual(repository['name'], 'IQ Autom8')
        for name in ('DOCS.md', 'CHANGELOG.md', 'icon.png', 'logo.png', 'translations/en.yaml', 'translations/pt-BR.yaml'):
            self.assertTrue((ADDON / name).exists(), name)
        self.assertIn(f'## {iq_edge.__version__}', (ADDON / 'CHANGELOG.md').read_text(encoding='utf-8'))
        self.assertEqual((ADDON / 'icon.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')



class BriefingOptionsTests(EdgeCase):
    """Lote A5: the Bom dia's options (config.yaml) become, at start, the IQ_BRIEFING_* variables that briefing.py reads."""

    def test_options_become_the_briefing_variables(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for variable in settings.BRIEFING_OPTIONS.values():
            os.environ.pop(variable, None)
        settings.write_json(settings.data_dir() / 'options.json', {
            'center_url': 'https://business.iqautom8.com', 'pairing_code': '', 'weather_entity': 'weather.casa',
            'temp_sensor': 'sensor.fora', 'satellite': 'assist_satellite.cozinha', 'tts_voice': 'voz-pt', 'tts_voice_en': '',
            'speaker_delay': 3.5, 'speaker_wait': 12, 'speaker_busy': 'interrupt', 'card_seconds': 60, 'prepare_minutes': 45,
            'prepare_at': '05:45'}, private=False)
        applied = settings.apply_briefing_options()
        self.assertEqual(set(applied), set(settings.BRIEFING_OPTIONS) - {'tts_voice_en'})  # an empty option sets nothing
        self.assertEqual((os.environ['IQ_BRIEFING_WEATHER_ENTITY'], os.environ['IQ_BRIEFING_TEMP_SENSOR'], os.environ['IQ_BRIEFING_CARD_SECONDS'],
                          os.environ['IQ_BRIEFING_PREPARE_MINUTES'], os.environ['IQ_BRIEFING_PREPARE_AT']),
                         ('weather.casa', 'sensor.fora', '60', '45', '05:45'))
        self.assertNotIn('IQ_BRIEFING_TTS_VOICE_EN', os.environ)
        from iq_edge import briefing, prefs, schedule
        prefs.save_local(self.prefs())
        cfg = briefing.speaker_config()
        self.assertEqual((cfg['atraso'], cfg['espera'], cfg['ocupado'], cfg['voz_pt'], cfg['voz_en'], cfg['satellite']),
                         (3.5, 12.0, 'interromper', 'voz-pt', 'voz-pt', 'assist_satellite.cozinha'))
        self.assertEqual((briefing.satellite(), schedule.prepare_minutes()), ('assist_satellite.cozinha', 45))


if __name__ == '__main__':
    unittest.main()
