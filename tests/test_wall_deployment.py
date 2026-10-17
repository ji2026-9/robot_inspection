import os,sys,unittest,uuid
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.safety_wall import DEFAULT_WALL,save_wall
from inspection_gui.safety_wall_view import SafetyWallDialog,SafetyWallWorkbench
from test_safety_wall_workbench import Scene
APP=QApplication.instance() or QApplication([])

class WallDeploymentTests(unittest.TestCase):
    def test_open_preserves_saved_settings_and_uses_fractional_buttons(self):
        folder=Path.cwd()/'.test-output'/'wall-deploy'/uuid.uuid4().hex;path=folder/'wall.json'
        save_wall(path,dict(DEFAULT_WALL,direction_confirmed=True,yaw_deg=90,distance_mm=300))
        original=path.read_bytes()
        with patch('socket.create_connection',side_effect=AssertionError('No real device')):
            p=SafetyWallDialog(config_path=path);p.show();APP.processEvents()
            self.assertEqual(p.fields['distance_mm'].value(),300);self.assertEqual(p.direction.currentIndex(),2)
            QTest.mouseClick(p.fields['distance_mm'].plus_button,Qt.LeftButton)
            self.assertAlmostEqual(p.fields['distance_mm'].value(),300.1)
            p.close();APP.processEvents()
        self.assertEqual(path.read_bytes(),original)

    def test_hiding_wall_workbench_stops_gui_timer(self):
        class Workspace(QWidget):
            def __init__(self):
                super().__init__();self.scene=Scene()
                self.storage_path=Path.cwd()/'.test-output'/'wall-deploy'/uuid.uuid4().hex/'positions.json'
            def backend(self):return self
            def snapshot(self):return None
        workspace=Workspace()
        with patch('inspection_gui.simulation_scene3d.Scene3D',Scene),patch('socket.create_connection',side_effect=AssertionError('No real device')):
            p=SafetyWallWorkbench(workspace);p.show();APP.processEvents();self.assertTrue(p.timer.isActive())
            p.hide();APP.processEvents();self.assertFalse(p.timer.isActive())
            p.show();APP.processEvents();self.assertTrue(p.timer.isActive())
            p.close();workspace.close();APP.processEvents()

if __name__=='__main__':unittest.main()
