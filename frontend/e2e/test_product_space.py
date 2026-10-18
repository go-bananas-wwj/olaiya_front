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
        self.page.get_by_role('button',name='看八维证据',exact=True).click()
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
        self.page.get_by_role('button',name='产品地图',exact=True).click()
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
        panel=self.page.get_by_role('complementary',name='产品详情')
        expect(panel).to_be_visible()
        self.assertEqual(self.page.get_by_role('dialog',name='产品详情').count(),0)
        self.page.get_by_role('button',name='关闭产品详情',exact=True).click()
        expect(panel).to_have_count(0)

    def test_keyboard_search_and_empty_search(self):
        self.ready();search=self.page.get_by_role('combobox',name='搜索全部产品')
        search.fill('没有这款产品abcdef');expect(self.page.get_by_text('未找到产品，试试品牌或其他名称。',exact=True)).to_be_visible()
        search.fill('Serum 10');search.press('ArrowDown');search.press('ArrowUp');search.press('Enter')
        expect(self.page.get_by_role('complementary',name='产品详情').get_by_role('heading',name='SkinCeuticals Serum 10',exact=True)).to_be_visible()

    def test_keyboard_active_result_stays_inside_scroll_view(self):
        self.ready();search=self.page.get_by_role('combobox',name='搜索全部产品');search.fill('修丽可')
        for _ in range(7):search.press('ArrowDown')
        option=self.page.locator('#space-result-7')
        self.page.wait_for_function('''() => {const e=document.getElementById('space-result-7');if(!e)return false;
          const a=e.getBoundingClientRect(),b=e.parentElement.getBoundingClientRect();return a.top>=b.top&&a.bottom<=b.bottom;}''')
        self.assertEqual(search.get_attribute('aria-activedescendant'),'space-result-7')

    def test_profile_numbers_are_readable_and_contributions_are_revealed(self):
        self.ready();self.select('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        self.page.get_by_role('button',name='看八维证据',exact=True).click()
        first=self.page.locator('.space-profile-row strong').first
        self.assertGreaterEqual(float(first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')),12)
        self.page.get_by_role('button',name='查看保湿的贡献成分',exact=True).click()
        self.page.wait_for_function('''() => {const e=document.querySelector('.space-panel-contributions');if(!e)return false;
          const r=e.getBoundingClientRect(),panel=e.closest('aside,dialog').getBoundingClientRect();
          return r.top>=Math.max(0,panel.top)&&r.top+80<Math.min(innerHeight,panel.bottom);}''')

    def test_two_core_entries_are_visible_and_comparison_is_immediate(self):
        self.ready()
        expect(self.page.get_by_role('button',name='产品地图',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='两款对比',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-loaded','true')
        self.assertLess(self.page.locator('#benefits').bounding_box()['y'],300)
        for name in ['保湿','抗皱','修护','舒缓','抗氧化','美白','控油祛痘','焕肤']:
            expect(self.page.get_by_role('button',name=f'查看{name}依据',exact=True)).to_be_visible()
        last=self.page.get_by_role('button',name='查看焕肤依据',exact=True).bounding_box()
        self.assertLess(last['y']+last['height'],800)

    def test_map_nodes_and_real_neighbor_comparison(self):
        self.ready()
        m=self.page.get_by_test_id('space-map')
        self.assertGreaterEqual(float(m.get_attribute('data-min-marker-radius')),5.5)
        expect(self.page.get_by_role('region',name='相近产品')).to_be_visible()
        action=self.page.get_by_role('region',name='相近产品').get_by_role('button',name='与',exact=False).first
        expect(action).to_be_visible();action.click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id','9')
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-loaded','true')

    def test_comparison_picker_state_survives_map_round_trip(self):
        self.ready();self.page.get_by_role('button',name='两款对比',exact=True).click()
        self.page.get_by_role('button',name='更换产品 A',exact=True).click()
        self.page.get_by_role('combobox',name='搜索产品 A').fill('Serum 10')
        self.page.get_by_role('option',name='选择 SkinCeuticals Serum 10',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id','414')
        self.page.get_by_role('button',name='产品地图',exact=True).click()
        self.page.get_by_role('button',name='两款对比',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id','414')
        self.assertIn('compare=414',self.page.url)

    def test_raw_coordinate_zero_and_maxima_are_drawn_after_reset(self):
        rows=[]
        for i,(x,y) in enumerate([(0,0),(1,2),(4.25,4.6)]):
            scores=[x,1,y,1,1,1,1,1]
            rows.append({'id':910001+i,'name':f'极值测试{i}','brand':'测试品牌','scores':scores,'statuses':['scored']*8,'coordinates':None,'ingredient_count':3,'evidence_ingredient_count':3,'source_count':1,'price_current':None})
        self.page.route('**/api/product-space',lambda r:r.fulfill(json={'total':3,'directions':['保湿','抗皱','修护','舒缓','抗氧化','美白','控油祛痘','焕肤'],'method_version':'evidence-index-v1','projection':{'status':'unavailable'},'products':rows}))
        self.page.reload();self.ready();self.page.get_by_role('button',name='重置地图',exact=True).click()
        expect(self.page.get_by_test_id('space-map')).to_have_attribute('data-rendered-product-count','3')

    def test_late_neighbors_do_not_replace_new_reference(self):
        self.ready();delayed=[]
        self.page.route('**/api/products/414/similar?*',lambda r:delayed.append((r,'composition')))
        self.page.route('**/api/products/414/space-neighbors?*',lambda r:delayed.append((r,'evidence')))
        with self.page.expect_request('**/api/products/414/similar?*'):
            self.select('Serum 10','SkinCeuticals Serum 10')
        self.page.get_by_role('button',name='功效证据接近',exact=True).click()
        self.select('C E Ferulic','SkinCeuticals Prevent C E Ferulic® With 15% L-Ascorbic Acid')
        region=self.page.get_by_role('region',name='相近产品')
        expect(region.locator('.related-card')).to_have_count(3)
        for route,kind in delayed:
            item={'id':73,'name':'STALE_CANDIDATE','brand':'测试'}
            route.fulfill(json={'similar':[item]} if kind=='composition' else {'available':True,'compared_directions':['保湿'],'items':[item]})
        self.page.wait_for_timeout(200)
        expect(region.get_by_text('STALE_CANDIDATE',exact=True)).to_have_count(0)
        expect(self.page.get_by_role('complementary',name='产品详情').get_by_role('heading',name='SkinCeuticals Prevent C E Ferulic® With 15% L-Ascorbic Acid',exact=True)).to_be_visible()

    def test_unavailable_neighbors_preserve_map_and_comparison(self):
        self.page.route('**/api/products/9/similar?*',lambda r:r.fulfill(json={'similar':None,'reason':'成分索引暂不可用'}))
        self.page.route('**/api/products/9/space-neighbors?*',lambda r:r.fulfill(json={'available':False,'reason':'参照资料不足（测试场景）','items':[]}))
        self.page.reload();self.ready()
        region=self.page.get_by_role('region',name='相近产品')
        expect(region.get_by_text('成分索引暂不可用',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='功效证据接近',exact=True).click()
        expect(region.get_by_text('参照资料不足（测试场景）',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='两款对比',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-loaded','true')
        expect(self.page.get_by_role('button',name='查看焕肤依据',exact=True)).to_be_visible()
