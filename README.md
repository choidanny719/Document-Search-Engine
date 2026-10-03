# Document Search Engine

A C++20 backend for searching text and Markdown files. It builds an inverted index,
ranks matches with TF-IDF and cosine similarity, and selects the best results with
a bounded heap. Includes a JSON API and a small search page.

Uses cpp-httplib, nlohmann/json, CMake, and Google Test. Dependencies are downloaded
at configure time with pinned versions and SHA-256 checksums.

## Run

Requires a C++20 compiler, CMake 3.24+, and Python 3 for API tests. Run these commands
from the project root on Linux or macOS:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 2
./build/search_server
```

Open http://127.0.0.1:8080. Eight sample documents are included. To search your own
folder, run `./build/search_server --data /path/to/documents`.

The server recursively loads `.txt` and `.md` files into memory at startup. Restart
it after changing files. Limits: 1 MiB per file, 64 MiB total text, 50,000 files.
Symbolic links are ignored. The index uses lowercase ASCII letters and digits;
there is no stemming, synonym matching, or exact-phrase search.

## API

| Route | Purpose |
| --- | --- |
| `GET /search?q=database%20locking` | Ranked matches with IDs, titles, scores, and previews |
| `GET /document?id=database-locking.md` | Full document text |
| `GET /health` | Status and document/term counts |

Search accepts `mode=any` (default) or `mode=all`, and `limit=1..100` (default 10).
Queries must contain a word and be at most 512 bytes. Equal scores are ordered by
document ID. TF uses `1 + ln(count)`; IDF uses `1 + ln((N + 1) / (df + 1))`.
Unknown words are ignored in `any` mode and produce no matches in `all` mode.

## Tests and benchmark

```sh
ctest --test-dir build --output-on-failure
./build/search_benchmark 10000
```

The benchmark generates a fixed-seed corpus and checks that indexed matching and
a scan of pre-tokenized documents return identical IDs. It reports build time and
p50/p95 query times. Ranked top-10 search is measured separately. Results depend
on the machine and corpus; the generated data is not a relevance evaluation.

CI also tests the search page in Chromium and builds and runs the Docker image.
To run browser tests locally, install `tests/requirements.txt`, run
`python3 -m playwright install chromium`, start the server, then run
`python3 tests/browser_test.py http://127.0.0.1:8080`.

## Docker

```sh
docker build -t document-search .
docker run --rm -p 127.0.0.1:8080:8080 document-search
```

The container runs as a non-root user. All indexed documents are readable through
the API; use a corpus intended for the people who can reach the service. The native
server binds to localhost by default; `--host` and `--port` change the address.
