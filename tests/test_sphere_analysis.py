import sys,unittest,uuid,time,copy,os
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.sphere_analysis import analyze_contacts,ContactSession,validate_reference,load_reference,ENGRAVED_REFERENCE

def record(point,angle=0):
    return dict(id=uuid.uuid4().hex,name='test',recorded_at=datetime.now(timezone.utc).isoformat(),
        feedback_received_at=time.time(),joints_deg=[0.]*6,tcp_pose=list(map(float,point))+[0.,0.,float(angle)],
        user_index=0,tool_index=1,tool_offset=[0.,0.,150.,0.,0.,0.],user_offset=[0.]*6,
        source='controller_feedback',units=dict(position='mm',angle='deg'),event_type='probe_trigger',
        controller_address='isolated',archived=False)

def sphere(n=30,radius=26.,centre=(100.,200.,300.)):
    z=np.linspace(-.95,.95,n);az=np.arange(n)*np.pi*(3-np.sqrt(5))
    pts=np.c_[np.sqrt(1-z*z)*np.cos(az),np.sqrt(1-z*z)*np.sin(az),z]*radius+centre
    return [record(p) for p in pts]

class SphereAnalysisTests(unittest.TestCase):
    def test_sphere_combined_radius_and_translation_without_precision_claim(self):
        rows=sphere();original=copy.deepcopy(rows)
        with patch('socket.create_connection',side_effect=AssertionError('network forbidden')):r=analyze_contacts(rows)
        np.testing.assert_allclose(r['fitted_centre_configured_tcp_mm'],[100,200,300],atol=1e-7)
        self.assertAlmostEqual(r['combined_radius_mm'],26,places=7)
        self.assertIsNone(r['reference_ball_diameter_mm']);self.assertIsNone(r['stylus_effective_radius_mm'])
        self.assertFalse(r['accuracy_verified']);self.assertFalse(r['tcp_calibrated']);self.assertEqual(rows,original)
        shifted=copy.deepcopy(rows)
        for row in shifted:row['tcp_pose'][:3]=[x+1000000 for x in row['tcp_pose'][:3]]
        self.assertAlmostEqual(analyze_contacts(shifted)['combined_radius_mm'],26,places=6)

    def test_degenerate_planar_and_narrow_cap_rejected(self):
        for rows in [[record([1,2,3]) for _ in range(12)],
            [record([np.cos(t)*25,np.sin(t)*25,5]) for t in np.linspace(0,6,15)]]:
            with self.assertRaises(ValueError):analyze_contacts(rows)
        rows=[]
        for i in range(20):
            theta=.01+.03*i/20;phi=i*2.4
            rows.append(record([25*np.sin(theta)*np.cos(phi),25*np.sin(theta)*np.sin(phi),25*np.cos(theta)]))
        with self.assertRaisesRegex(ValueError,'覆盖过窄'):analyze_contacts(rows)

    def test_count_and_configuration_and_orientation_checks(self):
        with self.assertRaises(ValueError):analyze_contacts(sphere(8))
        for change in ['orientation','tool','offset','user','address','duplicate','nan']:
            rows=sphere()
            if change=='orientation':rows[-1]['tcp_pose'][5]=1
            if change=='tool':rows[-1]['tool_index']=2
            if change=='offset':rows[-1]['tool_offset'][0]=1
            if change=='user':rows[-1]['user_index']=1
            if change=='address':rows[-1]['controller_address']='different'
            if change=='duplicate':rows[-1]['id']=rows[0]['id']
            if change=='nan':rows[-1]['tcp_pose'][0]=float('nan')
            with self.assertRaises(ValueError,msg=change):analyze_contacts(rows)

    def test_outliers_not_silently_deleted(self):
        rows=sphere();rows[-1]['tcp_pose'][2]+=4
        r=analyze_contacts(rows)
        self.assertEqual(r['sample_count'],30);self.assertGreater(r['max_abs_radial_residual_mm'],.5)
        self.assertTrue(any('较大' in w for w in r['warnings']))

    def test_repeatability_statistics_do_not_become_accuracy(self):
        rows=[record([100+x*.01,2,3]) for x in [-2,-1,0,1,2]]
        r=analyze_contacts(rows,'repeat')
        self.assertAlmostEqual(r['max_pair_distance_mm'],.04)
        self.assertAlmostEqual(r['axis_std_mm'][0],np.std([-.02,-.01,0,.01,.02],ddof=1))
        self.assertFalse(r['accuracy_verified']);self.assertNotIn('reference_ball_diameter_mm',r)
        with self.assertRaises(ValueError):analyze_contacts(rows[:4],'repeat')

    def test_sessions_baseline_dedupe_exclusion_and_recovery(self):
        root=Path(os.environ.get('ROBOT_TEST_OUTPUT',Path.cwd()/'.test-output'))/'sphere'/uuid.uuid4().hex
        old=record([0,0,0]);s=ContactSession.create(root,'sphere','test',[old['id']])
        self.assertFalse(s.append(old))
        for row in sphere():self.assertTrue(s.append(row))
        self.assertFalse(s.append(s.data['records'][0]))
        with self.assertRaises(ValueError):s.analyze()
        loaded=ContactSession.load(s.path);self.assertEqual(loaded.data['status'],'stopped')
        s.stop();r=s.analyze();self.assertEqual(r['sample_count'],30)
        identifier=s.data['records'][0]['id'];s.exclude(identifier);self.assertEqual(len(s.data['records']),30)
        self.assertEqual(s.analyze()['sample_count'],29);s.exclude(identifier);self.assertEqual(s.analyze()['sample_count'],30)
        self.assertFalse(s.data['hardware_executable'])

    def test_failed_save_retry_and_configuration_stop(self):
        root=Path(os.environ.get('ROBOT_TEST_OUTPUT',Path.cwd()/'.test-output'))/'sphere'/uuid.uuid4().hex
        s=ContactSession.create(root,'repeat','test',[]);row=record([0,0,0])
        with patch('inspection_gui.sphere_analysis.atomic_json',side_effect=OSError('disk')):
            with self.assertRaises(OSError):s.append(row)
        self.assertEqual(s.data['records'],[]);self.assertTrue(s.append(row))
        new=record([0,0,0]);new['tool_index']=2;self.assertFalse(s.append(new))
        self.assertEqual(s.data['status'],'stopped');self.assertEqual(len(s.data['records']),1)

    def test_known_reference_estimates_stylus_without_changing_raw_fit_or_flags(self):
        rows=sphere(radius=10.00025+1.5);original=copy.deepcopy(rows)
        r=analyze_contacts(rows,reference=ENGRAVED_REFERENCE)
        self.assertAlmostEqual(r['estimated_stylus_effective_radius_mm'],1.5,places=7)
        self.assertAlmostEqual(r['estimated_stylus_effective_diameter_mm'],3.,places=7)
        self.assertAlmostEqual(r['reference_ball_diameter_mm'],20.0005)
        self.assertAlmostEqual(r['combined_radius_mm'],11.50025,places=7)
        self.assertIsNone(r['stylus_effective_radius_mm']);self.assertFalse(r['calibration_verified'])
        self.assertFalse(r['reference_ball_metadata']['certificate_verified']);self.assertEqual(rows,original)

    def test_invalid_reference_or_bad_estimate_not_certified(self):
        for diameter in [True,0,-20,float('nan'),float('inf'),1001]:
            with self.assertRaises(ValueError):validate_reference({**ENGRAVED_REFERENCE,'diameter_mm':diameter})
        r=analyze_contacts(sphere(radius=9),reference=ENGRAVED_REFERENCE)
        self.assertEqual(r['estimation_status'],'blocked');self.assertIsNone(r['estimated_stylus_effective_radius_mm'])
        rows=sphere(radius=11.5);rows[-1]['tcp_pose'][2]+=4
        r=analyze_contacts(rows,reference=ENGRAVED_REFERENCE)
        self.assertEqual(r['estimation_status'],'blocked');self.assertIsNone(r['estimated_stylus_effective_radius_mm'])

    def test_reference_persisted_per_session_and_legacy_stays_unknown(self):
        root=Path(os.environ.get('ROBOT_TEST_OUTPUT',Path.cwd()/'.test-output'))/'reference'/uuid.uuid4().hex
        path=root/'reference_sphere.json';reference=load_reference(path)
        self.assertEqual(load_reference(path),reference)
        s=ContactSession.create(root/'sessions','sphere','reference test',[],reference=reference)
        reference['diameter_mm']=99
        loaded=ContactSession.load(s.path);self.assertEqual(loaded.data['reference_ball']['diameter_mm'],20.0005)
        self.assertIsNone(ContactSession.create(root/'sessions','sphere','legacy',[]).data['reference_ball'])
        self.assertFalse(validate_reference({**ENGRAVED_REFERENCE,'certificate_verified':True})['certificate_verified'])

if __name__=='__main__':unittest.main()
