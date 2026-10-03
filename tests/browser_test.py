import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import expect, sync_playwright


base = sys.argv[1].rstrip('/')
for attempt in range(100):
    try:
        with urllib.request.urlopen(base + '/health', timeout=1) as response:
            if response.status == 200:
                break
    except (urllib.error.URLError, TimeoutError):
        if attempt == 99:
            raise
        time.sleep(0.1)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base)
    field = page.get_by_label('Search documents', exact=True)
    button = page.get_by_role('button', name='Search', exact=True)

    def search(query, mode='any'):
        field.fill(query)
        page.get_by_label('Match', exact=True).select_option(mode)
        button.click()
        expect(button).to_be_enabled()

    search('database locking')
    expect(page.locator('article')).to_have_count(3)
    expect(page.locator('article').first.get_by_role('link')).to_have_text('database locking')
    search('database locking', 'all')
    expect(page.locator('article')).to_have_count(1)
    with page.expect_popup() as popup:
        page.get_by_role('link', name='database locking', exact=True).click()
    document = popup.value
    expect(document.locator('body')).to_contain_text('row level locking')
    document.close()

    search('zxqvnosuchword')
    expect(page.locator('article')).to_have_count(0)
    expect(page.get_by_role('status')).to_contain_text('No matching documents')
    search('!!!')
    expect(page.get_by_role('status')).to_contain_text('q must contain a word')

    page.set_viewport_size({'width': 390, 'height': 844})
    search('database locking', 'all')
    expect(page.locator('article')).to_have_count(1)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not errors, errors
    browser.close()

print('Browser checks passed: search, filters, document links, errors, and mobile layout')
