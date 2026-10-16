import copy
import unittest
import test_manual_control as helpers
from test_manual_control import frame, wait


class SafetyTests(unittest.TestCase):
    setUp=helpers.ManualTests.setUp
    tearDown=helpers.ManualTests.tearDown
    create=helpers.ManualTests.create
    connected=helpers.ManualTests.connected
    ready=helpers.ManualTests.ready

    def stopped(self):
        c=self.ready();c.request_stop('DI_1触发')
        self.assertTrue(wait(lambda:c.snapshot()['safety']['stop_state']=='acknowledged'))
        return c

    def stable_samples(self,c,di=0):
        for _ in range(9):
            self.now[0]+=.05
            f=frame(self.now[0]);f['digital_inputs']=di;c.observe(f,1)

    def test_ack_requires_post_ack_frames_and_manual_reset(self):
        c=self.stopped()
        self.assertFalse(c.snapshot()['can_unlock'])
        with self.assertRaises(ValueError):c.reset_safety()
        c.observe(frame(),1)  # Old frame cannot establish a stop.
        self.assertEqual(c.snapshot()['safety']['stop_state'],'acknowledged')
        self.stable_samples(c)
        self.assertEqual(c.snapshot()['phase'],'latched')
        self.assertFalse(c.snapshot()['unlocked'])
        with self.assertRaises(ValueError):c.unlock(True,1)
        calls=copy.deepcopy(self.channels[-1].calls)
        c.reset_safety()
        self.assertEqual(self.channels[-1].calls,calls)
        self.assertEqual(c.snapshot()['phase'],'locked')
        self.assertFalse(c.snapshot()['unlocked'])

    def test_held_probe_blocks_reset_even_after_pose_stability(self):
        c=self.stopped();self.stable_samples(c,1)
        self.assertEqual(c.snapshot()['phase'],'latched')
        self.assertFalse(c.snapshot()['safety']['can_reset'])
        with self.assertRaises(ValueError):c.reset_safety()

    def test_no_feedback_or_drifting_feedback_never_claims_stop(self):
        c=self.stopped();self.now[0]+=2.1
        self.assertTrue(wait(lambda:c.snapshot()['safety']['stop_state']=='unconfirmed'))
        self.assertFalse(c.snapshot()['safety']['can_reset'])
        self.assertFalse(c.snapshot()['can_unlock'])

    def test_malformed_feedback_blocks_unlock_and_trips_authorization(self):
        for field,value in [('error',None),('running',None),('digital_inputs',True),
                            ('tool_offset',[float('nan')]*6),('pose',[0]*5),
                            ('received_monotonic',float('nan'))]:
            c=self.ready();f=frame();f[field]=value;c.observe(f,1)
            self.assertFalse(c.snapshot()['unlocked'],field)
            self.assertFalse(c.snapshot()['safety']['feedback_ok'],field)
            self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
            c.close();c.worker.join(1)

    def test_unexpected_direction_and_rotation_request_stop(self):
        for index,change in [(1,.3),(3,1),(0,-.3)]:
            c=self.ready();p=c.preview('X',.5);c.execute(p['id'])
            self.assertTrue(wait(lambda:c.accepted_at is not None))
            self.now[0]+=.02;f=frame(self.now[0]);f['pose'][index]+=change;c.observe(f,1)
            self.assertFalse(c.snapshot()['unlocked'])
            self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
            c.close();c.worker.join(1);self.now[0]=100

    def test_snapshot_stale_feedback_disables_unlock(self):
        c=self.connected();self.assertTrue(c.snapshot()['can_unlock'])
        self.now[0]+=.16
        self.assertFalse(c.snapshot()['can_unlock'])
        with self.assertRaises(ValueError):c.unlock(True,1)

    def test_motion_after_verified_stop_invalidates_reset(self):
        c=self.stopped();self.stable_samples(c)
        self.assertTrue(c.snapshot()['safety']['can_reset'])
        self.now[0]+=.02;f=frame(self.now[0]);f['pose'][0]+=.1;c.observe(f,1)
        self.assertEqual(c.snapshot()['safety']['stop_state'],'unconfirmed')
        with self.assertRaises(ValueError):c.reset_safety()


if __name__=='__main__':unittest.main()
