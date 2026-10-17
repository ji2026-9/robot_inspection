import math,unittest
import numpy as np
from inspection_gui.manual_preview import fit_preview_view
from inspection_gui.offline_planning import robot_frames

class PreviewCameraTests(unittest.TestCase):
    def test_whole_arm_path_fits_short_and_narrow_viewports(self):
        frames=[dict(joints=np.deg2rad(q),tip=np.asarray(t)) for q,t in [
            ([176,-21,-76,8,92,-106],[-591,130,241]),
            ([174,-28,-70,8,92,-104],[-650,130,241])]]
        for width,height in ((1000,220),(600,300),(300,500)):
            center,distance=fit_preview_view(frames,width,height)
            az,el=np.deg2rad([-58,29]);z=np.array([math.cos(az)*math.cos(el),math.sin(az)*math.cos(el),math.sin(el)])
            x=np.cross([0,0,1],z);x/=np.linalg.norm(x);y=np.cross(z,x)
            for f in frames:
                for point in [t[:3,3] for t in robot_frames(f['joints'],(0,0,0)).values()]+[f['tip']]:
                    v=(point-center)@np.array([x,y,z]).T;depth=distance-v[2]
                    self.assertLess(abs(v[1])/(depth*math.tan(math.radians(37)/2)),1)
                    self.assertLess(abs(v[0])/(depth*math.tan(math.radians(37)/2)*width/height),1)

if __name__=='__main__':unittest.main()
