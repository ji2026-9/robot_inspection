import copy,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import test_integrated_target as ui
from inspection_gui.manual_control import ManualControl
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.manual_origin import load_origin,origin_position,save_origin
from PySide6.QtCore import Qt

class OriginSelectionTests(unittest.TestCase):
    def setUp(self):
        self.w=ui.Workspace(Path.cwd()/'.test-output'/uuid.uuid4().hex);self.w.b.snapshot=ui.sample
        self.c=ManualControl(self.w.storage_path.parent/'audit',ui.FakeChannel,wall_guard=None);self.w.b.manual_control=self.c
        self.network=patch('socket.create_connection',side_effect=AssertionError('No hardware'));self.network.start()
        self.p=ManualControlDialog(self.w);self.p.open_coordinate_target()
    def tearDown(self):
        self.p.close();self.c.shutdown();self.w.close();ui.APP.processEvents();self.network.stop()
    def add(self,x):
        self.p.xyz[0].setValue(x);self.p.add_waypoint()
    def test_selected_targets_only_and_none_does_not_fallback(self):
        x=ui.sample()['pose'][0]
        for v in (x+1,x+2,x+3):self.add(v)
        self.p.route_list.item(1).setCheckState(Qt.Unchecked)
        self.assertEqual([p[0] for p in self.p.selected_route()],[round(x+1,3),round(x+3,3)])
        with patch.object(self.p.preview_view,'generate') as generate:
            self.p.generate_target_preview();self.assertEqual(generate.call_args.args[1],self.p.selected_route())
        self.p.select_waypoints(False)
        with patch.object(self.p.preview_view,'generate') as generate:
            self.p.generate_target_preview();generate.assert_not_called()
        self.assertIn('没有勾选',self.p.detail.text())
    def test_reordering_and_deletion_preserve_each_checkbox(self):
        self.add(100);self.add(101);self.p.route_list.item(1).setCheckState(Qt.Unchecked)
        self.p.route_list.setCurrentRow(1);self.p.move_waypoint()
        self.assertEqual(self.p.waypoint_enabled,[False,True]);self.assertEqual(self.p.selected_route()[0][0],100)
        self.p.route_list.setCurrentRow(0);self.p.remove_waypoint();self.assertEqual(self.p.waypoint_enabled,[True])
    def test_current_origin_persists_without_control_connection(self):
        self.p.set_origin_current();saved=load_origin(self.p.origin_path)
        self.assertEqual(saved['xyz'],ui.sample()['pose'][:3]);self.assertFalse(self.c.connected)
        p2=ManualControlDialog(self.w);self.assertEqual(p2.origin['xyz'],saved['xyz']);p2.close()
    def test_input_origin_is_previewed_separately_from_selected_route(self):
        x=ui.sample()['pose'][0];self.add(x+10);self.p.xyz[0].setValue(x+2);self.p.set_origin_input()
        with patch.object(self.p.preview_view,'generate') as generate:
            self.p.preview_origin();self.assertEqual(generate.call_args.args[1][0],round(x+2,3))
            self.assertEqual(self.p.selected_route()[0][0],round(x+10,3))
        self.assertFalse(self.c.connected)
    def test_origin_at_current_position_clears_old_preview_without_movement(self):
        self.p.set_origin_current();self.p.preview_view.plan={'old':True}
        with patch.object(self.p.preview_view,'generate') as generate:self.p.preview_origin();generate.assert_not_called()
        self.assertIsNone(self.p.preview_view.plan);self.assertIn('无需移动',self.p.target.text())
    def test_robot_or_tool_change_rejects_saved_origin(self):
        self.p.set_origin_current();f=ui.sample()
        with self.assertRaises(ValueError):origin_position(self.p.origin,f,'192.0.2.1')
        f['tool_offset'][2]+=1
        with self.assertRaises(ValueError):origin_position(self.p.origin,f,self.w.b.address)
        self.p.preview_view.plan={'old':True};self.w.b.snapshot=lambda:f
        self.p.preview_origin();self.assertIsNone(self.p.preview_view.plan);self.assertIn('配置',self.p.detail.text())
    def test_stale_origin_capture_and_invalid_record_rejected(self):
        f=ui.sample();f['received_monotonic']-=1
        with self.assertRaises(ValueError):save_origin(self.p.origin_path,[0,0,0],f,'127.0.0.1')
        self.p.origin_path.parent.mkdir(parents=True,exist_ok=True);self.p.origin_path.write_text('{broken',encoding='utf-8')
        with self.assertRaises(ValueError):load_origin(self.p.origin_path)
    def test_selecting_different_targets_cancels_previous_preview(self):
        self.add(100);self.p.preview_view.plan={'old':True};self.p.route_list.item(0).setCheckState(Qt.Unchecked)
        self.assertIsNone(self.p.preview_view.plan)
