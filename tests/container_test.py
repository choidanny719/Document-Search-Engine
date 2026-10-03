import json
import sys
import time
import urllib.error
import urllib.request


base = sys.argv[1].rstrip('/')


def get(path):
    with urllib.request.urlopen(base + path, timeout=3) as response:
        return json.load(response)


for attempt in range(100):
    try:
        health = get('/health')
        break
    except (urllib.error.URLError, TimeoutError):
        if attempt == 99:
            raise
        time.sleep(0.1)

assert health['status'] == 'ok'
assert health['documents'] == 8
results = get('/search?q=database%20locking&mode=all')
assert results['total'] == 1
assert results['results'][0]['id'] == 'database-locking.md'
with urllib.request.urlopen(base + '/document?id=database-locking.md', timeout=3) as response:
    assert 'row level locking' in response.read().decode('utf-8')
print('Container checks passed: health, ranked search, and document retrieval')
