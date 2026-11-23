"""The add-on's package as the Supervisor reads it: config.yaml (the same version as the code, ingress on 8099, Core API only, the
voice router's port 8098 not published on the host, amd64 + aarch64, the options), the Dockerfile (a fixed base image tag, no build.yaml), repository.yaml and the files a person sees."""
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
        for key in ('hassio_api', 'host_network', 'privileged', 'full_access', 'docker_api'):
            self.assertNotIn(key, config)  # nothing more than the Core API
        # 0.2.5: the voice router's port for Home Assistant Core, on the internal network; null = NOT published on the host by default
        self.assertEqual(config['ports'], {'8098/tcp': None})
        self.assertEqual(settings.voice_port(), 8098)
        self.assertEqual(config['options'], {'center_url': 'https://business.iqautom8.com', 'pairing_code': ''})
        # lote A5: the Bom dia's options are all optional (out of `options`, so they stay unset until someone fills them in)
        self.assertEqual(set(config['schema']), {'center_url', 'pairing_code'} | set(settings.BRIEFING_OPTIONS) | set(settings.VOICE_OPTIONS))
        for key in settings.VOICE_OPTIONS:  # 0.2.5: optional, and out of `options`: empty = what the add-on did before
            self.assertNotIn(key, config['options'])
        self.assertEqual(config['schema']['voice_route'], 'list(' + '|'.join(settings.VOICE_MODES) + ')?')
        agent = re.fullmatch(r'match\((.*)\)\?', config['schema']['voice_agent']).group(1)
        self.assertEqual(re.compile(agent).pattern, '^conversation\\.[a-z0-9_]+$')
        self.assertTrue(re.match(agent, 'conversation.iq_assistant'))
        for wrong in ('light.sala', 'conversation.', 'conversation.A', 'conversation.a b', 'xconversation.a'):
            self.assertIsNone(re.match(agent, wrong), wrong)
            self.assertIsNone(settings.VOICE_AGENT.fullmatch(wrong), wrong)  # the code reads exactly what the schema lets in
        self.assertEqual(config['schema']['greet_names'], 'bool?')  # 0.2.2: a switch; 0.2.3: unset = off (no names)
        for key in settings.DAY_OPTIONS:  # 0.2.4: an optional list of weekday names (a one-element YAML list is the Supervisor's list form)
            self.assertEqual(config['schema'][key], ['list(' + '|'.join(settings.WEEKDAYS) + ')?'], key)
            self.assertNotIn(key, config['options'])
        for key, kind in config['schema'].items():
            if key in settings.DAY_OPTIONS:
                continue
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
            network = yaml.safe_load((ADDON / 'translations' / f'{name}.yaml').read_text(encoding='utf-8'))['network']
            self.assertEqual(set(network), set(config['ports']), name)  # the port's description, in both languages
            self.assertTrue(all(isinstance(text, str) and text for text in network.values()), name)

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
            'prepare_at': '05:45', 'greet_names': False, 'trash_organic_days': ['thursday', 'monday'],
            'trash_recycling_days': ['saturday']}, private=False)
        applied = settings.apply_briefing_options()
        self.assertEqual(set(applied), set(settings.BRIEFING_OPTIONS) - {'tts_voice_en'})  # an empty option sets nothing
        self.assertEqual((os.environ['IQ_BRIEFING_WEATHER_ENTITY'], os.environ['IQ_BRIEFING_TEMP_SENSOR'], os.environ['IQ_BRIEFING_CARD_SECONDS'],
                          os.environ['IQ_BRIEFING_PREPARE_MINUTES'], os.environ['IQ_BRIEFING_PREPARE_AT']),
                         ('weather.casa', 'sensor.fora', '60', '45', '05:45'))
        self.assertNotIn('IQ_BRIEFING_TTS_VOICE_EN', os.environ)
        self.assertEqual((os.environ['IQ_BRIEFING_TRASH_ORGANIC_DAYS'], os.environ['IQ_BRIEFING_TRASH_RECYCLING_DAYS']),
                         ('monday,thursday', 'saturday'))  # the Supervisor's list becomes the valid names, in week order
        self.assertEqual(os.environ['IQ_BRIEFING_GREET_NAMES'], 'False')  # the Supervisor's JSON false, as text
        from iq_edge import briefing, prefs, schedule
        self.assertFalse(briefing._nomes_ligados())
        prefs.save_local(self.prefs())
        cfg = briefing.speaker_config()
        self.assertEqual((cfg['atraso'], cfg['espera'], cfg['ocupado'], cfg['voz_pt'], cfg['voz_en'], cfg['satellite']),
                         (3.5, 12.0, 'interromper', 'voz-pt', 'voz-pt', 'assist_satellite.cozinha'))
        self.assertEqual((briefing.satellite(), schedule.prepare_minutes()), ('assist_satellite.cozinha', 45))

    def test_greet_names_true_false_or_unset(self):
        """0.2.2: `greet_names` is a boolean: the Supervisor writes JSON true/false. 0.2.3: unset (or no options file) means off: no
        names (the company's default); `true` brings the names back."""
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        from iq_edge import briefing
        for options, variable, on in (({'greet_names': False}, 'False', False), ({'greet_names': True}, 'True', True), ({}, None, False)):
            os.environ.pop('IQ_BRIEFING_GREET_NAMES', None)
            settings.write_json(settings.data_dir() / 'options.json', dict(options, center_url='https://business.iqautom8.com'), private=False)
            applied = settings.apply_briefing_options()
            self.assertEqual(os.environ.get('IQ_BRIEFING_GREET_NAMES'), variable, options)
            self.assertEqual('greet_names' in applied, variable is not None, options)
            self.assertEqual(briefing._nomes_ligados(), on, options)
        os.environ.pop('IQ_BRIEFING_GREET_NAMES', None)
        (settings.data_dir() / 'options.json').unlink()  # no options file at all
        self.assertEqual(settings.apply_briefing_options(), [])
        self.assertFalse(briefing._nomes_ligados())

    def test_weekday_options_list_string_or_invalid(self):
        """0.2.4: `trash_organic_days` and `trash_recycling_days` come from the Supervisor as a list; the variable is the valid names
        separated by commas (lower case, no repeats, week order). A plain string works too; other options still skip a list."""
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        variable = 'IQ_BRIEFING_TRASH_ORGANIC_DAYS'
        cases = (
            (['tuesday', 'friday'], 'tuesday,friday'),
            (['Friday', ' TUESDAY ', 'friday', 'tuesday'], 'tuesday,friday'),  # case, spaces and repeats
            (['sunday', 'funday', 7, None, {'a': 1}], 'sunday'),  # only the seven names count
            ('tuesday, thursday', 'tuesday,thursday'),  # a plain string
            ('Thursday;monday saturday', 'monday,thursday,saturday'),
            ([], None), ('', None), (None, None), (['someday'], None), ('someday', None), (5, None), (True, None), ({'monday': 1}, None),
        )
        for value, expected in cases:
            os.environ.pop(variable, None)
            settings.write_json(settings.data_dir() / 'options.json', {'center_url': 'https://business.iqautom8.com',
                                'trash_organic_days': value}, private=False)
            applied = settings.apply_briefing_options()
            self.assertEqual(os.environ.get(variable), expected, value)  # nothing valid: nothing set
            self.assertEqual('trash_organic_days' in applied, expected is not None, value)
        self.assertNotIn('IQ_BRIEFING_TRASH_RECYCLING_DAYS', os.environ)
        settings.write_json(settings.data_dir() / 'options.json', {'center_url': 'https://business.iqautom8.com',
                            'weather_entity': ['weather.casa'], 'greet_names': ['true']}, private=False)
        os.environ.pop('IQ_BRIEFING_WEATHER_ENTITY', None)
        os.environ.pop('IQ_BRIEFING_GREET_NAMES', None)
        self.assertEqual(settings.apply_briefing_options(), [])  # a list in another option is still skipped
        self.assertEqual(settings.day_names('Monday, someday'), ('monday',))


if __name__ == '__main__':
    unittest.main()
