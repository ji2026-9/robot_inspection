import unittest
from unittest.mock import patch
from test_standard_workbench import StandardWorkbenchTests
from inspection_gui.workbench import Workbench
from PySide6.QtWidgets import QWidget

class SimplificationTests(StandardWorkbenchTests):
    def test_single_target_ignores_existing_route(self):
        self.p.add_waypoint();self.p.xyz[0].setValue(321)
        self.p.preview_source.setCurrentIndex(2)
        with patch.object(self.p.preview_view,'generate') as generate:
            self.p.generate_target_preview()
            self.assertEqual(generate.call_args.args[1][0],321)
        self.assertTrue(self.p.route_list.isHidden())
        self.p.preview_source.setCurrentIndex(0)
        self.assertFalse(self.p.route_list.isHidden())
    def test_main_sections_and_lazy_settings(self):
        host=Workbench(QWidget());created=[]
        for key in ('simulation','control','probe','circle','wall','events'):
            host.register(key,key,lambda:created.append(QWidget()) or created[-1])
        host.select_group('工作台');self.assertEqual(created,[])
        page=host.open_page('wall');self.assertEqual(host.group_nav.currentText(),'设置')
        host.open_page('control');self.assertTrue(host.tabs.tabBar().isHidden())
        self.assertIs(host.open_page('wall'),page)
        self.assertEqual(len(created),2);host.shutdown();host.close()
