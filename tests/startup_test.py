from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.parse

from server_support import Server


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

    def test_rejects_binary_and_oversized_corpora_before_listening(self):
        path = self.data / 'example.txt'
        for content, message in [(b'prefix\x00suffix', 'Document contains binary data'),
                                 (b'x' * (1024 * 1024 + 1), 'Document size limit exceeded')]:
            with self.subTest(message=message):
                path.write_bytes(content)
                self.assert_failure(message, '--port', '0')

    def test_help_does_not_require_existing_data_or_web_directories(self):
        result = self.run_server('--data', str(self.root / 'missing-data'),
                                 '--web', str(self.root / 'missing-web'), '--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('search_server [--data directory]', result.stdout)
        self.assertEqual(result.stderr, '')

    def test_absolute_paths_work_outside_the_project_directory(self):
        data = self.root / 'documents with spaces'
        web = self.root / 'web with spaces'
        data.mkdir()
        web.mkdir()
        (data / 'custom.md').write_text('custom corpus', encoding='utf-8')
        page = '<!doctype html>\n<title>Custom café</title>\r\n'
        (web / 'index.html').write_bytes(page.encode('utf-8'))
        with Server(data, web, cwd=self.root) as server:
            status, body, headers = server.request('/')
            self.assertEqual(status, 200)
            self.assertEqual(body, page)
            self.assertEqual(headers['Content-Type'], 'text/html; charset=utf-8')
            self.assertEqual(int(headers['Content-Length']), len(page.encode('utf-8')))
            self.assertEqual(server.request('/health')[1],
                             {'status': 'ok', 'documents': 1, 'terms': 2})
            self.assertEqual(server.request('/document?id=custom.md')[:2],
                             (200, 'custom corpus'))

    def test_relative_paths_resolve_from_the_working_directory(self):
        web = self.root / 'site'
        web.mkdir()
        (web / 'index.html').write_text('relative web directory', encoding='utf-8')
        with Server('documents', 'site', cwd=self.root) as server:
            self.assertEqual(server.request('/')[:2], (200, 'relative web directory'))
            status, body, _ = server.request('/search?q=example')
            self.assertEqual(status, 200)
            self.assertEqual(body['total'], 1)
            self.assertEqual(body['results'][0]['id'], 'example.txt')

    def test_repeated_options_use_the_last_value(self):
        web = self.root / 'site'
        web.mkdir()
        (web / 'index.html').write_text('selected page', encoding='utf-8')
        with Server(self.root / 'missing-data', self.root / 'missing-web',
                    '--host', '256.256.256.256', '--port', '1',
                    '--data', str(self.data), '--web', str(web),
                    '--host', '127.0.0.1', '--port', '0') as server:
            self.assertEqual(server.request('/')[:2], (200, 'selected page'))
            self.assertEqual(server.request('/document?id=example.txt')[:2],
                             (200, 'search example'))

    def test_restart_rebuilds_the_index_from_current_files(self):
        (self.data / 'removed.txt').write_text('obsolete record', encoding='utf-8')
        with Server(self.data, sys.argv[2]) as server:
            port = str(urllib.parse.urlsplit(server.base).port)
            (self.data / 'example.txt').write_text('replacement content', encoding='utf-8')
            (self.data / 'removed.txt').unlink()
            (self.data / 'added.md').write_text('fresh record', encoding='utf-8')
            self.assertEqual(server.request('/document?id=example.txt')[:2],
                             (200, 'search example'))
            self.assertEqual(server.request('/document?id=removed.txt')[0], 200)
            self.assertEqual(server.request('/document?id=added.md')[0], 404)
        with Server(self.data, sys.argv[2], '--port', port) as restarted:
            self.assertEqual(restarted.request('/health')[1],
                             {'status': 'ok', 'documents': 2, 'terms': 4})
            self.assertEqual(restarted.request('/document?id=example.txt')[:2],
                             (200, 'replacement content'))
            self.assertEqual(restarted.request('/document?id=added.md')[:2], (200, 'fresh record'))
            self.assertEqual(restarted.request('/document?id=removed.txt')[0], 404)
            self.assertEqual(restarted.request('/search?q=obsolete+example')[1]['total'], 0)
            result = restarted.request('/search?q=replacement+fresh')[1]
            self.assertEqual(result['total'], 2)
            self.assertEqual({hit['id'] for hit in result['results']}, {'example.txt', 'added.md'})

    def test_servers_keep_separate_corpora_and_lifetimes(self):
        other = self.root / 'other'
        other.mkdir()
        (other / 'example.txt').write_text('independent content', encoding='utf-8')
        with Server(other, sys.argv[2]) as second:
            with Server(self.data, sys.argv[2]) as first:
                self.assertNotEqual(first.base, second.base)
                for server, present, absent in [(first, 'search', 'independent'),
                                                (second, 'independent', 'search')]:
                    self.assertEqual(server.request('/search?q=' + present)[1]['total'], 1)
                    self.assertEqual(server.request('/search?q=' + absent)[1]['total'], 0)
                self.assertEqual(first.request('/document?id=example.txt')[1], 'search example')
                self.assertEqual(second.request('/document?id=example.txt')[1], 'independent content')
            self.assertEqual(second.request('/health')[0], 200)
            self.assertEqual(second.request('/search?q=independent')[1]['total'], 1)

    def test_corrected_corpus_starts_after_a_failed_load(self):
        broken = self.data / 'broken.txt'
        broken.write_bytes(b'bad\x00data')
        self.assert_failure('Document contains binary data', '--port', '0')
        broken.write_text('repaired document', encoding='utf-8')
        with Server(self.data, sys.argv[2]) as server:
            self.assertEqual(server.request('/health')[1],
                             {'status': 'ok', 'documents': 2, 'terms': 4})
            self.assertEqual(server.request('/document?id=broken.txt')[:2],
                             (200, 'repaired document'))
            self.assertEqual(server.request('/search?q=search+repaired')[1]['total'], 2)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
