"""主线浏览器验收：使用确定性 API 数据，不依赖模型在线或生产库价格覆盖。"""

import json
from urllib.parse import urlparse, parse_qs

from frontend.e2e.browser_case import BrowserTestCase, BASE_URL


class ProductJourneyTest(BrowserTestCase):
    def setUp(self):
        super().setUp()
        self.page.route("**/api/**", self.api_route)

    def product(self, pid):
        names = {1: "目标精华", 2: "相似精华", 3: "无价精华", 4: "低价精华"}
        price = {1: 120, 2: 100, 3: None, 4: 40}[pid]
        return {
            "id": pid, "name": names[pid], "brand": "测试品牌", "category": "精华",
            "nmpa_id": None, "registrant": None, "filing_date": None, "note": None,
            "source_url": "https://example.org/formula", "buy_url": None,
            "price_current": price, "spec": "30ml", "price_source": None,
            "unit_price": price / 30 if price is not None else None,
            "unit_price_unit": "ml" if price is not None else None,
            "ingredients": [{"ingredient_id": i, "cn_name": f"成分{i}",
                             "inci_name": f"INCI-{i}", "position": None,
                             "has_evidence": False, "purpose": "配方用途"} for i in range(1, 11)],
            "claims": [],
        }

    def candidate(self, pid, score):
        return {**self.product(pid), "score": score, "shared": 5, "union": 15,
                "shared_ingredients": [{"ingredient_id": 1, "cn_name": "成分1"}],
                "only_target_ingredients": [{"ingredient_id": 2, "cn_name": "成分2"}],
                "only_candidate_ingredients": [{"ingredient_id": 3, "cn_name": "成分3"}]}

    def api_route(self, route):
        path = urlparse(route.request.url).path
        if path == "/api/roundtable":
            self.assertEqual(route.request.post_data_json["product_name"], "目标精华")
            self.assertEqual(route.request.post_data_json["product_id"], 1)
            events = [{"event": "start", "product": {"products": [self.product(1)]}}]
            for role in ("ingredient_expert", "regulation_officer", "evidence_verifier", "dose_analyst"):
                events.append({"event": "speak", "role": role, "content": "证据不足，无法确定。"})
            events.append({"event": "verdict", "level": 2, "label": "证据不足", "reason": "缺少研究证据",
                           "evidence": {"ingredient_evidence": {"assertions": [{
                               "efficacy": "测试用途", "evidence_level": "unknown", "note": "仅测试资料",
                               "evidence": {"title": "测试来源", "url": "https://example.org/evidence"}}]}}})
            body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
            route.fulfill(content_type="text/event-stream", body=body + "data: [DONE]\n\n")
            return
        if path == "/api/stats":
            data = {"products": 4, "ingredients": 10, "evidence": 0}
        elif path.endswith("/similar-levels"):
            data = {"l1": [self.candidate(2, .8), self.candidate(4, .6), self.candidate(3, .5)],
                    "l2": {"available": False, "reason": "无推断浓度"}, "l3": [], "note": "相似不代表功效等同"}
        elif path.endswith("/similar"):
            data = {"similar": [self.candidate(3, .95), self.candidate(2, .9)]}
        elif path.endswith("/concentration"):
            data = {"inferred": False, "reason": "尚无浓度推断结果"}
        elif path.endswith("/fingerprint"):
            data = {"fingerprint": {}, "coverage": {"ingredients_total": 10}, "detail": []}
        elif path.endswith("/evidence-profile"):
            data = {"ingredients_with_assertions": 0, "ingredients_total": 10,
                    "assertions_total": 0, "by_level": []}
        elif path.startswith("/api/products/"):
            data = self.product(int(path.rsplit("/", 1)[1]))
        elif path == "/api/products":
            data = {"total": 4, "items": [self.product(i) for i in range(1, 5)]}
        elif path.startswith("/api/rankings/"):
            data = {"total": 0, "items": []}
        elif path == "/api/ingredients":
            query = parse_qs(urlparse(route.request.url).query).get("q", [""])[0]
            data = {"total": 1, "items": [{"id": 1, "cn_name": query, "inci_name": query,
                                          "assertion_count": 0}]} if query != "未收录" else {"total": 0, "items": []}
        else:
            data = {}
        route.fulfill(json=data)

    def open_product(self):
        self.page.goto(f"{BASE_URL}/#/products/1")
        self.page.get_by_role("heading", name="完整成分表（10 种）").wait_for()

    def test_complete_ingredients_precede_similar_and_evidence(self):
        self.open_product()
        headings = self.page.locator("h2").all_text_contents()
        self.assertLess(headings.index("完整成分表（10 种）"), headings.index("相似产品与价格"))
        self.assertLess(headings.index("相似产品与价格"), headings.index("功效证据"))
        self.assertTrue(self.page.get_by_role("link", name="成分10", exact=True).is_visible())
        self.assertEqual(self.page.get_by_text("位次未知", exact=True).count(), 10)

    def test_similarity_modes_price_sort_and_missing_price(self):
        self.open_product()
        board = self.page.get_by_role("region", name="相似产品与价格")
        cards = board.locator("[data-similar-product]")
        cards.first.wait_for()
        self.assertEqual(cards.first.get_attribute("data-similar-product"), "2")
        board.get_by_label("相似产品排序").select_option("price")
        self.assertEqual(cards.first.get_attribute("data-similar-product"), "4")
        self.assertEqual(cards.last.get_attribute("data-similar-product"), "3")
        self.assertTrue(cards.last.get_by_text("暂无价格", exact=True).is_visible())
        board.get_by_role("button", name="嵌入相似", exact=True).click()
        board.get_by_label("相似产品排序").select_option("similarity")
        self.assertEqual(cards.first.get_attribute("data-similar-product"), "3")
        self.assertIn("95.0%", cards.first.inner_text())

    def test_product_roundtable_is_prefilled_and_runs_four_roles(self):
        self.open_product()
        self.page.get_by_role("link", name="发起圆桌核验", exact=True).click()
        self.assertEqual(self.page.get_by_placeholder("输入产品名，如「修丽可」，回车开始…").input_value(), "目标精华")
        self.page.get_by_role("button", name="开始圆桌", exact=True).click()
        self.page.get_by_text("圆桌结束，可输入下一个产品名再开一场。", exact=True).wait_for()
        for role in ("成分专家", "法规合规官", "文献核验官", "剂量推断师"):
            self.assertTrue(self.page.get_by_text(role, exact=True).is_visible())
        self.page.get_by_text("查看圆桌引用资料（1 条）", exact=True).click()
        self.assertEqual(self.page.get_by_role("link", name="测试来源 ↗").get_attribute("href"), "https://example.org/evidence")

    def test_compare_shows_prices_shared_ingredients_and_evidence(self):
        self.page.goto(f"{BASE_URL}/#/compare?a=1&b=2")
        self.page.get_by_role("heading", name="价格与规格").wait_for()
        self.assertTrue(self.page.get_by_role("heading", name="证据差异").is_visible())
        self.assertTrue(self.page.get_by_role("button", name="共有成分（10）").is_visible())

    def test_decode_keeps_hit_and_miss_groups(self):
        self.page.goto(f"{BASE_URL}/#/decode")
        self.page.locator("textarea").fill("水、未收录")
        self.page.get_by_role("button", name="解析", exact=True).click()
        self.page.get_by_text("已命中", exact=True).first.wait_for()
        self.assertTrue(self.page.get_by_text("未收录", exact=True).is_visible())

    def test_compare_ignores_a_late_response_for_previous_selection(self):
        held = []
        self.page.route("**/api/products/1", lambda route: held.append(route))
        self.page.goto(f"{BASE_URL}/#/compare?a=1&b=2")
        self.page.get_by_role("button", name="清除产品 A").wait_for()
        self.page.evaluate("location.hash = '/compare?a=4&b=2'")
        self.page.get_by_role("heading", name="价格与规格").wait_for()
        self.assertTrue(held)
        held[0].fulfill(json=self.product(1))
        self.assertTrue(self.page.get_by_role("link", name="低价精华", exact=True).is_visible())
        self.assertEqual(self.page.get_by_role("link", name="目标精华", exact=True).count(), 0)

    def test_unit_price_sort_does_not_mix_grams_and_milliliters(self):
        self.page.route("**/api/products/1/similar-levels?*", lambda route: route.fulfill(json={
            "l1": [{**self.candidate(2, .9), "spec": "50g", "unit_price": .01, "unit_price_unit": "g"},
                   self.candidate(4, .5)],
            "l2": {"available": False, "reason": "无推断"}, "l3": [],
        }))
        self.open_product()
        board = self.page.get_by_role("region", name="相似产品与价格")
        board.get_by_label("相似产品排序").select_option("unit")
        cards = board.locator("[data-similar-product]")
        self.assertEqual(cards.first.get_attribute("data-similar-product"), "4")
        self.assertIn("/ g", cards.last.inner_text())

    def test_embedding_index_missing_has_an_explicit_empty_state(self):
        self.page.route("**/api/products/1/similar?*", lambda route: route.fulfill(json={
            "similar": None, "reason": "相似索引未构建",
        }))
        self.open_product()
        board = self.page.get_by_role("region", name="相似产品与价格")
        board.get_by_role("button", name="嵌入相似", exact=True).click()
        board.get_by_text("相似索引未构建", exact=True).wait_for()
        self.assertEqual(board.locator("[data-similar-product]").count(), 0)

    def test_dose_comparison_does_not_mark_absent_ingredient_as_present(self):
        for pid in (1, 2):
            product = self.product(pid)
            product["ingredients"] = [product["ingredients"][pid - 1]]
            self.page.route(f"**/api/products/{pid}", lambda route, *, p=product: route.fulfill(json=p))
            self.page.route(f"**/api/products/{pid}/concentration", lambda route, *, i=pid: route.fulfill(json={
                "inferred": True, "estimates": [{"ingredient_id": i, "dose": []}],
            }))
        self.page.goto(f"{BASE_URL}/#/compare?a=1&b=2")
        self.page.get_by_text("剂量与每起效成本（估计）", exact=True).click()
        details = self.page.locator("details")
        row = details.locator(".grid-cols-3").filter(has_text="成分1")
        self.assertIn("未列出", row.inner_text())
