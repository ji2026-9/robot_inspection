import unittest,json,uuid
from pathlib import Path
from unittest.mock import patch
import test_integrated_target as helpers
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.manual_control import ManualControl
from inspection_gui.circle_measurement_view import CircleMeasurementPage

class WorkflowAuditTests(unittest.TestCase):
    def setUp(self):
        self.root=Path.cwd()/'.test-output'/uuid.uuid4().hex;self.w=helpers.Workspace(self.root);self.w.b.snapshot=helpers.sample
        self.c=ManualControl(self.root/'audit',helpers.FakeChannel,wall_guard=None);self.w.b.manual_control=self.c
        self.network=patch('socket.create_connection',side_effect=AssertionError('No hardware'));self.network.start()
        self.p=ManualControlDialog(self.w);self.p.open_coordinate_target()
    def tearDown(self):
        self.p.close();self.c.shutdown();self.w.close();helpers.APP.processEvents();self.network.stop()
    def test_save_single_coordinate_does_not_save_old_route(self):
        self.p.add_waypoint();self.p.xyz[0].setValue(123);self.p.preview_source.setCurrentIndex(2)
        target=[v.value() for v in self.p.xyz];path=self.root/'single.json'
        with patch('inspection_gui.manual_control_view.QFileDialog.getSaveFileName',return_value=(str(path),'')):self.p.save_target_task()
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))['targets'],[target])
        self.p.xyz[0].setValue(456)
        with patch('inspection_gui.manual_control_view.QFileDialog.getOpenFileName',return_value=(str(path),'')):self.p.open_target_task()
        self.assertEqual(self.p.preview_source.currentIndex(),2);self.assertEqual([v.value() for v in self.p.xyz],target)
    def test_multitarget_roundtrip_preserves_selected_order_and_cancels_preview(self):
        for x in (100,200,300):self.p.xyz[0].setValue(x);self.p.add_waypoint()
        self.p.waypoint_enabled=[True,False,True];path=self.root/'route.json'
        with patch('inspection_gui.manual_control_view.QFileDialog.getSaveFileName',return_value=(str(path),'')):self.p.save_target_task()
        self.p.clear_waypoints();self.p.preview_view.plan={'old':True}
        with patch('inspection_gui.manual_control_view.QFileDialog.getOpenFileName',return_value=(str(path),'')):self.p.open_target_task()
        self.assertEqual([t[0] for t in self.p.selected_route()],[100,300]);self.assertIsNone(self.p.preview_view.plan);self.assertFalse(self.c.connected)
    def test_failed_fit_clears_old_numeric_result(self):
        page=CircleMeasurementPage(self.w)
        try:
            page.demo();self.assertIsNotNone(page.result)
            page.points=[[0,0,0],[1,0,0],[2,0,0]];page.analyze()
            self.assertIsNone(page.result);self.assertIn('拟合失败',page.detail.toPlainText())
        finally:page.close()
    def test_offline_fit_export_keeps_source_and_unverified_status(self):
        page=CircleMeasurementPage(self.w);path=self.root/'circle.json'
        try:
            page.demo()
            with patch('inspection_gui.circle_measurement_view.QFileDialog.getSaveFileName',return_value=(str(path),'')):page.export()
            data=json.loads(path.read_text(encoding="utf-8"));self.assertEqual(data['data_source'],'离线合成演练');self.assertFalse(data['precision_verified']);self.assertEqual(len(data['points']),8)
            self.assertIn(str(path.resolve()),page.status.text())
        finally:page.close()
