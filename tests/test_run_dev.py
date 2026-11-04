import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class RunDevTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'run-dev.sh', self.root / 'run-dev.sh')
        python = self.root / '.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.write_text('''#!/usr/bin/env bash
if [[ "$1" == '-c' ]]; then exit 0; fi
printf 'LAUNCHED:%s:%s:%s:%s:%s:%s\\n' "$PWD" "$TELEGRAM_API_ID" "$TELEGRAM_API_HASH" "$APP_PASSWORD" "$DATA_DIR" "$*"
''')
        python.chmod(0o700)

    def run_script(self, api_id='12345', api_hash='a' * 32, password='local-test-password'):
        return subprocess.run(
            ['bash', str(self.root / 'run-dev.sh')], cwd='/',
            input=f'{api_id}\n{api_hash}\n{password}\n', text=True,
            capture_output=True, timeout=10,
            env={**os.environ, 'APP_USER': 'admin'},
        )

    def test_exports_credentials_and_starts_python_from_repository(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'LAUNCHED:{self.root}:12345:{"a" * 32}:local-test-password:{self.root}/.data:', result.stdout)
        self.assertIn('-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log', result.stdout)
        self.assertFalse((self.root / '.env').exists())

    def test_invalid_inputs_never_start_server_or_print_credentials(self):
        for inputs, message in [
            ({'api_id': 'abc'}, 'API ID inválido'),
            ({'api_hash': 'not-a-hash'}, 'API hash inválido'),
            ({'password': 'x' * 11}, 'Senha inválida'),
        ]:
            with self.subTest(inputs=inputs):
                result = self.run_script(**inputs)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertNotIn('LAUNCHED', result.stdout)
                self.assertNotIn('local-test-password', result.stdout + result.stderr)

    def test_incomplete_input_does_not_start_server(self):
        result = subprocess.run(['bash', str(self.root / 'run-dev.sh')],
                                input='12345\n', text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('LAUNCHED', result.stdout)

    def test_accepts_password_with_exactly_twelve_characters(self):
        result = self.run_script(password='x' * 12)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('LAUNCHED:', result.stdout)
