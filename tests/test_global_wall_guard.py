import copy,os,time,threading,unittest,uuid
from pathlib import Path
from unittest.mock import patch,MagicMock
import numpy as np
os.environ['QT_QPA_PLATFORM']='offscreen'
from test_recent_ui import APP,Workspace
from test_coordinate_target import sample as physical_sample
import test_manual_control as helpers
from test_manual_control import frame,wait
from inspection_gui.global_wall import wall_service
from inspection_gui.safety_wall import DEFAULT_WALL
from inspection_gui.wall_guard import WallGuard
from inspection_gui.manual_control import ManualControl
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.manual_preview import ManualPreview
from inspection_gui.safety_wall_view import SafetyWallDialog
from PySide6.QtWidgets import QWidget

def confirmed(**changes):
    return dict(DEFAULT_WALL,direction_confirmed=True,wall_confirmed=True,tool_envelope_confirmed=True,
        distance_mm=10000.,visible=True,**changes)

class GlobalWallTests(unittest.TestCase):
    def setUp(self):
        self.folder=Path.cwd()/'.test-output'/'global-wall'/uuid.uuid4().hex
        self.service=wall_service(self.folder/'safety_wall.json')
        self.network=patch('socket.create_connection',side_effect=AssertionError('No hardware'));self.network.start()
        self.windows=[]
    def tearDown(self):
        for w in reversed(self.windows):w.close()
        APP.processEvents();self.network.stop()
    def guard(self):
        g=WallGuard(self.service);g.meshes=[dict(joint='base',name='isolated base fixture',vertices=np.array([[0.,0.,0.]]))]
        return g
    def test_missing_or_unconfirmed_wall_locks_real_controls_without_faking_position(self):
        g=self.guard()
        with self.assertRaisesRegex(ValueError,'位置未确认'):g.ready()
        self.assertFalse(self.service.display()['visible']);self.assertFalse(self.service.path.exists())
        w=Workspace(self.folder);p=ManualControlDialog(w);self.windows.extend([w,p])
        self.assertIsNotNone(p.controller.wall_guard)
        self.assertIn('位置未确认',p.controller.snapshot()['safety']['wall_reason'])
    def test_controller_defaults_to_global_guard_without_ui_wiring(self):
        c=ManualControl(self.folder/'manual_control_logs',helpers.FakeChannel)
        try:
            self.assertIsNotNone(c.wall_guard)
            self.assertIs(c.wall_guard.service,self.service)
            c.observe(frame(time.monotonic()),1)
            self.assertFalse(c.snapshot()['safety']['wall_ok'])
        finally:c.shutdown()
    def test_one_applied_config_updates_existing_and_later_scenes(self):
        class Scene(QWidget):
            def set_safety_wall(self,w):self.wall=w
        a=Scene();b=Scene();self.windows.extend([a,b]);self.service.attach_scene(a)
        self.service.apply(confirmed())
        self.service.attach_scene(b)
        self.assertEqual(a.wall,b.wall);self.assertEqual(a.wall['distance_mm'],10000)
        # Protection visibility is independent of a legacy hidden-display flag.
        self.service.apply(dict(confirmed(),visible=False));self.assertTrue(a.wall['visible'])
    def test_editor_drafts_are_local_and_apply_is_global(self):
        p=SafetyWallDialog(config_path=self.service.path);self.windows.append(p)
        p.direction.setCurrentIndex(2);p.fields['distance_mm'].setValue(900)
        p.preview();self.assertFalse(self.service.snapshot()['direction_confirmed'])
        p.tool_confirm.setChecked(True);p.save()
        self.assertEqual(self.service.snapshot()['yaw_deg'],90)
        self.assertEqual(self.service.snapshot()['distance_mm'],900)
        self.assertFalse(self.service.reason())
        p.fields['distance_mm'].setValue(901)
        self.assertFalse(p.tool_confirm.isChecked());self.assertEqual(self.service.snapshot()['distance_mm'],900)
    def test_wall_change_invalidates_manual_preview(self):
        w=Workspace(self.folder);p=ManualPreview(w);self.windows.extend([w,p])
        p.plan={'complete':True};self.service.apply(confirmed())
        self.assertIsNone(p.plan);self.assertIn('全局安全墙',p.note.text())
    def test_guard_checks_tool_and_repeated_same_unsafe_frame_remains_rejected(self):
        self.service.publish(confirmed());g=self.guard();f=dict(physical_sample(),pose_stable=True)
        result=g.monitor(f);self.assertTrue(result['tool_checked'])
        self.service.publish(dict(confirmed(),distance_mm=100))
        for _ in range(2):
            with self.assertRaises(ValueError):g.monitor(f)
    def test_guard_accepts_clear_complete_path_and_refuses_crossing_path(self):
        self.service.publish(confirmed());g=self.guard();f=dict(physical_sample(),pose_stable=True)
        target=f['pose'][:];target[0]+=5
        self.assertEqual(g.check_request(f,dict(target=target),lambda:False),self.service.revision)
        self.service.publish(dict(confirmed(),distance_mm=190,tool_radius_mm=10,stop_reserve_mm=10))
        f['received_monotonic']=time.monotonic();target=f['pose'][:];target[0]+=60
        with self.assertRaises(ValueError):g.check_request(f,dict(target=target),lambda:False)
    def test_bad_saved_file_causes_fail_closed_without_overwriting_it(self):
        self.service.apply(confirmed());self.service.path.write_text('{bad',encoding='utf-8')
        before=self.service.path.read_bytes();self.service.reload_if_changed()
        self.assertIn('读取失败',self.service.reason());self.assertEqual(self.service.path.read_bytes(),before)

class GuardedControllerTests(unittest.TestCase):
    setUp=helpers.ManualTests.setUp
    tearDown=helpers.ManualTests.tearDown
    create=helpers.ManualTests.create
    connected=helpers.ManualTests.connected
    def attach(self,c,check=None):
        service=wall_service(self.folder/'wall.json');service.publish(confirmed())
        guard=MagicMock();guard.service=service;guard.ready.return_value=(service.snapshot(),service.revision)
        guard.check_request.side_effect=check or (lambda f,p,cancelled:service.revision)
        c.wall_guard=guard;service.bind_controller(c);return guard,service
    def test_all_three_modes_pass_through_wall_gate_before_dispatch(self):
        for mode in ('jog','fixed','target'):
            c=self.connected();g,s=self.attach(c);c.unlock(True,1,interactive=True)
            if mode=='jog':c.start_jog('X',1)
            else:
                p=c.preview('X',1,50) if mode=='fixed' else c.preview_target([101,200,300,180,0,0],50)
                c.execute(p['id'])
            self.assertTrue(wait(lambda:c.accepted_at is not None));self.assertEqual(g.check_request.call_count,1)
            c.close();c.worker.join(1)
    def test_unsafe_gate_never_calls_channel_move_or_jog(self):
        c=self.connected();g,s=self.attach(c,lambda *args:(_ for _ in ()).throw(ValueError('安全墙禁止')))
        c.unlock(True,1,interactive=True);p=c.preview('X',1);c.execute(p['id'])
        self.assertTrue(wait(lambda:'安全墙禁止' in c.reason))
        self.assertFalse(any(isinstance(v,dict) for v in self.channels[-1].calls));self.assertEqual(c.phase,'ready')
    def test_stop_cancels_preflight_without_waiting_on_controller_lock(self):
        started=threading.Event()
        def checking(f,p,cancelled):
            started.set()
            while not cancelled():time.sleep(.001)
            raise InterruptedError('cancelled')
        c=self.connected();g,s=self.attach(c,checking);c.unlock(True,1,interactive=True)
        p=c.preview('X',1);c.execute(p['id']);self.assertTrue(started.wait(1))
        start=time.monotonic();c.request_stop('人工停止');self.assertLess(time.monotonic()-start,.05)
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
        self.assertFalse(any(isinstance(v,dict) for v in self.channels[-1].calls))
    def test_configuration_change_cancels_authorized_motion(self):
        c=self.connected();g,s=self.attach(c);c.unlock(True,1,interactive=True)
        s.publish(dict(confirmed(),distance_mm=9000))
        self.assertTrue(c.stop_event.is_set());self.assertFalse(c.permit)
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
    def test_wall_revision_change_cancels_inflight_path_analysis(self):
        started=threading.Event()
        def checking(f,p,cancelled):
            started.set()
            while not cancelled():time.sleep(.001)
            raise InterruptedError('wall updated')
        c=self.connected();g,s=self.attach(c,checking);c.unlock(True,1,interactive=True)
        p=c.preview('X',1);c.execute(p['id']);self.assertTrue(started.wait(1))
        s.publish(dict(confirmed(),distance_mm=8000))
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
        self.assertFalse(any(isinstance(v,dict) for v in self.channels[-1].calls))
    def test_feedback_wall_breach_requests_stop(self):
        c=self.connected();g,s=self.attach(c);c.unlock(True,1,interactive=True)
        g.monitor.side_effect=ValueError('安全墙预测进入预留区')
        c.observe(frame(self.now[0]),1)
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls));self.assertFalse(c.permit)

if __name__=='__main__':unittest.main()
