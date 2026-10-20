import math
from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase,BASE_URL

class ProjectorExploreTest(BrowserTestCase):
    def ready(self):
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-renderer-state','ready',timeout=30000)
    def idle(self):
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-transition-state','idle',timeout=10000)
    def test_first_entry_guides_need_and_projects_same_products_without_price_gate(self):
        self.ready();canvas=self.page.get_by_test_id('projector-canvas');before=canvas.evaluate('e=>[9,73,414].map(id=>e.getScreenPoint(id).worldPosition)')
        self.page.get_by_role('button',name='怎么操作',exact=True).click();expect(self.page.get_by_role('region',name='操作指南')).to_contain_text('点一个产品')
        self.page.get_by_role('button',name='从保湿开始',exact=True).click();self.idle();stage=self.page.get_by_test_id('projector-stage')
        expect(stage).to_have_attribute('data-view-kind','need');expect(stage).to_have_attribute('data-rendered-count','3749')
        after=canvas.evaluate('e=>[9,73,414].map(id=>e.getScreenPoint(id).worldPosition)')
        for a,b in zip(before,after):self.assertAlmostEqual(a[0],b[0]);self.assertAlmostEqual(a[1],b[1]);self.assertEqual(b[2],0)
        self.assertIn('plane=need',self.page.url)
        counts=self.page.request.get(BASE_URL+'/api/product-space').json();n=sum(p['scores'][0] is not None for p in counts['products']);self.assertGreater(n,200)
        expect(self.page.get_by_role('button',name=f'成分证据 {n}',exact=True)).to_be_visible()
    def test_native_threshold_sphere_and_list_agree_and_threshold_does_not_move_points(self):
        self.ready();self.page.get_by_role('button',name='试试黑绷带',exact=True).click();stage=self.page.get_by_test_id('projector-stage');expect(stage).to_have_attribute('data-view-kind','similarity');self.idle()
        data=self.page.request.get(BASE_URL+'/api/products/9/similarity-space').json();self.assertTrue(data['complete']);self.assertGreater(len(data['items']),100)
        canvas=self.page.get_by_test_id('projector-canvas');before=canvas.evaluate('e=>e.getScreenPoint(73).worldPosition')
        for threshold in [95,80,100]:
            self.page.get_by_role('slider',name='相似度筛选',exact=True).fill(str(threshold));self.idle()
            expected=[p for p in data['items'] if max(-1,min(1,p['score']))>=threshold/100-1e-6]
            expect(self.page.get_by_test_id('projector-neighbors')).to_have_attribute('data-matched-count',str(len(expected)))
            radius=float(stage.get_attribute('data-sphere-radius'))
            rows=canvas.evaluate('(e,ids)=>ids.map(id=>e.getScreenPoint(id))',[p['id'] for p in expected])
            self.assertTrue(all(p and p['semanticRadius']<=radius+1e-8 and math.hypot(*p['worldPosition'])<=radius+1e-8 and p['displayOffset']==[0,0] for p in rows))
            self.assertEqual(canvas.evaluate('e=>e.getScreenPoint(73).worldPosition'),before)
        self.page.get_by_role('button',name='返回全景',exact=True).click();self.idle();expect(stage).to_have_attribute('data-view-kind','overview')
    def test_quick_need_switches_keep_latest_plane_and_coverage(self):
        self.ready();side=self.page.get_by_role('complementary',name='数据与投影设置')
        for need in ['保湿','修护','舒缓']:side.get_by_role('button',name=need,exact=True).click()
        self.idle();expect(self.page.get_by_role('heading',name='舒缓 · 需求视图')).to_be_visible();expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-dimensions','2')
        self.page.get_by_role('button',name='返回三维全景',exact=True).click();self.idle();expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-dimensions','3')
    def test_white_surfaces_and_legacy_price_comparison_remain_available(self):
        self.ready();self.page.get_by_role('button',name='从保湿开始',exact=True).click();self.idle();self.page.get_by_role('button',name='比较参考价格',exact=False).click()
        expect(self.page.get_by_role('heading',name='保湿面霜选择图')).to_be_visible()
        self.assertEqual(self.page.locator('.selection-page').evaluate('e=>getComputedStyle(e).backgroundColor'),'rgb(255, 255, 255)')
        self.page.get_by_role('navigation',name='核心功能').get_by_role('button',name='两款对比',exact=True).click();expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-loaded','true')
        self.assertEqual(self.page.locator('body').evaluate('e=>getComputedStyle(e).backgroundColor'),'rgb(255, 255, 255)')

    def test_mobile_similarity_panel_has_opaque_background_and_selected_point_above_card(self):
        self.page.set_viewport_size({'width':390,'height':844});self.ready()
        self.page.get_by_role('button',name='试试黑绷带',exact=True).click()
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-view-kind','similarity');self.idle()
        point=self.page.get_by_test_id('projector-canvas').evaluate('e=>e.getScreenPoint(9)')
        self.assertLess(point['clientY']+70,self.page.get_by_test_id('projector-info').bounding_box()['y'])
        self.page.get_by_role('button',name='搜索与相似产品',exact=False).click()
        self.assertEqual(self.page.locator('.projector-inspector.is-open').evaluate('e=>getComputedStyle(e).backgroundColor'),'rgb(255, 255, 255)')
