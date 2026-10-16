import os
import unittest

from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("CFZ_E2E_BASE_URL", "http://127.0.0.1:8008")


class BrowserTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 900})
        self.page.set_default_timeout(5_000)
        self.page.goto(BASE_URL, wait_until="domcontentloaded")

    def tearDown(self):
        self.page.close()
