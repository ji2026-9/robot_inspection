import copy
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.manual_control import ManualControl,ControlChannel
from inspection_gui.dobot_feedback import DobotFeedback


def wait(predicate):
    end=time.monotonic()+1
    while time.monotonic()<end:
        if predicate():return True
        time.sleep(.002)
    return False


def frame(now=100):
    return dict(pose=[100.,200.,300.,180.,0.,0.],joints=[0.]*6,received_monotonic=now,
        mode=5,running=False,error=False,enabled=True,digital_inputs=0,pose_stable=True,
        user_index=0,tool_index=1,user_offset=[0.]*6,tool_offset=[0.,0.,150.,0.,0.,0.])


class FakeChannel:
    def __init__(self,address):self.calls=[];self.closed=False
    def check(self):self.calls.append('RobotMode()')
    def move(self,plan):self.calls.append(copy.deepcopy(plan));return 'mock MovL'
    def jog(self,plan,cancelled):
        if cancelled():return None
        self.calls.append(copy.deepcopy(plan));return 'mock MoveJog'
    def stop(self):self.calls+=['MoveJog()','Stop()'];return ['MoveJog()','Stop()']
    def close(self):self.closed=True


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.now=[100.];self.channels=[];self.controls=[]
        self.folder=Path.cwd()/'.test-output'/'manual-control'/uuid.uuid4().hex

    def create(self):
        def factory(address):
            channel=FakeChannel(address);self.channels.append(channel);return channel
        control=ManualControl(self.folder,factory,lambda:self.now[0],wall_guard=None);control.observe(frame(),1)
        self.controls.append(control);return control

    def connected(self):
        control=self.create();control.connect('127.0.0.1',1)
        self.assertTrue(wait(lambda:control.snapshot()['connected']));return control

    def ready(self):
        control=self.connected();control.unlock(True,1);return control

    def tearDown(self):
        for c in self.controls:
            c.close()
            if c.worker:c.worker.join(1)

    def test_default_off_and_connect_only_queries(self):
        c=self.create();self.assertEqual(self.channels,[])
        self.assertFalse(c.snapshot()['unlocked'])
        with self.assertRaises(ValueError):c.preview('X',.1)
        c.connect('127.0.0.1',1);self.assertTrue(wait(lambda:c.snapshot()['connected']))
        self.assertEqual(self.channels[0].calls,['RobotMode()'])
        self.assertFalse(c.snapshot()['unlocked'])

    def test_unlock_requires_explicit_conditions_and_realistic_weight(self):
        c=self.connected()
        for confirmations,weight in [(False,1),(True,0),(True,6),(True,float('nan'))]:
            with self.assertRaises(ValueError):c.unlock(confirmations,weight)
        self.assertEqual(self.channels[0].calls,['RobotMode()'])

    def test_parameter_bounds_pose_and_one_move_only(self):
        c=self.ready()
        for axis,delta,speed in [('RX',.1,1),('X',2,1),('X',float('nan'),1),('Y',.1,0),('X',.1,6)]:
            with self.assertRaises(ValueError):c.preview(axis,delta,speed)
        p=c.preview('Y',-.1)
        self.assertEqual(p['target'],[100.,199.9,300.,180.,0.,0.])
        self.assertEqual(len(self.channels[0].calls),1)
        c.execute(p['id'])
        with self.assertRaises(ValueError):c.execute(p['id'])
        self.assertTrue(wait(lambda:any(isinstance(x,dict) for x in self.channels[0].calls)))
        self.assertEqual(sum(isinstance(x,dict) for x in self.channels[0].calls),1)

    def test_stale_preview_moved_pose_and_configuration_rejected(self):
        for cause in ('time','pose','config','generation'):
            c=self.ready();p=c.preview('X',.1)
            if cause=='time':self.now[0]+=11;c.observe(frame(self.now[0]),1)
            elif cause=='pose':
                f=frame();f['pose'][0]+=.1;c.observe(f,1)
            elif cause=='config':
                f=frame();f['tool_index']=2;c.observe(f,1)
            else:c.observe(frame(),2)
            with self.assertRaises(ValueError):c.execute(p['id'])
            self.assertFalse(any(isinstance(x,dict) for x in self.channels[-1].calls))
            c.close();c.worker.join(1);self.now[0]=100

    def test_di_alarm_configuration_and_external_control_stop_and_lock(self):
        for cause in ('di','alarm','generation','config','external','radius','mode'):
            c=self.ready();f=frame();gen=1
            if cause=='di':f['digital_inputs']=1
            if cause=='alarm':f['error']=True
            if cause=='generation':gen=2
            if cause=='config':f['tool_index']=2
            if cause=='radius':f['pose'][0]+=6
            if cause=='mode':f['mode']=7
            c.observe(f,gen,cause=='external')
            self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls),cause)
            self.assertFalse(c.snapshot()['unlocked']);self.assertIsNone(c.snapshot()['plan'])
            c.close();c.worker.join(1)

    def test_feedback_loss_and_hold_heartbeat_loss_stop(self):
        c=self.ready();p=c.preview('X',.1);c.execute(p['id'])
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        self.now[0]+=.21;c.observe(frame(self.now[0]),1)
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
        self.assertFalse(c.snapshot()['unlocked'])
        c.close();c.worker.join(1);self.now[0]=100
        c=self.ready();self.now[0]+=.21
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))

    def test_ack_is_not_target_reached_and_stop_does_not_resume(self):
        c=self.ready();p=c.preview('X',.5);c.execute(p['id'])
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        self.assertEqual(c.snapshot()['phase'],'moving')
        self.now[0]+=.02;f=frame(self.now[0]);f['pose']=p['target'][:];c.observe(f,1)
        self.assertEqual(c.snapshot()['phase'],'ready')
        c.request_stop('test');self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
        self.assertFalse(c.snapshot()['unlocked'])
        with self.assertRaises(ValueError):c.preview('X',.1)

    def test_cumulative_and_anchor_limit(self):
        c=self.ready();c.used_distance=5
        with self.assertRaises(ValueError):c.preview('X',.1)
        c.used_distance=0;c.anchor[0]=95
        with self.assertRaises(ValueError):c.preview('X',.1)

    def test_preview_target_bounds_and_requires_interactive(self):
        c=self.connected()
        with self.assertRaises(ValueError):c.preview_target([101.,200.,300.,180.,0.,0.])
        c.unlock(True,1)  # interactive=False
        with self.assertRaises(ValueError):c.preview_target([101.,200.,300.,180.,0.,0.])
        c.close();c.worker.join(1)
        c=self.connected();c.unlock(True,1,interactive=True)
        for target,speed in [([1,2,3,180,0],5),([101.,200.,300.,180.,0.,0.],0),
                             ([101.,200.,300.,180.,0.,0.],1.5),([1e9,0,0,0,0,0],5)]:
            with self.assertRaises(ValueError):c.preview_target(target,speed)
        p=c.preview_target([101.,200.,300.,180.,0.,0.],5)
        self.assertEqual(p['kind'],'target');self.assertEqual(p['target'],[101.,200.,300.,180.,0.,0.])
        self.assertEqual(p['distance'],1.0);self.assertEqual(p['speed'],5)

    def test_target_move_monitors_corridor_and_stops_on_deviation(self):
        c=self.connected();c.unlock(True,1,interactive=True)
        p=c.preview_target([105.,200.,300.,180.,0.,0.],5);c.execute(p['id'])
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        self.now[0]+=.02;f=frame(self.now[0]);f['pose'][1]+=.5;c.observe(f,1)
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
        self.assertFalse(c.snapshot()['unlocked'])
        self.assertEqual(sum(isinstance(x,dict) for x in self.channels[-1].calls),1)

    def test_target_arrival_moves_to_ready_without_holding(self):
        c=self.connected();c.unlock(True,1,interactive=True)
        p=c.preview_target([105.,200.,300.,180.,0.,0.],5);c.execute(p['id'])
        self.assertTrue(wait(lambda:c.accepted_at is not None))
        self.now[0]+=.02;f=frame(self.now[0]);f['pose']=p['target'][:]
        c.observe(f,1)
        self.assertEqual(c.snapshot()['phase'],'ready')
        self.assertTrue(c.snapshot()['unlocked'])

    def test_move_response_failure_not_retried(self):
        c=self.ready()
        def fail(plan):self.channels[-1].calls.append('failed move');raise TimeoutError('lost reply')
        self.channels[-1].move=fail;p=c.preview('Z',.1);c.execute(p['id'])
        self.assertTrue(wait(lambda:c.snapshot()['phase']=='fault'))
        self.assertEqual(self.channels[-1].calls.count('failed move'),1)
        self.assertIn('Stop()',self.channels[-1].calls)
        self.assertFalse(c.snapshot()['unlocked'])

    def test_disk_failure_blocks_movement_before_dispatch(self):
        c=self.ready();p=c.preview('X',.1)
        with patch('inspection_gui.manual_control.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):c.execute(p['id'])
        self.assertFalse(any(isinstance(x,dict) for x in self.channels[-1].calls))

    def test_close_cancels_authorization(self):
        c=self.ready();c.close();c.worker.join(1)
        self.assertFalse(c.snapshot()['connected']);self.assertFalse(c.snapshot()['unlocked'])
        self.assertTrue(self.channels[-1].closed);self.assertIn('Stop()',self.channels[-1].calls)

    def test_rejected_tcp_check_never_sends_move_or_stop(self):
        c=self.create()
        class Rejected(FakeChannel):
            def check(self):self.calls.append('RobotMode()');raise ValueError('not TCP')
        channel=Rejected('127.0.0.1');c.factory=lambda address:channel
        c.connect('127.0.0.1',1)
        self.assertTrue(wait(lambda:c.snapshot()['phase']=='fault'))
        self.assertEqual(channel.calls,['RobotMode()'])
        self.assertFalse(c.snapshot()['connected'])

    def test_release_probe_backs_off_after_verified_stop(self):
        c=self.ready()
        c.observe(dict(frame(self.now[0]),digital_inputs=1),1)
        self.assertTrue(wait(lambda:'Stop()' in self.channels[-1].calls))
        for _ in range(8):
            self.now[0]+=.1;c.observe(frame(self.now[0]),1)
        self.assertTrue(wait(lambda:c.snapshot()['safety']['stop_state']=='verified'))
        with self.assertRaises(ValueError):c.release_probe('X',1,10,2)
        self.assertTrue(c.release_probe('X',-1,1.5,2))
        self.assertEqual(c.snapshot()['phase'],'releasing')
        target=[98.5,200.,300.,180.,0.,0.]
        for _ in range(80):
            self.now[0]+=.05;c.observe(dict(frame(self.now[0]),pose=target[:]),1)
            if c.snapshot()['phase']=='locked':break
            time.sleep(.01)
        self.assertEqual(c.snapshot()['phase'],'locked')
        self.assertTrue(any(isinstance(x,dict) and x.get('kind')=='release' for x in self.channels[-1].calls))


class WireTests(unittest.TestCase):
    def test_feedback_receiver_forwards_every_frame_and_shuts_down_control(self):
        class Control:
            def __init__(self):self.frames=[];self.closed=False;self.finished=False
            def observe(self,f,g,external):self.frames.append((f['digital_inputs'],g,external))
            def close(self):self.closed=True
            def shutdown(self):self.finished=True
        backend=DobotFeedback();control=Control();backend.manual_control=control
        f=frame(time.monotonic());backend._observe_probe(f)
        f=dict(f,digital_inputs=1,received_monotonic=time.monotonic(),received_at=time.time())
        backend._observe_probe(f)
        self.assertEqual([x[0] for x in control.frames],[0,1])
        backend.disconnect();self.assertTrue(control.closed);self.assertTrue(control.finished)

    def test_single_connection_queries_move_and_stops(self):
        client,server=socket.socketpair();seen=[]
        def serve():
            with server:
                for _ in range(3):
                    command=server.recv(4096);seen.append(command)
                    payload=b'5' if command==b'RobotMode()' else b''
                    reply=b'0,{'+payload+b'},'+command+b';'
                    server.sendall(reply[:3]);server.sendall(reply[3:])
        thread=threading.Thread(target=serve);thread.start()
        with patch('socket.create_connection',return_value=client) as factory:
            c=ControlChannel('127.0.0.1');c.check()
            c.move(dict(target=[1.,2.,3.,180.,0.,0.],speed=1,distance=.1,user=0,tool=1))
            c.stop();c.close()
        thread.join(1);self.assertEqual(factory.call_count,1)
        self.assertEqual(seen[0],b'RobotMode()');self.assertEqual(seen[-1],b'Stop()')
        self.assertNotIn(b'MoveJog()',seen)
        self.assertIn(b'a=1,speed=1,cp=0',seen[1]);self.assertNotIn(b'Enable',b''.join(seen))

    def test_control_mode_and_occupied_plaintext_are_failures(self):
        for message in (b'Control Mode Is Not Tcp\t',b'Connection refused, IP:Port has been occupied'):
            client,server=socket.socketpair()
            def serve():
                with server:server.recv(4096);server.sendall(message)
            t=threading.Thread(target=serve);t.start()
            with patch('socket.create_connection',return_value=client):
                c=ControlChannel('127.0.0.1')
                with self.assertRaises(ValueError):c.check()
                c.close()
            t.join(1)


if __name__=='__main__':unittest.main()
