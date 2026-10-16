"""Draft geometry/persistence and headless widget checks, never device control."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.safety_wall import DEFAULT_WALL,validate_wall,wall_vertices,load_wall,save_wall

class WallTests(unittest.TestCase):
    def test_default_is_unknown_and_no_motion_authorization(self):
        data=validate_wall(dict(DEFAULT_WALL,geometry_verified=True,motion_enforced=True))
        self.assertFalse(data['visible']);self.assertFalse(data['direction_confirmed'])
        self.assertFalse(data['motion_enforced']);self.assertFalse(data['geometry_verified'])

    def test_geometry_and_margin_follow_normal(self):
        for angle,axis,sign in ((0,0,1),(90,1,1),(180,0,-1),(-90,1,-1)):
            data=dict(DEFAULT_WALL,yaw_deg=angle,margin_mm=40,distance_mm=250)
            self.assertTrue(all(abs(p[axis]-sign*250)<1e-6 for p in wall_vertices(data)))
            self.assertTrue(all(abs(p[axis]-sign*210)<1e-6 for p in wall_vertices(data,True)))

    def test_invalid_fields_and_unknown_visible_wall_rejected(self):
        for change in ({'visible':True},{'distance_mm':float('nan')},{'yaw_deg':float('inf')},
                       {'height_mm':-1},{'units':'m'},{'frame':'camera'},
                       {'distance_mm':250,'margin_mm':250}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_wall(dict(DEFAULT_WALL,**change))

    def test_save_reload_cannot_certify_wall(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'wall.json'
            saved=save_wall(path,dict(DEFAULT_WALL,visible=True,direction_confirmed=True,motion_enforced=True))
            self.assertEqual(saved,load_wall(path));self.assertFalse(saved['motion_enforced'])

    def test_editor_does_not_connect_and_starts_unverified(self):
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PySide6.QtWidgets import QApplication
        from inspection_gui.safety_wall_view import SafetyWallDialog
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory,patch('socket.create_connection',side_effect=AssertionError('No device access')):
            path=Path(directory)/'wall.json';window=SafetyWallDialog(config_path=path)
            self.assertEqual(window.direction.currentIndex(),0);self.assertFalse(window.visible.isChecked())
            window.visible.setChecked(True);window.save();self.assertFalse(path.exists())
            window.direction.setCurrentIndex(2);window.fields['margin_mm'].setValue(30)
            received=[];window.wall_changed.connect(received.append);window.save()
            data=load_wall(path);self.assertEqual(data['yaw_deg'],90);self.assertEqual(data['margin_mm'],30)
            self.assertFalse(data['motion_enforced']);self.assertEqual(len(received),1)
            window.close();app.processEvents()

    def test_scene_wall_draw_restores_gl_state(self):
        from inspection_gui import simulation_scene3d as scene
        fake=MagicMock();fake.GL_ENABLE_BIT=1;fake.GL_CURRENT_BIT=2;fake.GL_LINE_BIT=4
        fake.GL_COLOR_BUFFER_BIT=8;fake.GL_DEPTH_BUFFER_BIT=16
        state=type('State',(),{'probe_only':True,'safety_wall':dict(DEFAULT_WALL,visible=True,direction_confirmed=True,margin_mm=40,distance_mm=250)})()
        with patch.object(scene,'gl',fake):scene.Scene3D._draw_safety_wall(state)
        fake.glPushAttrib.assert_called_once();fake.glPopAttrib.assert_called_once()
        points=[call.args[0] for call in fake.glVertex3fv.call_args_list]
        self.assertTrue(all(point[0]==250 for point in points[:8]))
        self.assertTrue(all(point[0]==210 for point in points[8:12]))

if __name__=='__main__':unittest.main(verbosity=2)
