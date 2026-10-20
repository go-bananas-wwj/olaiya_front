from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase

class NeedOverviewTransitionTest(BrowserTestCase):
 def test_need_switch_visits_3d_overview_and_missing_records_stay_outside_numeric_plot(self):
  stage=self.page.get_by_test_id('projector-stage')
  expect(stage).to_have_attribute('data-entry-animation','complete',timeout=30000)
  self.page.get_by_role('button',name='从保湿开始',exact=True).click();expect(stage).to_have_attribute('data-transition-state','idle')
  expect(stage).to_have_attribute('data-dimensions','2')
  self.assertEqual(self.page.locator('.projector-need-tabs').count(),0)
  self.assertEqual(self.page.get_by_test_id('projector-need-missing-rail').count(),0)
  self.page.evaluate('''()=>{window.needPhases=[];const e=document.querySelector('[data-testid=projector-stage]');new MutationObserver(()=>window.needPhases.push(e.dataset.transitionPhase)).observe(e,{attributes:true,attributeFilter:['data-transition-phase']})}''')
  self.page.get_by_role('complementary',name='数据与投影设置').get_by_role('button',name='舒缓',exact=True).click()
  expect(stage).to_have_attribute('data-transition-state','idle')
  phases=self.page.evaluate('window.needPhases')
  self.assertIn('to-overview',phases);self.assertIn('overview',phases);self.assertIn('to-need',phases)
  self.page.get_by_role('button',name='未入图',exact=False).click()
  expect(self.page.get_by_role('dialog',name='未入图的产品')).to_be_visible()
