"""Offline model tests: no controller, no motion commands."""
import sys,unittest,math,json,os,tempfile,time
from unittest.mock import patch
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.wall_collision import check_pose,check_path,load_collision_meshes
from inspection_gui.safety_wall import DEFAULT_WALL

class CollisionTests(unittest.TestCase):
    def setUp(self):
        self.wall=dict(DEFAULT_WALL,direction_confirmed=True,distance_mm=50)
        self.meshes=[dict(joint='J1',name='isolated fixture',vertices=np.array([[100.,0.,0.]]))]

    def test_clear_model_pose(self):
        result=check_pose(self.meshes,[math.pi/2,0,0,0,0,0],self.wall)
        self.assertFalse(result['collision']);self.assertAlmostEqual(result['minimum_clearance_mm'],50)
        self.assertFalse(result['hardware_executable']);self.assertFalse(result['tool_checked'])

    def test_link_crosses_infinite_wall_even_outside_draw_rectangle(self):
        wall=dict(self.wall,width_mm=1,height_mm=1,bottom_mm=2000)
        result=check_pose(self.meshes,[0]*6,wall)
        self.assertTrue(result['collision']);self.assertEqual(result['parts'][0]['part'],'J1')

    def test_tool_only_collision_and_radius(self):
        model=[dict(joint='base',name='origin fixture',vertices=np.zeros((1,3)))]
        result=check_pose(model,[0]*6,self.wall,[0,0,100,0,0,0],10,[45,0,0,0,0,0])
        self.assertFalse(result['parts'][0]['collision']);self.assertTrue(result['parts'][-1]['collision'])
        self.assertAlmostEqual(result['parts'][-1]['clearance_mm'],-5)

    def test_safe_endpoints_do_not_hide_middle_collision(self):
        a=[-math.pi/2,0,0,0,0,0];b=[math.pi/2,0,0,0,0,0]
        self.assertFalse(check_pose(self.meshes,a,self.wall)['collision'])
        self.assertFalse(check_pose(self.meshes,b,self.wall)['collision'])
        result=check_path(self.meshes,[a,b],self.wall)
        self.assertTrue(result['collision']);self.assertGreater(result['fraction'],0)
        self.assertLess(result['fraction'],1);self.assertFalse(result['continuous_verified'])

    def test_missing_data_never_produces_safe_result(self):
        for q,wall in (([float('nan')]*6,self.wall),([0]*6,DEFAULT_WALL)):
            with self.assertRaises(ValueError):check_pose(self.meshes,q,wall)
        with self.assertRaises(ValueError):check_pose([], [0]*6,self.wall)
        with self.assertRaises(ValueError):check_path(self.meshes,[[0]*6],self.wall)

    def test_actual_display_asset_and_convex_support(self):
        path=Path(__file__).resolve().parents[1]/'software/inspection_gui/assets/local_dobot_cr5.npz'
        
        if not path.is_file():self.skipTest('Optional local vendor display asset is not installed')
        meshes=load_collision_meshes(path)
        with np.load(path,allow_pickle=False) as raw:
            self.assertEqual(len(meshes),len(json.loads(str(raw['metadata']))))
            for i,mesh in enumerate(meshes):
                for direction in ([1,0,0],[0,1,0],[.2,-.7,.4]):
                    self.assertAlmostEqual(float(np.max(raw[f'v{i}']@direction)),float(np.max(mesh['vertices']@direction)),places=4)
        result=check_pose(meshes,[0]*6,dict(self.wall,distance_mm=10000))
        self.assertFalse(result['collision']);self.assertEqual(len(result['parts']),len(meshes))

    def test_current_snapshot_button_uses_no_control_channel(self):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        asset=Path(__file__).resolve().parents[1]/'software/inspection_gui/assets/local_dobot_cr5.npz'
        if not asset.is_file():self.skipTest('Optional local vendor display asset is not installed')
        from PySide6.QtWidgets import QApplication,QWidget
        from inspection_gui.safety_wall_view import SafetyWallDialog
        app=QApplication.instance() or QApplication([])
        class Scene:
            report=None
            def set_wall_test_result(self,result):self.report=result
        class Workspace(QWidget):
            scene=Scene();task=None;frames=[]
            def backend(self):return self
            def snapshot(self):return dict(received_monotonic=time.monotonic(),mode=5,running=False,user_index=0,joints=[0]*6,pose=[100,0,500,0,0,0],tool_offset=[0,0,100,0,0,0])
        with tempfile.TemporaryDirectory() as directory,patch('socket.create_connection',side_effect=AssertionError('No control channel')):
            workspace=Workspace();window=SafetyWallDialog(workspace,Path(directory)/'wall.json')
            results=[];window.test_completed.connect(results.append)
            window.direction.setCurrentIndex(1);window.fields['distance_mm'].setValue(10000)
            window.tool_confirm.setChecked(True);window.start_test(False)
            end=time.monotonic()+5
            while window._testing and time.monotonic()<end:app.processEvents();time.sleep(.01)
            self.assertFalse(window._testing);self.assertTrue(results)
            self.assertIsNone(workspace.scene.report)  # A local check never overwrites another page's pose.
            self.assertTrue(results[-1]['tool_checked']);self.assertFalse(results[-1]['hardware_executable'])
            self.assertEqual(len(list((Path(directory)/'wall_tests').glob('*.json'))),1)
            window.close();workspace.close();app.processEvents()

if __name__=='__main__':unittest.main(verbosity=2)
