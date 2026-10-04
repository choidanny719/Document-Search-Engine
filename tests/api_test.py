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


class ServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        root = Path(cls.folder.name)
        for name, text in cls.documents.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text if isinstance(text, bytes) else text.encode('utf-8'))
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
    def request(cls, path, method='GET', data=None):
        request = urllib.request.Request(cls.base + path, data=data, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read().decode('utf-8')
            if body and 'application/json' in response.headers.get('Content-Type', ''):
                body = json.loads(body)
            return response.status, body, response.headers

    def search(self, **parameters):
        return self.request('/search?' + urllib.parse.urlencode(parameters))


class ApiTest(ServerTestCase):
    documents = {
        'a.txt': 'database row locking',
        'b.md': 'database backup guide',
        'c.txt': 'cooking pasta guide',
    }

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

    def test_missing_document_id_and_unsupported_method(self):
        for path in ['/document', '/document?id=']:
            status, body, _ = self.request(path)
            self.assertEqual(status, 404)
            self.assertEqual(body['error'], 'Document not found')
        status, body, _ = self.request('/search?q=database', method='POST', data=b'')
        self.assertIn(status, [404, 405])
        self.assertIn('error', body)

    def test_head_preserves_headers_without_a_response_body(self):
        for path in ['/', '/health', '/search?q=database', '/document?id=a.txt']:
            with self.subTest(path=path):
                status, body, headers = self.request(path, method='HEAD')
                self.assertEqual(status, 200)
                self.assertEqual(body, '')
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
                self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])


class ApiBoundaryTest(ServerTestCase):
    documents = {
        **{f'ranked/{number:03}.txt': 'ranking' for number in range(110)},
        'nested/a &+#?.md': 'encoded filename',
        'empty.txt': '',
        'exact.txt': 'x' * 200,
        'long.txt': 'y' * 201,
        'whitespace.txt': ' \n\talpha\r\n beta\t\t gamma',
        'unicode.txt': 'unicode ' + 'a' * 191 + 'é',
        'invalid.txt': b'encoding \xff value',
        'markup.txt': '<script>alert("example")</script>',
    }

    def test_query_byte_boundaries(self):
        for query in ['ranking' + ' ' * 505, 'ranking' + 'é' * 252 + 'a', 'z' * 512]:
            with self.subTest(query=query):
                self.assertEqual(len(query.encode('utf-8')), 512)
                status, body, _ = self.search(q=query)
                self.assertEqual(status, 200)
                self.assertEqual(body['query'], query)
        query = 'ranking' + 'é' * 253
        self.assertEqual(len(query.encode('utf-8')), 513)
        self.assertEqual(self.search(q=query)[0], 400)

    def test_result_limits_and_tie_order(self):
        for limit in [1, 10, 100]:
            with self.subTest(limit=limit):
                status, body, _ = self.search(q='ranking', limit=limit)
                self.assertEqual(status, 200)
                self.assertEqual(body['total'], 110)
                self.assertEqual([hit['id'] for hit in body['results']],
                                 [f'ranked/{number:03}.txt' for number in range(limit)])
        _, body, _ = self.search(q='ranking')
        self.assertEqual(len(body['results']), 10)

    def test_encoded_filenames_and_empty_document(self):
        for identifier in ['nested/a &+#?.md', 'empty.txt', 'markup.txt']:
            with self.subTest(identifier=identifier):
                status, body, headers = self.request('/document?' + urllib.parse.urlencode({'id': identifier}))
                self.assertEqual(status, 200)
                self.assertEqual(body, self.documents[identifier])
                self.assertIn('text/plain', headers['Content-Type'])
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        _, body, _ = self.search(q='encoded')
        self.assertEqual(body['results'][0]['id'], 'nested/a &+#?.md')

    def test_preview_length_and_whitespace(self):
        for query, expected in [('x' * 200, 'x' * 200),
                                ('y' * 201, 'y' * 200 + '...'),
                                ('alpha', 'alpha beta gamma')]:
            with self.subTest(query=query):
                status, body, _ = self.search(q=query)
                self.assertEqual(status, 200)
                self.assertEqual(body['results'][0]['preview'], expected)

    def test_non_ascii_previews_remain_valid_json(self):
        for query, expected in [('unicode', 'unicode ' + 'a' * 191 + '\ufffd...'),
                                ('encoding', 'encoding \ufffd value')]:
            with self.subTest(query=query):
                status, body, _ = self.search(q=query)
                self.assertEqual(status, 200)
                self.assertEqual(body['results'][0]['preview'], expected)


class EmptyCorpusApiTest(ServerTestCase):
    documents = {}

    def test_empty_corpus_is_healthy_and_searchable(self):
        status, body, _ = self.request('/health')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'status': 'ok', 'documents': 0, 'terms': 0})
        for mode in ['any', 'all']:
            status, body, _ = self.search(q='search', mode=mode)
            self.assertEqual(status, 200)
            self.assertEqual(body['total'], 0)
            self.assertEqual(body['results'], [])
        self.assertEqual(self.request('/document?id=missing.txt')[0], 404)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
