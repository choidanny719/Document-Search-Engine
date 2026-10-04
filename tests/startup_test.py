from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest


class StartupTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.data = self.root / 'documents'
        self.data.mkdir()
        (self.data / 'example.txt').write_text('search example', encoding='utf-8')

    def run_server(self, *arguments):
        return subprocess.run(
            [sys.argv[1], '--data', str(self.data), '--web', sys.argv[2], *arguments],
            capture_output=True, text=True, timeout=5)

    def assert_failure(self, message, *arguments):
        result = self.run_server(*arguments)
        self.assertEqual(result.returncode, 1, result)
        self.assertIn(message, result.stderr)
        self.assertNotIn('Listening on', result.stdout)

    def test_help_exits_without_starting_a_server(self):
        result = self.run_server('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('search_server [--data directory]', result.stdout)
        self.assertEqual(result.stderr, '')

    def test_rejects_invalid_ports(self):
        for value in ['', '-1', '65536', 'abc', '80x', ' 80', '999999999999999999']:
            with self.subTest(value=value):
                self.assert_failure('Number must be between 0 and 65535', '--port', value)

    def test_rejects_unknown_options_and_missing_values(self):
        self.assert_failure('Unknown option: --unknown', '--unknown', 'value')
        self.assert_failure('Unknown option: unexpected', 'unexpected', 'argument')
        for option in ['--data', '--web', '--host', '--port']:
            with self.subTest(option=option):
                self.assert_failure('Missing value for ' + option, option)

    def test_rejects_missing_corpus_and_web_files(self):
        self.assert_failure('Document directory does not exist', '--data', str(self.root / 'missing'))
        self.assert_failure('Cannot read web/index.html', '--web', str(self.root))

    def test_rejects_an_occupied_port(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            self.assert_failure('Could not bind the server port', '--port', str(listener.getsockname()[1]))

    def test_rejects_an_invalid_bind_address(self):
        self.assert_failure('Could not bind the server port', '--host', '256.256.256.256', '--port', '0')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
