from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase


class ProductSpaceTest(BrowserTestCase):
    def ready(self):
        expect(self.page.get_by_role('heading',name='护肤品成分地图',exact=True)).to_be_visible()
        expect(self.page.get_by_test_id('space-map')).to_have_attribute('data-ready','true',timeout=20000)

    def select(self,query,name):
        search=self.page.get_by_role('combobox',name='搜索全部产品')
        search.fill(query)
        self.page.get_by_role('option',name=f'查看 {name}',exact=True).click()
        expect(self.page.get_by_role('complementary',name='产品详情').get_by_role('heading',name=name,exact=True)).to_be_visible()

    def test_whole_catalog_map_is_first_screen_and_global_search_works(self):
        self.page.set_viewport_size({'width':1280,'height':800});self.ready()
        m=self.page.get_by_test_id('space-map');box=m.bounding_box()
        self.assertLess(box['y'],250);self.assertGreaterEqual(box['height'],430)
        self.assertGreater(int(m.get_attribute('data-total')),3700)
        self.select('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        expect(self.page.get_by_role('button',name='查看保湿的贡献成分',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='查看保湿的贡献成分',exact=True).click()
        self.page.get_by_role('button',name='查看来源',exact=True).first.click()
        expect(self.page.get_by_role('dialog',name='成分证据')).to_be_visible()
        self.page.keyboard.press('Escape')

    def test_arbitrary_pair_comparison_and_return_preserve_map(self):
        self.ready()
        self.select('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        self.page.get_by_role('button',name='加入对比',exact=True).click()
        self.select('Serum 10','SkinCeuticals Serum 10')
        self.page.get_by_role('button',name='加入对比',exact=True).click()
        self.page.get_by_role('button',name='对比这两款',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id','9')
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-product-id','414')
        self.page.get_by_role('button',name='返回产品地图',exact=True).click()
        self.ready();expect(self.page.get_by_test_id('comparison-tray')).to_be_visible()

    def test_raw_dimensions_and_unknown_list_remain_accessible(self):
        self.ready();self.page.get_by_role('button',name='证据坐标',exact=True).click()
        self.page.get_by_label('横轴维度').select_option('7')
        self.page.get_by_label('纵轴维度').select_option('4')
        expect(self.page.get_by_role('button',name='查看未定位产品',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='查看未定位产品',exact=True).click()
        expect(self.page.get_by_role('complementary',name='产品列表')).to_be_visible()
        self.assertGreater(int(self.page.get_by_test_id('space-map').get_attribute('data-unplaced')),0)

    def test_phone_and_embedded_first_screen(self):
        for width,height in [(834,900),(390,844)]:
            self.page.set_viewport_size({'width':width,'height':height});self.ready()
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width)
            self.assertGreaterEqual(self.page.get_by_test_id('space-map').bounding_box()['height'],350)
        search=self.page.get_by_role('combobox',name='搜索全部产品');search.fill('Serum 10')
        self.page.get_by_role('option',name='查看 SkinCeuticals Serum 10',exact=True).click()
        dialog=self.page.get_by_role('dialog',name='产品详情')
        expect(dialog).to_be_visible();self.page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)

    def test_keyboard_search_and_empty_search(self):
        self.ready();search=self.page.get_by_role('combobox',name='搜索全部产品')
        search.fill('没有这款产品abcdef');expect(self.page.get_by_text('未找到产品，试试品牌或其他名称。',exact=True)).to_be_visible()
        search.fill('Serum 10');search.press('ArrowDown');search.press('Enter')
        expect(self.page.get_by_role('complementary',name='产品详情')).to_contain_text('SkinCeuticals Serum 10')

    def test_keyboard_active_result_stays_inside_scroll_view(self):
        self.ready();search=self.page.get_by_role('combobox',name='搜索全部产品');search.fill('修丽可')
        for _ in range(7):search.press('ArrowDown')
        option=self.page.locator('#space-result-7')
        self.page.wait_for_function('''() => {const e=document.getElementById('space-result-7');if(!e)return false;
          const a=e.getBoundingClientRect(),b=e.parentElement.getBoundingClientRect();return a.top>=b.top&&a.bottom<=b.bottom;}''')
        self.assertEqual(search.get_attribute('aria-activedescendant'),'space-result-7')

    def test_profile_numbers_are_readable_and_contributions_are_revealed(self):
        self.ready();self.select('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        first=self.page.locator('.space-profile-row strong').first
        self.assertGreaterEqual(float(first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')),12)
        self.page.get_by_role('button',name='查看保湿的贡献成分',exact=True).click()
        self.page.wait_for_function('''() => {const e=document.querySelector('.space-panel-contributions');if(!e)return false;
          const r=e.getBoundingClientRect(),panel=e.closest('aside,dialog').getBoundingClientRect();
          return r.top>=Math.max(0,panel.top)&&r.top+80<Math.min(innerHeight,panel.bottom);}''')
