import unittest
from unittest.mock import Mock,patch
from inspection_gui.start_guide import next_step,StartGuide
from test_integrated_target import APP,sample

class StartGuideTests(unittest.TestCase):
    def test_missing_or_stale_feedback_precedes_other_steps(self):
        self.assertEqual(next_step(None)[2],'devices')
        backend=Mock();backend.manual_control=None;frame=sample();frame['received_monotonic']=0;backend.snapshot.return_value=frame
        self.assertEqual(next_step(backend)[2],'devices')
    def test_wall_not_confirmed_is_not_permission_to_move(self):
        backend=Mock();backend.manual_control=None;backend.snapshot.side_effect=sample
        self.assertEqual(next_step(backend,'墙位置未确认')[2],'wall')
        self.assertIn('不代表允许运动',next_step(backend)[1])
    def test_controller_alarm_and_running_have_priority(self):
        backend=Mock();backend.manual_control=None
        backend.snapshot.side_effect=lambda:dict(sample(),error=True)
        self.assertEqual(next_step(backend)[2],'devices')
        backend.snapshot.side_effect=lambda:dict(sample(),error=False,running=True)
        self.assertEqual(next_step(backend,'墙未确认')[2],'control')
    def test_navigation_does_not_connect_or_start_motion(self):
        navigate=Mock()
        with patch('socket.create_connection',side_effect=AssertionError('No hardware')):
            guide=StartGuide(lambda:None,lambda:'墙未确认',navigate)
            guide.refresh();guide.action.click();navigate.assert_called_once_with('devices')
            guide.show();APP.processEvents();self.assertTrue(guide.timer.isActive())
            guide.hide();self.assertFalse(guide.timer.isActive());guide.close()
