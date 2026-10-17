import unittest
import test_integrated_target as helpers
from PySide6.QtWidgets import QWidget
from inspection_gui.workbench import Workbench

class SettingsNavigationTests(unittest.TestCase):
    def setUp(self):
        self.created=[];self.host=Workbench(QWidget())
        for key in ('devices','wall','sphere','stop','models','configs','control'):
            self.host.register(key,key,lambda k=key:self.make(k))
    def make(self,key):self.created.append(key);return QWidget()
    def tearDown(self):self.host.shutdown();self.host.close();helpers.APP.processEvents()
    def visible(self):return [key for i,key in enumerate(self.host.keys) if self.host.tabs.isTabVisible(i)]
    def test_common_contains_only_daily_pages(self):
        self.host.select_group('设置');self.assertEqual(self.visible(),['devices','wall'])
    def test_direct_advanced_link_switches_tier_and_reuses_page(self):
        first=self.host.open_page('models');self.assertEqual(self.host.settings_tier,'高级工具')
        self.assertEqual(self.visible(),['sphere','stop','models','configs'])
        self.assertIs(self.host.open_page('models'),first);self.assertEqual(self.created,['models'])
    def test_switching_tier_remembers_daily_page(self):
        first=self.host.open_page('wall');self.host.open_page('configs');self.host.select_settings_tier('常用设置')
        self.assertEqual(self.host.keys[self.host.tabs.currentIndex()],'wall');self.assertIs(self.host.open_page('wall'),first)
    def test_navigation_is_lazy_and_nonsettings_pages_unaffected(self):
        self.assertEqual(self.created,[]);self.host.open_page('control');self.assertTrue(self.host.settings_bar.isHidden())
        self.assertEqual(self.visible(),['control']);self.assertEqual(self.created,['control'])
