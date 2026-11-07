import concurrent.futures
import http.client
import json
from pathlib import Path
import sys
import unittest
import urllib.parse
import urllib.request

from server_support import ServerTestCase


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

    def test_query_normalization_preserves_the_original_response_query(self):
        query = ' \tDATABASE---ROW+locking!\n'
        status, body, headers = self.search(q=query, mode='all')
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {'query', 'mode', 'total', 'elapsed_ms', 'results'})
        self.assertEqual(body['query'], query)
        self.assertEqual(body['mode'], 'all')
        self.assertEqual(body['total'], 1)
        self.assertEqual(len(body['results']), 1)
        hit = body['results'][0]
        self.assertEqual(set(hit), {'id', 'title', 'score', 'preview'})
        self.assertEqual(hit['id'], 'a.txt')
        self.assertEqual(hit['title'], 'a')
        self.assertAlmostEqual(hit['score'], 1.0, places=12)
        self.assertEqual(hit['preview'], self.documents['a.txt'])
        self.assertIn('application/json', headers['Content-Type'])

    def test_defaults_and_unknown_parameters_preserve_search_results(self):
        _, expected, _ = self.search(q='database')
        status, actual, _ = self.search(q='database', mode='any', limit='010', unused='ignored')
        self.assertEqual(status, 200)
        self.assertEqual(expected['mode'], 'any')
        for key in ['query', 'mode', 'total', 'results']:
            self.assertEqual(actual[key], expected[key])

    def test_parameter_errors_follow_query_mode_then_limit_validation(self):
        cases = [
            ({'q': '!', 'mode': 'bad', 'limit': 'bad'},
             'q must contain a word and be at most 512 bytes'),
            ({'q': 'database', 'mode': 'bad', 'limit': 'bad'}, 'mode must be any or all'),
            ({'q': 'database', 'mode': 'any', 'limit': 'bad'},
             'limit must be an integer between 1 and 100'),
        ]
        for parameters, expected in cases:
            with self.subTest(parameters=parameters):
                status, body, _ = self.search(**parameters)
                self.assertEqual(status, 400)
                self.assertEqual(body, {'error': expected})
        for mode in ['', 'ANY', 'All', ' any', 'all ']:
            with self.subTest(mode=mode):
                self.assertEqual(self.search(q='database', mode=mode)[0], 400)
        for limit in ['+1', ' 1', '1 ', '1.0', '1e1', '0x10', '\t1', '1\x00']:
            with self.subTest(limit=limit):
                self.assertEqual(self.search(q='database', limit=limit)[0], 400)

    def test_repeated_parameters_use_the_first_value(self):
        status, body, _ = self.request('/search?' + urllib.parse.urlencode([
            ('q', 'database'), ('q', 'missing'), ('mode', 'all'), ('mode', 'bad'),
            ('limit', '1'), ('limit', 'bad')]))
        self.assertEqual(status, 200)
        self.assertEqual(body['query'], 'database')
        self.assertEqual(body['mode'], 'all')
        self.assertEqual(body['total'], 2)
        self.assertEqual(len(body['results']), 1)
        self.assertEqual(self.request('/search?q=&q=database')[0], 400)
        status, text, _ = self.request('/document?id=a.txt&id=missing.txt')
        self.assertEqual(status, 200)
        self.assertEqual(text, self.documents['a.txt'])

    def test_errors_keep_json_security_headers_and_head_has_no_body(self):
        for path, expected in [('/search?q=!', 400), ('/document?id=missing.txt', 404), ('/missing', 404)]:
            with self.subTest(path=path):
                status, body, headers = self.request(path)
                self.assertEqual(status, expected)
                self.assertEqual(set(body), {'error'})
                self.assertIn('application/json', headers['Content-Type'])
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
                self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
                status, body, headers = self.request(path, method='HEAD')
                self.assertEqual(status, expected)
                self.assertEqual(body, '')
                self.assertIn('application/json', headers['Content-Type'])

    def test_mixed_concurrent_requests_do_not_share_response_state(self):
        paths = ['/health', '/document?id=b.md', '/search?q=database&limit=1',
                 '/search?q=database+locking&mode=all', '/search?q=missing', '/search?q=!']
        expected = [self.request(path)[:2] for path in paths]
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            responses = list(pool.map(self.request, paths * 10))
        for number, (status, body, _) in enumerate(responses):
            expected_status, expected_body = expected[number % len(paths)]
            self.assertEqual(status, expected_status)
            if isinstance(body, dict) and 'elapsed_ms' in body:
                self.assertGreaterEqual(body['elapsed_ms'], 0)
                body = {key: value for key, value in body.items() if key != 'elapsed_ms'}
                expected_body = {key: value for key, value in expected_body.items() if key != 'elapsed_ms'}
            self.assertEqual(body, expected_body)

    def test_http_client_reconnects_after_errors_and_reuses_successful_connections(self):
        address = urllib.parse.urlsplit(self.base)
        connection = http.client.HTTPConnection(address.hostname, address.port, timeout=3)
        self.addCleanup(connection.close)
        cases = [
            ('/search?q=database&limit=1', 200, 'total', 2),
            ('/search?q=database&limit=0', 400, 'error', 'limit must be an integer between 1 and 100'),
            ('/document?id=missing.txt', 404, 'error', 'Document not found'),
            ('/search?q=locking&mode=all', 200, 'total', 1),
            ('/health', 200, 'status', 'ok'),
        ]
        for path, status, key, expected in cases:
            with self.subTest(path=path):
                connection.request('GET', path)
                request_socket = connection.sock
                response = connection.getresponse()
                body = json.loads(response.read())
                self.assertEqual(response.status, status)
                self.assertEqual(body[key], expected)
                if status == 200:
                    self.assertIs(connection.sock, request_socket)
                else:
                    self.assertEqual(response.getheader('Connection'), 'close')
                    self.assertIsNone(connection.sock)

    def test_request_body_size_limit_and_recovery(self):
        for size, expected_status in [(1024, 200), (1025, 413)]:
            with self.subTest(size=size):
                status, body, headers = self.request('/search?q=database', data=b'x' * size)
                self.assertEqual(status, expected_status)
                self.assertIn('application/json', headers['Content-Type'])
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
                if expected_status == 200:
                    self.assertEqual(body['total'], 2)
                else:
                    self.assertEqual(body, {'error': 'Request failed'})
        self.assertEqual(self.search(q='locking')[1]['total'], 1)

    def test_queries_without_ascii_words_are_rejected(self):
        for query in [' \t\r\n', '\x00', 'é', '中文', '🙂']:
            with self.subTest(query=query):
                status, body, _ = self.search(q=query)
                self.assertEqual(status, 400)
                self.assertEqual(body, {'error': 'q must contain a word and be at most 512 bytes'})
        query = 'database\x00élocking'
        status, body, _ = self.search(q=query, mode='all')
        self.assertEqual(status, 200)
        self.assertEqual(body['query'], query)
        self.assertEqual([hit['id'] for hit in body['results']], ['a.txt'])


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
        'nested/café-资料.md': 'international filename',
        'literal%2Fname.txt': 'literal percent filename',
        'literal/name.txt': 'nested slash filename',
        'padded.txt': ' \t\r\n' * 100 + 'padding' + ' \t\r\n' * 100 + 'tail',
        'collapsed.txt': 'compressed ' + 'a' * 188 + '\t\n  tail',
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

    def test_document_lookup_preserves_invalid_utf8_bytes(self):
        with urllib.request.urlopen(self.base + '/document?id=invalid.txt', timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), self.documents['invalid.txt'])
            self.assertIn('text/plain', response.headers['Content-Type'])

    def test_document_ids_are_not_normalized_as_filesystem_paths(self):
        for identifier in ['./empty.txt', 'EMPTY.TXT', 'nested/../empty.txt', '%2e%2e/empty.txt']:
            with self.subTest(identifier=identifier):
                path = '/document?' + urllib.parse.urlencode({'id': identifier})
                status, body, _ = self.request(path)
                self.assertEqual(status, 404)
                self.assertEqual(body, {'error': 'Document not found'})

    def test_unicode_identifiers_survive_search_and_document_lookup(self):
        status, body, _ = self.search(q='international')
        self.assertEqual(status, 200)
        self.assertEqual(body['total'], 1)
        hit = body['results'][0]
        self.assertEqual(hit['id'], 'nested/café-资料.md')
        self.assertEqual(hit['title'], 'café 资料')
        status, body, _ = self.request('/document?' + urllib.parse.urlencode({'id': hit['id']}))
        self.assertEqual(status, 200)
        self.assertEqual(body, self.documents[hit['id']])

    def test_percent_encoded_identifiers_are_decoded_once(self):
        for identifier in ['literal%2Fname.txt', 'literal/name.txt']:
            with self.subTest(identifier=identifier):
                status, body, _ = self.request('/document?' + urllib.parse.urlencode({'id': identifier}))
                self.assertEqual(status, 200)
                self.assertEqual(body, self.documents[identifier])

    def test_preview_limit_applies_after_whitespace_collapsing(self):
        for query, preview in [('padding', 'padding tail'),
                               ('compressed', 'compressed ' + 'a' * 188 + ' ...')]:
            with self.subTest(query=query):
                status, body, _ = self.search(q=query)
                self.assertEqual(status, 200)
                self.assertEqual(body['results'][0]['preview'], preview)


class CorpusSnapshotApiTest(ServerTestCase):
    documents = {'kept.txt': 'original snapshot', 'deleted.txt': 'retained content'}

    def test_file_changes_do_not_modify_the_running_index(self):
        root = Path(self.folder.name)
        (root / 'kept.txt').write_text('changed replacement', encoding='utf-8')
        (root / 'deleted.txt').unlink()
        (root / 'added.txt').write_text('new arrival', encoding='utf-8')
        status, body, _ = self.request('/health')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'status': 'ok', 'documents': 2, 'terms': 4})
        for identifier, text in self.documents.items():
            with self.subTest(identifier=identifier):
                status, body, _ = self.request('/document?' + urllib.parse.urlencode({'id': identifier}))
                self.assertEqual(status, 200)
                self.assertEqual(body, text)
        self.assertEqual(self.request('/document?id=added.txt')[0], 404)
        self.assertEqual(self.search(q='changed new')[1]['total'], 0)
        self.assertEqual(self.search(q='original retained')[1]['total'], 2)


class LargeDocumentApiTest(ServerTestCase):
    documents = {'large.txt': 'payload ' * (1024 * 1024 // 8)}

    def test_retrieves_a_full_sized_document_with_a_bounded_search_preview(self):
        status, text, headers = self.request('/document?id=large.txt')
        self.assertEqual(status, 200)
        self.assertEqual(text, self.documents['large.txt'])
        self.assertEqual(int(headers['Content-Length']), 1024 * 1024)
        status, body, _ = self.search(q='payload')
        self.assertEqual(status, 200)
        self.assertEqual(body['total'], 1)
        self.assertEqual(body['results'][0]['preview'], self.documents['large.txt'][:200] + '...')


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


class UnsearchableCorpusApiTest(ServerTestCase):
    documents = {'empty.txt': '', 'symbols.md': ' \t\n!!! é 中文'}

    def test_documents_without_indexed_terms_remain_readable(self):
        status, body, _ = self.request('/health')
        self.assertEqual(status, 200)
        self.assertEqual(body, {'status': 'ok', 'documents': 2, 'terms': 0})
        for mode in ['any', 'all']:
            status, body, _ = self.search(q='anything', mode=mode)
            self.assertEqual(status, 200)
            self.assertEqual(body['total'], 0)
            self.assertEqual(body['results'], [])
        for identifier, expected in self.documents.items():
            status, text, _ = self.request('/document?' + urllib.parse.urlencode({'id': identifier}))
            self.assertEqual(status, 200)
            self.assertEqual(text, expected)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
