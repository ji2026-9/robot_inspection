import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"software"))
import numpy as np
from inspection_gui.offline_planning import SimulationConfig,build_plan,transform_point,translated,compile_trajectory,robot_frames

class OfflinePlanningTests(unittest.TestCase):
    def test_rigid_transform_roundtrip_and_known_axes(self):
        t=np.array([[0,-1,0,10],[1,0,0,20],[0,0,1,30],[0,0,0,1]],float)
        self.assertTrue(np.allclose(transform_point(t,[2,3,4]),[7,22,34]))
        self.assertTrue(np.allclose(transform_point(np.linalg.inv(t),transform_point(t,[2,3,4])),[2,3,4]))
        with self.assertRaises(ValueError):transform_point(np.diag([2,1,1,1]),[0,0,0])

    def test_selection_and_uncertain_identity(self):
        result={'fitted_holes':[{'id':f'H{i:02}','reliable_center':True,'center_px':[i*100,200]} for i in range(1,5)]}
        plan=build_plan(result,['H02','H04'])
        self.assertEqual(plan['selected_ids'],['H02','H04'])
        self.assertEqual({w['hole_id'] for w in plan['waypoints'][1:]},{'H02','H04'})
        self.assertFalse(plan['hardware_executable']);self.assertFalse(plan['calibration_verified'])
        self.assertFalse(plan['physical_identity_verified'])
        result['fitted_holes'].pop()
        self.assertEqual(build_plan(result,['H02'])['selected_ids'],[])

    def test_example_selection_and_empty_task(self):
        self.assertEqual(build_plan(None,['H03'])['selected_ids'],['H03'])
        self.assertEqual(compile_trajectory(build_plan(None,[])),([],[]))

    def test_depth_and_clearance_parameters(self):
        p=build_plan(None,['H01'],SimulationConfig(approach_mm=80,insertion_mm=20))
        by_stage={w['stage']:w for w in p['waypoints']}
        self.assertEqual(by_stage['接近']['tip_world_mm'][2],330)
        self.assertEqual(by_stage['进入']['tip_world_mm'][2],230)
        self.assertEqual(by_stage['退出']['tip_world_mm'],by_stage['接近']['tip_world_mm'])
        for cfg in [SimulationConfig(insertion_mm=130),SimulationConfig(bore_pitch_mm=90),SimulationConfig(probe_ball_diameter_mm=101)]:
            with self.assertRaises(ValueError):cfg.validate()

    def test_camera_to_b_composes_with_world(self):
        p=build_plan();local=[20,30,320]
        direct=transform_point(p['b_base_from_virtual_camera'],local)
        via_world=transform_point(np.linalg.inv(p['world_from_b_base']),transform_point(p['world_from_virtual_camera'],local))
        self.assertTrue(np.allclose(direct,via_world))

    def test_cartesian_path_matches_display_model(self):
        plan=build_plan();frames,errors=compile_trajectory(plan,14)
        self.assertLess(max(errors),1)
        for f in frames:
            t=robot_frames(f['joints'],(480,100,0))['J6']
            tip=t[:3,3]+t[:3,2]*plan['config']['tool_length_mm']
            self.assertLess(np.linalg.norm(tip-f['tip']),.01)
            self.assertLess(np.linalg.norm(t[:3,2]-[0,0,-1]),1e-4)
        jumps=np.abs(np.diff([f['joints'] for f in frames],axis=0))
        self.assertLess(np.max(jumps),np.deg2rad(25))

if __name__=='__main__':unittest.main(verbosity=2)
