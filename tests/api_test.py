import concurrent.futures
import json
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        root = Path(cls.folder.name)
        (root / 'a.txt').write_text('database row locking', encoding='utf-8')
        (root / 'b.md').write_text('database backup guide', encoding='utf-8')
        (root / 'c.txt').write_text('cooking pasta guide', encoding='utf-8')
        cls.process = subprocess.Popen(
            [sys.argv[1], '--data', str(root), '--web', sys.argv[2], '--port', '0'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        cls.addClassCleanup(cls.stop_server)
        if not select.select([cls.process.stdout], [], [], 20)[0]:
            raise RuntimeError('Server did not report its listening address')
        line = cls.process.stdout.readline()
        match = re.search(r'http://127\.0\.0\.1:(\d+)', line)
        if not match:
            raise RuntimeError(f'Server failed to start: {line} {cls.process.stderr.read()}')
        cls.base = f'http://127.0.0.1:{match.group(1)}'
        for _ in range(100):
            try:
                cls.request('/health')
                return
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.02)
        raise RuntimeError('Server did not become ready')

    @classmethod
    def stop_server(cls):
        cls.process.terminate()
        try:
            cls.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.communicate()

    @classmethod
    def request(cls, path):
        try:
            response = urllib.request.urlopen(cls.base + path, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read().decode('utf-8')
            if 'application/json' in response.headers.get('Content-Type', ''):
                body = json.loads(body)
            return response.status, body, response.headers

    def search(self, **parameters):
        return self.request('/search?' + urllib.parse.urlencode(parameters))

    def test_health_and_page(self):
        status, body, _ = self.request('/health')
        self.assertEqual(status, 200)
        self.assertEqual(body['documents'], 3)
        self.assertEqual(body['terms'], 7)
        status, body, headers = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn('Document Search Engine', body)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')

    def test_ranking_and_limit(self):
        status, body, _ = self.search(q='database locking', limit=1)
        self.assertEqual(status, 200)
        self.assertEqual(body['total'], 2)
        self.assertEqual(len(body['results']), 1)
        self.assertEqual(body['results'][0]['id'], 'a.txt')
        self.assertGreater(body['results'][0]['score'], 0)
        self.assertGreaterEqual(body['elapsed_ms'], 0)

    def test_matching_modes(self):
        _, body, _ = self.search(q='database locking', mode='all')
        self.assertEqual(body['total'], 1)
        _, body, _ = self.search(q='database absent', mode='all')
        self.assertEqual(body['results'], [])
        _, body, _ = self.search(q='database absent', mode='any')
        self.assertEqual(body['total'], 2)

    def test_invalid_parameters(self):
        cases = [{}, {'q': ''}, {'q': '!!!'}, {'q': 'a' * 513},
                 {'q': 'database', 'mode': 'none'}]
        cases.extend({'q': 'database', 'limit': value}
                     for value in ['', '0', '-1', '101', 'abc', '1x', '999999999999999'])
        for parameters in cases:
            with self.subTest(parameters=parameters):
                status, body, _ = self.search(**parameters)
                self.assertEqual(status, 400)
                self.assertIn('error', body)

    def test_document_lookup_does_not_read_arbitrary_paths(self):
        status, body, _ = self.request('/document?id=a.txt')
        self.assertEqual(status, 200)
        self.assertEqual(body, 'database row locking')
        for identifier in ['missing.txt', '../README.md', '/etc/passwd']:
            status, body, _ = self.request('/document?' + urllib.parse.urlencode({'id': identifier}))
            self.assertEqual(status, 404)
            self.assertEqual(body['error'], 'Document not found')
        self.assertEqual(self.request('/missing')[0], 404)

    def test_concurrent_queries_return_consistent_results(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            responses = list(pool.map(lambda _: self.search(q='database locking'), range(60)))
        for status, body, _ in responses:
            self.assertEqual(status, 200)
            self.assertEqual(body['total'], 2)
            self.assertEqual(body['results'][0]['id'], 'a.txt')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
