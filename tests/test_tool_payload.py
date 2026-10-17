import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json,sys,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from inspection_gui.tool_payload import FILE_NAME,load_payload,save_payload
from inspection_gui.manual_control_view import ManualControlDialog
import test_recent_ui as ui
APP=QApplication.instance() or QApplication([])


class ToolPayloadFileTests(unittest.TestCase):
    def setUp(self):
        self.folder=Path.cwd()/'.test-output'/'tool-payload'/uuid.uuid4().hex
        self.path=self.folder/FILE_NAME

    def test_roundtrip_and_rejects_out_of_range(self):
        saved=save_payload(self.path,1.234)
        self.assertEqual(saved['declared_tool_mass_kg'],1.234)
        self.assertEqual(load_payload(self.path)['mass_kg'],1.234)
        with self.assertRaises(ValueError):save_payload(self.path,0)
        with self.assertRaises(ValueError):save_payload(self.path,5.1)

    def test_missing_or_corrupt_file_is_treated_as_unset(self):
        self.assertIsNone(load_payload(self.path))
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text('{not json',encoding='utf-8')
        self.assertIsNone(load_payload(self.path))
        self.path.write_text(json.dumps({'declared_tool_mass_kg':9}),encoding='utf-8')
        self.assertIsNone(load_payload(self.path))


class ToolPayloadViewTests(unittest.TestCase):
    def setUp(self):
        self.folder=Path.cwd()/'.test-output'/'tool-payload-ui'/uuid.uuid4().hex
        self.path=self.folder/FILE_NAME
        self.workspace=ui.Workspace(self.folder)
        self.windows=[]
        self.network=patch('socket.create_connection',side_effect=AssertionError('No hardware in payload tests'))
        self.network.start()

    def tearDown(self):
        for window in reversed(self.windows):
            if window.isVisible():window.close()
        self.windows.clear();self.workspace.close();APP.processEvents();self.network.stop()

    def dialog(self):
        p=ManualControlDialog(self.workspace);self.windows.append(p);p.show();APP.processEvents();return p

    def test_restores_saved_mass_without_unlocking_or_confirming(self):
        save_payload(self.path,2.5)
        p=self.dialog()
        self.assertAlmostEqual(p.payload.value(),2.5)
        self.assertFalse(p.checks[0].isChecked())
        self.assertFalse(p.controller.snapshot()['connected'])
        self.assertIsNone(p.plan_id)

    def test_corrupt_file_starts_from_zero_instead_of_failing(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.write_text('broken',encoding='utf-8')
        p=self.dialog()
        self.assertEqual(p.payload.value(),0)

    def test_mass_is_saved_automatically_after_edit(self):
        p=self.dialog()
        p.payload.setValue(3.2)
        QTest.qWait(900)
        self.assertEqual(load_payload(self.path)['mass_kg'],3.2)

    def test_closing_saves_latest_value(self):
        p=self.dialog()
        p.payload.setValue(4)
        p.close()
        self.assertEqual(load_payload(self.path)['mass_kg'],4)


if __name__=='__main__':unittest.main()
