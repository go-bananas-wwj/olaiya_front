from playwright.sync_api import expect

from frontend.e2e.browser_case import BASE_URL, BrowserTestCase


class ComparisonPaletteTest(BrowserTestCase):
    def setUp(self):
        super().setUp()
        self.page.goto(BASE_URL + '?compare=9,73', wait_until='domcontentloaded')
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-loaded', 'true')

    def test_neutral_text_and_consistent_blue_purple_product_identity(self):
        neutrals = ['.ss-product-name', '.comparison-direction', '.comparison-value strong',
                    '.comparison-section-nav a', '.comparison-index-note']
        for selector in neutrals:
            colors = self.page.locator('.comparison-page ' + selector).evaluate_all(
                'es => es.map(e => getComputedStyle(e).color)')
            self.assertTrue(colors, selector)
            for color in colors:
                rgb = [int(v) for v in color.removeprefix('rgb(').removesuffix(')').split(',')]
                self.assertLessEqual(max(rgb) - min(rgb), 30, (selector, color))
        colors = self.page.locator('.compact-side').evaluate_all(
            'es => es.map(e => getComputedStyle(e).color)')
        self.assertNotEqual(colors[0], colors[1])
        for side, color in zip(['A', 'B'], colors):
            self.assertEqual(self.page.locator('.comparison-letter.' + side).evaluate(
                'e => getComputedStyle(e).color'), color)
            self.assertEqual(self.page.get_by_test_id('bar-' + side + '-保湿').evaluate(
                'e => getComputedStyle(e).backgroundColor'), color)
        self.assertEqual(self.page.locator('.comparison-page').evaluate(
            'e => getComputedStyle(e).backgroundColor'), 'rgb(255, 255, 255)')

    def test_phone_keeps_both_product_labels_and_readable_values_without_overflow(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        for side in ['A', 'B']:
            expect(self.page.locator('.compact-' + side + ' .compact-side')).to_have_text(side)
            expect(self.page.get_by_test_id('bar-' + side + '-保湿')).to_be_visible()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
