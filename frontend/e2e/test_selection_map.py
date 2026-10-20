import json
from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase,BASE_URL

class SelectionMapTest(BrowserTestCase):
    def ready(self):
        self.page.goto(BASE_URL+'/?view=selection&efficacy=保湿')
        expect(self.page.get_by_role('heading',name='保湿面霜选择图')).to_be_visible()
        expect(self.page.locator('.selection-plot svg[role=group]')).to_be_visible(timeout=30000)

    def test_budget_keeps_axes_and_context_then_two_candidate_roundtrip(self):
        self.ready()
        svg=self.page.locator('.selection-plot svg[role=group]')
        before=svg.locator('text').all_text_contents()
        self.page.get_by_role('spinbutton',name='整件参考价上限').fill('1000')
        expect(self.page.locator('.selection-dot.is-faded').first).to_be_visible()
        self.assertEqual(before,svg.locator('text').all_text_contents())
        self.page.get_by_role('button',name='加入候选夹',exact=True).click()
        self.page.locator('.selection-product-list summary').click()
        buttons=self.page.get_by_role('button',name='加入候选 ',exact=False)
        for i in range(buttons.count()):
            if buttons.nth(i).is_enabled():buttons.nth(i).click();break
        checks=self.page.get_by_role('checkbox',name='对比候选 ',exact=False)
        expect(checks).to_have_count(2)
        checks.nth(0).check();checks.nth(1).check()
        self.page.get_by_role('button',name='对比所选两款').click()
        expect(self.page.get_by_test_id('capability-chart')).to_be_visible(timeout=20000)
        self.page.get_by_role('button',name='返回选品地图').click()
        expect(self.page.get_by_role('heading',name='保湿面霜选择图')).to_be_visible()
        expect(self.page.get_by_role('spinbutton',name='整件参考价上限')).to_have_value('1000')
        expect(self.page.get_by_role('checkbox',name='对比候选 ',exact=False)).to_have_count(2)

    def test_missing_records_are_explained_not_plotted_at_zero(self):
        self.ready()
        self.page.get_by_role('button',name='元/g',exact=False).click()
        expect(self.page.locator('.selection-empty-plot')).to_be_visible()
        expect(self.page.locator('.selection-dot')).to_have_count(0)
        self.page.locator('.selection-excluded summary').click()
        expect(self.page.locator('.selection-excluded')).to_contain_text('属于另一单位组')
        self.page.get_by_role('button',name='元/ml',exact=False).click()
        expect(self.page.locator('.selection-dot').first).to_be_visible()

    def test_source_is_one_click_and_slow_response_cannot_replace_new_need(self):
        self.ready()
        self.page.locator('.selection-source-row').first.click()
        expect(self.page.get_by_role('dialog')).to_be_visible()
        self.page.keyboard.press('Escape')
        self.page.route('**/api/selection-map?**',lambda route: self._slow_old(route))
        self.page.get_by_role('button',name='修护',exact=False).first.click()
        self.page.get_by_role('button',name='舒缓',exact=False).first.click()
        expect(self.page.get_by_role('heading',name='舒缓面霜选择图')).to_be_visible()
        expect(self.page.get_by_role('group',name='舒缓方向价格与成分证据选择图')).to_be_visible(timeout=20000)
        self.page.wait_for_timeout(1200)
        expect(self.page.get_by_role('group',name='舒缓方向价格与成分证据选择图')).to_be_visible()

    def _slow_old(self,route):
        response=route.fetch()
        if 'efficacy=%E4%BF%AE%E6%8A%A4' in route.request.url:self.page.wait_for_timeout(800)
        route.fulfill(response=response)

    def test_mobile_keyboard_list_and_no_horizontal_overflow(self):
        self.page.set_viewport_size({'width':390,'height':844});self.ready()
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'))
        self.page.locator('.selection-product-list summary').click()
        button=self.page.get_by_role('button',name='加入候选 ',exact=False).first
        button.focus();self.page.keyboard.press('Enter')
        expect(self.page.get_by_role('checkbox',name='对比候选 ',exact=False)).to_have_count(1)
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'))

    def test_rectangle_selection_caps_four_and_keeps_fixed_axes(self):
        self.ready();svg=self.page.locator('.selection-plot svg[role=group]')
        text=svg.locator('text').all_text_contents()
        self.page.get_by_role('button',name='框选候选',exact=True).click()
        box=svg.bounding_box()
        self.page.mouse.move(box['x']+2,box['y']+2);self.page.mouse.down()
        self.page.mouse.move(box['x']+box['width']-2,box['y']+box['height']-2,steps=8);self.page.mouse.up()
        expect(self.page.get_by_role('checkbox',name='对比候选 ',exact=False)).to_have_count(4)
        self.assertEqual(text,svg.locator('text').all_text_contents())
        expect(self.page.get_by_role('complementary',name='候选夹快捷入口')).to_be_visible()

    def test_map_api_failure_preserves_comparison_and_overview(self):
        self.page.route('**/api/selection-map?**',lambda route:route.fulfill(status=503,json={'detail':'验收：数据暂不可用'}))
        self.page.goto(BASE_URL+'/?view=selection&efficacy=保湿')
        expect(self.page.get_by_role('alert')).to_contain_text('数据暂不可用')
        self.page.get_by_role('button',name='两款对比',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-loaded','true')

    def test_candidate_identity_survives_catalogue_failure_and_category_switch(self):
        self.page.route('**/api/product-space',lambda route:route.fulfill(status=503,json={'detail':'全库暂不可用'}))
        self.ready()
        name=self.page.locator('.selection-detail h2').inner_text()
        self.page.get_by_role('button',name='加入候选夹',exact=True).click()
        self.page.get_by_role('combobox',name='护肤品类').select_option('精华')
        expect(self.page.get_by_role('heading',name='保湿精华选择图')).to_be_visible()
        expect(self.page.get_by_role('checkbox',name='对比候选 '+name,exact=True)).to_have_count(1)
