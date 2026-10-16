import copy,unittest
import test_manual_control as helpers
from test_manual_control import frame,wait


class ResumeTests(unittest.TestCase):
    setUp=helpers.ManualTests.setUp
    tearDown=helpers.ManualTests.tearDown
    create=helpers.ManualTests.create
    connected=helpers.ManualTests.connected
    ready=helpers.ManualTests.ready

    def pause(self,c):
        c.request_stop('人工停止',recoverable=True)
        self.assertTrue(wait(lambda:c.snapshot()['safety']['stop_state']=='acknowledged'))
        for _ in range(9):
            self.now[0]+=.05;c.observe(frame(self.now[0]),1)

    def test_continue_preserves_budget_but_never_replays_move(self):
        c=self.ready();old=c.preview('X',.1);c.used_distance=1.5;expires=c.expires;anchor=c.anchor[:]
        self.pause(c)
        self.assertTrue(c.snapshot()['safety']['can_resume'])
        calls=copy.deepcopy(self.channels[-1].calls)
        c.resume_control()
        self.assertEqual(c.snapshot()['phase'],'ready');self.assertIsNone(c.snapshot()['plan'])
        self.assertEqual(c.expires,expires);self.assertEqual(c.used_distance,1.5);self.assertEqual(c.anchor,anchor)
        self.assertEqual(self.channels[-1].calls,calls)
        with self.assertRaises(ValueError):c.execute(old['id'])
        new=c.preview('Y',.1);c.execute(new['id'])
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        self.assertEqual(sum(isinstance(x,dict) for x in self.channels[-1].calls),1)

    def test_continue_requires_post_stop_feedback(self):
        c=self.ready();c.request_stop('松开',recoverable=True)
        with self.assertRaises(ValueError):c.resume_control()
        self.assertFalse(c.snapshot()['unlocked'])

    def test_protective_stop_and_end_session_cannot_resume(self):
        for cause in ('probe','alarm','config','end'):
            c=self.ready()
            if cause=='end':c.request_stop('结束本轮')
            else:
                self.pause(c);f=frame(self.now[0])
                if cause=='probe':f['digital_inputs']=1
                if cause=='alarm':f['error']=True
                if cause=='config':f['tool_index']=2
                c.observe(f,1)
            self.assertFalse(c.snapshot()['resumable'],cause)
            with self.assertRaises(ValueError):c.resume_control()
            c.close();c.worker.join(1);self.now[0]=100

    def test_resume_cannot_reset_time_or_distance_limits(self):
        c=self.ready();self.pause(c);c.used_distance=5
        with self.assertRaises(ValueError):c.resume_control()
        c.used_distance=1;self.now[0]=c.expires+.01;c.observe(frame(self.now[0]),1)
        with self.assertRaises(ValueError):c.resume_control()
        self.assertFalse(c.snapshot()['unlocked'])

    def test_feedback_loss_while_paused_revokes_continue(self):
        c=self.ready();self.pause(c);self.now[0]+=.21
        self.assertTrue(wait(lambda:not c.snapshot()['resumable']))
        c.observe(frame(self.now[0]),1)
        self.assertFalse(c.snapshot()['safety']['can_resume'])

    def test_stopped_move_is_not_queued_again_after_continue(self):
        c=self.ready();p=c.preview('X',.5);c.execute(p['id'])
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        self.pause(c);before=sum(isinstance(x,dict) for x in self.channels[-1].calls)
        c.resume_control()
        self.assertEqual(sum(isinstance(x,dict) for x in self.channels[-1].calls),before)
        self.assertIsNone(c.plan);self.assertTrue(c.tasks.empty())
        with self.assertRaises(ValueError):c.execute(p['id'])

if __name__=='__main__':unittest.main()
