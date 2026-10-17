import unittest,uuid
from pathlib import Path
from unittest.mock import MagicMock,patch
import test_manual_control as helpers
from test_manual_control import frame,wait
from test_recent_ui import APP,Workspace
from inspection_gui.manual_control import ControlChannel
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.manual_preview import estimate_timing

class RemovedLimitsTests(unittest.TestCase):
    setUp=helpers.ManualTests.setUp
    tearDown=helpers.ManualTests.tearDown
    create=helpers.ManualTests.create
    connected=helpers.ManualTests.connected
    def test_jog_beyond_100mm_keeps_moving_and_probe_still_stops(self):
        c=self.connected();c.unlock(True,1,interactive=True);c.start_jog('X',1,50)
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        self.now[0]+=.05;c.maintain_hold();f=frame(self.now[0])
        f.update(mode=8,running=True,pose_stable=False);f['pose'][0]+=150;c.observe(f,1)
        self.assertEqual(c.phase,'moving');self.assertFalse(c.stop_event.is_set())
        self.assertIsNone(c.active_plan['max_distance_mm'])
        f['digital_inputs']=1;c.observe(f,1)
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls));self.assertFalse(c.permit)
    def test_fixed_and_target_moves_accept_older_limits_exceeded(self):
        c=self.connected();c.unlock(True,1,interactive=True)
        p=c.preview('X',250,100);self.assertEqual(p['distance'],250);self.assertEqual(p['speed'],100)
        p=c.preview_target([450.,200.,300.,180.,0.,0.],250)
        self.assertEqual(p['speed'],250)
        self.assertAlmostEqual(estimate_timing(250,100,50)['duration_seconds'],5)
    def test_wire_preserves_explicit_speed_and_protocol_ratio_limits(self):
        c=object.__new__(ControlChannel);c._exchange=MagicMock(return_value='')
        command=c.move(dict(target=[1.,2.,3.,180.,0.,0.],speed=250,distance=250,user=0,tool=1))
        self.assertIn('speed=250',command)
        c.jog(dict(axis='X',sign=1,ratio=100,user=0,tool=1),lambda:False)
        self.assertIn(unittest.mock.call('SpeedFactor(100)'),c._exchange.call_args_list)
        with self.assertRaises(ValueError):c.jog(dict(axis='X',sign=1,ratio=101,user=0,tool=1),lambda:False)
    def test_ui_modes_accept_explicit_values_without_raising_defaults(self):
        w=Workspace(Path.cwd()/'.test-output'/'removed-limits'/uuid.uuid4().hex)
        with patch('socket.create_connection',side_effect=AssertionError('No hardware')):
            p=ManualControlDialog(w)
            try:
                self.assertEqual(p.speed.value(),1);p.speed.setEditText('75');self.assertEqual(p.speed.value(),75)
                self.assertTrue(p.step.isHidden())
                p.motion_mode.setCurrentIndex(1);p.step.setEditText('250');p.speed.setEditText('250')
                self.assertEqual(p.step.value(),250);self.assertEqual(p.speed.value(),250)
                p.speed.plus_button.pressed.emit();self.assertEqual(p.speed.value(),251)
                p.motion_mode.setCurrentIndex(2);p.speed.setEditText('500');self.assertEqual(p.speed.value(),500)
            finally:p.close();w.b.manual_control.shutdown();w.close();APP.processEvents()

if __name__=='__main__':unittest.main()
