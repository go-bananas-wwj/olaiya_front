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
        expect(intro).to_contain_text('护肤品选品地图')
        expect(intro).to_contain_text('每个点是一款产品')
        self.assertLess(intro.bounding_box()['height'],140)
        side=self.page.get_by_role('complementary',name='数据与投影设置')
        self.assertNotIn('无向量',side.inner_text())
        self.assertNotIn('绿色突出',side.inner_text())
        color=side.locator('.projector-need-intro').evaluate('e=>getComputedStyle(e).backgroundColor')
        self.assertIn(color,['rgb(255, 255, 255)','rgba(0, 0, 0, 0)'])
        expect(self.page.get_by_test_id('projector-paper-axes')).to_have_count(0)
        expect(self.page.locator('.projector-toolbar-stat,.projector-paper-legend,.projector-plot-footer')).to_have_count(0)
        expect(self.page.get_by_role('region',name='成分群组')).to_have_count(0)
        self.assertEqual(self.page.locator('.projector-center').evaluate('e=>getComputedStyle(e).backgroundColor'),'rgb(255, 255, 255)')
        self.assertEqual(self.page.locator('.projector-header').evaluate('e=>getComputedStyle(e).backgroundColor'),'rgba(255, 255, 255, 0.86)')

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

    def test_selection_smoothly_focuses_and_caps_visible_names(self):
        self.ready();stage=self.page.get_by_test_id('projector-stage')
        before=float(stage.get_attribute('data-camera-distance'))
        self.page.get_by_role('combobox',name='搜索全部产品').fill('黑绷带面霜')
        self.page.get_by_role('option',name='选择 黑绷带面霜（Re-Plasty Age Recovery Night）',exact=True).click()
        expect(stage).to_have_attribute('data-transition-state','morphing')
        expect(stage).to_have_attribute('data-transition-state','idle')
        # Context framing deliberately keeps more of the surrounding space visible.
        expect(stage).to_have_attribute('data-envelope-style','surface')
        self.assertGreaterEqual(float(stage.get_attribute('data-context-opacity')),.25)
        point=self.page.get_by_test_id('projector-canvas').evaluate('e=>e.getScreenPoint(9)')
        self.assertTrue(point['visible'])
        expect(self.page.locator('.projector-point-label.is-selected')).to_be_visible()
        self.assertLessEqual(self.page.locator('.projector-point-label').count(),4)
        self.page.get_by_role('button',name='返回全景',exact=True).click()
        self.page.wait_for_function("(expected)=>Math.abs(Number(document.querySelector('[data-testid=projector-stage]').dataset.cameraDistance)-expected)<.001",arg=before)

    def test_reduced_motion_and_drag_cancel_focus(self):
        self.ready();stage=self.page.get_by_test_id('projector-stage')
        self.page.emulate_media(reduced_motion='reduce')
        search=self.page.get_by_role('combobox',name='搜索全部产品');search.fill('Serum 10')
        self.page.get_by_role('option',name='选择 SkinCeuticals Serum 10',exact=True).click()
        expect(stage).to_have_attribute('data-transition-state','idle')
        self.page.emulate_media(reduced_motion='no-preference');search.fill('黑绷带面霜')
        self.page.get_by_role('option',name='选择 黑绷带面霜（Re-Plasty Age Recovery Night）',exact=True).click()
        expect(stage).to_have_attribute('data-transition-state','morphing')
        canvas=self.page.get_by_test_id('projector-canvas');box=canvas.bounding_box()
        self.page.mouse.move(box['x']+60,box['y']+box['height']-80);self.page.mouse.down()
        self.page.mouse.move(box['x']+100,box['y']+box['height']-90);self.page.mouse.up()
        expect(stage).to_have_attribute('data-transition-state','idle')

    def test_mobile_card_starts_compact_and_can_expand_details_without_covering_labels(self):
        self.page.set_viewport_size({'width':390,'height':844});self.ready()
        self.page.get_by_role('button',name='搜索与相似产品',exact=False).click()
        self.page.get_by_role('combobox',name='搜索全部产品').fill('黑绷带面霜')
        self.page.get_by_role('option',name='选择 黑绷带面霜（Re-Plasty Age Recovery Night）',exact=True).click()
        self.page.get_by_role('button',name='关闭搜索与相似产品',exact=True).click()
        card=self.page.get_by_test_id('projector-info');heading=card.locator('.projector-info-heading')
        expect(heading).to_have_attribute('aria-expanded','false')
        self.assertLess(card.bounding_box()['height'],self.page.get_by_test_id('projector-stage').bounding_box()['height']*.6)
        expect(card.locator('img')).to_be_visible()
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-camera-motion','idle')
        heading.click();expect(heading).to_have_attribute('aria-expanded','true')
        expect(card.get_by_role('button',name='成分与证据',exact=True)).to_be_visible()
        self.page.wait_for_timeout(100)
        for rect in self.page.locator('.projector-point-label').evaluate_all('(es)=>es.map(e=>{const r=e.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom}})'):
            c=card.bounding_box()
            self.assertTrue(rect['right']<=c['x'] or rect['left']>=c['x']+c['width'] or rect['bottom']<=c['y'] or rect['top']>=c['y']+c['height'])

    def test_expanded_3d_depth_has_actual_depth_cues_and_original_2d_stays_unscaled(self):
        self.ready();stage=self.page.get_by_test_id('projector-stage');canvas=self.page.get_by_test_id('projector-canvas')
        expect(stage).to_have_attribute('data-display-axes','1.12,1.1,2.1')
        data=self.page.request.get(BASE_URL+'/api/product-space').json()
        ids=[p['id'] for p in data['products'] if p['coordinates_3d'] is not None]
        points=canvas.evaluate('(e,ids)=>ids.map(id=>e.getScreenPoint(id)).filter(p=>p&&p.visible)',ids)
        scales=[p['pointScale'] for p in points]
        self.assertGreater(max(scales)/min(scales),1.3)
        self.page.locator('.projector-explore-settings').evaluate('e=>e.open=true')
        self.page.get_by_role('button',name='二维',exact=True).click()
        expect(stage).to_have_attribute('data-display-axes','1,1,1')
        self.assertEqual(canvas.evaluate('e=>e.getScreenPoint(9).pointScale'),1)
        self.assertEqual(self.page.request.get(BASE_URL+'/api/product-space').json(),data)
