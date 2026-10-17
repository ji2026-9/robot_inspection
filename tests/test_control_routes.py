import copy,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch,MagicMock
import test_manual_control as helpers
import test_integrated_target as ui
from inspection_gui.manual_preview import build_route_preview
from inspection_gui.safety_wall import DEFAULT_WALL
from inspection_gui.global_wall import GlobalWall
from inspection_gui.wall_alert import WallAlertPresenter
from PySide6.QtWidgets import QWidget

class RouteTests(unittest.TestCase):
    def test_route_preview_has_all_targets_and_total_duration(self):
        f=ui.sample();a=f['pose'][:3];a[0]+=1;b=a[:];b[1]+=1
        p=build_route_preview(f,[a,b],1,DEFAULT_WALL,Path('unused'))
        self.assertEqual(len(p['targets']),2);self.assertAlmostEqual(p['distance'],2)
        self.assertEqual(p['targets'][0][:3],a);self.assertEqual(p['target'][:3],b)
        self.assertEqual(p['start']['joints'],f['joints'])
        self.assertAlmostEqual(p['timing']['duration_seconds'],2/p['timing']['effective_mm_s'])
    def controller(self):
        c=helpers.ManualControl(Path.cwd()/'.test-output'/uuid.uuid4().hex,helpers.FakeChannel,wall_guard=None)
        c.observe(helpers.frame(time.monotonic()),1);c.connect('127.0.0.1',1)
        self.assertTrue(helpers.wait(lambda:c.connected));c.unlock(True,1,interactive=True)
        self.addCleanup(c.shutdown);return c
    def test_sequence_waits_for_arrival_and_stop_cancels_remaining(self):
        c=self.controller();a=c.latest['pose'][:];a[0]+=1;b=a[:];b[1]+=1
        p=c.preview_route([a,b],5);c.execute(p['id'])
        self.assertTrue(helpers.wait(lambda:c.accepted_at is not None))
        calls=lambda:[x for x in c.channel.calls if isinstance(x,dict)]
        self.assertEqual(len(calls()),1)
        c.observe(helpers.frame(time.monotonic()),1);self.assertEqual(len(calls()),1)
        time.sleep(.025);c.observe(dict(helpers.frame(time.monotonic()),pose=a),1)
        self.assertTrue(helpers.wait(lambda:len(calls())==2));self.assertEqual(calls()[1]['target'],b)
        c.request_stop('test');c.observe(dict(helpers.frame(time.monotonic()),pose=b),1)
        self.assertTrue(helpers.wait(lambda:'Stop()' in c.channel.calls));self.assertEqual(len(calls()),2)
    def test_probe_trigger_at_first_target_does_not_send_second(self):
        c=self.controller();a=c.latest['pose'][:];a[0]+=1;b=a[:];b[1]+=1
        p=c.preview_route([a,b]);c.execute(p['id']);self.assertTrue(helpers.wait(lambda:c.accepted_at is not None))
        c.observe(dict(helpers.frame(time.monotonic()),pose=a,digital_inputs=1),1)
        self.assertTrue(helpers.wait(lambda:'Stop()' in c.channel.calls))
        self.assertEqual(len([x for x in c.channel.calls if isinstance(x,dict)]),1)
    def test_all_route_segments_reach_guard_before_first_dispatch(self):
        c=self.controller();guard=MagicMock();guard.ready.return_value=({},7);guard.service.revision=7
        guard.check_request.side_effect=ValueError('安全墙：第二段进入禁区')
        c.wall_guard=guard;a=c.latest['pose'][:];a[0]+=1;b=a[:];b[1]+=1
        p=c.preview_route([a,b]);c.execute(p['id'])
        self.assertTrue(helpers.wait(lambda:guard.check_request.called))
        self.assertEqual(guard.check_request.call_args.args[1]['route_tail'],[b])
        self.assertEqual(len([x for x in c.channel.calls if isinstance(x,dict)]),0)
    def test_wall_alert_follows_priority_stop_request(self):
        c=self.controller();guard=MagicMock();guard.monitor.side_effect=ValueError('安全墙：进入预留区')
        received=[];guard.service.warn.side_effect=lambda *args:received.append(c.stop_event.is_set())
        c.wall_guard=guard;c.observe(helpers.frame(time.monotonic()),1)
        self.assertEqual(received,[True]);self.assertFalse(c.permit)
    def test_popup_is_nonblocking_and_deduplicated(self):
        parent=QWidget();service=GlobalWall(Path.cwd()/'.test-output'/uuid.uuid4().hex/'wall.json')
        presenter=WallAlertPresenter(service,parent);service.warn('测试安全墙','虚拟预览');ui.APP.processEvents()
        box=presenter.box;self.assertIsNotNone(box);self.assertTrue(box.isVisible())
        service.warn('测试安全墙','虚拟预览');ui.APP.processEvents();self.assertIs(presenter.box,box)
        box.accept();ui.APP.processEvents();self.assertIsNone(presenter.box);parent.close();service.timer.stop()
    def test_ui_route_edit_and_expansion_keep_stop_visible(self):
        w=ui.Workspace(Path.cwd()/'.test-output'/uuid.uuid4().hex);w.b.snapshot=ui.sample
        c=helpers.ManualControl(w.storage_path.parent/'audit',helpers.FakeChannel,wall_guard=None);w.b.manual_control=c
        p=ui.ManualControlDialog(w);p.show();p.open_coordinate_target();ui.APP.processEvents()
        p.add_waypoint();p.xyz[0].setValue(p.xyz[0].value()+1);p.add_waypoint()
        self.assertEqual(p.route_list.count(),2);p.route_list.setCurrentRow(1);p.move_waypoint()
        self.assertEqual(p.waypoints[0][0],p.xyz[0].value())
        before=p.preview_view.width();p.preview_view.expand_button.setChecked(True);ui.APP.processEvents()
        self.assertGreater(p.preview_view.width(),before);self.assertTrue(p.stop_button.isVisible())
        p.close();c.shutdown();w.close();ui.APP.processEvents()
