import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import math, sys, time, unittest, uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from inspection_gui.contact_points import ContactStore, export_csv, make_point, new_session
from inspection_gui.hole_probe import (ProbeRunner, center_from_contacts, endpoint_xyz, pose_for,
                                       validate_hole, validate_params)
from test_manual_control import frame as feedback_frame


def hole(center=(100.,100.,50.), diameter=10.0, name='A1'):
    return {'id': uuid.uuid4().hex, 'name': name, 'pose': [*center,180.,0.,0.],
            'xyz': list(center), 'diameter_mm': diameter, 'note': ''}


def live_frame(pose=None, di=0):
    value = feedback_frame(time.monotonic())
    value['received_at'] = time.time()
    if pose is not None:
        value['pose'] = list(pose)
    value['digital_inputs'] = di
    return value


def params(holes, **overrides):
    values = dict(safe_z_mm=70., search_limit_mm=4., probe_speed_mm_s=2, travel_speed_mm_s=20,
                  retract_speed_mm_s=5, release_mm=1.5, release_speed_mm_s=2, payload_kg=1.0, holes=holes)
    values.update(overrides)
    return values


class HoleGeometryTests(unittest.TestCase):
    def test_search_limit_cannot_exceed_hole(self):
        with self.assertRaises(ValueError):
            validate_params(params([hole()], search_limit_mm=4.5), [hole()])
        accepted = validate_params(params([hole()]), [hole()])
        self.assertEqual(accepted['search_limit_mm'], 4.0)

    def test_safe_height_must_be_above_probe_z(self):
        with self.assertRaises(ValueError):
            validate_params(params([hole()], safe_z_mm=40.), [hole()])

    def test_center_uses_symmetric_contact_pairs(self):
        spec = validate_hole(hole())
        contacts = [
            {'axis':'X','sign':1,'xyz':[104.,100.,50.]},
            {'axis':'X','sign':-1,'xyz':[96.,100.,50.]},
            {'axis':'Y','sign':1,'xyz':[100.,104.,50.]},
            {'axis':'Y','sign':-1,'xyz':[100.,96.,50.]},
        ]
        result = center_from_contacts(spec, contacts)
        self.assertAlmostEqual(result['center'][0], 100.0)
        self.assertAlmostEqual(result['center'][1], 100.0)
        self.assertAlmostEqual(result['spans_mm']['x_mm'], 8.0)

    def test_endpoint_and_pose_keep_orientation(self):
        spec = validate_hole(hole())
        self.assertEqual(endpoint_xyz(spec, 'X', -1, 3.5), [96.5, 100., 50.])
        self.assertEqual(pose_for([1,2,3], [180.,0.,0.]), [1.,2.,3.,180.,0.,0.])


class ContactPointFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path.cwd()/'.test-output'/'contact-points'/uuid.uuid4().hex

    def test_point_and_library_roundtrip(self):
        point = make_point(live_frame(), name='接触点', hole_id='h1', direction='X+')
        store = ContactStore(self.folder)
        self.assertTrue(store.append(point))
        self.assertFalse(store.append(point))
        reloaded = ContactStore(self.folder)
        self.assertEqual(len(reloaded.points), 1)
        self.assertTrue(reloaded.update_note(point['id'], '右壁'))
        self.assertEqual(reloaded.points[0]['note'], '右壁')
        output = self.folder/'points.csv'
        export_csv(output, reloaded.points)
        self.assertIn('右壁', output.read_text(encoding='utf-8-sig'))

    def test_session_is_saved_with_points(self):
        point = make_point(live_frame())
        store = ContactStore(self.folder)
        session = new_session(params={'safe_z_mm':70})
        session['points'].append(point)
        path = store.save_session(session)
        self.assertTrue(path.is_file())
        self.assertIn(point['id'], path.read_text(encoding='utf-8'))


class FakeController:
    def __init__(self):
        self.phase = 'ready'; self.plan = None; self.pose = [90., 95., 70., 180., 0., 0.]
        self.target = None; self.di = 0; self.stop_state = 'none'; self.stop_reason = ''
        self.calls = []

    def snapshot(self):
        return {'connected': True, 'unlocked': True, 'phase': self.phase, 'plan': self.plan,
                'reason': '', 'safety': {'feedback_ok': True, 'wall_ok': True,
                'stop_state': self.stop_state, 'stop_reason': self.stop_reason,
                'can_resume': self.phase == 'latched' and self.stop_state == 'verified'}}

    def preview_target(self, target, speed):
        self.target = list(target); self.plan = {'id': uuid.uuid4().hex}; self.calls.append(('preview', list(target), speed))
        return dict(self.plan)

    def execute(self, plan_id):
        self.phase = 'moving'; self.calls.append(('execute', plan_id))

    def arrive(self):
        self.pose = list(self.target); self.phase = 'ready'; self.plan = None

    def request_stop(self, reason, **kwargs):
        self.phase = 'stopping'; self.stop_reason = reason; self.stop_state = 'requested'
        self.calls.append(('stop', reason))

    def stopped(self):
        self.phase = 'latched'; self.stop_state = 'verified'

    def release_probe(self, axis, sign, distance, speed):
        self.phase = 'locked'; self.calls.append(('release', axis, sign, distance))
        self.di = 0

    def unlock(self, confirmations, payload, interactive=False):
        self.phase = 'ready'; self.stop_state = 'none'; self.calls.append(('unlock', payload))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.now = [time.monotonic()]

    def make_runner(self, holes, **opts):
        values = validate_params(params(holes), holes)
        controller = FakeController()
        runner = ProbeRunner(controller, values, clock=lambda: self.now[0], **opts)
        return controller, runner

    def frame(self, controller):
        return live_frame(controller.pose, controller.di)

    def drive(self, controller, runner, contact=True, limit=500):
        runner.start(controller.snapshot(), self.frame(controller))
        for _ in range(limit):
            self.now[0] += 0.2
            runner.step(self.now[0], controller.snapshot(), self.frame(controller))
            if runner.stage in ('done', 'failed', 'await_continue'):
                return runner
            if controller.phase == 'moving':
                if runner.stage == 'probe' and contact:
                    controller.pose = list(controller.target); controller.di = 1
                    controller.request_stop('测头 DI_1 触发', recoverable=True)
                else:
                    controller.arrive()
            elif controller.phase == 'stopping':
                controller.di = 0; controller.stopped()
            elif controller.phase == 'locked':
                pass
        return runner

    def test_four_directions_then_center_and_safe_height(self):
        holes = [validate_hole(hole())]
        controller, runner = self.make_runner(holes, confirm_each_hole=False)
        self.drive(controller, runner)
        self.assertEqual(runner.stage, 'done')
        self.assertEqual(len(runner.results), 1)
        result = runner.results[0]
        self.assertAlmostEqual(result['center'][0], 100.0, places=3)
        self.assertAlmostEqual(result['center'][1], 100.0, places=3)
        self.assertEqual(len(runner.session_points), 4)
        stages = [call[0] for call in controller.calls]
        self.assertEqual(stages.count('release'), 4)
        self.assertEqual(stages.count('unlock'), 4)

    def test_missing_contact_stops_without_continuing(self):
        holes = [validate_hole(hole())]
        controller, runner = self.make_runner(holes, confirm_each_hole=False)
        self.drive(controller, runner, contact=False)
        self.assertEqual(runner.stage, 'failed')
        self.assertIn('未接触', runner.failure)
        self.assertEqual(runner.results, [])

    def test_confirm_each_hole_pauses_between_holes(self):
        holes = [validate_hole(hole()), validate_hole(hole(center=(140.,100.,50.), name='A2'))]
        controller, runner = self.make_runner(holes, confirm_each_hole=True)
        self.drive(controller, runner)
        self.assertEqual(runner.stage, 'await_continue')
        self.assertEqual(len(runner.results), 1)
        self.assertEqual(runner.hole_index, 1)


class PageTests(unittest.TestCase):
    def test_page_loads_saved_holes_and_refuses_without_controller(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import test_recent_ui as ui
        from inspection_gui.hole_probe_view import HOLES_NAME, HoleProbePage
        from inspection_gui.probe_workspace import atomic_json
        folder = Path.cwd()/'.test-output'/'hole-page'/uuid.uuid4().hex
        atomic_json(folder/HOLES_NAME, {'schema_version':1, 'kind':'hole_probe_holes', 'holes':[hole()]})
        workspace = ui.Workspace(folder)
        page = HoleProbePage(workspace)
        try:
            self.assertEqual(page.hole_table.rowCount(), 1)
            page.start_run()
            self.assertIn('实机控制', page.progress.text())
        finally:
            page.close(); workspace.close(); app.processEvents()


if __name__ == '__main__':
    unittest.main()
