import sys,unittest,time,struct,socket,json,uuid,os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.dobot_feedback import DobotFeedback,decode_frame
from inspection_gui.probe_trigger import ProbeEdgeTracker,di1_state,TriggerJournal

def packet(inputs=0,outputs=1,x=100,tool=1,stamp=1):
    b=bytearray(1440);struct.pack_into('<H',b,0,1440);struct.pack_into('<Q',b,48,0x123456789abcdef)
    struct.pack_into('<Q',b,8,inputs);struct.pack_into('<Q',b,16,outputs);struct.pack_into('<Q',b,32,stamp)
    struct.pack_into('<6d',b,624,x,2,3,4,5,6);b[1013]=tool
    return b

def eventually(predicate):
    end=time.monotonic()+1
    while time.monotonic()<end:
        if predicate():return True
        time.sleep(.005)
    return False

class TriggerTests(unittest.TestCase):
    def test_uint64_offsets_and_di1_bit(self):
        f=decode_frame(packet((1<<63)|1,(1<<61)|1))
        self.assertTrue(di1_state(f));self.assertEqual(f['digital_outputs'],(1<<61)|1)
        self.assertFalse(di1_state(decode_frame(packet(2))))
        for f in [None,{},dict(digital_inputs=True),dict(digital_inputs=-1)]:self.assertIsNone(di1_state(f))

    def event(self):
        t=ProbeEdgeTracker();self.assertIsNone(t.feed(decode_frame(packet())))
        return t.feed(decode_frame(packet(1,x=321,stamp=9)))

    def test_only_rising_edges_use_same_packet_pose_and_metadata(self):
        t=ProbeEdgeTracker();self.assertIsNone(t.feed(decode_frame(packet(1))))
        self.assertIsNone(t.feed(decode_frame(packet(1))))
        self.assertIsNone(t.feed(decode_frame(packet(0))))
        e=t.feed(decode_frame(packet(1,x=654,stamp=9)))
        self.assertEqual(e['tcp_pose'][0],654);self.assertEqual(e['controller_timestamp_ms'],9)
        self.assertEqual(e['di_channel'],1);self.assertFalse(e['controller_latched']);self.assertFalse(e['hardware_executable'])
        self.assertIsNone(t.feed(decode_frame(packet(1,stamp=17))))
        self.assertIsNone(t.feed(decode_frame(packet(0,stamp=25))))
        self.assertIsNotNone(t.feed(decode_frame(packet(1,stamp=33))))

    def test_gap_config_change_and_controller_restart_do_not_invent_edge(self):
        for mode in ['gap','config','restart','unknown']:
            t=ProbeEdgeTracker();f=decode_frame(packet(stamp=500));t.feed(f)
            g=decode_frame(packet(1,stamp=508))
            if mode=='gap':g['received_monotonic']=f['received_monotonic']+.3
            if mode=='config':g['tool_index']=2
            if mode=='restart':g['controller_timestamp_ms']=1
            if mode=='unknown':t.feed({})
            self.assertIsNone(t.feed(g),mode)

    def test_receive_thread_preserves_pulse_between_gui_refreshes(self):
        b=DobotFeedback();client,server=socket.socketpair();server.sendall(packet(0))
        try:
            with patch('socket.create_connection',return_value=client),patch.object(b,'refresh_identity'):
                b.connect({'address':'127.0.0.1'})
            server.sendall(packet(1,x=765,stamp=9)+packet(0,x=999,stamp=17))
            self.assertTrue(eventually(lambda:b.snapshot()['pose'][0]==999))
            result=b.probe_events_since(0)
            self.assertEqual(len(result['events']),1);self.assertEqual(result['events'][0]['tcp_pose'][0],765)
            self.assertFalse(di1_state(b.snapshot()));self.assertEqual(result['missed_events'],0)
            self.assertEqual(b.probe_events_since(1)['events'],[])
            server.settimeout(.03)
            with self.assertRaises(socket.timeout):server.recv(1)  # no commands transmitted
        finally:b.disconnect();server.close()

    def test_queue_overflow_count_and_disconnect_baseline_reset(self):
        b=DobotFeedback();b.address='test'
        for i in range(515):
            b._observe_probe(decode_frame(packet(0,stamp=i*16+1)))
            b._observe_probe(decode_frame(packet(1,stamp=i*16+9)))
        result=b.probe_events_since(0)
        self.assertEqual(len(result['events']),512);self.assertEqual(result['missed_events'],3)
        b.disconnect();b._observe_probe(decode_frame(packet(1,stamp=9999)))
        self.assertEqual(b.probe_sequence,515)

    def test_atomic_journal_retry_export_and_corrupt_history(self):
        root=Path(os.environ.get('ROBOT_TEST_OUTPUT',Path.cwd()/'.test-output'))/'probe-trigger'/uuid.uuid4().hex
        root.mkdir(parents=True)
        if root.exists():
            j=TriggerJournal(Path(root)/'events');event=self.event()
            with patch('inspection_gui.probe_trigger.atomic_json',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):j.save(event)
            self.assertEqual(j.records,[])
            j.save(event);j.save(event);self.assertEqual(len(j.records),1)
            path=Path(root)/'export.json';j.export(path)
            data=json.loads(path.read_text(encoding='utf-8'));self.assertFalse(data['controller_latched'])
            (j.directory/'broken.json').write_text('{"event_type":"probe_trigger"}',encoding='utf-8')
            loaded=TriggerJournal(j.directory);self.assertEqual(len(loaded.records),1);self.assertEqual(len(loaded.load_errors),1)

if __name__=='__main__':unittest.main()
