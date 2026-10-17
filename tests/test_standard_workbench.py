import copy,json,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch,MagicMock
import test_integrated_target as helpers
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.manual_control import ManualControl
from inspection_gui.manual_origin import save_origin,load_origin
from inspection_gui.target_task import save_task,load_task
from inspection_gui.global_status_view import read_status,GlobalStatusStrip
from inspection_gui.ui_events import EventJournal
from inspection_gui.workbench import Workbench
from PySide6.QtWidgets import QWidget

class StandardWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.root=Path.cwd()/'.test-output'/uuid.uuid4().hex
        self.w=helpers.Workspace(self.root);self.w.b.snapshot=helpers.sample
        self.c=ManualControl(self.root/'audit',helpers.FakeChannel,wall_guard=None);self.w.b.manual_control=self.c
        self.p=ManualControlDialog(self.w);self.p.open_coordinate_target()
        self.network=patch('socket.create_connection',side_effect=AssertionError('No hardware'));self.network.start()
    def tearDown(self):
        self.p.close();self.c.shutdown();self.w.close();helpers.APP.processEvents();self.network.stop()
    def test_return_origin_then_generic_preview_keeps_origin_not_current_input(self):
        f=helpers.sample();a=f['pose'][:3];a[0]+=10
        save_origin(self.p.origin_path,a,f,self.w.b.address)
        # Current input/route is the current physical feedback, a no-op target.
        self.p.copy_position();self.p.add_waypoint()
        with patch.object(self.p.preview_view,'generate') as generate:
            self.p.preview_origin();self.p.generate_target_preview()
            self.assertEqual(generate.call_count,2)
            for call in generate.call_args_list:self.assertEqual(call.args[1],a);self.assertEqual(call.kwargs['purpose'],'origin')
        self.assertIn('返回目标',self.p.path_source_summary.text());self.assertFalse(self.c.connected)
    def test_origin_reloads_file_instead_of_stale_dialog_cache(self):
        f=helpers.sample();a=f['pose'][:3];a[0]+=2;save_origin(self.p.origin_path,a,f,self.w.b.address)
        with patch.object(self.p.preview_view,'generate') as generate:self.p.preview_origin();self.assertEqual(generate.call_args.args[1],a)
        b=a[:];b[0]+=3;save_origin(self.p.origin_path,b,helpers.sample(),self.w.b.address)
        with patch.object(self.p.preview_view,'generate') as generate:self.p.generate_target_preview();self.assertEqual(generate.call_args.args[1],b)
        self.assertTrue(list((self.root/'config_versions/origin').glob('*.json')))
    def test_changed_origin_rejects_old_execution_before_any_motion(self):
        f=helpers.sample();a=f['pose'][:3];a[0]+=2;saved=save_origin(self.p.origin_path,a,f,self.w.b.address)
        self.p.preview_view.plan={'purpose':'origin','reference':saved}
        b=a[:];b[0]+=1;save_origin(self.p.origin_path,b,helpers.sample(),self.w.b.address)
        self.p.execute_target();self.assertIn('原点已变化',self.p.detail.text());self.assertFalse(self.c.connected)
    def test_table_edit_and_reorder_preserve_checkbox_and_cancel_preview(self):
        self.p.add_waypoint();self.p.xyz[0].setValue(self.p.xyz[0].value()+2);self.p.add_waypoint()
        self.p.preview_view.plan={'old':True};self.p.route_list.item(0,1).setText('123.456')
        self.assertEqual(self.p.waypoints[0][0],123.456);self.assertIsNone(self.p.preview_view.plan)
        self.p.route_list.setCurrentRow(0);self.p.move_waypoint_down();self.assertEqual(self.p.waypoints[1][0],123.456)
    def test_task_validation_and_loading_do_not_overwrite_origin(self):
        self.p.set_origin_current();original=self.p.origin_path.read_bytes();path=self.root/'task.json'
        save_task(path,[[1,2,3],[4,5,6]],[True,False],5)
        with patch('inspection_gui.manual_control_view.QFileDialog.getOpenFileName',return_value=(str(path),'')):self.p.open_target_task()
        self.assertEqual(self.p.waypoints,[[1,2,3],[4,5,6]]);self.assertEqual(self.p.waypoint_enabled,[True,False]);self.assertEqual(self.p.origin_path.read_bytes(),original)
        bad=json.loads(path.read_text());bad['targets'][0][0]=float('nan');path.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):load_task(path)
    def test_failed_config_backup_does_not_overwrite_origin(self):
        f=helpers.sample();a=f['pose'][:3];save_origin(self.p.origin_path,a,f,self.w.b.address);original=self.p.origin_path.read_bytes()
        b=a[:];b[0]+=1
        with patch('inspection_gui.config_history.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):save_origin(self.p.origin_path,b,helpers.sample(),self.w.b.address)
        self.assertEqual(self.p.origin_path.read_bytes(),original)

    def test_stale_global_feedback_never_displays_old_probe_or_scale(self):
        f=helpers.sample();f['speed_percent']=22;self.w.b.snapshot=lambda:f
        status=read_status(self.w.b,f['received_monotonic']);self.assertEqual(status['scale'],'倍率 22%')
        status=read_status(self.w.b,f['received_monotonic']+1);self.assertFalse(status['fresh']);self.assertEqual(status['scale'],'倍率 —');self.assertEqual(status['probe'],'测头 —')
    def test_global_stop_only_requests_existing_controller_stop(self):
        with patch.object(self.c,'request_stop') as stop:
            strip=GlobalStatusStrip(lambda:self.w.b);strip.request_stop();stop.assert_called_once();strip.timer.stop();strip.close()
        self.assertFalse(self.c.connected)
    def test_group_navigation_reuses_pages(self):
        host=Workbench(QWidget());host.register('control','实机控制',lambda:QWidget());host.register('wall','安全墙',lambda:QWidget())
        host.group_nav.setCurrentText('工作台');page=host.open_page('wall');self.assertEqual(host.group_nav.currentText(),'设置')
        self.assertIs(host.open_page('wall'),page);host.shutdown();host.close()
    def test_event_history_persists_and_reloads_with_deduplication(self):
        path=self.root/'events.jsonl';j=EventJournal();j.configure(path);j.record('错误','error','测试','重试');j.record('错误','error','测试','重试');j.pending.join()
        self.assertEqual(len(j.snapshot()),1);j2=EventJournal();j2.configure(path);j2.pending.join();self.assertEqual(j2.snapshot()[0]['message'],'错误')
