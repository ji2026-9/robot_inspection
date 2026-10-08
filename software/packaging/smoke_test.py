import json
from pathlib import Path
import torch
from PySide6.QtWidgets import QApplication
from inspection_gui.gui import MainWindow
from dataset_update import active_models
from detect_core import EngineDetector
from runtime_paths import python_executable

root = Path.cwd()
models = active_models()
assert all(Path(models[key]).is_file() for key in ('bore','part'))
assert len(models['entries']) == 28
assert all(Path(entry[key]).is_file() for entry in models['entries'] for key in ('image','annotation'))
assert python_executable().is_file()
assert python_executable(labelme=True,windowless=True).is_file()
app = QApplication([])
window = MainWindow()
assert not window.records.groups, 'Fresh install must not contain personal experiment records'
window.close()
torch.cuda.is_available = lambda: False
torch.set_num_threads(4)
detector = EngineDetector()
assert detector.device == 'cpu'
result = detector.analyze(models['entries'][0]['image'],root/'packaging_test_output')
assert result['bore_selected_count'] == 4
assert len(result['centers']) == 4
print(json.dumps({'cpu_detection':True, 'holes':4, 'centers':4, 'dataset':28, 'models':models['bore']},ensure_ascii=False))
