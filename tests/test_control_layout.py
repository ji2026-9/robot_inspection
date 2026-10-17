import unittest,uuid
from pathlib import Path
import test_integrated_target as helpers
from inspection_gui.manual_control import ManualControl
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.manual_preview import build_preview
from inspection_gui.safety_wall import DEFAULT_WALL
from PySide6.QtCore import QPoint

class ControlLayoutTests(unittest.TestCase):
    def setUp(self):
        self.w=helpers.Workspace(Path.cwd()/'.test-output'/uuid.uuid4().hex);self.w.b.snapshot=helpers.sample
        self.c=ManualControl(self.w.storage_path.parent/'audit',helpers.FakeChannel,wall_guard=None);self.w.b.manual_control=self.c
        self.p=ManualControlDialog(self.w);self.p.open_coordinate_target();self.p.show();helpers.APP.processEvents()
    def tearDown(self):
        self.p.close();self.c.shutdown();self.w.close();helpers.APP.processEvents()
    def test_stop_and_viewport_fit_compact_regular_and_large_with_errors(self):
        for width,height in [(1000,720),(1440,900),(1920,1080)]:
            self.p.resize(width,height);self.p.error('目标位置无效，请核对坐标与单位后重新预览。');helpers.APP.processEvents()
            stop=self.p.stop_button.mapTo(self.p,self.p.stop_button.rect().bottomRight())
            self.assertLess(stop.y(),self.p.height());self.assertLess(stop.x(),self.p.width())
            scene=self.p.preview_view.scene
            self.assertGreaterEqual(scene.height(),175);self.assertLessEqual(scene.width()/scene.height(),2.21)
            self.assertLess(self.p.detail.geometry().top(),self.p.control_scroll.mapTo(self.p,QPoint()).y())
    def test_expand_and_details_do_not_change_approved_path(self):
        f=helpers.sample();xyz=f['pose'][:3];xyz[0]+=1
        preview=self.p.preview_view;plan=build_preview(f,xyz,1,DEFAULT_WALL,Path('unused'))
        preview.finished(preview.revision,plan,'');preview.details_button.setChecked(True);preview.expand_button.setChecked(True);helpers.APP.processEvents()
        self.assertIs(preview.plan,plan);self.assertTrue(preview.note.isVisible());self.assertTrue(self.p.stop_button.isVisible())
        self.assertFalse(self.c.connected)
    def test_success_notice_does_not_take_viewport_height_but_error_is_pinned(self):
        self.p.preview_feedback('路径预览已生成：一个目标',False);helpers.APP.processEvents()
        self.assertEqual(self.p.parameter_layout.indexOf(self.p.detail),0)
        self.p.error('路径预览失败：目标与起点重合');helpers.APP.processEvents()
        self.assertGreaterEqual(self.p.root_layout.indexOf(self.p.detail),0);self.assertEqual(self.p.detail.level,'error')
