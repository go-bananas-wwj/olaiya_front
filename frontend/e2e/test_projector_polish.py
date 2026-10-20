import io
from PIL import Image
from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase,BASE_URL

class ProjectorPolishTest(BrowserTestCase):
    def ready(self):
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-renderer-state','ready',timeout=30000)

    def test_intro_and_neutral_sidebar_explain_the_product_without_filling_the_plot(self):
        self.page.set_viewport_size({'width':1280,'height':800});self.ready()
        intro=self.page.get_by_role('region',name='产品介绍')
        expect(intro).to_contain_text('护肤品地图')
        expect(intro).to_contain_text('参考价格')
        self.assertLess(intro.bounding_box()['height'],100)
        side=self.page.get_by_role('complementary',name='数据与投影设置')
        self.assertNotIn('无向量',side.inner_text())
        self.assertNotIn('绿色突出',side.inner_text())
        color=side.locator('.projector-need-intro').evaluate('e=>getComputedStyle(e).backgroundColor')
        self.assertIn(color,['rgb(255, 255, 255)','rgb(249, 250, 252)'])
        expect(self.page.get_by_test_id('projector-paper-axes')).to_contain_text('UMAP 1')
        expect(self.page.get_by_test_id('projector-paper-axes')).to_contain_text('UMAP 3')

    def test_spread_points_are_individually_drawn_at_their_hit_targets_and_source_coords_stay_equal(self):
        self.ready();data=self.page.request.get(BASE_URL+'/api/product-space').json();groups={}
        for p in data['products']:
            if p['coordinates_3d'] is not None:groups.setdefault(tuple(p['coordinates_3d']),[]).append(p['id'])
        ids=next(ids for ids in groups.values() if len(ids)==2)
        canvas=self.page.get_by_test_id('projector-canvas')
        points=[canvas.evaluate('(e,id)=>e.getScreenPoint(id)',i) for i in ids]
        self.assertAlmostEqual(points[0]['rawX'],points[1]['rawX']);self.assertAlmostEqual(points[0]['rawY'],points[1]['rawY'])
        self.assertGreaterEqual(((points[0]['x']-points[1]['x'])**2+(points[0]['y']-points[1]['y'])**2)**.5,17.99)
        expect(self.page.locator('.projector-coincident-badge')).to_have_count(0)
        raster=Image.open(io.BytesIO(canvas.screenshot(scale='css'))).convert('RGB')
        for point in points:
            x,y=round(point['x']),round(point['y']);pixels=[raster.getpixel((xx,yy)) for xx in range(x-1,x+2) for yy in range(y-1,y+2)]
            self.assertTrue(any(min(rgb)<230 for rgb in pixels),'WebGL must draw at the same separated position used by picking')
        self.page.locator('.projector-explore-settings').evaluate('e=>e.open=true')
        self.page.get_by_role('checkbox',name='展开重合点').uncheck()
        self.page.wait_for_timeout(100)
        raw=[canvas.evaluate('(e,id)=>e.getScreenPoint(id)',i) for i in ids]
        self.assertAlmostEqual(raw[0]['x'],raw[1]['x']);self.assertAlmostEqual(raw[0]['y'],raw[1]['y'])
        self.page.get_by_role('checkbox',name='展开重合点').check()
        self.assertEqual(self.page.request.get(BASE_URL+'/api/product-space').json()['catalog_signature'],data['catalog_signature'])

    def test_mobile_intro_needs_and_canvas_fit_without_overflow(self):
        self.page.set_viewport_size({'width':390,'height':844});self.ready()
        expect(self.page.get_by_role('region',name='产品介绍')).to_be_visible()
        expect(self.page.locator('.projector-mobile-needs').get_by_role('button',name='保湿',exact=False)).to_be_visible()
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'))
        canvas=self.page.get_by_test_id('projector-canvas').bounding_box()
        self.assertGreater(canvas['height'],300)
        self.assertLessEqual(canvas['y']+canvas['height'],845)

    def test_dense_point_click_selects_one_product_without_a_record_picker(self):
        self.ready();canvas=self.page.get_by_test_id('projector-canvas')
        point=canvas.evaluate('e=>e.getScreenPoint(9)')
        self.page.mouse.click(point['clientX'],point['clientY'])
        expect(self.page.get_by_test_id('projector-info')).to_be_visible()
        expect(self.page.get_by_role('dialog',name='重叠位置的产品')).to_have_count(0)
