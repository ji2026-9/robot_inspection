import copy,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import test_integrated_target as helpers
from inspection_gui.ui_feedback import FeedbackLabel
from inspection_gui.manual_preview import build_preview,build_route_preview
from inspection_gui.safety_wall import DEFAULT_WALL
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.manual_control import ManualControl
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtCore import QPoint

class FeedbackTests(unittest.TestCase):
    def test_plain_copyable_error_has_visible_next_step_and_not_erased_by_status(self):
        label=FeedbackLabel();label.show_message('没有勾选目标 <b>原始内容</b>','error')
        self.assertIn('下一步',label.text());self.assertIn('<b>',label.text());self.assertIn('勾选',label.text())
        label.set_status('正常刷新');self.assertEqual(label.level,'error')
        label.copy_message();self.assertEqual(QApplication.clipboard().text(),label.text())
        label.setText('已保存');self.assertEqual(label.level,'success');label.close()
    def test_route_failure_names_execution_target_and_coordinates(self):
        f=helpers.sample();xyz=f['pose'][:3]
        with self.assertRaisesRegex(ValueError,'第 1 个执行目标.*重合'):
            build_route_preview(f,[xyz],1,DEFAULT_WALL,Path('unused'))
        xyz=xyz[:];xyz[0]+=2001
        with self.assertRaisesRegex(ValueError,'超过单段2000'):
            build_preview(f,xyz,1,DEFAULT_WALL,Path('unused'))
    def panel(self):
        w=helpers.Workspace(Path.cwd()/'.test-output'/uuid.uuid4().hex);w.b.snapshot=helpers.sample
        c=ManualControl(w.storage_path.parent/'audit',helpers.FakeChannel,wall_guard=None);w.b.manual_control=c
        p=ManualControlDialog(w);p.open_coordinate_target();p.show();helpers.APP.processEvents()
        self.addCleanup(lambda:(p.close(),c.shutdown(),w.close(),helpers.APP.processEvents()))
        return p,c,w
    def test_async_preview_error_reaches_top_banner_and_survives_refresh(self):
        p,c,w=self.panel();p.preview_view.finished(p.preview_view.revision,None,'目标与当前起点重合')
        self.assertTrue(p.detail.isVisible());self.assertIn('重合',p.detail.text());self.assertIn('下一步',p.detail.text())
        p.refresh();self.assertIn('重合',p.detail.text());self.assertLess(p.detail.geometry().top(),p.control_scroll.mapTo(p,QPoint()).y())
        self.assertFalse(c.connected)
    def test_stale_success_does_not_claim_preview_still_ready(self):
        p,c,w=self.panel();plan=build_preview(helpers.sample(),[helpers.sample()['pose'][0]+1]+helpers.sample()['pose'][1:3],1,DEFAULT_WALL,Path('unused'))
        p.preview_view.finished(p.preview_view.revision,plan,'');self.assertEqual(p.detail.level,'success')
        p.preview_view.clear();self.assertFalse(p.detail.isVisible())
    def test_critical_popup_deduplicated_and_does_not_dispatch_move(self):
        p,c,w=self.panel();state=c.snapshot();state['phase']='fault';state['reason']='无法确认停止';state['safety']['stop_state']='unconfirmed'
        p.show_control_fault(state);helpers.APP.processEvents();box=p._fault_box
        self.assertIsNotNone(box);self.assertTrue(box.isVisible());p.show_control_fault(state);self.assertIs(p._fault_box,box)
        self.assertFalse(c.connected);box.accept();helpers.APP.processEvents();self.assertIsNone(p._fault_box)
