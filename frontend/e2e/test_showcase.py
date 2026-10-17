from frontend.e2e.browser_case import BrowserTestCase
from playwright.sync_api import expect
from urllib.parse import parse_qs, urlparse


class ShowcaseTest(BrowserTestCase):
    def test_presets_compare_real_products_and_open_evidence(self):
        expect(self.page.get_by_role("heading", name="成分对照台", exact=True)).to_be_visible()
        self.page.get_by_role("button", name="黑绷带 / A.G.E.").click()
        expect(self.page.get_by_role("heading", name="共有与差异成分")).to_be_visible()
        self.page.get_by_test_id("shared-ingredients").get_by_role("button").first.click()
        expect(self.page.get_by_role("dialog", name="成分证据")).to_be_visible()
        self.page.keyboard.press("Escape")
        self.page.get_by_role("button", name="Serum 10 / C E Ferulic").click()
        expect(self.page.get_by_test_id("candidate-product").get_by_text("参考价 ¥1720.00", exact=False)).to_be_visible()
        self.page.get_by_role("button", name="嵌入相似", exact=True).click()
        self.assertTrue(self.page.get_by_text("相似不代表功效等同", exact=False).first.is_visible())

    def test_search_and_mobile_layout(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.get_by_role("textbox", name="搜索参照产品").fill("烟酰胺")
        self.page.get_by_role("button", name="选择 烟酰胺10%+锌1%精华（Niacinamide 10% + Zinc 1%）").click()
        expect(self.page.get_by_test_id("target-product").get_by_text("The Ordinary", exact=True)).to_be_visible()
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 390)

    def test_roundtable_uses_exact_product_id_and_detects_disconnect(self):
        seen = []
        def handler(route):
            seen.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="text/event-stream", body='data: {"event":"speak","role":"ingredient_expert","content":"测试发言"}\n\n')
        self.page.route("**/api/roundtable", handler)
        self.page.get_by_role("button", name="Serum 10 / C E Ferulic").click()
        self.page.get_by_role("button", name="核验对照产品", exact=True).click()
        expect(self.page.get_by_text("连接中断：未收到完整结论，请重试。", exact=True)).to_be_visible()
        self.assertEqual(seen[0]["product_id"], 3202)

    def test_search_ignores_late_response(self):
        delayed = []
        def handler(route):
            q = parse_qs(urlparse(route.request.url).query).get("q", [""])[0]
            if q == "oldquery":
                delayed.append(route)
            else:
                route.fulfill(json={"items": [{"id": 414, "brand": "修丽可", "name": "new result"}]})
        self.page.route("**/api/products?*", handler)
        search = self.page.get_by_role("textbox", name="搜索参照产品")
        with self.page.expect_request("**/api/products?q=oldquery&limit=8"):
            search.fill("oldquery")
        search.fill("newquery")
        expect(self.page.get_by_role("button", name="选择 new result", exact=True)).to_be_visible()
        delayed[0].fulfill(json={"items": [{"id": 73, "brand": "修丽可", "name": "old result"}]})
        expect(self.page.get_by_role("button", name="选择 old result", exact=True)).to_have_count(0)
        expect(self.page.get_by_role("button", name="选择 new result", exact=True)).to_be_visible()

    def test_missing_index_and_missing_price_remain_explicit(self):
        self.page.route("**/api/products/*/similar?*", lambda route: route.fulfill(json={"similar": None, "reason": "相似索引未构建"}))
        self.page.get_by_role("button", name="嵌入相似", exact=True).click()
        expect(self.page.get_by_text("相似索引未构建，可切换成分重合继续对照。", exact=True)).to_be_visible()
        self.page.get_by_role("button", name="成分重合", exact=True).click()
        expect(self.page.get_by_text("暂无价格", exact=True).first).to_be_visible()

    def test_switching_products_clears_roundtable(self):
        self.page.route("**/api/roundtable", lambda route: route.fulfill(content_type="text/event-stream", body='data: {"event":"speak","role":"ingredient_expert","content":"旧产品发言"}\n\ndata: [DONE]\n\n'))
        self.page.get_by_role("button", name="核验参照产品", exact=True).click()
        expect(self.page.get_by_text("旧产品发言", exact=True)).to_be_visible()
        self.page.get_by_role("button", name="Serum 10 / C E Ferulic").click()
        expect(self.page.get_by_test_id("target-product").get_by_role("heading", name="SkinCeuticals Serum 10", exact=True)).to_be_visible()
        expect(self.page.get_by_text("旧产品发言", exact=True)).to_have_count(0)
