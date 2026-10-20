import math
from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase, BASE_URL


class ContextBallCanvasTest(BrowserTestCase):
    def ready(self):
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-renderer-state', 'ready', timeout=30000)

    def idle(self):
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-transition-state', 'idle', timeout=10000)

    def test_selected_range_keeps_visible_context_without_wireframe(self):
        self.ready()
        self.page.get_by_role('button', name='试试黑绷带', exact=True).click()
        stage = self.page.get_by_test_id('projector-stage')
        expect(stage).to_have_attribute('data-view-kind', 'similarity')
        self.idle()
        expect(stage).to_have_attribute('data-envelope-style', 'surface')
        canvas = self.page.get_by_test_id('projector-canvas')
        data = self.page.request.get(BASE_URL + '/api/products/9/similarity-space').json()
        outside = [p['id'] for p in data['items'] if p['score'] < .9 - 1e-6]
        points = canvas.evaluate('(e,ids)=>ids.map(id=>e.getScreenPoint(id)).filter(p=>p?.visible)', outside)
        self.assertGreater(len(points), 100)
        self.assertGreaterEqual(float(stage.get_attribute('data-context-opacity')), .25)
        self.assertLess(float(stage.get_attribute('data-sphere-screen-diameter')), stage.bounding_box()['width'] * .55)

    def test_coincident_products_have_distinct_clickable_display_positions(self):
        self.ready()
        self.page.get_by_role('button', name='试试黑绷带', exact=True).click()
        stage = self.page.get_by_test_id('projector-stage')
        expect(stage).to_have_attribute('data-view-kind', 'similarity')
        self.idle()
        canvas = self.page.get_by_test_id('projector-canvas')
        data = self.page.request.get(BASE_URL + '/api/products/9/similarity-space').json()
        points = canvas.evaluate('(e,ids)=>ids.map(id=>({id,...e.getScreenPoint(id)})).filter(p=>p.visible)', [p['id'] for p in data['items']])
        pairs = [(a,b) for i,a in enumerate(points) for b in points[i+1:] if math.dist(a['worldPosition'], b['worldPosition']) < 1e-8]
        self.assertTrue(pairs)
        pairs=[pair for pair in pairs if math.dist([pair[0]['x'],pair[0]['y']],[pair[1]['x'],pair[1]['y']])>4]
        self.assertTrue(pairs)
        a,b = pairs[0]
        self.assertGreater(math.dist([a['x'],a['y']], [b['x'],b['y']]), 4)
        self.page.mouse.click(b['clientX'], b['clientY'])
        self.idle()
        expect(self.page.get_by_role('dialog', name='重叠位置的产品')).to_have_count(0)

    def test_need_plane_shows_real_axes_and_changes_positions_for_each_direction(self):
        self.ready()
        self.page.get_by_role('button', name='从保湿开始', exact=True).click()
        self.idle()
        axes = self.page.get_by_test_id('projector-need-axes')
        expect(axes).to_be_visible()
        expect(axes).to_contain_text('已收录成分数')
        expect(axes).to_contain_text('保湿成分证据指数')
        canvas = self.page.get_by_test_id('projector-canvas')
        before = canvas.evaluate('e=>[9,73,414].map(id=>e.getScreenPoint(id).worldPosition)')
        self.page.get_by_role('complementary', name='数据与投影设置').get_by_role('button', name='修护', exact=True).click()
        self.idle()
        expect(axes).to_contain_text('修护成分证据指数')
        after = canvas.evaluate('e=>[9,73,414].map(id=>e.getScreenPoint(id).worldPosition)')
        self.assertTrue(any(a[1] != b[1] for a,b in zip(before,after)))
        self.assertTrue(all(a[0] == b[0] for a,b in zip(before,after)))
        expect(axes).to_contain_text('资料待补')
