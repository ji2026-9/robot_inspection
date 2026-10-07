"""Isolated integration check; never appends to the user's experiment history."""
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtCore import QTimer
from experiment_records import ExperimentRecords
import inspection_gui.gui as gui
from inspection_gui.records_view import RecordsDialog
from inspection_gui.devices_view import show_devices

OUT = Path(__file__).resolve().parent
protected = [BASE / n for n in ('active_models.json', 'experiment_records.json', 'last_batch.json')]
def hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
before = hashes()
app = QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
app.setFont(QFont('Microsoft YaHei', 10))
gui.LAST_BATCH = OUT / 'isolated_last_batch.json'
record_path = OUT / 'isolated_records.json'
record_path.write_text('[]', encoding='utf-8')
window = gui.MainWindow(records=ExperimentRecords(record_path))
reports = json.loads((BASE / 'last_batch.json').read_text(encoding='utf-8'))
paths = [r['image'] for r in reports[:3]] + [str(OUT / 'missing_photo.jpg')]
window.set_images(paths)
window.show()
window.start_batch()
ticks = 0
def check():
    global ticks
    ticks += 1
    if window.batch_running:
        if ticks > 180:
            print('TIMEOUT', flush=True)
        return
    timer.stop()
    results = window.results
    assert len(results) == 4 and all(r is not None for r in results)
    assert all(not r.get('errors') for r in results[:3]), [r.get('errors') for r in results]
    assert results[3]['errors'] and results[3]['center_count'] == 0
    assert len(window.records.rows()) == 4
    assert hashes() == before, 'Production files changed'
    window.show_index(0)
    app.processEvents()
    window.grab().save(str(OUT / 'integrated_main.png'))
    dialog = RecordsDialog(window, records=window.records)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(OUT / 'records_grid.png'))
    dialog.close()
    devices = show_devices(window)
    app.processEvents()
    if devices is None:
        devices = window.findChildren(__import__('PySide6.QtWidgets', fromlist=['QDialog']).QDialog)[-1]
    devices.grab().save(str(OUT / 'devices_panel.png'))
    devices.close()
    summary = {'photos': len(results), 'record_rows': len(window.records.rows()),
               'results': [{'file': Path(p).name, 'holes': r.get('detections'),
                            'centers': r.get('center_count'), 'errors': r.get('errors', [])}
                           for p,r in zip(paths,results)],
               'production_files_unchanged': hashes() == before}
    (OUT / 'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    window.detector.release()
    window.close()
    app.quit()
timer = QTimer()
timer.timeout.connect(check)
timer.start(500)
app.exec()
