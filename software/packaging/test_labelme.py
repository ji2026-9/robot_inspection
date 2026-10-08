import json
from pathlib import Path
from PySide6.QtWidgets import QApplication
from labelme._app import MainWindow
app=QApplication([])
entry=json.loads(Path('active_models.json').read_text(encoding='utf-8'))['entries'][0]
window=MainWindow(config_file='labelme_training.yaml',file_or_dir=str(Path(entry['annotation']).resolve()))
assert window._image is not None
assert len(window._canvas_widgets.canvas.shapes) > 0
window.close()
print('Labelme image and annotation loaded successfully')



