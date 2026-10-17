import copy,socket,threading,unittest
from unittest.mock import patch
import test_manual_control as helpers
from test_manual_control import frame,wait
from inspection_gui.manual_control import ControlChannel


class ContinuousJogTests(unittest.TestCase):
    setUp=helpers.ManualTests.setUp
    tearDown=helpers.ManualTests.tearDown
    create=helpers.ManualTests.create
    connected=helpers.ManualTests.connected

    def ready(self):
        c=self.connected();c.unlock(True,1,interactive=True);return c

    def release(self,c):
        c.request_stop('松开方向',recoverable=True,auto_rearm=True)
        self.assertTrue(wait(lambda:c.snapshot()['safety']['stop_state']=='acknowledged'))
        for _ in range(10):
            self.now[0]+=.05;c.observe(frame(self.now[0]),1)

    def test_hold_uses_one_start_and_release_rearms_without_moving(self):
        c=self.ready();c.start_jog('X',1)
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        for i in range(1,10):
            self.now[0]+=.05;c.maintain_hold();f=frame(self.now[0])
            f.update(mode=8,running=True,pose_stable=False);f['pose'][0]+=i*2;c.observe(f,1)
        self.assertEqual(c.snapshot()['phase'],'moving')
        self.assertEqual(sum(isinstance(x,dict) for x in self.channels[-1].calls),1)
        self.release(c)
        self.assertEqual(c.snapshot()['phase'],'ready');self.assertIsNone(c.plan)
        calls=copy.deepcopy(self.channels[-1].calls);self.assertTrue(c.tasks.empty())
        self.assertEqual(self.channels[-1].calls,calls)
        c.start_jog('Y',-1,2)
        self.assertTrue(wait(lambda:sum(isinstance(x,dict) for x in self.channels[-1].calls)==2))

    def test_repeated_taps_need_no_new_unlock_and_can_exceed_old_total_5mm(self):
        c=self.ready()
        for _ in range(3):
            c.start_jog('X',1);self.assertTrue(wait(lambda:c.accepted_at is not None))
            self.release(c);self.assertTrue(c.snapshot()['unlocked'])
        c.used_distance=20
        p=c.preview('Y',1);self.assertEqual(p['distance'],1)
        self.assertEqual(sum(isinstance(x,dict) for x in self.channels[-1].calls),3)

    def test_new_direction_during_motion_or_stop_is_rejected_without_queue(self):
        c=self.ready();c.start_jog('X',1)
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        with self.assertRaises(ValueError):c.start_jog('Y',1)
        c.request_stop('release',recoverable=True,auto_rearm=True)
        with self.assertRaises(ValueError):c.start_jog('Z',1)
        self.assertEqual(sum(isinstance(x,dict) for x in self.channels[-1].calls),1)

    def test_probe_during_release_verification_blocks_automatic_rearm(self):
        c=self.ready();c.start_jog('X',1)
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        c.request_stop('release',recoverable=True,auto_rearm=True)
        self.assertTrue(wait(lambda:c.snapshot()['safety']['stop_state']=='acknowledged'))
        self.now[0]+=.02;f=frame(self.now[0]);f['digital_inputs']=1;c.observe(f,1)
        for _ in range(10):self.now[0]+=.05;c.observe(frame(self.now[0]),1)
        self.assertFalse(c.snapshot()['unlocked']);self.assertFalse(c.snapshot()['resumable'])
        with self.assertRaises(ValueError):c.start_jog('X',1)

    def test_focus_loss_degrades_auto_rearm_to_manual_continue(self):
        c=self.ready();c.start_jog('X',1);self.assertTrue(wait(lambda:c.accepted_at is not None))
        c.request_stop('release',recoverable=True,auto_rearm=True)
        c.request_stop('window hidden',recoverable=True)
        self.assertFalse(c.auto_rearm)
        self.assertFalse(c.snapshot()['unlocked'])

    def test_jog_lateral_deviation_and_heartbeat_still_stop(self):
        for cause in ('deviation','heartbeat'):
            c=self.ready();c.start_jog('X',1);self.assertTrue(wait(lambda:c.accepted_at is not None))
            if cause=='deviation':
                self.now[0]+=.05;f=frame(self.now[0]);f.update(mode=8,running=True,pose_stable=False)
                f['pose'][1]+=.3;c.observe(f,1)
            else:self.now[0]+=.21
            self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
            self.assertFalse(c.snapshot()['unlocked']);self.assertFalse(c.auto_rearm)
            c.close();c.worker.join(1);self.now[0]=100

    def test_hold_timeout_requests_stop(self):
        c=self.ready();c.start_jog('X',1);self.assertTrue(wait(lambda:c.accepted_at is not None))
        self.now[0]+=30.01;c.maintain_hold();c.observe(frame(self.now[0]),1)
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
        self.assertFalse(c.snapshot()['unlocked'])


class JogWireTests(unittest.TestCase):
    def test_native_jog_speed_ratio_and_stop_commands_share_one_connection(self):
        client,server=socket.socketpair();seen=[]
        def serve():
            with server:
                for _ in range(4):
                    command=server.recv(4096);seen.append(command)
                    server.sendall(b'0,{},'+command+b';')
        thread=threading.Thread(target=serve);thread.start()
        with patch('socket.create_connection',return_value=client):
            c=ControlChannel('127.0.0.1')
            c.jog(dict(axis='Z',sign=-1,ratio=1,user=0,tool=1),lambda:False)
            c.stop();c.close()
        thread.join(1)
        self.assertEqual(seen,[b'SpeedFactor(1)',b'MoveJog(Z-,coordtype=1,user=0,tool=1)',b'Stop()',b'MoveJog()'])

    def test_release_while_speed_reply_pending_cancels_start(self):
        client,server=socket.socketpair();released=threading.Event();seen=[]
        def serve():
            with server:
                command=server.recv(4096);seen.append(command);released.set()
                server.sendall(b'0,{},'+command+b';')
                self.assertEqual(server.recv(4096),b'')
        t=threading.Thread(target=serve);t.start()
        with patch('socket.create_connection',return_value=client):
            c=ControlChannel('127.0.0.1')
            result=c.jog(dict(axis='X',sign=1,ratio=1,user=0,tool=1),released.is_set)
            c.close()
        t.join(1);self.assertIsNone(result);self.assertEqual(seen,[b'SpeedFactor(1)'])

if __name__=='__main__':unittest.main()
