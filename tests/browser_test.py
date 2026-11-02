import json
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

from playwright.sync_api import expect, sync_playwright


class BrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = sys.argv[1].rstrip('/')
        for attempt in range(100):
            try:
                with urllib.request.urlopen(cls.base + '/health', timeout=1) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, TimeoutError):
                if attempt == 99:
                    raise
                time.sleep(0.1)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 800})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.addCleanup(lambda: self.assertFalse(self.errors, self.errors))
        self.page.goto(self.base)
        self.field = self.page.get_by_label('Search documents', exact=True)
        self.button = self.page.get_by_role('button', name='Search', exact=True)
        self.mode = self.page.get_by_label('Match', exact=True)
        self.status = self.page.get_by_role('status')
        self.articles = self.page.locator('article')

    def search(self, query, mode='any'):
        self.field.fill(query)
        self.mode.select_option(mode)
        self.button.click()
        expect(self.button).to_be_enabled()

    def mock_response(self, body, status=200):
        self.page.route('**/search?*', lambda route: route.fulfill(
            status=status, content_type='application/json', body=body))

    def assert_recovery(self):
        self.page.unroute('**/search?*')
        self.search('database locking', 'all')
        expect(self.articles).to_have_count(1)
        expect(self.articles.first.get_by_role('link')).to_have_text('database locking')

    def test_initial_state_and_required_query(self):
        requests = []
        self.page.on('request', lambda request: requests.append(request.url))
        expect(self.field).to_be_empty()
        expect(self.button).to_be_enabled()
        expect(self.mode).to_have_value('any')
        expect(self.articles).to_have_count(0)
        expect(self.status).to_have_text('Enter a query to get started.')
        self.button.click()
        self.assertTrue(self.field.evaluate('input => input.validity.valueMissing'))
        expect(self.status).to_have_text('Enter a query to get started.')
        self.assertFalse([url for url in requests if urllib.parse.urlsplit(url).path == '/search'])

    def test_any_and_all_search(self):
        self.search('database locking')
        expect(self.articles).to_have_count(3)
        expect(self.articles.first.get_by_role('link')).to_have_text('database locking')
        self.search('database locking', 'all')
        expect(self.articles).to_have_count(1)

    def test_opens_document_in_a_separate_tab(self):
        self.search('database locking', 'all')
        link = self.page.get_by_role('link', name='database locking', exact=True)
        expect(link).to_have_attribute('target', '_blank')
        expect(link).to_have_attribute('rel', 'noopener')
        with self.page.expect_popup() as popup:
            link.click()
        document = popup.value
        expect(document.locator('body')).to_contain_text('row level locking')
        self.assertTrue(document.evaluate('window.opener === null'))
        document.close()
        expect(self.articles).to_have_count(1)

    def test_unknown_query_clears_previous_results(self):
        self.search('database locking')
        self.search('zxqvnosuchword')
        expect(self.articles).to_have_count(0)
        expect(self.status).to_contain_text('No matching documents')

    def test_invalid_query_recovers(self):
        self.search('!!!')
        expect(self.status).to_contain_text('q must contain a word')
        expect(self.articles).to_have_count(0)
        self.assert_recovery()

    def test_multibyte_query_exceeding_byte_limit_recovers(self):
        query = 'a' + 'é' * 256
        self.assertLess(len(query), 512)
        self.assertEqual(len(query.encode('utf-8')), 513)
        self.search(query)
        expect(self.status).to_have_text('q must contain a word and be at most 512 bytes')
        expect(self.articles).to_have_count(0)
        self.assert_recovery()

    def test_network_failure_clears_results_and_recovers(self):
        self.search('database locking')
        self.page.route('**/search?*', lambda route: route.abort('failed'))
        self.search('database locking')
        expect(self.status).to_contain_text('Failed to fetch')
        expect(self.articles).to_have_count(0)
        self.assert_recovery()

    def test_server_errors_show_custom_or_default_message_and_recover(self):
        for body, message in [({'error': 'Temporarily unavailable'}, 'Temporarily unavailable'),
                              ({}, 'Search failed.')]:
            with self.subTest(body=body):
                self.mock_response(json.dumps(body), status=503)
                self.search('database locking')
                expect(self.status).to_have_text(message)
                expect(self.articles).to_have_count(0)
                self.assert_recovery()

    def test_invalid_json_recovers(self):
        self.mock_response('invalid json')
        self.search('database locking')
        expect(self.status).not_to_have_text('Searching...')
        expect(self.status).not_to_be_empty()
        expect(self.articles).to_have_count(0)
        self.assert_recovery()

    def test_result_markup_is_literal_and_document_id_is_encoded(self):
        markup = '<img src=x onerror="window.injected=true">'
        identifier = 'nested/a &+#?.md'
        result = {'total': 1, 'elapsed_ms': 1, 'results': [
            {'id': identifier, 'title': markup, 'preview': markup, 'score': 1}]}
        self.mock_response(json.dumps(result))
        self.search('markup')
        expect(self.page.locator('article h2 a')).to_have_text(markup)
        expect(self.page.locator('article p')).to_have_text(markup)
        expect(self.page.locator('article img')).to_have_count(0)
        self.assertTrue(self.page.evaluate('window.injected === undefined'))
        self.assertEqual(self.page.locator('article a').evaluate(
            "link => new URL(link.href).searchParams.get('id')"), identifier)

    def test_pending_search_clears_results_and_ignores_duplicate_submissions(self):
        self.search('database locking')
        pending = []
        self.page.route('**/search?*', lambda route: pending.append(route))
        self.field.fill('database locking')
        self.mode.select_option('all')
        self.button.click()
        expect(self.button).to_be_disabled()
        expect(self.status).to_have_text('Searching...')
        expect(self.articles).to_have_count(0)
        self.field.fill('cooking')
        self.mode.select_option('any')
        for _ in range(3):
            self.page.locator('form').dispatch_event('submit')
        self.assertEqual(len(pending), 1)
        parameters = urllib.parse.parse_qs(urllib.parse.urlsplit(pending[0].request.url).query)
        self.assertEqual(parameters, {'q': ['database locking'], 'mode': ['all'], 'limit': ['10']})
        pending[0].fulfill(status=200, content_type='application/json', body=json.dumps({
            'total': 1, 'elapsed_ms': 1, 'results': [
                {'id': 'first.txt', 'title': 'First search', 'preview': 'First result', 'score': 1}]}))
        expect(self.button).to_be_enabled()
        expect(self.articles).to_have_count(1)
        expect(self.articles.first.get_by_role('link')).to_have_text('First search')
        self.assertEqual(len(pending), 1)
        self.assert_recovery()

    def test_keyboard_submission_encodes_query_and_selected_mode(self):
        query = 'database + % & locking?'
        self.field.fill(query)
        self.mode.select_option('all')
        with self.page.expect_request(lambda request: urllib.parse.urlsplit(request.url).path == '/search') as sent:
            self.field.press('Enter')
        parameters = urllib.parse.parse_qs(urllib.parse.urlsplit(sent.value.url).query)
        self.assertEqual(parameters, {'q': [query], 'mode': ['all'], 'limit': ['10']})
        expect(self.button).to_be_enabled()
        expect(self.articles).to_have_count(1)

    def test_result_summary_distinguishes_total_from_displayed_count(self):
        result = {'total': 13, 'elapsed_ms': 1.23456, 'results': [
            {'id': 'a.txt', 'title': 'First', 'preview': 'First result', 'score': 0.98765},
            {'id': 'b.txt', 'title': 'Second', 'preview': 'Second result', 'score': 0.12345}]}
        self.mock_response(json.dumps(result))
        self.search('summary')
        expect(self.status).to_have_text('13 matches · showing 2 · 1.23 ms')
        expect(self.articles).to_have_count(2)
        expect(self.page.locator('article h2 a')).to_have_text(['First', 'Second'])
        expect(self.page.locator('article .path')).to_have_text([
            'a.txt · score 0.988', 'b.txt · score 0.123'])

    def test_mobile_layout_does_not_overflow(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.search('database locking', 'all')
        expect(self.articles).to_have_count(1)
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
