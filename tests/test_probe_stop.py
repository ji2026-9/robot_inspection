import copy
import json
import socket
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.probe_stop import ProbeStopMonitor, PoseStabilityTracker, send_stop_only, run_simulation, STOP_COMMANDS
from inspection_gui.dobot_feedback import DobotFeedback


def frame():
    return dict(digital_inputs=0,received_monotonic=time.monotonic(),mode=5,running=False,error=False,
        joint_speeds=[0.]*6,tcp_speeds=[0.]*6,user_index=0,tool_index=1,
        user_offset=[0.]*6,tool_offset=[0.]*6,controller_timestamp_ms=1,pose_stable=True)


def wait_for(predicate):
    end=time.monotonic()+1
    while time.monotonic()<end:
        if predicate():return True
        time.sleep(.002)
    return False


class StopTests(unittest.TestCase):
    def test_equal_host_ticks_do_not_erase_valid_distinct_frame_sequence(self):
        for static_only in (False, True):
            now=[100.0]
            m=ProbeStopMonitor(sender=lambda _:[dict(accepted=True),dict(accepted=True)],clock=lambda:now[0])
            f=frame();f['received_monotonic']=now[0]
            path=Path.cwd()/'.test-output'/'probe-stop'/uuid.uuid4().hex/'audit.json'
            m.arm(f,'127.0.0.1',0,live=True,confirmations=True,audit_path=path,static_only=static_only)
            m.observe(dict(f,digital_inputs=1),0)
            self.assertTrue(wait_for(lambda:m.snapshot()['state']=='acknowledged'))
            for i in range(1,4):
                now[0]=100+i*.016
                sample=dict(f,received_monotonic=now[0])
                m.observe(sample,0)
                m.observe(sample,0)
                if i<3:self.assertEqual(m.snapshot()['state'],'acknowledged')
            self.assertEqual(m.snapshot()['state'],'confirmed')
            self.assertEqual(m.snapshot()['confirmed_stopped'],not static_only)

    def test_equal_tick_motion_still_breaks_confirmation_sequence(self):
        now=[100.0]
        m=ProbeStopMonitor(sender=lambda _:[dict(accepted=True),dict(accepted=True)],clock=lambda:now[0])
        f=frame();f['received_monotonic']=now[0]
        path=Path.cwd()/'.test-output'/'probe-stop'/uuid.uuid4().hex/'audit.json'
        m.arm(f,'127.0.0.1',0,live=True,confirmations=True,audit_path=path,static_only=True)
        m.observe(dict(f,digital_inputs=1),0)
        self.assertTrue(wait_for(lambda:m.snapshot()['state']=='acknowledged'))
        now[0]+=.016;f['received_monotonic']=now[0];m.observe(f,0)
        m.observe(dict(f,pose_stable=False),0)
        self.assertEqual(m.quiet_frames,0)
        for _ in range(2):
            now[0]+=.016;f['received_monotonic']=now[0];m.observe(f,0)
        self.assertEqual(m.snapshot()['state'],'acknowledged')
        now[0]+=.016;f['received_monotonic']=now[0];m.observe(f,0)
        self.assertEqual(m.snapshot()['state'],'confirmed')

    def test_static_window_tolerates_velocity_noise_but_rejects_drift_and_gaps(self):
        for problem in (None,'drift','gap','mode','config','stamp','nonfinite'):
            tracker=PoseStabilityTracker();start=time.monotonic();stable=False
            for i in range(26):
                f=frame();f.update(pose=[0.]*6,joints=[0.]*6,received_monotonic=start+i*.02,
                    controller_timestamp_ms=i*20, tcp_speeds=[1.3]*6)
                if problem=='drift':f['pose'][0]=i*.002
                if problem=='gap' and i>=20:f['received_monotonic']+=.2
                if problem=='mode' and i>=20:f['mode']=8
                if problem=='config' and i>=20:f['tool_index']=2
                if problem=='stamp' and i>=20:f['controller_timestamp_ms']-=400
                if problem=='nonfinite':f['pose'][0]=float('nan')
                stable=tracker.feed(f)
            self.assertEqual(stable,problem is None,problem)

    def test_static_arm_requires_window_evidence_and_motion_mode_retains_velocity_check(self):
        f=frame();f['pose_stable']=False
        with self.assertRaises(ValueError):ProbeStopMonitor().arm(f,'127.0.0.1',0,static_only=True)
        f['pose_stable']=True;f['tcp_speeds']=[1.3]*6
        with self.assertRaises(ValueError):ProbeStopMonitor().arm(f,'127.0.0.1',0)
        m=ProbeStopMonitor();m.arm(f,'127.0.0.1',0,static_only=True);m.disarm()

    def test_static_mode_does_not_certify_motion_stopping(self):
        m=ProbeStopMonitor(sender=lambda _:[dict(accepted=True),dict(accepted=True)])
        path=Path.cwd()/'.test-output'/'probe-stop'/uuid.uuid4().hex/'audit.json'
        m.arm(frame(),'127.0.0.1',0,live=True,confirmations=True,audit_path=path,static_only=True)
        f=frame();f['digital_inputs']=1;m.observe(f,0)
        self.assertTrue(wait_for(lambda:m.snapshot()['state']=='acknowledged'))
        for _ in range(3):time.sleep(.02);m.observe(frame(),0)
        r=m.snapshot();self.assertEqual(r['state'],'confirmed');self.assertTrue(r['static_only'])
        self.assertIn('未验证运动停止能力',r['reason']);self.assertFalse(r['safety_verified'])
        self.assertTrue(r['communication_verified']);self.assertFalse(r['confirmed_stopped'])

    def test_static_mode_motion_requests_stop_without_touch(self):
        called=[]
        m=ProbeStopMonitor(sender=lambda address:called.append(address) or [dict(accepted=False)])
        path=Path.cwd()/'.test-output'/'probe-stop'/uuid.uuid4().hex/'audit.json'
        m.arm(frame(),'127.0.0.1',0,live=True,confirmations=True,audit_path=path,static_only=True)
        f=frame();f['mode']=8;f['joint_speeds'][0]=1;m.observe(f,0)
        self.assertTrue(wait_for(lambda:len(called)==1))
        self.assertNotEqual(m.snapshot()['state'],'armed')

    def live(self, sender):
        m=ProbeStopMonitor(sender=sender)
        path=Path.cwd()/'.test-output'/'probe-stop'/uuid.uuid4().hex/'audit.json'
        m.arm(frame(),'127.0.0.1',2,live=True,confirmations=True,audit_path=path)
        return m,path

    def test_off_and_simulation_never_transmit(self):
        with patch('socket.create_connection',side_effect=AssertionError('network')):
            m=ProbeStopMonitor();f=frame();f['digital_inputs']=1;m.observe(f,0)
            self.assertEqual(m.snapshot()['state'],'off')
            r=run_simulation();self.assertEqual(r['state'],'simulated')
            self.assertFalse(r['live']);self.assertFalse(r['confirmed_stopped'])

    def test_arm_rejects_stale_high_motion_alarm_unconfirmed_and_unlogged(self):
        for key,value in [('digital_inputs',1),('mode',8),('error',True),
                          ('received_monotonic',time.monotonic()-1),('tcp_speeds',[1.]*6)]:
            f=frame();f[key]=value
            with self.assertRaises(ValueError):ProbeStopMonitor().arm(f,'127.0.0.1',0)
        for kw in [dict(),dict(confirmations=True),dict(audit_path=Path('unused.json'))]:
            with self.assertRaises(ValueError):ProbeStopMonitor().arm(frame(),'127.0.0.1',0,live=True,**kw)
        with patch('inspection_gui.probe_stop.atomic_json',side_effect=OSError('disk')):
            with self.assertRaises(ValueError):self.live(lambda _:None)

    def test_single_trigger_ack_not_stopped_then_three_new_stationary_frames(self):
        calls=[]
        def sender(address):
            calls.append(address)
            return [dict(command=c,accepted=True) for c in STOP_COMMANDS]
        m,path=self.live(sender)
        f=frame();f['digital_inputs']=1;m.observe(f,2)
        self.assertTrue(wait_for(lambda:m.snapshot()['state']=='acknowledged'))
        self.assertFalse(m.snapshot()['confirmed_stopped'])
        old=copy.deepcopy(f)
        for _ in range(4):m.observe(old,2)
        self.assertFalse(m.snapshot()['confirmed_stopped'])
        for i in range(3):
            time.sleep(.02);f=frame();f['digital_inputs']=1;m.observe(f,2)
        self.assertEqual(m.snapshot()['state'],'confirmed')
        self.assertEqual(calls,['127.0.0.1'])
        m.observe(f,2);self.assertEqual(len(calls),1)
        self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['confirmed_stopped'])
        with self.assertRaises(ValueError):m.arm(f,'127.0.0.1',2)

    def test_loss_generation_config_gap_and_disarm_each_request_once(self):
        for cause in ('loss','generation','config','gap','disarm','age','controller_restart'):
            calls=[]
            def sender(address):calls.append(address);return [dict(accepted=False)]
            m,_=self.live(sender)
            f=frame()
            if cause=='loss':m.disconnected()
            elif cause=='disarm':m.disarm()
            else:
                if cause=='config':f['tool_index']=2
                if cause=='gap':f['received_monotonic']+=1
                if cause=='age':f['received_monotonic']-=1
                if cause=='controller_restart':f['controller_timestamp_ms']=0
                m.observe(f,3 if cause=='generation' else 2)
            self.assertTrue(wait_for(lambda:len(calls)==1),cause)
            self.assertTrue(wait_for(lambda:m.snapshot()['state']=='failed'))
            m.disconnected();m.observe(frame(),4);self.assertEqual(len(calls),1)

    def test_stale_watchdog_and_expiry(self):
        now=[time.monotonic()]
        for reason in ('stale','expiry'):
            m=ProbeStopMonitor(clock=lambda:now[0]);f=frame();f['received_monotonic']=now[0]
            m.arm(f,'127.0.0.1',0)
            if reason=='stale':now[0]+=.3
            else:m.expires=now[0]
            m.check_time();self.assertEqual(m.snapshot()['state'],'simulated')

    def test_ack_timeout_and_motion_not_confirmed(self):
        m,_=self.live(lambda _:[dict(accepted=True),dict(accepted=True)])
        f=frame();f['digital_inputs']=1;m.observe(f,2)
        self.assertTrue(wait_for(lambda:m.snapshot()['state']=='acknowledged'))
        for i in range(3):
            f=frame();f['tcp_speeds'][0]=.2;m.observe(f,2)
        self.assertFalse(m.snapshot()['confirmed_stopped'])
        m.verify_deadline=0;m.check_time();self.assertEqual(m.snapshot()['state'],'failed')

    def test_pending_timeout_cannot_be_overwritten_by_late_ack(self):
        gate=threading.Event()
        def sender(_):gate.wait(1);return [dict(accepted=True),dict(accepted=True)]
        m,_=self.live(sender);f=frame();f['digital_inputs']=1;m.observe(f,2)
        m.send_deadline=0;m.check_time();gate.set();time.sleep(.02)
        self.assertEqual(m.snapshot()['state'],'failed')

    def test_wire_whitelist_fragmented_ack_and_reject(self):
        for bad in (False,True):
            peers=[];threads=[]
            def factory(*args,**kwargs):
                client,server=socket.socketpair();index=len(peers);peers.append(b'')
                def serve():
                    with server:
                        for _ in range(2):
                            data=server.recv(1024)
                            if not data:return
                            peers[index]+=data
                            reply=(b'-1' if bad else b'0')+b',{},'+data+b';'
                            server.sendall(reply[:3]);server.sendall(reply[3:])
                t=threading.Thread(target=serve);threads.append(t);t.start();return client
            with patch('socket.create_connection',side_effect=factory):result=send_stop_only('127.0.0.1')
            for t in threads:t.join(1)
            self.assertEqual(peers,[b'MoveJog()Stop()'])
            self.assertTrue(all(r['accepted']==(not bad) for r in result))

    def test_plain_mode_error_without_semicolon_is_not_a_timeout(self):
        peers=[];threads=[]
        def factory(*args,**kwargs):
            client,server=socket.socketpair()
            def serve():
                with server:
                    peers.append(server.recv(1024))
                    server.sendall(b'Control Mode Is ')
                    time.sleep(.005)
                    server.sendall(b'Not Tcp\t')
            t=threading.Thread(target=serve);threads.append(t);t.start();return client
        with patch('socket.create_connection',side_effect=factory):result=send_stop_only('127.0.0.1')
        for t in threads:t.join(1)
        self.assertEqual(peers,[b'MoveJog()'])
        self.assertTrue(all(r['control_mode_blocked'] for r in result))
        self.assertEqual(result[0]['phase'],'receive');self.assertTrue(result[0]['sent'])
        self.assertIn('Control Mode Is Not Tcp',result[0]['raw_reply'])
        self.assertFalse(result[1]['sent']);self.assertNotIn('timed out',result[0]['error'])

    def test_connect_timeout_is_identified_before_any_transmission(self):
        with patch('socket.create_connection',side_effect=socket.timeout('connect timeout')):
            result=send_stop_only('127.0.0.1')
        self.assertEqual(result[0]['phase'],'connect')
        self.assertTrue(all(not r['sent'] for r in result))

    def test_occupied_connection_is_explicit_and_never_retried(self):
        client,server=socket.socketpair()
        def serve():
            with server:
                server.recv(1024)
                server.sendall(b'Connection refused, IP:Port has been occupied')
        thread=threading.Thread(target=serve);thread.start()
        with patch('socket.create_connection',return_value=client) as factory:
            result=send_stop_only('127.0.0.1')
        thread.join(1)
        self.assertEqual(factory.call_count,1)
        self.assertIn('occupied',result[0]['raw_reply'])
        self.assertFalse(result[1]['sent'])
        self.assertFalse(any(r['accepted'] for r in result))

    def test_feedback_monitor_default_off_and_reconnect_not_rearmed(self):
        b=DobotFeedback();self.assertEqual(b.stop_monitor.snapshot()['state'],'off')
        f=frame();b.stop_monitor.arm(f,'127.0.0.1',b.generation)
        b.disconnect();self.assertEqual(b.stop_monitor.snapshot()['state'],'simulated')
        b._observe_probe(dict(f,received_at=time.time(),joints=[0.]*6,pose=[0.]*6))
        self.assertNotEqual(b.stop_monitor.snapshot()['state'],'armed')


if __name__=='__main__':unittest.main()
