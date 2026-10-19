from playwright.sync_api import expect
from frontend.e2e import test_product_space as existing
from frontend.e2e.browser_case import BrowserTestCase, BASE_URL


class ProjectorModesTest(BrowserTestCase):
    ready = existing.ProductSpaceTest.ready
    choose = existing.ProductSpaceTest.choose
    # Only this class's new cases are loaded by the dedicated test command.
    def test_modes_explain_different_features_and_actual_evidence_coverage(self):
        self.ready()
        self.page.get_by_role('button',name='功效证据相似',exact=True).click()
        expect(self.page.get_by_test_id('projector-shell')).to_have_attribute('data-mode','evidence')
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-algorithm','pca')
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count','39',timeout=15000)
        expect(self.page.get_by_test_id('mode-coverage')).to_contain_text('39')
        expect(self.page.get_by_test_id('mode-coverage')).to_contain_text('3710')
        self.page.get_by_role('button',name='成分组成相似',exact=True).click()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count','3749')

    def test_version_identity_and_distance_semantics_are_visible(self):
        self.ready()
        self.choose('科瑞肤多维智效修护面霜（莹润型）','科瑞肤多维智效修护面霜（莹润型）')
        expect(self.page.get_by_test_id('projector-info')).to_contain_text('莹润型')
        expect(self.page.get_by_test_id('distance-explanation')).to_contain_text('越小越接近')
        expect(self.page.get_by_test_id('distance-heading')).to_contain_text('余弦距离')

    def test_evidence_missing_directions_do_not_become_zero_or_fake_points(self):
        self.ready()
        self.page.get_by_role('button',name='功效证据相似',exact=True).click()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count','39')
        self.choose('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        expect(self.page.get_by_test_id('projector-info')).to_contain_text('未进入此地图')
        expect(self.page.get_by_test_id('projector-neighbors')).to_contain_text('资料')
        expect(self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]')).to_have_count(0)
        self.page.get_by_test_id('projector-info').get_by_role('button',name='两款对比',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id','9')

    def test_evidence_neighbors_use_original_eight_axes_and_keep_real_pair(self):
        self.ready()
        self.page.get_by_role('button',name='功效证据相似',exact=True).click()
        data=self.page.request.get(BASE_URL+'/api/product-space/evidence').json()
        chosen=next(p for p in data['products'] if p['eligible'])
        self.choose(chosen['name'],chosen['name'])
        rows=self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]')
        expect(rows).to_have_count(38)
        expected=self.page.request.get(f"{BASE_URL}/api/products/{chosen['id']}/evidence-space-neighbors?limit=100").json()['items']
        self.assertEqual(rows.evaluate_all('(es)=>es.map(e=>Number(e.dataset.neighborId))'),[p['id'] for p in expected])
        expect(self.page.get_by_test_id('distance-heading')).to_contain_text('八方向证据距离')
        self.page.get_by_role('button',name='二维',exact=True).click()
        self.assertEqual(rows.evaluate_all('(es)=>es.map(e=>Number(e.dataset.neighborId))'),[p['id'] for p in expected])
        rows.first.get_by_role('button',name='比较这两款',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id',str(chosen['id']))
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-product-id',str(expected[0]['id']))

    def test_late_semantic_response_cannot_replace_evidence_neighbors(self):
        self.ready()
        data=self.page.request.get(BASE_URL+'/api/product-space/evidence').json()
        chosen=next(p for p in data['products'] if p['eligible'])
        delayed=[]
        self.page.route(f"**/api/products/{chosen['id']}/similar?*",lambda r:delayed.append(r))
        with self.page.expect_request(f"**/api/products/{chosen['id']}/similar?*"):
            self.choose(chosen['name'],chosen['name'])
        self.page.get_by_role('button',name='功效证据相似',exact=True).click()
        rows=self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]')
        expect(rows).to_have_count(38)
        ids=rows.evaluate_all('(es)=>es.map(e=>e.dataset.neighborId)')
        for route in delayed:
            route.fulfill(json={'product_id':chosen['id'],'similar':[{'id':9,'score':1}]})
        self.page.wait_for_timeout(100)
        self.assertEqual(rows.evaluate_all('(es)=>es.map(e=>e.dataset.neighborId)'),ids)
        expect(self.page.get_by_test_id('distance-heading')).to_contain_text('八方向证据距离')

    def test_evidence_failure_preserves_semantic_map_and_two_product_comparison(self):
        self.ready()
        self.page.route('**/api/product-space/evidence',lambda r:r.fulfill(status=503,json={'detail':'temporary'}))
        self.page.get_by_role('button',name='功效证据相似',exact=True).click()
        expect(self.page.get_by_role('alert')).to_contain_text('失败')
        self.page.get_by_role('button',name='成分组成相似',exact=True).click()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count','3749')
        self.page.get_by_role('navigation',name='核心功能').get_by_role('button',name='两款对比',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id','9')

    def test_coincident_groups_remain_distinct_and_keyboard_accessible_without_labels(self):
        self.ready()
        self.page.get_by_role('button',name='显示点标签',exact=True).click()
        summary=self.page.locator('.projector-coincident-summary')
        expect(summary).to_be_visible()
        summary.focus()
        self.page.keyboard.press('Enter')
        dialog=self.page.get_by_role('dialog',name='同位投影记录',exact=True)
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text('按位置分组')
        expect(dialog).to_contain_text('来源记录 #22')
        expect(dialog).to_contain_text('来源记录 #24')
        expect(dialog).to_contain_text('来源记录 #30')
        dialog.locator('.projector-coincident-list button').filter(has_text='兰蔻是我三重精华气垫粉底液 P10').click()
        expect(self.page.get_by_test_id('projector-info')).to_have_attribute('data-product-id','24')
        expect(self.page.get_by_test_id('projector-info')).to_contain_text('P10')
