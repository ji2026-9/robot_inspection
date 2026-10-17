import copy,math,time,unittest,uuid
from pathlib import Path
import test_integrated_target as helpers
from inspection_gui.circle_measurement import fit_circle,plan_circle
from inspection_gui.circle_measurement_view import CircleMeasurementPage
from inspection_gui.config_history import read_revision
from inspection_gui.config_history_view import ConfigHistoryPage
from inspection_gui.manual_origin import save_origin,load_origin
class CircleAndConfigTests(unittest.TestCase):
    def test_circle_fit_center_and_inner_diameter_compensation(self):
        points=[[10+9*math.cos(a),20+9*math.sin(a),30] for a in [i*math.pi/4 for i in range(8)]]
        r=fit_circle(points,1);self.assertAlmostEqual(r['estimated_bore_diameter_mm'],20);self.assertAlmostEqual(r['center_configured_tcp_mm'][0],10);self.assertLess(r['rms_residual_mm'],1e-9);self.assertFalse(r['precision_verified'])
        self.assertIsNone(fit_circle(points)['estimated_bore_diameter_mm'])
    def test_degenerate_and_mixed_height_points_rejected(self):
        for points in ([[0,0,0],[1,0,0],[2,0,0]],[[0,0,0],[1,0,1],[0,1,0]]):
            with self.assertRaises(ValueError):fit_circle(points)
    def test_circle_page_demo_never_connects_and_is_labeled_synthetic(self):
        w=helpers.Workspace(Path.cwd()/'.test-output'/uuid.uuid4().hex);w.b.snapshot=helpers.sample;p=CircleMeasurementPage(w)
        try:
            p.demo();self.assertEqual(len(p.points),8);self.assertIn('合成',p.status.text());self.assertIsNotNone(p.result);self.assertFalse(p.plan['hardware_executable'])
        finally:p.close();w.close();helpers.APP.processEvents()
    def test_receive_only_collection_keeps_raw_points_and_saves_on_end(self):
        root=Path.cwd()/'.test-output'/uuid.uuid4().hex;w=helpers.Workspace(root);w.b.snapshot=lambda:dict(helpers.sample(),received_at=time.time());p=CircleMeasurementPage(w)
        try:
            p.start_collection();self.assertTrue(p.active,p.status.text())
            for i in range(8):
                record=copy.deepcopy(p.anchor);record['id']=str(i);record['tcp_pose'][0]+=math.cos(i*math.pi/4);record['tcp_pose'][1]+=math.sin(i*math.pi/4)
                w.trigger_journal.records.append(record)
            p.poll();self.assertEqual(len(p.records),8,p.status.text());p.end_collection();self.assertTrue(p.session_path.exists())
            p.analyze();self.assertIsNotNone(p.result);self.assertFalse(p.result['precision_verified'])
        finally:p.close();w.close();helpers.APP.processEvents()

    def test_config_restore_uses_verified_content_and_keeps_old_version(self):
        root=Path.cwd()/'.test-output'/uuid.uuid4().hex;f=helpers.sample();path=root/'manual_origin.json'
        a=f['pose'][:3];a[0]+=1;save_origin(path,a,f,'127.0.0.1');b=a[:];b[0]+=2;save_origin(path,b,helpers.sample(),'127.0.0.1')
        p=ConfigHistoryPage(root,lambda:None)
        try:
            self.assertEqual(len(p.rows),1);p.table.selectRow(0);p.restore_selected();self.assertEqual(load_origin(path)['xyz'],a)
            record,data=read_revision(p.rows[0]);self.assertEqual(record['kind'],'origin')
        finally:p.close();helpers.APP.processEvents()
