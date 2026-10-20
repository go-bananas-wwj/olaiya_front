from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase, BASE_URL

class NeedAxesTest(BrowserTestCase):
 def ready(self):expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-renderer-state','ready',timeout=30000)
 def idle(self):expect(self.page.get_by_test_id('projector-stage')).to_have_attribute('data-transition-state','idle',timeout=10000)
 def test_explicit_axes_and_real_need_change_with_shared_scales(self):
  self.ready();self.page.get_by_role('button',name='从保湿开始',exact=True).click();self.idle()
  axes=self.page.get_by_test_id('projector-need-axes');expect(axes).to_contain_text('已收录成分数（项）');expect(axes).to_contain_text('保湿成分证据指数');expect(axes).to_contain_text('资料待补')
  canvas=self.page.get_by_test_id('projector-canvas');before=canvas.evaluate('e=>e.getScreenPoint(9).worldPosition');bounds=axes.get_attribute('data-scale')
  self.page.get_by_role('complementary',name='数据与投影设置').get_by_role('button',name='修护',exact=True).click();self.idle()
  after=canvas.evaluate('e=>e.getScreenPoint(9).worldPosition');self.assertEqual(before[0],after[0]);self.assertNotEqual(before[1],after[1]);self.assertEqual(after[2],0)
  self.assertEqual(axes.get_attribute('data-scale'),bounds);expect(axes).to_contain_text('修护成分证据指数')
  self.page.get_by_role('combobox',name='需求视图品类',exact=True).select_option('面霜');self.idle();self.assertEqual(axes.get_attribute('data-scale'),bounds)
 def test_mobile_axes_remain_readable_and_page_has_no_overflow(self):
  self.page.set_viewport_size({'width':390,'height':844});self.ready();self.page.get_by_role('button',name='从保湿开始',exact=True).click();self.idle()
  expect(self.page.get_by_test_id('projector-need-axes')).to_be_visible();self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
  for text in ['已收录成分数（项）','保湿成分证据指数']:
   el=self.page.get_by_test_id('projector-need-axes').get_by_text(text,exact=True);expect(el).to_be_visible();b=el.bounding_box();self.assertGreaterEqual(b['x'],0);self.assertLessEqual(b['x']+b['width'],390)

 def test_mobile_x_label_and_missing_band_have_separate_space(self):
  self.page.set_viewport_size({'width':390,'height':844});self.ready();self.page.get_by_role('button',name='从保湿开始',exact=True).click();self.idle()
  axes=self.page.get_by_test_id('projector-need-axes');label=axes.get_by_text('已收录成分数（项）',exact=True).bounding_box();rail=self.page.get_by_test_id('projector-need-missing-rail').bounding_box()
  self.assertLessEqual(label['y']+label['height']+12,rail['y'])
