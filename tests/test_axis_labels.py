"""Coordinate letters share the exact drawn 3D axis endpoints."""
import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui import simulation_scene3d as scene

class AxisLabelTests(unittest.TestCase):
    def test_xyz_labels_follow_rotated_tool_axes(self):
        state=SimpleNamespace(axis_labels=[])
        rotation=np.array([[0,-1,0],[1,0,0],[0,0,1]],float)
        with patch.object(scene,'gl',MagicMock()) as gl:
            scene.Scene3D._draw_axes(state,[100,200,300],rotation,65,'TCP实时')
            axes=state.axis_labels[0]
            self.assertTrue(np.allclose(axes['endpoints'],[[100,265,300],[35,200,300],[100,200,365]]))
            drawn=[call.args[0] for call in gl.glVertex3fv.call_args_list]
            for i in range(3):self.assertTrue(np.allclose(drawn[2*i+1],axes['endpoints'][i]))
            self.assertEqual(axes['label'],'TCP实时')

    def test_base_and_virtual_axes_have_distinct_origin_names(self):
        state=SimpleNamespace(axis_labels=[])
        with patch.object(scene,'gl',MagicMock()):
            scene.Scene3D._draw_axes(state,[0,0,0],np.eye(3),150,'底座B')
            scene.Scene3D._draw_axes(state,[10,20,30],np.eye(3),55,'TCP虚拟')
        self.assertEqual([a['label'] for a in state.axis_labels],['底座B','TCP虚拟'])
        self.assertTrue(np.allclose(state.axis_labels[0]['endpoints'][0],[150,0,0]))

    def test_projection_hides_points_behind_camera(self):
        state=SimpleNamespace(view=np.eye(4),width=lambda:800,height=lambda:600)
        self.assertIsNone(scene.Scene3D._project_axis_label(state,[0,0,100]))
        center=scene.Scene3D._project_axis_label(state,[0,0,-100])
        self.assertAlmostEqual(center.x(),400);self.assertAlmostEqual(center.y(),300)

if __name__=='__main__':unittest.main(verbosity=2)
