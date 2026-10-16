import sys, unittest, copy
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.joint_preview import compile_joint_preview,tcp_matrix,pose_matrix


class JointPreviewTests(unittest.TestCase):
    def setUp(self):
        self.q=np.array([177.82,-24.7,-69.8,5.03,92.48,-105.24])
        self.offset=[-19.47,-45.07,152.68,12,-8,17]

    def path(self,qs):
        frames=[]
        for q in qs:
            t=tcp_matrix(np.deg2rad(q),pose_matrix(self.offset))
            frames.append(dict(tip=t[:3,3],rotation=t[:3,:3],stage='test'))
        return frames

    def test_full_pose_tool_rotation_continuity_and_no_network(self):
        frames=self.path([self.q+i*np.array([.2,-.1,.15,.1,.1,-.2]) for i in range(12)])
        original=copy.deepcopy(frames)
        with patch('socket.create_connection',side_effect=AssertionError('network forbidden')):
            solved,r=compile_joint_preview(frames,self.offset,self.q.tolist())
        self.assertTrue(r['complete']);self.assertEqual(len(solved),12)
        self.assertLess(r['max_joint_step_deg'],1)
        for f,target in zip(solved,original):
            actual=tcp_matrix(f['joints'],pose_matrix(self.offset))
            np.testing.assert_allclose(actual[:3,3],target['tip'],atol=.5)
            self.assertLess(Rotation.from_matrix(actual[:3,:3]@target['rotation'].T).magnitude(),np.deg2rad(.25))
        self.assertNotIn('joints',frames[0]);self.assertFalse(r['hardware_executable'])

    def test_unreachable_stops_without_fake_joint_samples(self):
        frames=self.path([self.q,self.q]);frames[1]['tip']=np.array([3000.,0,0])
        solved,r=compile_joint_preview(frames,self.offset,self.q.tolist())
        self.assertEqual(len(solved),1);self.assertFalse(r['complete'])
        self.assertEqual(r['failure']['frame_index'],1)

    def test_large_branch_step_is_not_animated(self):
        qs=[self.q,self.q+np.array([35,0,0,0,0,0])]
        solved,r=compile_joint_preview(self.path(qs),self.offset,self.q.tolist())
        self.assertEqual(len(solved),1);self.assertIn('12°',r['failure']['reason'])

    def test_cancelled_and_invalid_input(self):
        f=self.path([self.q])
        solved,r=compile_joint_preview(f,self.offset,self.q.tolist(),cancelled=lambda:True)
        self.assertEqual(solved,[]);self.assertTrue(r['cancelled'])
        for offset in [[0]*5,[float('nan')]*6]:
            with self.assertRaises(ValueError):compile_joint_preview(f,offset)
        f[0]['rotation']=np.diag([1,1,-1])
        with self.assertRaises(ValueError):compile_joint_preview(f,self.offset)
        with self.assertRaises(ValueError):compile_joint_preview(self.path([self.q]),self.offset,[400]*6)

    def test_static_singularity_is_flagged(self):
        q=[0,0,0,0,0,0]
        solved,r=compile_joint_preview(self.path([q]),self.offset,q)
        self.assertEqual(len(solved),1);self.assertEqual(r['near_singular_frames'],[0])

if __name__=='__main__':unittest.main()
