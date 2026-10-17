import copy,os,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
from test_recent_ui import APP,Workspace
from test_coordinate_target import sample as raw_sample
from test_manual_control import FakeChannel,wait
from inspection_gui.manual_control import ManualControl
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.manual_preview import build_preview,validate_preview
from inspection_gui.safety_wall import DEFAULT_WALL

def sample():return dict(raw_sample(),pose_stable=True)

class IntegratedTargetTests(unittest.TestCase):
    def setUp(self):
        self.w=Workspace(Path.cwd()/'.test-output'/'integrated'/uuid.uuid4().hex)
        self.w.b.snapshot=sample
        self.network=patch('socket.create_connection',side_effect=AssertionError('No hardware'));self.network.start()
        self.c=ManualControl(self.w.storage_path.parent/'audit',FakeChannel,wall_guard=None)
        self.w.b.manual_control=self.c;self.p=ManualControlDialog(self.w)
    def tearDown(self):
        self.p.close();self.c.shutdown();self.w.close();APP.processEvents();self.network.stop()
    def candidate(self):
        self.p.open_coordinate_target();f=sample();xyz=f['pose'][:3];xyz[0]+=1
        return build_preview(f,xyz,1,DEFAULT_WALL,Path('unused'))
    def test_preview_and_edit_never_connect(self):
        plan=self.candidate();self.assertFalse(plan['hardware_executable'])
        self.assertEqual(plan['target'][3:],plan['start']['pose'][3:])
        self.p.preview_view.finished(self.p.preview_view.revision,plan,'');self.p.refresh()
        self.assertFalse(self.p.execute_button.isEnabled());self.assertFalse(self.c.connected)
        self.p.xyz[0].setValue(self.p.xyz[0].value()+.1)
        self.assertIsNone(self.p.preview_view.plan)
    def test_changed_start_generation_and_wall_reject(self):
        plan=self.candidate()
        for f,g,w in [(dict(sample(),pose=[0.]*6),1,None),(sample(),2,None),(sample(),1,dict(DEFAULT_WALL,distance_mm=1000))]:
            with self.assertRaises(ValueError):validate_preview(plan,f,g,w)
    def test_cancelled_worker_cannot_restore_preview(self):
        plan=self.candidate();token=self.p.preview_view.revision
        self.p.preview_view.busy=True;self.p.preview_view.clear()
        self.p.preview_view.finished(token,plan,'')
        self.assertIsNone(self.p.preview_view.plan);self.assertFalse(self.p.preview_view.busy)
    def test_explicit_execution_once_and_release_keeps_target_deadline(self):
        plan=self.candidate();self.c.observe(sample(),1);self.c.connect('127.0.0.1',1)
        self.assertTrue(wait(lambda:self.c.connected));self.c.unlock(True,1,interactive=True)
        self.p.preview_view.finished(self.p.preview_view.revision,plan,'')
        self.p.execute();self.assertIsNone(self.p.preview_view.plan)
        deadline=self.c.hold_until;self.p.release();self.c.maintain_hold()
        self.assertEqual(self.c.hold_until,deadline);self.assertFalse(self.c.stop_event.is_set())
        self.p.execute();self.assertTrue(wait(lambda:any(isinstance(c,dict) for c in self.c.channel.calls)))
        self.assertEqual(len([c for c in self.c.channel.calls if isinstance(c,dict)]),1)
        self.p.stop_motion();self.assertTrue(self.c.stop_event.is_set())

if __name__=='__main__':unittest.main()
