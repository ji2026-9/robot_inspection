import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,unittest,socket,threading,time,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from inspection_gui.manual_control import ControlChannel,ManualControl
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.dobot_feedback import DobotFeedback
import test_manual_control as helpers
import test_recent_ui as ui

APP=QApplication.instance() or QApplication([])

class StopWireTests(unittest.TestCase):
    def wire(self,kind,rejected):
        client,server=socket.socketpair();seen=[]
        commands=['Stop()','MoveJog()'] if kind=='jog' else ['Stop()']
        def serve():
            with server:
                for expected in commands:
                    cmd=server.recv(4096);seen.append(cmd.decode())
                    code=b'-1' if cmd.decode() in rejected else b'0'
                    server.sendall(code+b',{},'+cmd+b';')
        t=threading.Thread(target=serve);t.start()
        try:
            with patch('socket.create_connection',return_value=client):
                c=ControlChannel('127.0.0.1');c.motion_kind=kind
                if rejected:
                    with self.assertRaises(ValueError):c.stop()
                else:self.assertEqual(c.stop(),commands)
                report=c.last_stop_attempt;c.close()
        finally:client.close();t.join(1)
        self.assertEqual(seen,commands);return report

    def test_fixed_move_cancels_queue_without_jog_command(self):
        report=self.wire('step',set());self.assertEqual(report['acknowledged'],['Stop()'])

    def test_rejected_jog_cannot_prevent_queue_stop(self):
        report=self.wire('jog',{'MoveJog()'})
        self.assertEqual(report['acknowledged'],['Stop()'])
        self.assertIn('MoveJog()',report['errors'][0])

    def test_rejected_queue_stop_does_not_skip_jog_cancellation(self):
        report=self.wire('jog',{'Stop()'})
        self.assertEqual(report['acknowledged'],['MoveJog()'])

class TriggerDispatchTests(unittest.TestCase):
    def test_pending_move_is_cancelled_and_stop_wakes_worker(self):
        now=[100.];channels=[]
        def factory(address):
            channel=helpers.FakeChannel(address);channels.append(channel);return channel
        c=ManualControl(Path.cwd()/'.test-output'/'stop-priority'/uuid.uuid4().hex,factory,lambda:now[0])
        c.observe(helpers.frame(),1);c.connect('127.0.0.1',1)
        try:
            self.assertTrue(helpers.wait(lambda:c.snapshot()['connected']))
            with c.lock:
                c.unlock(True,1,interactive=True);p=c.preview('X',10,1);c.execute(p['id'])
                c.request_stop('最高优先级停止')
                self.assertTrue(c.wake_event.is_set())
            self.assertTrue(helpers.wait(lambda:'Stop()' in channels[0].calls))
            self.assertFalse(any(isinstance(v,dict) for v in channels[0].calls))
            self.assertIsNone(c.plan);self.assertIsNone(c.permit)
        finally:c.shutdown()

    def test_short_di_pulse_during_movl_reaches_actual_channel_stop(self):
        calls=[]
        class Channel(ControlChannel):
            def __init__(self,address):pass
            def _exchange(self,cmd):
                calls.append(cmd)
                if cmd=='MoveJog()':raise ValueError('-1,{},MoveJog();')
                return '5' if cmd=='RobotMode()' else ''
            def close(self):pass
        now=[100.];folder=Path.cwd()/'.test-output'/'stop-dispatch'/uuid.uuid4().hex
        c=ManualControl(folder,Channel,lambda:now[0]);backend=DobotFeedback();backend.manual_control=c;backend.generation=1
        c.observe(helpers.frame(),1);c.connect('127.0.0.1',1)
        try:
            self.assertTrue(helpers.wait(lambda:c.snapshot()['connected']))
            c.unlock(True,1,interactive=True);p=c.preview('X',50,5);c.execute(p['id'])
            self.assertTrue(helpers.wait(lambda:c.accepted_at is not None))
            now[0]+=.008;f=helpers.frame(now[0]);f.update(mode=7,running=True,digital_inputs=1)
            backend._observe_probe(f)
            now[0]+=.008;f=helpers.frame(now[0]);f.update(mode=7,running=True)
            backend._observe_probe(f)
            self.assertTrue(helpers.wait(lambda:'Stop()' in calls))
            self.assertNotIn('MoveJog()',calls);self.assertEqual(calls.count('Stop()'),1)
            self.assertFalse(c.snapshot()['unlocked']);self.assertFalse(c.snapshot()['resumable'])
            self.assertTrue(any(e['event']=='stop_requested' and e['digital_inputs']==1 and 'DI_1' in e['reason'] for e in c.events))
        finally:c.shutdown()

class StopUITests(unittest.TestCase):
    def test_visible_inline_stop_responds_on_press_and_escape(self):
        folder=Path.cwd()/'.test-output'/'stop-ui'/uuid.uuid4().hex
        workspace=ui.Workspace(folder);workspace.b.manual_control=ManualControl(folder,helpers.FakeChannel)
        p=ManualControlDialog(workspace);p.show();APP.processEvents()
        c=p.controller
        try:
            p.motion_mode.setCurrentIndex(1);c.observe(workspace.b.snapshot(),1);c.connect('127.0.0.1',1)
            self.assertTrue(helpers.wait(lambda:c.snapshot()['connected']))
            p.refresh();self.assertTrue(p.inline_stop.isVisible());self.assertTrue(p.inline_stop.isEnabled())
            c.unlock(True,1,interactive=True)
            QTest.mousePress(p.inline_stop,Qt.LeftButton)
            self.assertTrue(c.stop_event.is_set());self.assertIsNone(c.permit)
            QTest.mouseRelease(p.inline_stop,Qt.LeftButton)
            with patch.object(c,'request_stop') as stop:
                p.activateWindow();p.setFocus();APP.processEvents();QTest.keyClick(p,Qt.Key_Escape);APP.processEvents()
                self.assertTrue(stop.called);self.assertTrue(p.isVisible())
        finally:p.close();c.shutdown();workspace.close()

if __name__=='__main__':unittest.main()
