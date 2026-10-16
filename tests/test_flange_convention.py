from pathlib import Path
import sys,json,struct,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.offline_planning import robot_frames,translated,rotation,Y_UP_TO_Z_UP
from inspection_gui.readonly_kinematics import audit_snapshot,pose_matrix

class FlangeConventionTests(unittest.TestCase):
    def test_flange_axes_do_not_move_the_robot_mesh_or_tip(self):
        for joints in (np.zeros(6),np.deg2rad([226.87565,23.9864,-65.1854,.274,66.7044,-51.8799]),np.deg2rad([-30,45,20,-70,80,160])):
            frames=robot_frames(joints,(0,0,0))
            np.testing.assert_allclose(frames['flange'][:3,3],frames['J6'][:3,3])
            np.testing.assert_allclose(frames['flange'][:3,2],frames['J6'][:3,2])
            np.testing.assert_allclose(frames['flange'][:3,:2],-frames['J6'][:3,:2])
    def test_multiple_angles_against_manufacturer_tool_frame(self):
        asset=Path(r'D:\DobotStudio Pro 4.6\resources\3d\static\cr5\all.glb')
        if not asset.is_file():self.skipTest('Manufacturer display asset is not installed')
        raw=asset.read_bytes()
        nodes=json.loads(raw[20:20+struct.unpack_from('<I',raw,12)[0]])['nodes']
        nodes={n['name']:n for n in nodes if n.get('name') in ['base','J1','J2','J3','J4','J5','J6','TOOL']}
        # Independently compose the bundled manufacturer's joint translations;
        # rotation axes and TOOL Rz=180deg come from RoboticArmLoader.ts.
        for joints in (np.zeros(6),np.deg2rad([20,-60,90,15,80,-130]),np.deg2rad([-90,20,-50,40,-100,60])):
            reference=Y_UP_TO_Z_UP.copy()
            for i,axis in enumerate(['y','z','z','z','y','z']):
                reference=reference@translated(*nodes[f'J{i+1}']['translation'])@rotation(axis,joints[i])
            reference=reference@translated(*nodes['TOOL'].get('translation',[0,0,0]))@rotation('z',np.pi)
            np.testing.assert_allclose(robot_frames(joints,(0,0,0))['flange'],reference,atol=2e-5)
    def test_real_sample_still_reports_remaining_error(self):
        sample={'joints_deg':[226.8756561279297,23.986404418945312,-65.18537902832031,.2740563154220581,66.70435333251953,-51.87990951538086],'feedback_tcp':[-377.78143310546875,-106.23741149902344,739.1676025390625,-157.05618286132812,-49.633644104003906,166.88258361816406],'sample_received_at':0}
        frame={'joints':sample['joints_deg'],'pose':sample['feedback_tcp'],'tool_index':1,'user_index':0,
               'tool_offset':[-19.469261169433594,-45.07438278198242,152.67613220214844,0,0,0],
               'received_at':sample['sample_received_at']}
        report=audit_snapshot('192.168.5.1',frame)
        self.assertGreater(report['joint6_frame_vs_reference']['orientation_deg'],179)
        self.assertLess(report['visual_vs_controller']['orientation_deg'],2)
        self.assertGreater(report['visual_vs_controller']['position_mm'],4)
        self.assertFalse(report['display_chain_matches_sample'])
        self.assertFalse(report['physical_tool_calibration_verified'])
        self.assertFalse(report['motion_executed'])
        print('Corrected static sample:',report['visual_vs_controller'])

if __name__=='__main__':unittest.main(verbosity=2)
