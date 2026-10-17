import copy,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import numpy as np
from test_recent_ui import APP,Workspace
from test_integrated_target import sample
from inspection_gui.manual_preview import ManualPreview,build_preview,estimate_timing,validate_preview
from inspection_gui.safety_wall import DEFAULT_WALL

class PreviewTimingTests(unittest.TestCase):
    def setUp(self):
        self.network=patch('socket.create_connection',side_effect=AssertionError('No hardware'));self.network.start()
        self.w=Workspace(Path.cwd()/'.test-output'/'timing'/uuid.uuid4().hex)
        self.p=ManualPreview(self.w);self.now=[100.];self.p.clock=lambda:self.now[0]
        f=dict(sample(),speed_percent=10);xyz=f['pose'][:3];xyz[0]+=1
        self.plan=build_preview(f,xyz,1,DEFAULT_WALL,Path('unused'),speed=1)
        self.p.finished(self.p.revision,self.plan,'')
    def tearDown(self):
        self.p.shutdown();self.p.close();self.w.close();APP.processEvents();self.network.stop()
    def test_speed_and_global_multiplier_determine_duration(self):
        self.assertEqual(estimate_timing(50,5,100)['duration_seconds'],10)
        self.assertEqual(estimate_timing(50,5,20)['duration_seconds'],50)
        self.assertFalse(estimate_timing(50,5,None)['scale_known'])
        zero=estimate_timing(50,5,0)
        self.assertIsNone(zero['duration_seconds']);self.assertEqual(zero['effective_mm_s'],0)
    def test_wall_clock_midpoint_smooth_interpolation_and_no_mutation(self):
        original=copy.deepcopy(self.plan['frames']);self.p.toggle()
        self.now[0]+=5;self.p.tick()
        self.assertEqual(self.p.slider.value(),5000)
        expected=(np.asarray(self.plan['start']['pose'][:3])+np.asarray(self.plan['target'][:3]))/2
        np.testing.assert_allclose(self.p.scene.manual_frames[0]['tip'],expected,atol=1e-5)
        self.assertIn('已移动 0.50 / 1.00 mm',self.p.virtual_pose.text())
        self.assertFalse(np.allclose(self.p.scene.manual_frames[0]['joints'],self.plan['frames'][0]['joints']))
        for a,b in zip(original,self.plan['frames']):np.testing.assert_array_equal(a['joints'],b['joints'])
        self.assertIn('5.0 / 10.0',self.p.progress.text())
    def test_pause_seek_resume_and_completion_follow_elapsed_time(self):
        self.p.toggle();self.now[0]+=2;self.p.toggle();self.assertFalse(self.p.timer.isActive())
        self.now[0]+=20;self.p.toggle();self.now[0]+=1;self.p.tick()
        self.assertAlmostEqual(self.p.elapsed,3)
        self.p.slider.setValue(7500);self.now[0]+=.5;self.p.tick();self.assertAlmostEqual(self.p.elapsed,8)
        self.now[0]+=50;self.p.tick()
        self.assertEqual(self.p.slider.value(),10000);self.assertFalse(self.p.timer.isActive())
        self.p.toggle();self.assertEqual(self.p.elapsed,0)
    def test_scale_change_requires_new_preview(self):
        with self.assertRaisesRegex(ValueError,'倍率'):
            validate_preview(self.plan,dict(sample(),speed_percent=20),1)

    def test_zero_multiplier_builds_path_but_keeps_model_at_start(self):
        f=dict(sample(),speed_percent=0);xyz=f['pose'][:3];xyz[0]+=1
        plan=build_preview(f,xyz,1,DEFAULT_WALL,Path('unused'),speed=1)
        self.p.finished(self.p.revision,plan,'')
        self.assertIs(self.p.plan,plan);self.assertIsNone(self.p.duration)
        self.assertFalse(self.p.play.isEnabled());self.assertFalse(self.p.slider.isEnabled())
        self.p.toggle();self.now[0]+=100;self.p.tick()
        self.assertFalse(self.p.timer.isActive())
        np.testing.assert_allclose(self.p.scene.manual_frames[0]['tip'],f['pose'][:3])
        self.assertIn('路径已生成',self.p.note.text())
        validate_preview(plan,dict(sample(),speed_percent=0),1)
        self.p.finished(self.p.revision,self.plan,'')
        self.assertTrue(self.p.play.isEnabled());self.assertTrue(self.p.slider.isEnabled())

if __name__=='__main__':unittest.main()
