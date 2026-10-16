from pathlib import Path
import sys,json,tempfile,time,unittest,struct,uuid
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.probe_workspace import *
from inspection_gui.readonly_kinematics import positive_command,parse_pose_reply,audit_snapshot,pose_matrix,read_positive_kinematics
from inspection_gui.dobot_feedback import decode_frame

def frame():
    return {'joints':[1.,2.,3.,4.,5.,6.],'pose':[100.,200.,300.,10.,20.,30.],
        'user_index':0,'tool_index':1,'tool_offset':[0.,0.,145.,0.,0.,0.],'user_offset':[0.]*6,
        'received_at':time.time(),'received_monotonic':time.monotonic(),
        'mode':4,'enabled':False,'running':False,'error':False}

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.folder=Path(__file__).parent/('probe_test_'+uuid.uuid4().hex)
        self.folder.mkdir();self.path=self.folder/'positions.json'
    def tearDown(self):
        assert self.folder.resolve().is_relative_to(Path(__file__).parent.resolve())
        for file in self.folder.iterdir():
            assert file.resolve().is_relative_to(self.folder.resolve())
            file.unlink()
        self.folder.rmdir()
    def test_records_survive_restart_with_original_coordinates(self):
        lib=PositionLibrary(self.path);r=capture_position('  起点  ',frame());lib.add(r)
        lib.change(r['id'],name='新名称',archived=True);loaded=PositionLibrary(self.path).records[0]
        self.assertEqual(loaded['name'],'新名称');self.assertTrue(loaded['archived'])
        self.assertEqual(loaded['tcp_pose'],r['tcp_pose']);self.assertFalse(loaded['hardware_executable'])
        with self.assertRaises(ValueError):lib.change(r['id'],tcp_pose=[0]*6)
        lib.change(r['id'],archived=False);self.assertFalse(lib.records[0]['archived'])
    def test_expired_and_invalid_feedback_cannot_be_saved(self):
        for f in [None,{**frame(),'received_monotonic':time.monotonic()-3},{**frame(),'pose':[float('nan')]*6}]:
            with self.assertRaises(ValueError):capture_position('位置',f)
    def test_import_is_atomic_and_deduplicated(self):
        lib=PositionLibrary(self.path);r=capture_position('A',frame());lib.add(r);export=self.path.with_name('export.json');lib.export(export)
        self.assertEqual(lib.import_file(export),0)
        before=self.path.read_bytes();bad=capture_position('B',frame());bad['tcp_pose']=[0,0]
        export.write_text(json.dumps({'schema_version':1,'positions':[r,bad]}),encoding='utf-8')
        with self.assertRaises(ValueError):lib.import_file(export)
        self.assertEqual(self.path.read_bytes(),before)
    def test_import_cannot_enable_execution(self):
        r=capture_position('A',frame());r['hardware_executable']=True;r['tool_calibration_verified']=True
        lib=PositionLibrary(self.path);lib.add(r);self.assertFalse(lib.records[0]['hardware_executable']);self.assertFalse(lib.records[0]['tool_calibration_verified'])
    def test_unreadable_library_is_preserved(self):
        self.path.write_text('{broken',encoding='utf-8')
        with self.assertRaises(ValueError):PositionLibrary(self.path)
        self.assertEqual(self.path.read_text(),'{broken')
    def test_manual_candidate_point_uses_target_orientation(self):
        task=manual_task([0,0,0,0,0,0],[100,200,300,0,90,0],1,50)
        self.assertTrue(np.allclose(task['waypoints'][1]['tcp_pose'][:3],[50,200,300]))
        self.assertEqual(task['waypoints'][1]['tcp_pose'],task['waypoints'][-1]['tcp_pose'])
        self.assertFalse(task['hardware_executable']);self.assertFalse(task['collision_verified'])
    def test_shortest_orientation_interpolation(self):
        task=manual_task([0,0,0,0,0,179],[10,0,0,0,0,-179],1,5)
        frames=cartesian_frames(task,10)
        first=frames[0]['rotation'];half=frames[5]['rotation']
        angle=Rotation.from_matrix(half@first.T).magnitude()
        self.assertLess(angle,np.deg2rad(2));self.assertTrue(np.allclose(frames[-1]['tip'],task['waypoints'][-1]['tcp_pose'][:3]))
        task['user_index']=1
        with self.assertRaises(ValueError):cartesian_frames(task)
    def test_command_injection_is_rejected(self):
        command=positive_command([1,2,3,4,5,6],0,1)
        self.assertEqual(command,'PositiveKin(1,2,3,4,5,6,user=0,tool=1)')
        for bad in [['0);EnableRobot()',0,0,0,0,0],[float('nan')]*6]:
            with self.assertRaises(ValueError):positive_command(bad,0,1)
        with self.assertRaises(ValueError):positive_command([0]*6,'0);MovJ()',1)
    def test_reply_rejects_failure_and_invalid_values(self):
        self.assertEqual(parse_pose_reply('0,{1,2,3,4,5,6},PositiveKin(...);'),[1,2,3,4,5,6])
        for bad in ['-1,{0,0,0,0,0,0};','0,{nan,0,0,0,0,0};','0,{1,2};','garbled']:
            with self.assertRaises(ValueError):parse_pose_reply(bad)
    def test_default_audit_never_opens_control_socket(self):
        with patch('socket.create_connection',side_effect=AssertionError('No network query expected')):
            r=audit_snapshot('192.168.5.1',frame())
        derived=pose_matrix(r['controller_flange'])@pose_matrix(frame()['tool_offset'])
        self.assertTrue(np.allclose(derived,pose_matrix(frame()['pose'])))
        self.assertIsNone(r['feedback_matches_sample']);self.assertFalse(r['motion_executed'])
    def test_query_failure_remains_explicit(self):
        with patch('inspection_gui.readonly_kinematics.read_positive_kinematics',side_effect=TimeoutError('no reply')):
            r=audit_snapshot('192.168.5.1',frame(),True)
        self.assertEqual(r['reference_source'],'feedback_tool_configuration');self.assertEqual(r['controller_query_error'],'no reply')
        with self.assertRaises(ValueError):audit_snapshot('192.168.5.1',{**frame(),'user_index':1})
    def test_feedback_offset_layout(self):
        data=bytearray(1440);struct.pack_into('<H',data,0,1440);struct.pack_into('<Q',data,48,0x123456789abcdef)
        struct.pack_into('<6d',data,1200,10,20,30,0,0,0);struct.pack_into('<6d',data,1248,1,2,145,0,0,0)
        f=decode_frame(data);self.assertEqual(f['tool_offset'],[1,2,145,0,0,0]);self.assertEqual(f['user_offset'],[10,20,30,0,0,0])

if __name__=='__main__':unittest.main(verbosity=2)
