import unittest
from inspection_gui.control_overview import workflow_state,target_summary

def state(phase='ready',**safety):
    return dict(phase=phase,connected=True,reason='测头触发',safety=dict(feedback_ok=True,**safety))

class OverviewTests(unittest.TestCase):
    def test_stop_unconfirmed_always_wins(self):
        self.assertEqual(workflow_state(state('moving',stop_state='unconfirmed'),2,True,True)[0],'停止未确认')
    def test_model_preview_is_not_execution_permission(self):
        self.assertNotEqual(workflow_state(state(),2,True,False)[0],'可执行')
        self.assertEqual(workflow_state(state(),2,True,True)[0],'可执行')
    def test_stop_reason_is_preserved(self):
        self.assertEqual(workflow_state(state('latched'),2)[1],'测头触发')
    def test_wall_blocks_ready_caption(self):
        self.assertEqual(workflow_state(state(wall_reason='墙未确认'),2,True,True)[0],'安全墙条件未满足')
    def test_stale_feedback_never_has_distance(self):
        frame=dict(pose=[0,0,0],received_monotonic=1)
        self.assertIn('5.000',target_summary(frame,[3,4,0],1.1))
        self.assertIn('距离不可用',target_summary(frame,[3,4,0],2))
    def test_nonfinite_target_is_not_displayed(self):
        self.assertIn('不可用',target_summary({},[float('nan'),0,0]))

class LifecycleTests(unittest.TestCase):
    def test_queued_refresh_ignores_deleted_pose_widget(self):
        import uuid
        from pathlib import Path
        import test_integrated_target as helpers
        from inspection_gui.manual_control import ManualControl
        from inspection_gui.manual_control_view import ManualControlDialog
        from shiboken6 import delete
        folder=Path.cwd()/'.test-output'/uuid.uuid4().hex
        w=helpers.Workspace(folder);w.b.snapshot=helpers.sample
        c=ManualControl(folder/'audit',helpers.FakeChannel,wall_guard=None);w.b.manual_control=c
        p=ManualControlDialog(w)
        try:delete(p.pose);p.refresh()
        finally:p.close();c.shutdown();w.close();helpers.APP.processEvents()
