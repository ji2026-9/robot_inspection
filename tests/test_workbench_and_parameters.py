import os,sys,time,unittest,uuid
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QWidget,QDialog,QMainWindow,QLabel,QLineEdit
from inspection_gui.workbench import Workbench
from inspection_gui.numeric_parameter import NumericParameter
from inspection_gui.manual_control_view import ManualControlDialog
import test_manual_control as helpers
from test_manual_control import frame,wait
import test_recent_ui as ui_helpers

APP=QApplication.instance() or QApplication([])

class ParameterTests(unittest.TestCase):
    setUp=helpers.ManualTests.setUp
    tearDown=helpers.ManualTests.tearDown
    create=helpers.ManualTests.create
    connected=helpers.ManualTests.connected
    def test_custom_values_validate_in_widget_and_backend(self):
        combo=NumericParameter();combo.configure([.1,1,10],.01,100,.1)
        for value in (.01,.25,7.35,100):combo.setEditText(str(value));self.assertEqual(combo.value(),value)
        for value in ('','nan','inf','0','100.1','bad'):
            combo.setEditText(value)
            with self.assertRaises(ValueError):combo.value()
        c=self.connected();c.unlock(True,1,interactive=True)
        p=c.preview('X',25,12);self.assertEqual(p['target'][0],125);self.assertEqual(p['speed'],12)
        for delta,speed in [(2000.1,1),(.001,1),(1,0),(1,1.5)]:
            with self.assertRaises(ValueError):c.preview('Y',delta,speed)
        with self.assertRaises(ValueError):c.start_jog('X',1,101)
        with self.assertRaises(ValueError):c.start_jog('X',1,1,-1)

    def test_custom_jog_limit_stops_and_rearms_without_queuing(self):
        c=self.connected();c.unlock(True,1,interactive=True);c.start_jog('X',1,3,2.5)
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        self.now[0]+=.05;f=frame(self.now[0]);f.update(mode=8,running=True,pose_stable=False);f['pose'][0]+=2.5;c.observe(f,1)
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
        self.assertTrue(c.auto_rearm)

    def test_large_step_timeout_accounts_for_distance_and_global_ratio(self):
        c=self.connected();c.unlock(True,1,interactive=True)
        f=frame();f['speed_percent']=10;c.observe(f,1)
        p=c.preview('X',20,2);c.execute(p['id']);self.assertTrue(wait(lambda:c.accepted_at is not None))
        self.assertGreater(c.motion_deadline-self.now[0],100)

    def test_modes_keep_custom_parameters_and_edit_clears_target(self):
        folder=Path.cwd()/'.test-output'/'parameter-ui'/uuid.uuid4().hex
        w=ui_helpers.Workspace(folder);p=ManualControlDialog(w)
        try:
            p.step.setEditText('35');p.speed.setEditText('4')
            p.motion_mode.setCurrentIndex(1)
            self.assertEqual(p.step.value(),.1);self.assertEqual(p.speed.value(),1)
            p.step.setEditText('7.25');p.speed.setEditText('12')
            p.motion_mode.setCurrentIndex(0)
            self.assertEqual(p.step.value(),35);self.assertEqual(p.speed.value(),4)
            p.motion_mode.setCurrentIndex(1)
            self.assertEqual(p.step.value(),7.25);self.assertEqual(p.speed.value(),12)
            p.plan_id='old';p.step.setEditText('9.5');self.assertIsNone(p.plan_id)
        finally:p.close();w.close()

    def test_control_page_connects_feedback_without_opening_parent_page(self):
        folder=Path.cwd()/'.test-output'/'direct-connect'/uuid.uuid4().hex
        w=ui_helpers.Workspace(folder);w.b.active=False;w.address=QLineEdit('127.0.0.1')
        w.connect_feedback=MagicMock(side_effect=lambda:setattr(w.b,'active',True))
        p=ManualControlDialog(w);p.controller.factory=helpers.FakeChannel
        try:
            self.assertFalse(w.connect_feedback.called)
            p.connect_control();self.assertTrue(w.connect_feedback.called);self.assertTrue(p.waiting_feedback)
            p.refresh();self.assertTrue(wait(lambda:p.controller.snapshot()['connected']))
            self.assertEqual(p.controller.channel.calls,['RobotMode()'])
            self.assertFalse(p.controller.snapshot()['unlocked'])
        finally:p.controller.shutdown();p.close();w.close()

    def test_leaving_page_cancels_pending_control_connection(self):
        folder=Path.cwd()/'.test-output'/'cancel-connect'/uuid.uuid4().hex
        w=ui_helpers.Workspace(folder);w.b.active=False;w.address=QLineEdit('127.0.0.1');w.connect_feedback=MagicMock()
        p=ManualControlDialog(w);p.show();APP.processEvents()
        try:
            p.connect_control();self.assertTrue(p.waiting_feedback)
            p.hide();APP.processEvents();w.b.active=True;p.refresh()
            self.assertFalse(p.waiting_feedback);self.assertIsNone(p.controller.worker)
        finally:p.close();w.close()


class WorkbenchTests(unittest.TestCase):
    def test_lazy_pages_embed_reuse_and_close_returns_home(self):
        main=QMainWindow();home=QWidget();host=Workbench(home,main);main.setCentralWidget(host)
        created=[]
        def factory():
            page=QDialog(main);created.append(page);return page
        host.register('control','实机控制',factory);main.show();APP.processEvents()
        try:
            self.assertEqual(created,[])
            page=host.open_page('control');APP.processEvents()
            self.assertFalse(page.isWindow());self.assertIs(page.window(),main)
            host.open_page('visual');host.open_page('control');self.assertEqual(len(created),1)
            page.close();APP.processEvents();APP.processEvents()
            self.assertEqual(host.tabs.currentIndex(),0)
            self.assertIs(host.open_page('control'),page);self.assertTrue(page.isVisible())
        finally:host.shutdown();main.close()

    def test_navigation_away_from_active_control_requests_stop(self):
        folder=Path.cwd()/'.test-output'/'navigation-ui'/uuid.uuid4().hex
        main=QMainWindow();host=Workbench(QWidget(),main);main.setCentralWidget(host)
        w=ui_helpers.Workspace(folder);page=ManualControlDialog(w)
        host.register('control','实机控制',lambda:page);main.show();host.open_page('control');APP.processEvents()
        try:
            page.controller.permit='test';page.controller.configuration=(0,1,(),())
            page.controller.expires=time.monotonic()+60;page.controller.used_distance=0
            with patch.object(page.controller,'request_stop') as stop:
                host.open_page('visual');APP.processEvents();self.assertTrue(stop.called)
            self.assertFalse(page.timer.isActive())
        finally:page.controller.permit=None;host.shutdown();main.close();w.close()

if __name__=='__main__':unittest.main()
