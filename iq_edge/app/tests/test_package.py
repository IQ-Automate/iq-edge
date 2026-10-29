"""The add-on's package as the Supervisor reads it: config.yaml (the same version as the code, ingress on 8099, Core API only,
amd64 + aarch64, the two options), the Dockerfile (a fixed base image tag, no build.yaml), repository.yaml and the files a person sees."""
import re
import unittest
from pathlib import Path

import yaml

import iq_edge

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
        self.assertEqual(set(config['schema']), {'center_url', 'pairing_code'})
        self.assertTrue(config['schema']['pairing_code'].endswith('?'))

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


if __name__ == '__main__':
    unittest.main()
