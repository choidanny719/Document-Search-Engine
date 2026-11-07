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


class Server:
    def __init__(self, data, web, *arguments, cwd=None):
        self.process = subprocess.Popen(
            [str(Path(sys.argv[1]).resolve()), '--data', str(data), '--web', str(web),
             '--port', '0', *arguments], cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            if not select.select([self.process.stdout], [], [], 20)[0]:
                raise RuntimeError('Server did not report its listening address')
            line = self.process.stdout.readline()
            match = re.search(r'http://127\.0\.0\.1:(\d+)', line)
            if not match:
                _, error = self.process.communicate(timeout=5)
                raise RuntimeError(f'Server failed to start: {line} {error}')
            self.base = f'http://127.0.0.1:{match.group(1)}'
            for _ in range(100):
                try:
                    if self.request('/health')[0] == 200:
                        break
                except (urllib.error.URLError, TimeoutError):
                    pass
                time.sleep(0.02)
            else:
                raise RuntimeError('Server did not become ready')
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate()

    def __enter__(self):
        return self

    def __exit__(self, *error):
        self.close()

    def request(self, path, method='GET', data=None):
        request = urllib.request.Request(self.base + path, data=data, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read().decode('utf-8')
            if body and 'application/json' in response.headers.get('Content-Type', ''):
                body = json.loads(body)
            return response.status, body, response.headers


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
        cls.server = Server(root, sys.argv[2])
        cls.addClassCleanup(cls.server.close)
        cls.base = cls.server.base

    @classmethod
    def request(cls, path, method='GET', data=None):
        return cls.server.request(path, method, data)

    def search(self, **parameters):
        return self.request('/search?' + urllib.parse.urlencode(parameters))
