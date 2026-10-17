import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import copy,sys,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch,MagicMock
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from PySide6.QtWidgets import QApplication,QDialog,QWidget,QPushButton,QFileDialog,QInputDialog,QMessageBox
from inspection_gui.probe_stop import ProbeStopMonitor
from inspection_gui.sphere_analysis_view import SphereAnalysisDialog
from inspection_gui.probe_stop_view import ProbeStopDialog
from inspection_gui.probe_workspace_view import ProbeWorkspaceDialog
from inspection_gui.probe_workspace import capture_position
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.manual_control import ManualControl
from test_manual_control import frame,FakeChannel,wait

APP=QApplication.instance() or QApplication([])

class Backend:
    address='127.0.0.1';generation=1;identity=None;manual_control=None
    def __init__(self):self.stop_monitor=ProbeStopMonitor();self.active=True
    def snapshot(self):
        if not self.active:return None
        f=frame(time.monotonic());f['received_at']=time.time();return f
    def is_connected(self):return self.active
    def probe_events_since(self,sequence):return dict(events=[],latest_sequence=0,missed_events=0)

class Workspace(QDialog):
    def __init__(self,folder):
        super().__init__();self.storage_path=folder/'positions.json';self.b=Backend()
        self.trigger_save_error='';self.trigger_missed=0
        self.trigger_journal=type('Journal',(),{'records':[]})()
    def backend(self):return self.b
    def refresh_feedback(self):pass

class Scene(QWidget):
    def __init__(self):
        super().__init__();self.pan=np.zeros(3);self.distance=2000;self.meshes=[];self.live_frame=None
    def set_manual_preview(self,*args):self.preview=args
    def set_live_frame(self,f,enabled):self.live_frame=f
    def set_plan(self,*args):pass
    def reset_view(self):pass
    def view_top(self):pass

class RecentUITests(unittest.TestCase):
    def setUp(self):
        self.folder=Path.cwd()/'.test-output'/'recent-ui'/uuid.uuid4().hex
        self.w=Workspace(self.folder);self.windows=[];self.errors=[]
        self.previous_hook=sys.excepthook
        sys.excepthook=lambda *exc:self.errors.append(exc)
        self.network=patch('socket.create_connection',side_effect=AssertionError('Real networking forbidden in UI audit'))
        self.network.start()
    def tearDown(self):
        for window in reversed(self.windows):window.close()
        if self.w.b.manual_control:self.w.b.manual_control.shutdown()
        self.w.close();APP.processEvents();self.network.stop();sys.excepthook=self.previous_hook
        self.assertEqual(self.errors,[],'Qt signal handler raised an exception')
    def sphere(self):
        p=SphereAnalysisDialog(self.w);self.windows.append(p);p.show();APP.processEvents()
        p.ready.setChecked(True);p.start.click();self.assertIsNotNone(p.session);return p
    def event(self):
        e=capture_position('trigger',self.w.b.snapshot());e.update(event_type='probe_trigger',controller_address='127.0.0.1');return e
    def test_end_button_includes_last_pending_contact(self):
        p=self.sphere();self.w.trigger_journal.records.append(self.event());p.stop.click()
        self.assertEqual(len(p.session.data['records']),1)
        self.assertEqual(p.table.rowCount(),1)
    def test_escape_stops_sphere_collection_and_timer(self):
        p=self.sphere();p.reject();APP.processEvents()
        self.assertEqual(p.session.data['status'],'stopped');self.assertFalse(p.timer.isActive())
    def test_escape_disarms_stop_monitor(self):
        monitor=MagicMock();monitor.snapshot.return_value={'state':'armed','reason':'fake armed'}
        self.w.b.stop_monitor=monitor;p=ProbeStopDialog(self.w);self.windows.append(p)
        p.show();APP.processEvents();p.reject()
        self.assertTrue(monitor.disarm.called);self.assertFalse(p.timer.isActive())
    def workspace(self):
        with patch('inspection_gui.probe_workspace_view.Scene3D',Scene):
            p=ProbeWorkspaceDialog(storage_path=self.folder/'positions.json')
        p.backend=lambda:self.w.b;p.auto_attempted=True;self.windows.append(p);p.show();APP.processEvents();return p
    def test_escape_closes_workspace_timers(self):
        p=self.workspace();p.reject();APP.processEvents()
        self.assertTrue(p.closed);self.assertFalse(p.refresh_timer.isActive())
    def test_position_record_buttons_and_export(self):
        p=self.workspace();p.position_name.setText('test position');p.record_button.click()
        self.assertEqual(len(p.library.records),1);p.positions_table.selectRow(0)
        with patch.object(QInputDialog,'getText',return_value=('renamed',True)):
            next(b for b in p.findChildren(QPushButton) if b.text()=='重命名').click()
        self.assertEqual(p.library.records[0]['name'],'renamed')
        next(b for b in p.findChildren(QPushButton) if b.text()=='作为预览起点').click()
        self.assertIsNotNone(p.start_record)
        p.tabs.setCurrentIndex(0);p.positions_table.selectRow(0)
        archive=next(b for b in p.findChildren(QPushButton) if b.text()=='归档 / 恢复')
        archive.click();self.assertEqual(p.positions_table.rowCount(),0)
        p.show_archived.setChecked(True);p.positions_table.selectRow(0);archive.click()
        self.assertFalse(p.library.records[0]['archived'])
        output=self.folder/'export.json'
        with patch.object(QFileDialog,'getSaveFileName',return_value=(str(output),'')):
            next(b for b in p.findChildren(QPushButton) if b.text()=='导出位置库').click()
        self.assertTrue(output.is_file())
    def test_manual_error_is_visible_without_scrolling(self):
        p=ManualControlDialog(self.w);self.windows.append(p);p.show();APP.processEvents()
        p.error(ValueError('test visible error'))
        APP.processEvents()
        self.assertIs(p.detail.parentWidget(),p)
        self.assertLess(p.detail.y()+p.detail.height(),p.stop_button.y())
    def test_stop_monitor_rejects_control_channel_conflict(self):
        self.w.b.manual_control=MagicMock();self.w.b.manual_control.snapshot.return_value={'connected':True}
        p=ProbeStopDialog(self.w);self.windows.append(p)
        p.static_ready.setChecked(True)
        self.assertFalse(p.static_test.isEnabled())

    def test_optional_query_explains_control_port_conflict(self):
        p=self.workspace();self.w.b.manual_control=MagicMock()
        self.w.b.manual_control.snapshot.return_value={'connected':True}
        p.refresh_feedback()
        self.assertFalse(p.optional_audit_button.isEnabled());self.assertTrue(p.audit_button.isEnabled())
        p.start_audit(query_controller=True)
        self.assertFalse(p.auditing);self.assertIn('断开',p.message_label.text())

    def test_sphere_repeat_analysis_exclude_restore_export_open(self):
        p=self.sphere();p.stop.click();p.mode.setCurrentIndex(1);p.start.click()
        for index in range(6):
            event=self.event();event['tcp_pose'][0]+=index*.001
            self.w.trigger_journal.records.append(event)
        p.stop.click();self.assertEqual(len(p.session.data['records']),6)
        p.analyze_button.click();self.assertEqual(p.session.data['analysis']['sample_count'],6)
        self.assertFalse(p.exclude.isEnabled())
        p.table.selectRow(0);p.exclude.click();p.analyze_button.click()
        self.assertEqual(p.session.data['analysis']['sample_count'],5)
        p.table.selectRow(0);p.exclude.click();p.analyze_button.click()
        self.assertEqual(p.session.data['analysis']['sample_count'],6)
        output=self.folder/'session_export.json'
        with patch.object(QFileDialog,'getSaveFileName',return_value=(str(output),'')):p.export.click()
        self.assertTrue(output.is_file())
        with patch.object(QFileDialog,'getOpenFileName',return_value=(str(output),'')):p.load.click()
        self.assertEqual(p.table.rowCount(),6);self.assertEqual(p.session.data['status'],'stopped')

    def test_expired_manual_preview_disables_execute(self):
        p=ManualControlDialog(self.w);self.windows.append(p)
        p.motion_mode.setCurrentIndex(1)
        p.controller.factory=FakeChannel;p.connect_control()
        self.assertTrue(wait(lambda:p.controller.snapshot()['connected']))
        p.controller.observe(self.w.b.snapshot(),1)
        for c in p.checks:c.setChecked(True)
        p.payload.setValue(1)
        p.controller.wall_guard=None  # This test isolates the preview-expiry UI, not wall configuration.
        p.controller.observe(self.w.b.snapshot(),1);p.refresh()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):p.unlock_button.click()
        self.assertTrue(p.controller.snapshot()['unlocked'])
        # User can click the directional preview once explicitly unlocked.
        p.controller.observe(self.w.b.snapshot(),1);p.refresh()
        p.directions[1].click();self.assertIsNotNone(p.plan_id)
        p.controller.plan['created']-=11;p.refresh()
        self.assertFalse(p.execute_button.isEnabled());self.assertIn('过期',p.target.text())

    def test_simulation_escape_stops_timers(self):
        from inspection_gui.simulation_view import SimulationDialog
        from inspection_gui.devices_view import _registered_backends
        with patch('inspection_gui.simulation_view.Scene3D',Scene),patch.dict(_registered_backends,{'robot_b':self.w.b}):
            p=SimulationDialog();self.windows.append(p);p.auto_attempted=True;p.show();APP.processEvents()
            p.reject();self.assertTrue(p.closed);self.assertFalse(p.feedback_timer.isActive())
            p.shutdown()

    def test_simulated_vision_buttons_build_play_reset_export(self):
        p=self.workspace();p.tabs.setCurrentIndex(3)
        p.vision_example_button.click();p.vision_build_button.click()
        deadline=time.monotonic()+20
        while p.joint_busy and time.monotonic()<deadline:
            APP.processEvents();time.sleep(.01)
        self.assertFalse(p.joint_busy,'Joint preview worker did not finish')
        self.assertIsNotNone(p.task);self.assertEqual(p.vision_table.rowCount(),4)
        self.assertTrue(p.frames,'Example path must have playable joint samples')
        p.play_button.click();self.assertTrue(p.timer.isActive())
        p.progress.setValue(min(2,p.progress.maximum()));p.reset_button.click()
        self.assertFalse(p.timer.isActive());self.assertEqual(p.progress.value(),0)
        p.focus_button.click();self.assertTrue(p.preview_focused)
        output=self.folder/'preview.json'
        with patch.object(QFileDialog,'getSaveFileName',return_value=(str(output),'')):p.vision_export_button.click()
        self.assertTrue(output.is_file());self.assertFalse(p.task['hardware_executable'])
        p.vision_clearance.setValue(51)
        self.assertIsNone(p.task);self.assertFalse(p.play_button.isEnabled())

if __name__=='__main__':unittest.main()
