"""Clicking a product must not request similarities or move the view implicitly."""
from playwright.sync_api import expect
from frontend.e2e.browser_case import BrowserTestCase

class ExplicitSimilarityTest(BrowserTestCase):
 def test_selection_is_still_until_explicit_apply_and_threshold_edits_are_deferred(self):
  stage=self.page.get_by_test_id('projector-stage')
  expect(stage).to_have_attribute('data-entry-animation','complete',timeout=30000)
  requests=[];self.page.on('request',lambda r:requests.append(r.url) if '/similarity-space' in r.url else None)
  distance=stage.get_attribute('data-camera-distance')
  self.page.get_by_role('button',name='试试黑绷带',exact=True).click()
  expect(self.page.get_by_test_id('projector-info')).to_have_attribute('data-product-id','9')
  expect(stage).to_have_attribute('data-view-kind','overview');self.page.wait_for_timeout(100)
  self.assertEqual(requests,[]);self.assertEqual(stage.get_attribute('data-camera-distance'),distance)
  slider=self.page.get_by_role('slider',name='相似度筛选',exact=True);expect(slider).to_have_value('75')
  self.page.get_by_role('button',name='开始相似度筛选',exact=True).click()
  expect(stage).to_have_attribute('data-view-kind','similarity');expect(stage).to_have_attribute('data-transition-state','idle')
  self.assertEqual(len(requests),1);radius=stage.get_attribute('data-sphere-radius');slider.fill('85')
  self.assertEqual(stage.get_attribute('data-sphere-radius'),radius)
  self.page.get_by_role('button',name='应用筛选',exact=True).click()
  self.page.wait_for_function('r=>document.querySelector("[data-testid=projector-stage]").dataset.sphereRadius!==r',arg=radius)
  self.assertEqual(len(requests),1)
