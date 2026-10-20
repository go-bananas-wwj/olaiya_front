from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase,BASE_URL

class ProductSpaceTest(BrowserTestCase):
    def ready(self):
        from frontend.e2e.browser_case import BASE_URL
        total=self.page.request.get(BASE_URL+'/api/product-space').json()['total']
        self.assertGreaterEqual(total,3749)
        expect(self.page.get_by_test_id('projector-shell')).to_have_attribute('data-total',str(total),timeout=30000)
        self.page.locator('.projector-explore-settings').evaluate("e=>e.open=true")
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-dimensions','3')
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-renderer-state','ready')
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count','3749')

    def choose(self,query,name):
        self.page.get_by_role('combobox',name='搜索全部产品').fill(query)
        self.page.get_by_role('option',name='选择 '+name,exact=True).click()

    def test_three_dimensional_projector_is_the_default(self):
        self.ready()
        canvas=self.page.get_by_test_id('projector-canvas')
        self.assertGreater(int(canvas.get_attribute('data-rendered-count')),3700)
        expect(self.page.get_by_role('button',name='两款对比',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='二维',exact=True).click()
        expect(canvas).to_have_attribute('data-dimensions','2')
        self.page.get_by_role('button',name='PCA',exact=True).click()
        expect(canvas).to_have_attribute('data-algorithm','pca')
        self.page.get_by_role('button',name='三维',exact=True).click()
        expect(canvas).to_have_attribute('data-dimensions','3')

    def test_selection_isolates_original_neighbors_and_clears(self):
        self.ready();self.choose('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        expect(self.page.get_by_test_id('projector-info')).to_have_attribute('data-product-id','9')
        expect(self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]')).to_have_count(20,timeout=20000)
        self.page.get_by_role('button',name='隔离选择',exact=True).click()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count',str(int(self.page.get_by_test_id('projector-neighbors').get_attribute('data-matched-count'))+1))
        self.page.get_by_role('button',name='显示全部',exact=True).click()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count','3749')
        self.page.get_by_role('button',name='清除选择',exact=True).click()
        expect(self.page.get_by_test_id('projector-info')).to_have_count(0)
        expect(self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]')).to_have_count(0)

    def test_neighbor_can_open_real_pair_comparison(self):
        self.ready();self.choose('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        row=self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]').first
        expect(row).to_be_visible(timeout=20000)
        neighbor=row.get_attribute('data-neighbor-id');row.get_by_role('button',name='比较这两款',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id','9')
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-product-id',neighbor)
        expect(self.page.get_by_role('button',name='查看焕肤依据',exact=True)).to_be_visible()

    def point(self,pid):
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-transition-state','idle')
        return self.page.get_by_test_id('projector-canvas').evaluate('(e,id)=>e.getScreenPoint(id)',pid)

    def test_real_canvas_rotation_picking_and_home(self):
        self.ready();canvas=self.page.get_by_test_id('projector-canvas')
        before=self.point(9);self.assertTrue(before['visible'])
        self.page.mouse.click(before['clientX'],before['clientY'])
        coincident=self.page.get_by_role('dialog',name='重叠位置的产品')
        if coincident.is_visible():coincident.locator('.projector-coincident-list button').first.click()
        expect(self.page.get_by_test_id('projector-info')).to_be_visible()
        self.assertGreater(int(self.page.get_by_test_id('projector-info').get_attribute('data-product-id')),0)
        box=canvas.bounding_box();self.page.mouse.move(box['x']+box['width']*.25,box['y']+box['height']*.65)
        self.page.mouse.down();self.page.mouse.move(box['x']+box['width']*.5,box['y']+box['height']*.8,steps=15);self.page.mouse.up()
        after=self.point(9);self.assertGreater(abs(before['x']-after['x'])+abs(before['y']-after['y']),20)
        self.page.get_by_role('button',name='重置视角',exact=True).click()
        reset=self.point(9);self.assertLess(abs(before['x']-reset['x'])+abs(before['y']-reset['y']),.2)

    def test_original_neighbor_identity_survives_projection_and_metric_changes(self):
        self.ready();self.choose('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        rows=self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]')
        expect(rows).to_have_count(20)
        ids=rows.evaluate_all('(es)=>es.map(e=>e.dataset.neighborId)')
        self.page.get_by_role('button',name='PCA',exact=True).click()
        self.page.get_by_role('button',name='二维',exact=True).click()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-algorithm','pca')
        self.assertEqual(rows.evaluate_all('(es)=>es.map(e=>e.dataset.neighborId)'),ids)
        expect(self.page.get_by_test_id('distance-heading')).to_contain_text('成分相似度')
        values=rows.locator('.projector-neighbor-main>span').all_text_contents()
        scores=[float(v.rstrip('%')) for v in values]
        self.assertEqual(scores,sorted(scores,reverse=True))
        self.assertEqual(rows.evaluate_all('(es)=>es.map(e=>e.dataset.neighborId)'),ids)
        self.assertEqual(self.page.get_by_text('原始10近邻保留',exact=False).count(),0)
        self.page.get_by_role('slider',name='相似度筛选',exact=True).fill('95')
        expected=[p for p in self.page.request.get(BASE_URL+'/api/products/9/similarity-space').json()['items'] if p['score']>=.95-1e-6]
        expect(rows).to_have_count(min(20,len(expected)))
        self.page.get_by_role('button',name='隔离选择',exact=True).click()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count',str(int(self.page.get_by_test_id('projector-neighbors').get_attribute('data-matched-count'))+1))
        self.assertEqual(rows.evaluate_all('(es)=>es.map(e=>e.dataset.neighborId)'),[str(p['id']) for p in expected][:20])

    def test_pca_axes_and_label_display_actually_change(self):
        self.ready();self.page.get_by_role('button',name='PCA',exact=True).click()
        canvas=self.page.get_by_test_id('projector-canvas');expect(canvas).to_have_attribute('data-algorithm','pca')
        before=self.point(414)
        self.page.get_by_label('X主成分').select_option('2')
        after=self.point(414);self.assertGreater(abs(before['x']-after['x'])+abs(before['y']-after['y']),1)
        self.choose('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        expect(self.page.locator('.projector-point-label.is-selected')).to_be_visible()
        self.page.get_by_label('点标签内容').select_option('brand')
        expect(self.page.locator('.projector-point-label.is-selected')).to_have_text('赫莲娜')
        self.page.get_by_role('button',name='显示点标签',exact=True).click()
        expect(self.page.locator('.projector-point-label')).to_have_count(0)

    def test_evidence_and_source_remain_traceable(self):
        self.ready();self.choose('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        self.page.get_by_test_id('projector-info').get_by_role('button',name='成分与证据',exact=True).click()
        detail=self.page.get_by_role('dialog',name='产品成分与证据');expect(detail).to_be_visible()
        detail.get_by_role('button',name='查看保湿的贡献成分',exact=True).click()
        detail.get_by_role('button',name='查看来源',exact=True).first.click()
        source=self.page.get_by_role('dialog',name='成分证据');expect(source).to_be_visible()
        self.assertGreater(source.locator('a[href^="http"]').count(),0)
        self.page.keyboard.press('Escape');expect(source).to_have_count(0);expect(detail).to_be_visible()
        self.page.keyboard.press('Escape');expect(detail).to_have_count(0)

    def test_comparison_roundtrip_keeps_arbitrary_pair(self):
        self.ready();self.page.get_by_role('button',name='两款对比',exact=True).click()
        self.page.get_by_role('button',name='更换产品 A',exact=True).click()
        self.page.get_by_role('combobox',name='搜索产品 A').fill('Serum 10')
        self.page.get_by_role('option',name='选择 SkinCeuticals Serum 10',exact=True).click()
        self.page.get_by_role('button',name='更换产品 B',exact=True).click()
        self.page.get_by_role('combobox',name='搜索产品 B').fill('C E Ferulic')
        self.page.get_by_role('option',name='选择 SkinCeuticals Prevent C E Ferulic® With 15% L-Ascorbic Acid',exact=True).click()
        self.page.get_by_role('button',name='产品空间',exact=True).click()
        self.page.get_by_role('button',name='两款对比',exact=True).click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-product-id','414')
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-product-id','3202')
        self.assertIn('compare=414',self.page.url)

    def test_rapid_selection_ignores_late_neighbors_and_clear(self):
        self.ready();delayed=[]
        self.page.route('**/api/products/414/similarity-space?basis=composition',lambda r:delayed.append(r))
        with self.page.expect_request('**/api/products/414/similarity-space?basis=composition'):
            self.choose('Serum 10','SkinCeuticals Serum 10')
        self.choose('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        rows=self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]');expect(rows).to_have_count(20)
        for route in delayed:route.fulfill(json={'product_id':414,'available':True,'complete':True,'items':[{'id':73,'score':1,'name':'STALE'}]})
        expect(self.page.get_by_test_id('projector-info')).to_have_attribute('data-product-id','9')
        expect(rows).to_have_count(20)
        self.page.get_by_role('button',name='清除选择',exact=True).click()
        expect(self.page.locator('.projector-point-label')).to_have_count(0)

    def test_no_index_keeps_map_and_product_comparison_available(self):
        self.page.route('**/api/products/9/similarity-space?basis=composition',lambda r:r.fulfill(json={'product_id':9,'available':False,'complete':False,'items':[],'reason':'相似索引暂不可用（验收场景）'}))
        self.ready();self.choose('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        expect(self.page.get_by_text('相似索引暂不可用（验收场景）',exact=True)).to_be_visible()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count','3749')
        self.page.get_by_role('button',name='两款对比',exact=True).first.click()
        expect(self.page.get_by_test_id('profile-A')).to_have_attribute('data-loaded','true')

    def test_missing_three_dimensional_asset_does_not_fabricate_depth(self):
        from frontend.e2e.browser_case import BASE_URL
        data=self.page.request.get(BASE_URL+'/api/product-space').json()
        data['projection']['umap_3d']['status']='unavailable';data['coordinate_count_3d']=0
        for p in data['products']:p['coordinates_3d']=None
        self.page.route('**/api/product-space',lambda r:r.fulfill(json=data));self.page.reload()
        expect(self.page.get_by_role('alert')).to_contain_text('UMAP 3D 投影暂不可用')
        self.page.get_by_role('button',name='查看二维投影',exact=True).click()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count','3749')
        self.page.get_by_role('button',name='两款对比',exact=True).click()
        expect(self.page.get_by_test_id('profile-B')).to_have_attribute('data-loaded','true')

    def test_mobile_tight_subset_is_fitted_and_panels_do_not_overflow(self):
        self.ready()
        for width,height in [(834,900),(390,844)]:
            self.page.set_viewport_size({'width':width,'height':height})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width)
        self.page.get_by_role('button',name='搜索与相似产品',exact=False).click()
        self.choose('Serum 10','SkinCeuticals Serum 10')
        self.page.get_by_role('slider',name='相似度筛选',exact=True).fill('95')
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-view-kind','similarity')
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-transition-state','idle')
        ids=[414]+[int(x) for x in self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]').evaluate_all('(es)=>es.map(e=>e.dataset.neighborId)')]
        self.page.get_by_role('button',name='隔离选择',exact=True).click()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count',str(int(self.page.get_by_test_id('projector-neighbors').get_attribute('data-matched-count'))+1))
        positions=[self.point(pid) for pid in ids];self.assertTrue(all(p['visible'] for p in positions))
        extent=max(p['x'] for p in positions)-min(p['x'] for p in positions)
        self.assertGreater(extent,20)
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)

    def test_keyboard_catalog_search_and_empty_results(self):
        self.ready();search=self.page.get_by_role('combobox',name='搜索全部产品')
        search.fill('没有这个产品abcdef');expect(self.page.get_by_text('未找到产品，试试其他名称或品牌。',exact=True)).to_be_visible()
        search.fill('Serum 10');search.press('ArrowDown');search.press('ArrowUp');search.press('Enter')
        expect(self.page.get_by_test_id('projector-info')).to_have_attribute('data-product-id','414')

    def test_canvas_keeps_real_point_pixels_after_isolate_restore_and_resize(self):
        import io
        from PIL import Image
        self.ready();self.choose('黑绷带面霜','黑绷带面霜（Re-Plasty Age Recovery Night）')
        expect(self.page.get_by_test_id('projector-neighbors').locator('[data-neighbor-id]')).to_have_count(20)
        self.page.get_by_role('button',name='隔离选择',exact=True).click()
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count',str(int(self.page.get_by_test_id('projector-neighbors').get_attribute('data-matched-count'))+1))
        self.page.get_by_role('button',name='显示全部',exact=True).click()
        for width,height in [(1280,800),(390,844)]:
            self.page.set_viewport_size({'width':width,'height':height})
        canvas=self.page.get_by_test_id('projector-canvas')
        expect(canvas).to_have_attribute('data-rendered-count','3749')
        self.page.wait_for_timeout(200)
        self.page.get_by_role('button',name='返回全景',exact=True).click()
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-transition-state','idle')
        frame=canvas.bounding_box();info=None
        raster=Image.open(io.BytesIO(canvas.screenshot())).convert('RGB')
        coloured=0
        for y in range(raster.height):
            for x in range(raster.width):
                if info and info['x']<=x+frame['x']<=info['x']+info['width'] and info['y']<=y+frame['y']<=info['y']+info['height']:continue
                r,g,b=raster.getpixel((x,y))
                if min(r,g,b)<220 and max(r,g,b)-min(r,g,b)>25:coloured+=1
        self.assertGreater(coloured,1200,'Canvas must contain the actual coloured point cloud, not background or DOM labels')

    def test_webgl_context_loss_can_retry_without_losing_other_flows(self):
        self.ready();canvas=self.page.get_by_test_id('projector-canvas')
        supported=canvas.evaluate("e=>{const gl=e.getContext('webgl2');const ext=gl?.getExtension('WEBGL_lose_context');if(!ext)return false;ext.loseContext();return true}")
        if not supported:self.skipTest('Browser has no WEBGL_lose_context extension')
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-renderer-state','unavailable')
        expect(self.page.get_by_role('button',name='重试图形渲染',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='重试图形渲染',exact=True).click()
        expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-renderer-state','ready')
        expect(self.page.get_by_test_id('projector-canvas')).to_have_attribute('data-rendered-count','3749')
