import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from inspection_gui.stepper import DoubleParameter,IntegerParameter
from inspection_gui.numeric_parameter import NumericParameter
from inspection_gui.camera_parameters import CameraParametersDialog
from inspection_gui.simulation_view import SimulationDialog
from inspection_gui.manual_control_view import ManualControlDialog
from inspection_gui.probe_workspace_view import ProbeWorkspaceDialog
import test_recent_ui as ui
import test_manual_control as helpers
APP=QApplication.instance() or QApplication([])

class StepperTests(unittest.TestCase):
    def setUp(self):
        self.windows=[];self.folder=Path.cwd()/'.test-output'/'steppers'/uuid.uuid4().hex
        self.network=patch('socket.create_connection',side_effect=AssertionError('No hardware in button tests'));self.network.start()
    def tearDown(self):
        for p in reversed(self.windows):
            if hasattr(p,'shutdown'):p.shutdown()
            p.close()
        self.network.stop();APP.processEvents()
    def show(self,w):self.windows.append(w);w.show();APP.processEvents();return w
    def click(self,button):QTest.mouseClick(button,Qt.LeftButton);APP.processEvents()

    def test_double_buttons_step_on_press_without_extra_release_step(self):
        p=self.show(DoubleParameter());p.setRange(-1,2);p.setDecimals(3);p.setSingleStep(.1);p.setValue(1)
        QTest.mousePress(p.plus_button,Qt.LeftButton);self.assertAlmostEqual(p.value(),1.1)
        QTest.mouseRelease(p.plus_button,Qt.LeftButton);self.assertAlmostEqual(p.value(),1.1)
        self.click(p.minus_button);self.assertAlmostEqual(p.value(),1)
    def test_native_typed_value_is_committed_before_step(self):
        p=self.show(DoubleParameter());p.setRange(0,5);p.setSingleStep(.1)
        p.lineEdit().setText('1.25');self.click(p.plus_button);self.assertAlmostEqual(p.value(),1.35)
    def test_limits_readonly_and_disabled_states_are_visible(self):
        p=self.show(IntegerParameter());p.setRange(1,3);p.setValue(1)
        self.assertFalse(p.minus_button.isEnabled());self.click(p.plus_button);self.assertEqual(p.value(),2)
        self.click(p.plus_button);self.assertEqual(p.value(),3);self.assertFalse(p.plus_button.isEnabled())
        p.setReadOnly(True);self.assertFalse(p.minus_button.isEnabled());p.setReadOnly(False)
        p.setEnabled(False);self.assertFalse(p.minus_button.isEnabled());p.setEnabled(True);self.assertTrue(p.minus_button.isEnabled())
    def test_long_hold_repeats_but_release_cancels_repeat(self):
        p=self.show(DoubleParameter());p.setRange(0,100);p.setSingleStep(.1)
        QTest.mousePress(p.plus_button,Qt.LeftButton);QTest.qWait(720);QTest.mouseRelease(p.plus_button,Qt.LeftButton)
        value=p.value();self.assertGreaterEqual(value,.3);QTest.qWait(180);self.assertEqual(p.value(),value)
    def test_editable_presets_step_fraction_integer_and_recover_invalid_text(self):
        p=self.show(NumericParameter());p.configure([.1,1,10],.01,100,.1)
        self.click(p.plus_button);self.assertAlmostEqual(p.value(),.2);self.click(p.minus_button);self.assertAlmostEqual(p.value(),.1)
        p.setEditText('7.25');self.click(p.plus_button);self.assertAlmostEqual(p.value(),7.35)
        p.setEditText('');self.click(p.minus_button);self.assertAlmostEqual(p.value(),7.25)
        p.configure([1,2,5],1,10,1,integer=True);self.assertFalse(p.minus_button.isEnabled())
        self.click(p.plus_button);self.assertEqual(p.value(),2)
        p.setEditText('10');self.assertFalse(p.plus_button.isEnabled());self.assertGreater(p.plus_button.width(),20)
    def test_camera_exposure_and_gain_have_useful_steps_without_writing_device(self):
        p=self.show(CameraParametersDialog());p.exposure.setValue(1000);p.gain.setValue(1)
        self.click(p.exposure.plus_button);self.assertEqual(p.exposure.value(),1100)
        self.click(p.gain.minus_button);self.assertAlmostEqual(p.gain.value(),.9)
        self.assertIsNone(p.worker)
    def test_simulation_dimensions_and_playback_speed_buttons(self):
        with patch('inspection_gui.simulation_view.Scene3D',ui.Scene):p=SimulationDialog()
        p.auto_attempted=True;self.show(p)
        with patch.object(p,'schedule_rebuild'):
            field=p.spins['bore_diameter_mm'];before=field.value();self.click(field.plus_button);self.assertAlmostEqual(field.value(),before+.1)
        p.debounce.stop();p.speed.setValue(1);self.click(p.speed.plus_button);self.assertEqual(p.speed.value(),1.25)
    def test_manual_payload_and_parameter_buttons_do_not_move_robot(self):
        workspace=ui.Workspace(self.folder);self.windows.append(workspace);p=self.show(ManualControlDialog(workspace))
        self.click(p.payload.plus_button);self.assertAlmostEqual(p.payload.value(),.1)
        p.motion_mode.setCurrentIndex(1);p.step.setEditText('1');self.click(p.step.plus_button);self.assertAlmostEqual(p.step.value(),1.1)
        self.click(p.speed.plus_button);self.assertEqual(p.speed.value(),2)
        self.assertFalse(p.controller.snapshot()['connected']);self.assertIsNone(p.plan_id)
    def test_preview_coordinate_buttons_change_fractional_values(self):
        with patch('inspection_gui.probe_workspace_view.Scene3D',ui.Scene):p=ProbeWorkspaceDialog(storage_path=self.folder/'positions.json')
        p.auto_attempted=True;self.show(p)
        field=p.target_fields['X'];field.setValue(1);self.click(field.plus_button);self.assertAlmostEqual(field.value(),1.1)

if __name__=='__main__':unittest.main()
