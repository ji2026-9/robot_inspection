import math,struct,unittest
from inspection_gui.dobot_feedback import decode_frame
from inspection_gui.manual_preview import estimate_timing

class FeedbackSpeedTests(unittest.TestCase):
    def packet(self,percent,ratio=0):
        data=bytearray(1440);struct.pack_into('<H',data,0,1440)
        struct.pack_into('<Q',data,48,0x123456789abcdef)
        struct.pack_into('<d',data,64,percent);data[1016]=ratio
        return data
    def test_actual_case_22_percent_with_velocity_ratio_zero(self):
        f=decode_frame(self.packet(22.,0))
        self.assertEqual(f['speed_percent'],22);self.assertEqual(f['velocity_ratio_raw'],0)
        self.assertAlmostEqual(estimate_timing(11,5,f['speed_percent'])['duration_seconds'],10)
    def test_byte_ratio_does_not_override_speed_scaling(self):
        self.assertEqual(decode_frame(self.packet(10.,80))['speed_percent'],10)
        self.assertEqual(decode_frame(self.packet(0.,80))['speed_percent'],0)
    def test_invalid_scaling_is_unknown_instead_of_false_zero(self):
        for v in (float('nan'),float('inf'),-1.,101.):
            with self.subTest(v=v):self.assertIsNone(decode_frame(self.packet(v))['speed_percent'])

if __name__=='__main__':unittest.main()
