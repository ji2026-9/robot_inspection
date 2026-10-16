"""Headless page integration; no device connections or GPU rendering."""
import os,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from PySide6.QtWidgets import QApplication,QWidget
from inspection_gui import simulation_scene3d,probe_workspace_view
from inspection_gui.gui import MainWindow

class Scene(QWidget):
    def __init__(self):super().__init__();self.report=None;self.safety_wall=None
    def reset_view(self):pass
    def set_manual_preview(self,*args):pass
    def set_live_frame(self,*args):pass
    def set_safety_wall(self,wall):self.safety_wall=wall
    def set_wall_test_result(self,result):self.report=result

class IntegrationTests(unittest.TestCase):
    def test_mainline_wall_tab_uses_same_configuration_and_no_connection(self):
        app=QApplication.instance() or QApplication([])
        with patch.object(simulation_scene3d,'Scene3D',Scene),patch.object(probe_workspace_view,'Scene3D',Scene), \
             patch('socket.create_connection',side_effect=AssertionError('No device access during wall navigation')):
            main=MainWindow(records=SimpleNamespace(groups=[]))
            self.assertIn('wall',main.workbench.keys)
            page=main.workbench.open_page('wall');self.assertIsNotNone(page)
            self.assertTrue(page.editor.close_button.isHidden())
            self.assertIsNotNone(page.scene.safety_wall)
            wall=dict(page.editor.config(),visible=True,direction_confirmed=True)
            page.editor.wall_changed.emit(wall)
            self.assertEqual(page.scene.safety_wall,page.workspace.scene.safety_wall)
            marker={'joints_rad':[0.]*6,'parts':[]}
            page.editor.test_completed.emit(marker);self.assertEqual(page.scene.report,marker)
            page.editor.clear_test();self.assertIsNone(page.scene.report)
            self.assertIsNone(page.workspace.backend().manual_control)
            main.close();app.processEvents()

if __name__=='__main__':unittest.main(verbosity=2)
