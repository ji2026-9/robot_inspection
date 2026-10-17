import importlib.util,json,unittest,uuid
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('handoff_refresh',Path(__file__).resolve().parents[1]/'scripts/refresh_handoff.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class HandoffSnapshotTests(unittest.TestCase):
    def test_detects_source_and_runtime_drift_without_hardware(self):
        base=Path.cwd()/'.test-output'/uuid.uuid4().hex;repo=base/'repo';source=repo/'software/inspection_gui';source.mkdir(parents=True)
        (source/'workbench.py').write_text('one',encoding='utf-8');(source/'build_manifest.json').write_text(json.dumps({'build_id':'test','modules':{'workbench.py':'old'}}),encoding='utf-8')
        runtime=base/'inspection_app/inspection_gui';runtime.mkdir(parents=True);(runtime/'workbench.py').write_text('one',encoding='utf-8')
        with patch('socket.create_connection',side_effect=AssertionError('No hardware')):
            before=module.collect(repo);(runtime/'workbench.py').write_text('two',encoding='utf-8');after=module.collect(repo)
        self.assertNotIn('software/inspection_gui/workbench.py',before['runtime_comparison']['different_or_missing'])
        self.assertIn('software/inspection_gui/workbench.py',after['runtime_comparison']['different_or_missing'])
        (source/'workbench.py').write_text('new',encoding='utf-8');self.assertNotEqual(before['source_sha256'],module.collect(repo)['source_sha256'])
    def test_missing_runtime_is_explicit(self):
        repo=Path.cwd()/'.test-output'/uuid.uuid4().hex/'repo';repo.mkdir(parents=True)
        data=module.collect(repo);self.assertFalse(data['runtime_comparison']['available']);self.assertIsNone(data['build_id'])
