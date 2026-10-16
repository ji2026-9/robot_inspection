import sys,copy,time,unittest,struct,socket,threading
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.simulated_vision import *
from inspection_gui.probe_workspace import cartesian_frames
from inspection_gui.dobot_feedback import DobotFeedback,decode_frame

class VisionTests(unittest.TestCase):
    def setUp(self):self.data,self.transform=example_data()
    def test_known_rotation_translation_and_direction(self):
        self.data['holes']=[{'id':'H01','position_mm':[10,0,0],'approach_direction':[1,0,0]}]
        self.transform['matrix']=[[0,-1,0,100],[1,0,0,200],[0,0,1,300],[0,0,0,1]]
        task=build_preview(self.data,self.transform)
        np.testing.assert_allclose(task['holes_in_b_base'][0]['position_mm'],[100,210,300])
        np.testing.assert_allclose(task['waypoints'][1]['tcp_pose'][:3],[100,160,300])
        np.testing.assert_allclose(task['waypoints'][2]['tcp_pose'][:3],[100,210,300])
        np.testing.assert_allclose(task['waypoints'][3]['tcp_pose'][:3],[100,160,300])
        np.testing.assert_allclose(Rotation.from_euler('xyz',task['waypoints'][2]['tcp_pose'][3:],degrees=True).as_matrix()[:,2],[0,1,0],atol=1e-12)
    def test_four_holes_preview_flags_and_no_network(self):
        self.data['hardware_executable']=True
        original=copy.deepcopy(self.data)
        with patch('socket.create_connection',side_effect=AssertionError('Simulation opened network')):
            task=build_preview(self.data,self.transform);frames=cartesian_frames(task)
        self.assertEqual(len(task['waypoints']),13);self.assertEqual(len(frames),289)
        self.assertTrue(task['simulation_only']);self.assertTrue(task['preview_only'])
        for flag in ['hardware_executable','calibration_verified','tool_calibration_verified','collision_verified','kinematics_verified']:self.assertIs(task[flag],False)
        self.assertEqual(self.data,original)
    def test_missing_or_duplicate_holes_rejected(self):
        for holes in [[],self.data['holes']*4,[self.data['holes'][0],{**self.data['holes'][0],'id':'h01'}],[{'id':'H01'}]]:
            with self.assertRaises(ValueError):build_preview({**self.data,'holes':holes},self.transform)
    def test_invalid_numbers_or_direction_rejected(self):
        for changes in [{'position_mm':[float('nan'),0,0]},{'position_mm':[True,0,0]},
                        {'approach_direction':[0,0,0]},{'approach_direction':[0,0,-2]}]:
            data=copy.deepcopy(self.data);data['holes'][0].update(changes)
            with self.assertRaises(ValueError):build_preview(data,self.transform)
    def test_units_frames_and_non_simulated_data_rejected(self):
        for changes in [{'units':{'position':'m','angle':'deg'}},{'coordinate_frame':'image_pixels'},
                        {'source':'live_camera'},{'schema_version':True}]:
            with self.assertRaises(ValueError):build_preview({**self.data,**changes},self.transform)
    def test_missing_or_forged_calibration_rejected(self):
        for transform in [None,{}, {**self.transform,'calibration_verified':True}, {**self.transform,'kind':'real'},
                          {**self.transform,'source_frame':'robot_a_base'}, {**self.transform,'target_frame':'robot_a_base'}]:
            with self.assertRaises(ValueError):build_preview(self.data,transform)
    def test_scaling_reflection_or_nonfinite_matrix_rejected(self):
        for row,col,val in [(0,0,2),(2,2,-1),(3,0,1),(0,3,float('inf'))]:
            transform=copy.deepcopy(self.transform);transform['matrix'][row][col]=val
            with self.assertRaises(ValueError):build_preview(self.data,transform)
    def test_preview_range_checks_targets_and_approach(self):
        transform=copy.deepcopy(self.transform);transform['matrix'][0][3]=2000
        with self.assertRaises(ValueError):build_preview(self.data,transform)
        data=copy.deepcopy(self.data);data['holes']=[{'id':'H01','position_mm':[0,0,0],'approach_direction':[0,0,-1]}]
        transform['matrix']=np.eye(4).tolist();transform['matrix'][2][3]=1480
        with self.assertRaises(ValueError):build_preview(data,transform,clearance_mm=50)
        with self.assertRaises(ValueError):build_preview(self.data,self.transform,start_pose=[2000,0,0,0,0,0])

def packet(x=100,tool=1):
    data=bytearray(1440);struct.pack_into('<H',data,0,1440);struct.pack_into('<Q',data,48,0x123456789abcdef)
    struct.pack_into('<6d',data,432,1,2,3,4,5,6);struct.pack_into('<6d',data,624,x,200,300,10,20,30);data[1013]=tool
    return data

def eventually(predicate):
    deadline=time.monotonic()+1
    while time.monotonic()<deadline:
        if predicate():return True
        time.sleep(.01)
    return False

class FeedbackRecoveryTests(unittest.TestCase):
    def test_socket_disconnect_reconnect_and_old_data_not_reused(self):
        b=DobotFeedback();client,server=socket.socketpair();server.sendall(packet(100))
        try:
            with patch('socket.create_connection',return_value=client),patch.object(b,'refresh_identity'):
                self.assertTrue(b.connect({'address':'127.0.0.1','port':30004}))
            self.assertEqual(b.snapshot()['pose'][0],100)
            server.close();self.assertTrue(eventually(lambda:b.snapshot() is None))
            client2,server2=socket.socketpair();server2.sendall(packet(450,2))
            try:
                with patch('socket.create_connection',return_value=client2),patch.object(b,'refresh_identity'):
                    self.assertTrue(b.connect({'address':'127.0.0.1','port':30004}))
                self.assertEqual(b.snapshot()['pose'][0],450);self.assertEqual(b.snapshot()['tool_index'],2)
                b.disconnect();self.assertIsNone(b.snapshot())
            finally:server2.close()
        finally:b.disconnect();server.close()
    def test_corrupt_packet_invalidates_previous_feedback(self):
        b=DobotFeedback();client,server=socket.socketpair();server.sendall(packet())
        try:
            with patch('socket.create_connection',return_value=client),patch.object(b,'refresh_identity'):b.connect({'address':'127.0.0.1'})
            bad=bytearray(packet());struct.pack_into('<Q',bad,48,0);server.sendall(bad)
            self.assertTrue(eventually(lambda:b.snapshot() is None));self.assertIn('校验',b.error)
        finally:b.disconnect();server.close()
    def test_future_and_expired_samples_are_not_current(self):
        b=DobotFeedback();b.sock=object();b.latest=decode_frame(packet())
        for offset in [-3,3]:
            b.latest['received_monotonic']=time.monotonic()+offset
            self.assertIsNone(b.snapshot())
        b.sock=None

if __name__=='__main__':unittest.main(verbosity=2)
