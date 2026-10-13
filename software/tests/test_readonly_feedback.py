import sys,unittest,struct,time,socket,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from inspection_gui.dobot_feedback import decode_frame,receive_frame,DobotFeedback

def packet():
    data=bytearray(1440);struct.pack_into('<H',data,0,1440);struct.pack_into('<Q',data,48,0x123456789abcdef)
    struct.pack_into('<6d',data,432,1,2,3,4,5,6);struct.pack_into('<6d',data,624,100,200,300,10,20,30)
    return data

class FeedbackTests(unittest.TestCase):
    def test_decode_rejects_bad_frames(self):
        data=packet();self.assertEqual(decode_frame(data)['joints'],[1,2,3,4,5,6])
        for field,fmt,value in ((0,'<H',1441),(48,'<Q',0),(432,'<d',float('nan'))):
            bad=packet();struct.pack_into(fmt,bad,field,value)
            with self.assertRaises(ValueError):decode_frame(bad)
    def test_partial_tcp_reads(self):
        data=packet()
        class Chunked:
            def __init__(self):self.remaining=bytes(data)
            def recv(self,count):
                out=self.remaining[:min(count,17)];self.remaining=self.remaining[len(out):];return out
        self.assertEqual(receive_frame(Chunked())['pose'],[100,200,300,10,20,30])
    def test_only_feedback_port_and_stale_snapshot(self):
        b=DobotFeedback()
        with self.assertRaises(ValueError):b.connect({'address':'127.0.0.1','port':29999})
        b.sock=object();b.latest=decode_frame(packet());snap=b.snapshot();snap['joints'][0]=123
        self.assertEqual(b.latest['joints'][0],1)
        b.latest['received_monotonic']=time.monotonic()-3;self.assertIsNone(b.snapshot())
    def test_cancel_during_initial_receive_cannot_reconnect(self):
        ready=threading.Event();release=threading.Event()
        class FakeSocket:
            def __init__(self):self.remaining=bytes(packet());self.closed=False
            def settimeout(self,_):pass
            def recv(self,count):ready.set();release.wait(2);out=self.remaining[:count];self.remaining=self.remaining[count:];return out
            def close(self):self.closed=True
        sock=FakeSocket();b=DobotFeedback();out=[]
        with patch('socket.create_connection',return_value=sock):
            thread=threading.Thread(target=lambda:out.append(b.connect({'address':'127.0.0.1','port':30004})))
            thread.start();self.assertTrue(ready.wait(2));b.disconnect();release.set();thread.join(2)
        self.assertEqual(out,[False]);self.assertTrue(sock.closed);self.assertIsNone(b.snapshot())

if __name__=='__main__':unittest.main(verbosity=2)
