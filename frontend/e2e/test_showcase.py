from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase


class ShowcaseTest(BrowserTestCase):
    def test_first_screen_shows_purpose_products_and_all_eight_directions(self):
        expect(self.page.get_by_role('heading', name='护肤品功效证据对比', exact=True)).to_be_visible()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-loaded', 'true')
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-loaded', 'true')
        self.assertLess(self.page.get_by_test_id('target-product').bounding_box()['y'], 300)
        last = self.page.get_by_role('button', name='查看焕肤依据', exact=True)
        expect(last).to_be_visible()
        box = last.bounding_box()
        self.assertLessEqual(box['y'] + box['height'], 800)
        self.assertEqual(self.page.get_by_role('button', name='核验参照产品').count(), 0)
        direction = self.page.get_by_role('button', name='查看抗皱依据', exact=True)
        direction.focus(); direction.press('Enter')
        expect(self.page.get_by_role('complementary', name='抗皱的成分依据')).to_be_visible()

    def test_direction_to_ingredient_to_actual_source_and_both_presets(self):
        self.page.get_by_role('button', name='查看保湿依据', exact=True).click()
        self.page.get_by_test_id('contributions-A').get_by_role('button', name='查看来源', exact=True).first.click()
        dialog = self.page.get_by_role('dialog', name='成分证据')
        expect(dialog.get_by_text('本指数采用的证据', exact=True)).to_be_visible()
        expect(dialog.get_by_text('计算贡献', exact=False)).to_be_visible()
        self.page.keyboard.press('Escape')
        self.page.get_by_role('button', name='Serum 10 / C E Ferulic', exact=True).click()
        expect(self.page.get_by_test_id('candidate-product').get_by_text('参考价 ¥1720.00', exact=False)).to_be_visible()
        self.page.get_by_role('button', name='黑绷带 / A.G.E.', exact=True).click()
        expect(self.page.get_by_test_id('candidate-product').get_by_text('参考价 ¥1920.00', exact=False)).to_be_visible()

    def test_both_product_searches_and_mobile_layout(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.get_by_role('combobox', name='搜索产品 A').fill('烟酰胺')
        self.page.get_by_role('option', name='选择 烟酰胺10%+锌1%精华（Niacinamide 10% + Zinc 1%）').click()
        expect(self.page.get_by_test_id('target-product').get_by_text('The Ordinary', exact=True)).to_be_visible()
        self.page.get_by_role('combobox', name='搜索产品 B').fill('Serum 10')
        self.page.get_by_role('option', name='选择 SkinCeuticals Serum 10', exact=True).click()
        expect(self.page.get_by_test_id('candidate-product').get_by_role('heading', name='SkinCeuticals Serum 10', exact=True)).to_be_visible()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)

    def test_search_ignores_old_response(self):
        delayed = []
        def handler(route):
            q = parse_qs(urlparse(route.request.url).query).get('q', [''])[0]
            if q == 'oldquery': delayed.append(route)
            else: route.fulfill(json={'items': [{'id': 414, 'brand': '修丽可', 'name': 'new result'}]})
        self.page.route('**/api/products?*', handler)
        search = self.page.get_by_role('combobox', name='搜索产品 A')
        with self.page.expect_request('**/api/products?q=oldquery&limit=8'):
            search.fill('oldquery')
        search.fill('newquery')
        expect(self.page.get_by_role('option', name='选择 new result', exact=True)).to_be_visible()
        delayed[0].fulfill(json={'items': [{'id': 73, 'brand': '修丽可', 'name': 'old result'}]})
        expect(self.page.get_by_role('option', name='选择 old result', exact=True)).to_have_count(0)

    def test_failed_profile_keeps_other_product_and_prices(self):
        self.page.route('**/api/products/73/capability-profile', lambda route: route.fulfill(status=503, json={'detail':'测试加载失败'}))
        self.page.reload()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-loaded', 'true')
        expect(self.page.get_by_text('B 的指数加载失败', exact=False)).to_be_visible()
        expect(self.page.get_by_test_id('candidate-product').get_by_text('参考价 ¥1920.00', exact=False)).to_be_visible()

    def test_similar_is_lazy_and_missing_index_is_explicit(self):
        seen = []
        self.page.on('request', lambda r: seen.append(r.url) if '/similar' in r.url else None)
        self.page.reload()
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-loaded', 'true')
        self.assertEqual(seen, [])
        self.page.get_by_role('button', name='找相似产品', exact=True).click()
        expect(self.page.get_by_role('dialog', name='选择相似候选')).to_be_visible()
        self.page.get_by_text('匹配说明', exact=True).click()
        self.page.route('**/api/products/*/similar?*', lambda route: route.fulfill(json={'similar':None,'reason':'相似索引未构建'}))
        self.page.get_by_label('匹配方式').select_option('embedding')
        expect(self.page.get_by_text('相似索引未构建', exact=False)).to_be_visible()

    def test_common_scale_unknown_values_and_zero_are_visible(self):
        names = ['保湿','抗皱','修护','舒缓','抗氧化','美白','控油祛痘','焕肤']
        def profile(pid, score):
            return {'product_id':pid,'method_version':'evidence-index-v1','coverage':{'ingredients_total':2,'ingredients_scored':1},'excluded':[],
                    'dimensions':[{'canonical':f,'score':score if f=='保湿' else None,'status':'scored' if f=='保湿' else 'no_evidence',
                                   'ingredient_count':1 if f=='保湿' else 0,'source_count':1,'dose_coverage':{'assessable':0,'total':1},'contributions':[]} for f in names]}
        self.page.route('**/api/products/9/capability-profile', lambda r:r.fulfill(json=profile(9,0)))
        self.page.route('**/api/products/73/capability-profile', lambda r:r.fulfill(json=profile(73,2.8)))
        self.page.reload()
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-loaded', 'true')
        expect(self.page.get_by_test_id('capability-chart')).to_have_attribute('data-scale', '3')
        expect(self.page.get_by_test_id('bar-A-保湿')).to_have_attribute('data-score','0')
        expect(self.page.get_by_test_id('bar-B-保湿')).to_have_attribute('data-score','2.8')
        expect(self.page.get_by_role('button',name='查看抗皱依据')).to_contain_text('资料不足')

    def test_profile_race_does_not_replace_new_selection(self):
        delayed=[]
        self.page.route('**/api/products/9/capability-profile',lambda route:delayed.append(route))
        self.page.reload()
        self.page.get_by_role('button',name='Serum 10 / C E Ferulic',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id','414')
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-loaded','true')
        for route in delayed: route.fulfill(json={'product_id':9,'dimensions':[],'coverage':{}})
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id','414')

    def test_same_product_has_equal_scores_and_no_invented_difference(self):
        self.page.get_by_role('combobox', name='搜索产品 B').fill('黑绷带面霜')
        self.page.get_by_role('option', name='选择 黑绷带面霜（Re-Plasty Age Recovery Night）', exact=True).click()
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-product-id', '9')
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-loaded', 'true')
        expect(self.page.get_by_text('此视图暂无列出的成分。', exact=True)).to_be_visible()
        self.assertEqual(self.page.get_by_test_id('bar-A-保湿').get_attribute('data-score'), self.page.get_by_test_id('bar-B-保湿').get_attribute('data-score'))
