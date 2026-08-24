"""首页核心交互的浏览器回归测试。

运行前须启动本地站点：
    /tmp/pwenv/bin/python -m unittest frontend/e2e/test_home_page.py
"""

import os
import unittest

from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("CFZ_E2E_BASE_URL", "http://127.0.0.1:8008")


class HomePageTest(unittest.TestCase):
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

    def test_home_search_button_opens_results_for_entered_query(self):
        """防止首页只支持回车、点击搜索按钮失效。"""
        self.page.get_by_role("textbox", name="搜索产品、成分或备案号").fill("烟酰胺")
        self.page.get_by_role("button", name="搜索", exact=True).click()
        self.page.wait_for_url("**/#/search?q=%E7%83%9F%E9%85%B0%E8%83%BA")

    def test_home_shows_four_separate_efficacy_product_rankings(self):
        """防止四类功效榜退化回单一可切换榜单。"""
        for label in ("美白产品榜", "抗老产品榜", "保湿产品榜", "祛痘产品榜"):
            self.assertTrue(self.page.get_by_role("heading", name=label, exact=True).is_visible())

    def test_home_uses_the_approved_evidence_slogan(self):
        """防止首页回退为旧的“挂真实文献”表述。"""
        self.assertTrue(
            self.page.get_by_text("每条功效断言，都有迹可循", exact=True).is_visible()
        )
