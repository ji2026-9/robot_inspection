"""Offline tests: target entry never bypasses physical trajectory validation."""
import copy,sys,time,unittest,os,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui import coordinate_target as target
from inspection_gui.safety_wall import DEFAULT_WALL
from inspection_gui.joint_preview import tcp_matrix
from inspection_gui.readonly_kinematics import pose_matrix

def sample():
    joints=[130.,-50.,100.,40.,90.,0.];tool=[0.,0.,145.,0.,0.,0.]
    matrix=tcp_matrix(np.deg2rad(joints),pose_matrix(tool))
    pose=np.r_[matrix[:3,3],Rotation.from_matrix(matrix[:3,:3]).as_euler('xyz',degrees=True)].tolist()
    return dict(pose=pose,joints=joints,tool_offset=tool,user_offset=[0.]*6,received_monotonic=time.monotonic(),
                digital_inputs=0,user_index=0,tool_index=1,mode=5,running=False,error=False,enabled=True)

class TargetTests(unittest.TestCase):
    def setUp(self):
        self.frame=sample();self.wall=dict(DEFAULT_WALL,direction_confirmed=True,distance_mm=10000)
        self.mesh=[dict(joint='base',name='isolated fixture',vertices=np.zeros((1,3)))]
    def plan(self):
        pose=self.frame['pose'][:];pose[0]+=1
        with patch('socket.create_connection',side_effect=AssertionError('No real motion')):
            return target.build_target_preview(self.frame,pose,self.wall,20.,self.mesh,generation=3)
    def test_saved_flags_cannot_authorize_execution(self):
        plan=self.plan();self.assertTrue(plan['preview_complete']);self.assertTrue(plan['sampled_path_clear'])
        self.assertFalse(plan['hardware_executable']);self.assertTrue(plan['frames'])
        self.assertEqual(plan['task']['waypoints'][-1]['tcp_pose'],plan['target_pose'])
        frame=copy.deepcopy(self.frame);frame['received_monotonic']=time.monotonic()
        plan['hardware_executable']=True;plan['execution_blockers']=[]
        # Editing saved fields never authorises motion: they are ignored.
        approval=target.request_execution(plan,frame,self.wall,3)
        self.assertTrue(approval['approved']);self.assertFalse(approval['hardware_executable'])
        self.assertGreaterEqual(approval['minimum_clearance_mm'],target.EXECUTION_MIN_CLEARANCE_MM)
    def test_clearance_below_margin_refuses_execution(self):
        plan=self.plan()
        plan['collision']=dict(plan['collision'],minimum_clearance_mm=5.)
        frame=copy.deepcopy(self.frame);frame['received_monotonic']=time.monotonic()
        with self.assertRaises(ValueError):target.request_execution(plan,frame,self.wall,3)
    def test_start_wall_tool_and_generation_changes_refuse(self):
        plan=self.plan()
        cases=[(dict(self.frame,joints=[0.]*6),self.wall,3),
               (self.frame,dict(self.wall,distance_mm=9999),3),
               (dict(self.frame,tool_index=2),self.wall,3),(self.frame,self.wall,4)]
        for f,w,g in cases:
            f=copy.deepcopy(f);f['received_monotonic']=time.monotonic()
            with self.subTest(g=g),self.assertRaises(ValueError):target.validate_context(plan,f,w,g)
    def test_bad_feedback_and_missing_radius_refuse(self):
        for change in ({'received_monotonic':0.},{'running':True},{'user_index':1},{'digital_inputs':1}):
            with self.assertRaises(ValueError):target.validate_start(dict(self.frame,**change))
        with self.assertRaises(ValueError):target.build_target_preview(self.frame,self.frame['pose'],self.wall,0,self.mesh)
    def test_unconfirmed_wall_skips_check_and_allows_execution(self):
        pose=self.frame['pose'][:];pose[0]+=1
        with patch('socket.create_connection',side_effect=AssertionError('No real motion')):
            plan=target.build_target_preview(self.frame,pose,DEFAULT_WALL,None,self.mesh,generation=3)
        self.assertFalse(plan['wall_checked']);self.assertTrue(plan['collision']['skipped']);self.assertFalse(plan['problems'])
        self.assertTrue(plan['sampled_path_clear'])
        frame=copy.deepcopy(self.frame);frame['received_monotonic']=time.monotonic()
        approval=target.request_execution(plan,frame,DEFAULT_WALL,3)
        self.assertTrue(approval['approved']);self.assertFalse(approval['wall_checked'])
    def test_collision_is_error_not_motion_permit(self):
        pose=self.frame['pose'][:];pose[0]+=1
        unsafe=dict(self.wall,distance_mm=1)
        plan=target.build_target_preview(self.frame,pose,unsafe,20,self.mesh)
        self.assertTrue(plan['problems']);self.assertFalse(plan['sampled_path_clear']);self.assertFalse(plan['hardware_executable'])
    def test_ui_entry_does_not_open_control_channel(self):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PySide6.QtWidgets import QApplication,QWidget
        from inspection_gui import coordinate_target_view as view
        app=QApplication.instance() or QApplication([])
        class Scene(QWidget):
            seeds=[]
            def set_safety_wall(self,*args):pass
            def set_wall_test_result(self,*args):pass
            def set_manual_preview(self,task,frames,seed):self.seeds.append((task,seed))
        class Workspace(QWidget):
            def backend(self):return SimpleNamespace(snapshot=sample,generation=1)
        with tempfile.TemporaryDirectory() as folder,patch.object(view,'Scene3D',Scene),patch('socket.create_connection',side_effect=AssertionError('No real motion')):
            workspace=Workspace();workspace.storage_path=Path(folder)/'positions.json'
            dialog=view.CoordinateTargetDialog(workspace)
            self.assertTrue(dialog.hold_orientation.isChecked());self.assertFalse(dialog.execute.isEnabled())
            # The arm must be visible before any preview is generated.
            self.assertTrue(dialog.scene.seeds);self.assertIsNone(dialog.scene.seeds[-1][0])
            self.assertEqual(dialog.scene.seeds[-1][1]['joints_deg'],sample()['joints'])
            dialog.read_current();self.assertAlmostEqual(dialog.fields[0].value(),sample()['pose'][0],places=3)
            dialog.fields[0].setValue(123);self.assertIsNone(dialog.plan);self.assertFalse(dialog.execute.isEnabled())
            self.assertEqual(dialog.scene.seeds[-1][1]['joints_deg'],sample()['joints'])
            dialog.close();workspace.close();app.processEvents()
    def test_execute_requires_unlocked_control_in_this_window(self):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PySide6.QtWidgets import QApplication,QWidget
        from inspection_gui import coordinate_target_view as view
        app=QApplication.instance() or QApplication([])
        class Scene(QWidget):
            def set_safety_wall(self,*args):pass
            def set_wall_test_result(self,*args):pass
            def set_manual_preview(self,*args):pass
        class Control:
            def __init__(self,connected,unlocked,stop='none'):
                self._state=dict(connected=connected,unlocked=unlocked,phase='ready',reason='测试',
                    resumable=False,safety=dict(stop_state=stop))
            def snapshot(self):return copy.deepcopy(self._state)
        class Workspace(QWidget):
            def __init__(self,control):super().__init__();self.control=control
            def backend(self):return SimpleNamespace(snapshot=sample,generation=1,manual_control=self.control)
        with tempfile.TemporaryDirectory() as folder,patch.object(view,'Scene3D',Scene),patch('socket.create_connection',side_effect=AssertionError('No real motion')):
            for connected,unlocked,expected in ((False,False,False),(True,False,False),(True,True,True)):
                workspace=Workspace(Control(connected,unlocked));workspace.storage_path=Path(folder)/'positions.json'
                dialog=view.CoordinateTargetDialog(workspace)
                dialog.execute_ready=True;dialog.refresh_control_state()
                self.assertEqual(dialog.execute.isEnabled(),expected,(connected,unlocked))
                self.assertEqual(dialog.enable_control.isEnabled(),connected and not unlocked)
                dialog.close();workspace.close();app.processEvents()

if __name__=='__main__':unittest.main(verbosity=2)
