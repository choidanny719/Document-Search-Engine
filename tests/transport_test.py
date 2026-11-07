import http.client
import json
import socket
import sys
import unittest
import urllib.parse

from server_support import ServerTestCase


class TransportTest(ServerTestCase):
    documents = {'alpha.txt': 'alpha beta', 'beta.md': 'beta gamma'}

    def connection(self):
        address = urllib.parse.urlsplit(self.base)
        connection = http.client.HTTPConnection(address.hostname, address.port, timeout=3)
        self.addCleanup(connection.close)
        return connection

    def assert_json_response(self, connection, status):
        response = connection.getresponse()
        body = json.loads(response.read())
        self.assertEqual(response.status, status)
        self.assertEqual(response.getheader('Content-Type'), 'application/json; charset=utf-8')
        self.assertEqual(response.getheader('X-Content-Type-Options'), 'nosniff')
        self.assertIn("frame-ancestors 'none'", response.getheader('Content-Security-Policy'))
        return body

    def test_chunked_bodies_accept_the_limit_and_leave_the_connection_readable(self):
        for chunks in [[], [b'x' * 1024], [b'a' * 511, b'\x00\xff', b'b' * 511]]:
            with self.subTest(sizes=[len(chunk) for chunk in chunks]):
                connection = self.connection()
                connection.request('GET', '/search?q=alpha', body=iter(chunks),
                                   headers={'Content-Type': 'application/octet-stream'},
                                   encode_chunked=True)
                request_socket = connection.sock
                body = self.assert_json_response(connection, 200)
                self.assertEqual(body['total'], 1)
                self.assertEqual(body['results'][0]['id'], 'alpha.txt')
                self.assertIs(connection.sock, request_socket)
                connection.request('GET', '/health')
                self.assertEqual(self.assert_json_response(connection, 200),
                                 {'status': 'ok', 'documents': 2, 'terms': 3})
                self.assertIs(connection.sock, request_socket)
                connection.close()

    def test_chunked_size_limit_counts_the_whole_body(self):
        for chunks in [[b'x' * 1025], [b'x' * 512, b'y' * 513]]:
            with self.subTest(sizes=[len(chunk) for chunk in chunks]):
                connection = self.connection()
                connection.request('GET', '/search?q=alpha', body=iter(chunks),
                                   headers={'Content-Type': 'application/octet-stream'},
                                   encode_chunked=True)
                self.assertEqual(self.assert_json_response(connection, 413), {'error': 'Request failed'})
                self.assertIsNone(connection.sock)
                connection.request('GET', '/search?q=gamma')
                result = self.assert_json_response(connection, 200)
                self.assertEqual([hit['id'] for hit in result['results']], ['beta.md'])
                connection.close()

    def test_request_bodies_do_not_replace_url_search_parameters(self):
        connection = self.connection()
        body = b'q=gamma&mode=all&limit=100'
        for chunked in [False, True]:
            with self.subTest(chunked=chunked):
                connection.request('GET', '/search?q=alpha&mode=any&limit=1',
                                   body=iter([body]) if chunked else body,
                                   headers={'Content-Type': 'application/octet-stream'},
                                   encode_chunked=chunked)
                result = self.assert_json_response(connection, 200)
                self.assertEqual(result['query'], 'alpha')
                self.assertEqual(result['mode'], 'any')
                self.assertEqual([hit['id'] for hit in result['results']], ['alpha.txt'])

    def test_keep_alive_closes_at_the_configured_request_count(self):
        connection = self.connection()
        connection.connect()
        original = connection.sock
        for number in range(20):
            with self.subTest(number=number + 1):
                self.assertIs(connection.sock, original)
                connection.request('GET', '/health')
                self.assertEqual(self.assert_json_response(connection, 200)['status'], 'ok')
                if number < 19:
                    self.assertIs(connection.sock, original)
        self.assertIsNone(connection.sock)
        connection.request('GET', '/search?q=gamma')
        self.assertEqual(self.assert_json_response(connection, 200)['total'], 1)
        self.assertIsNot(connection.sock, original)

    def test_explicit_connection_close_finishes_the_response_before_reconnecting(self):
        connection = self.connection()
        connection.request('GET', '/document?id=alpha.txt', headers={'Connection': 'close'})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Connection'), 'close')
        self.assertEqual(response.read(), b'alpha beta')
        self.assertIsNone(connection.sock)
        connection.request('GET', '/health')
        self.assertEqual(self.assert_json_response(connection, 200)['status'], 'ok')

    def test_head_does_not_leave_body_bytes_before_the_next_response(self):
        connection = self.connection()
        connection.request('HEAD', '/document?id=alpha.txt')
        original = connection.sock
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(int(response.getheader('Content-Length')), len('alpha beta'))
        self.assertEqual(response.read(), b'')
        self.assertIs(connection.sock, original)
        connection.request('GET', '/document?id=beta.md')
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), b'beta gamma')
        self.assertIs(connection.sock, original)

    def test_incomplete_requests_do_not_exhaust_the_worker_pool(self):
        address = urllib.parse.urlsplit(self.base)
        requests = [
            b'GET /search?q=alpha HTTP/1.1\r\nHost: localhost\r\n',
            b'GET /search?q=alpha HTTP/1.1\r\nHost: localhost\r\nContent-Length: 1024\r\n\r\nx',
            b'GET /search?q=alpha HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n8\r\nx',
        ]
        for request in requests:
            with self.subTest(request=request):
                for _ in range(24):
                    with socket.create_connection((address.hostname, address.port), timeout=3) as client:
                        client.sendall(request)
                status, result, _ = self.search(q='beta', mode='all')
                self.assertEqual(status, 200)
                self.assertEqual(result['total'], 2)
                self.assertEqual({hit['id'] for hit in result['results']}, {'alpha.txt', 'beta.md'})


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
