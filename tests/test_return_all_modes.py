import unittest,uuid
from pathlib import Path
from unittest.mock import patch
import test_integrated_target as helpers
from inspection_gui.manual_control import ManualControl
from inspection_gui.manual_control_view import ManualControlDialog

class ReturnAllModesTests(unittest.TestCase):
    def setUp(self):
        self.root=Path.cwd()/'.test-output'/uuid.uuid4().hex;self.w=helpers.Workspace(self.root);self.w.b.snapshot=helpers.sample
        self.c=ManualControl(self.root/'audit',helpers.FakeChannel,wall_guard=None);self.w.b.manual_control=self.c
        self.network=patch('socket.create_connection',side_effect=AssertionError('No hardware'));self.network.start()
        self.p=ManualControlDialog(self.w)
    def tearDown(self):self.p.close();self.c.shutdown();self.w.close();helpers.APP.processEvents();self.network.stop()
    def test_return_entry_visible_in_all_modes_and_only_previews(self):
        frame=helpers.sample();xyz=frame['pose'][:3];xyz[0]+=10;self.p.save_user_origin(xyz)
        for mode in (0,1,2):
            with self.subTest(mode=mode):
                self.p.motion_mode.setCurrentIndex(mode);self.p.refresh()
                self.assertFalse(self.p.return_origin_button.isHidden());self.assertTrue(self.p.return_origin_button.isEnabled())
                with patch.object(self.p.preview_view,'generate') as generate,patch.object(self.c,'execute') as execute:
                    self.p.return_origin_button.click()
                    self.assertEqual(self.p.motion_mode.currentIndex(),2);self.assertEqual(self.p.preview_source.currentIndex(),1)
                    self.assertEqual(generate.call_args.args[1],xyz);self.assertEqual(generate.call_args.kwargs['purpose'],'origin');execute.assert_not_called()
        self.assertFalse(self.c.connected)
    def test_no_saved_position_disables_entry_with_explanation(self):
        for mode in (0,1,2):
            self.p.motion_mode.setCurrentIndex(mode);self.p.refresh()
            self.assertFalse(self.p.return_origin_button.isHidden());self.assertFalse(self.p.return_origin_button.isEnabled());self.assertIn('未设置',self.p.return_origin_button.toolTip())
    def test_motion_in_progress_cannot_change_mode_or_generate_return(self):
        self.p.motion_mode.setCurrentIndex(0);state=self.c.snapshot();state['phase']='moving'
        with patch.object(self.c,'snapshot',return_value=state),patch.object(self.p.preview_view,'generate') as generate:
            self.p.preview_origin();generate.assert_not_called();self.assertEqual(self.p.motion_mode.currentIndex(),0)
