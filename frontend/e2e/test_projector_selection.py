from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase,BASE_URL


class ProjectorSelectionTest(BrowserTestCase):
    def ready(self):
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-renderer-state','ready',timeout=30000)

    def select(self):
        canvas=self.page.get_by_test_id('projector-canvas');point=canvas.evaluate('e=>e.getScreenPoint(9)')
        self.page.mouse.click(point['clientX'],point['clientY'])
        expect(self.page.get_by_test_id('projector-info')).to_have_attribute('data-product-id','9')

    def assert_overview(self,before):
        expect(self.page.get_by_test_id('projector-info')).to_have_count(0)
        expect(self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]')).to_have_count(0)
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-camera-motion','idle')
        self.page.wait_for_function("d=>Math.abs(Number(document.querySelector('[data-testid=projector-stage]').dataset.cameraDistance)-d)<.001",arg=before)
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count','3749')

    def test_visible_return_cancels_inflight_focus_and_restores_initial_overview(self):
        self.ready();before=float(self.page.get_by_test_id('projector-stage').get_attribute('data-camera-distance'))
        self.select();self.page.get_by_role('button',name='返回全景',exact=True).click()
        self.assert_overview(before);self.page.wait_for_timeout(750);self.assert_overview(before)

    def test_empty_click_clears_but_rotation_does_not_and_escape_can_return(self):
        self.ready();stage=self.page.get_by_test_id('projector-stage');before=float(stage.get_attribute('data-camera-distance'));self.select()
        expect(stage).to_have_attribute('data-camera-motion','idle');canvas=self.page.get_by_test_id('projector-canvas');box=canvas.bounding_box()
        self.page.mouse.move(box['x']+15,box['y']+box['height']-20);self.page.mouse.down();self.page.mouse.move(box['x']+80,box['y']+box['height']-30,steps=5);self.page.mouse.up()
        expect(self.page.get_by_test_id('projector-info')).to_be_visible()
        self.page.mouse.click(box['x']+8,box['y']+8);self.assert_overview(before)
        self.select();canvas.focus();self.page.keyboard.press('Escape');self.assert_overview(before)

    def test_mobile_has_a_direct_return_and_immediate_product_picture(self):
        self.page.set_viewport_size({'width':390,'height':844});self.ready();before=float(self.page.get_by_test_id('projector-stage').get_attribute('data-camera-distance'));self.select()
        card=self.page.get_by_test_id('projector-info');expect(card.locator('img')).to_be_visible()
        expect(self.page.get_by_role('button',name='返回全景',exact=True)).to_be_visible()
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-camera-motion','idle')
        point=self.page.get_by_test_id('projector-canvas').evaluate('e=>e.getScreenPoint(9)')
        self.assertLess(point['clientY']+10,card.bounding_box()['y'])
        self.page.get_by_role('button',name='返回全景',exact=True).click();self.assert_overview(before)

    def test_selected_product_shows_photo_actual_ingredients_claims_and_sources(self):
        self.ready();self.select();card=self.page.get_by_test_id('projector-info')
        expect(card.locator('img')).to_be_visible();expect(card.get_by_role('heading',name='已收录成分',exact=False)).to_be_visible()
        expect(card.get_by_role('button',name='查看成分 甘油',exact=True)).to_be_visible()
        expect(card).to_contain_text('功效宣称')
        card.get_by_role('button',name='查看成分 甘油',exact=True).click();expect(self.page.get_by_role('dialog',name='成分证据')).to_be_visible()
        self.page.keyboard.press('Escape');card.get_by_role('button',name='取消选中产品',exact=True).click();expect(card).to_have_count(0)

    def test_late_product_description_cannot_replace_new_selection_or_clear(self):
        self.ready();old=self.page.request.get(BASE_URL+'/api/products/9').json();delayed=[]
        self.page.route('**/api/products/9',lambda route:delayed.append(route))
        self.select()
        search=self.page.get_by_role('combobox',name='搜索全部产品');search.fill('Serum 10')
        self.page.get_by_role('option',name='选择 SkinCeuticals Serum 10',exact=True).click()
        card=self.page.get_by_test_id('projector-info');expect(card).to_have_attribute('data-product-id','414')
        expect(card.locator('img')).to_have_attribute('src','/products/414.jpg')
        for route in delayed:route.fulfill(json=old)
        self.page.wait_for_timeout(150);expect(card).to_have_attribute('data-product-id','414')
        self.page.get_by_role('button',name='返回全景',exact=True).click();self.page.wait_for_timeout(700);expect(card).to_have_count(0)

    def test_missing_photo_does_not_hide_real_product_or_ingredients(self):
        self.ready();self.page.route('**/products/9.jpg',lambda route:route.abort());self.select()
        card=self.page.get_by_test_id('projector-info');expect(card).to_contain_text('图片暂不可用')
        expect(card.get_by_role('button',name='查看成分 甘油',exact=True)).to_be_visible()
        expect(self.page.get_by_role('button',name='返回全景',exact=True)).to_be_visible()

    def test_real_recorded_claims_are_shown_without_substituting_ingredient_effects(self):
        self.ready();product=self.page.request.get(BASE_URL+'/api/products/124').json()
        self.page.get_by_role('combobox',name='搜索全部产品').fill(product['name'])
        self.page.get_by_role('option',name='选择 '+product['name'],exact=True).click()
        card=self.page.get_by_test_id('projector-info');expect(card).to_have_attribute('data-product-id','124')
        for claim in product['claims']:expect(card.get_by_role('region',name='产品功效宣称')).to_contain_text(claim['claim'])
