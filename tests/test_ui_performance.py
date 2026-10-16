import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,json,uuid,threading,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import QTimer
from inspection_gui.workbench import Workbench
from inspection_gui.simulation_view import SimulationDialog
from inspection_gui.records_view import RecordsDialog
from inspection_gui.model_management_view import ModelManagementPage,read_model_overview
from inspection_gui.training_bridge import TrainingBridge
from inspection_gui import scene_assets
from experiment_records import ExperimentRecords
from test_recent_ui import Scene

APP=QApplication.instance() or QApplication([])

def pump_until(check,timeout=2):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        APP.processEvents()
        if check():return True
        time.sleep(.002)
    return False

class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.folder=Path.cwd()/'.test-output'/'ui-performance'/uuid.uuid4().hex;self.folder.mkdir(parents=True)
        self.network=patch('socket.create_connection',side_effect=AssertionError('No hardware in performance tests'));self.network.start()
        self.windows=[]
    def tearDown(self):
        for w in self.windows:w.close()
        APP.processEvents();self.network.stop()

    def test_tab_container_is_stable_and_user_selection_defers_construction(self):
        w=Workbench(QWidget());self.windows.append(w);factory=MagicMock(side_effect=QWidget)
        w.register('test','Test',factory);container=w.tabs.widget(1)
        w.tabs.setCurrentIndex(1);self.assertFalse(factory.called)
        APP.processEvents();self.assertTrue(factory.called);self.assertIs(w.tabs.widget(1),container)
        for _ in range(5):w.open_page('visual');w.open_page('test')
        self.assertEqual(factory.call_count,1);self.assertIs(w.tabs.widget(1),container)

    def test_fast_tab_changes_do_not_construct_abandoned_page(self):
        w=Workbench(QWidget());self.windows.append(w);factory=MagicMock(side_effect=QWidget)
        w.register('test','Test',factory);w.tabs.setCurrentIndex(1);w.tabs.setCurrentIndex(0)
        APP.processEvents();self.assertFalse(factory.called)

    def test_simulation_copies_geometry_without_large_image_payload(self):
        class Payload:
            def __deepcopy__(self,memo):raise AssertionError('Full image copied on UI thread')
        with patch('inspection_gui.simulation_view.Scene3D',Scene):p=SimulationDialog(embedded=True)
        self.windows.append(p)
        with patch.object(p,'rebuild'):
            p.set_detection(dict(image_path='image.png',fitted_holes=[],mask=Payload()),[])
        self.assertEqual(set(p.result),{'image_path','fitted_holes'})
        p.shutdown()

    def test_hidden_simulation_stops_playback_and_feedback_ui_timers(self):
        with patch('inspection_gui.simulation_view.Scene3D',Scene):p=SimulationDialog()
        self.windows.append(p);p.auto_attempted=True;p.show();APP.processEvents()
        p.timer.start();self.assertTrue(p.feedback_timer.isActive());p.hide();APP.processEvents()
        self.assertFalse(p.timer.isActive());self.assertFalse(p.feedback_timer.isActive());p.shutdown()

    def test_shared_asset_requests_use_one_background_future(self):
        ready=threading.Event();calls=[]
        def load(path):calls.append(path);ready.wait(1);return ([],None,'test')
        path=self.folder/'asset.npz'
        with patch.object(scene_assets,'load_display_assets',side_effect=load):
            one=scene_assets.display_assets(path);two=scene_assets.display_assets(path)
            self.assertIs(one,two);ready.set();one.result(timeout=2)
        self.assertEqual(len(calls),1)

    def test_procedural_assets_are_read_only_when_shared(self):
        import numpy as np
        with patch('inspection_gui.offline_planning.solve_visual_ik',return_value=(np.zeros(6),0)):
            models,_,_=scene_assets.load_display_assets(self.folder/'missing.npz')
        self.assertTrue(models)
        self.assertTrue(all(not m[k].flags.writeable for m in models for k in ('vertices','normals','faces')))

    def test_large_records_load_in_background_and_fill_over_multiple_events(self):
        path=self.folder/'records.json'
        group=dict(id='g',number=1,time='now',status='完成',model='test.pt',reports=[dict(image=f'{i}.png') for i in range(900)])
        path.write_text(json.dumps([group]),encoding='utf-8')
        records=ExperimentRecords(path);p=RecordsDialog(records=records,deferred=True);self.windows.append(p)
        self.assertEqual(p.table.rowCount(),0)
        heartbeats=[];timer=QTimer();timer.setInterval(0);timer.timeout.connect(lambda:heartbeats.append(1));timer.start()
        p.show()
        try:self.assertTrue(pump_until(lambda:getattr(p,'_fill_cursor',0)==900),p.summary.text())
        finally:timer.stop()
        self.assertEqual(p.table.item(899,2).text(),'899.png');self.assertGreater(len(heartbeats),2)
        with patch.object(p,'refresh_async') as reread:
            p.refresh_if_changed();self.assertFalse(reread.called)

    def test_model_metadata_checks_files_without_loading_weights(self):
        (self.folder/'models').mkdir();(self.folder/'models'/'bore.pt').write_bytes(b'not a torch model')
        (self.folder/'active_models.json').write_text(json.dumps(dict(bore='models/bore.pt',part='models/missing.pt',version='test')),encoding='utf-8')
        data=read_model_overview(self.folder)
        self.assertTrue(data['models'][0]['present']);self.assertFalse(data['models'][1]['present']);self.assertEqual(data['version'],'test')

    def test_model_page_background_refresh_and_bounded_log(self):
        bridge=TrainingBridge(base=self.folder,executable=sys.executable);page=ModelManagementPage(bridge,base=self.folder);self.windows.append(page)
        page.refresh_async();self.assertTrue(pump_until(lambda:not page.loading))
        self.assertIn('尚无版本清单',page.version.text())
        for i in range(300):bridge.log.emit(str(i))
        self.assertLessEqual(page.log.blockCount(),150)
        bridge._busy=True;bridge.busy_changed.emit(True);self.assertIn('运行中',page.task_state.text());bridge.detach()

if __name__=='__main__':unittest.main()
