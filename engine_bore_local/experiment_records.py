"""Persistent batch records, independent of the detector and GUI."""
from datetime import datetime
from pathlib import Path
import csv
import json
import uuid

BASE = Path(__file__).resolve().parent
RECORD_FILE = BASE / 'experiment_records.json'
COLUMNS = [
    ('group', '实验组'), ('time', '测试时间'), ('photo', '照片'),
    ('count', '保留孔数'), ('fit_count', '圆心数'),
    ('hole1', '孔1置信度'), ('hole2', '孔2置信度'),
    ('hole3', '孔3置信度'), ('hole4', '孔4置信度'),
    ('mean', '孔平均置信度'), ('minimum', '孔最低置信度'),
    ('part', 'part置信度'), ('constraint', '位置筛选'),
    ('status', '组状态'), ('warnings', '复核提示'), ('mode','检测方案'), ('model', '模型路径'),
    ('image', '照片路径'), ('result_image', '结果图片路径'),
    ('part_model', 'part模型路径'),
]
COLUMNS += [(f'hole{i}_{axis}', f'孔{i}相机{axis.upper()} mm（估计）') for i in range(1,5) for axis in ('x','y','z')]
COLUMNS += [(f'hole{i}_depth_quality', f'孔{i}深度复核信息') for i in range(1,5)]


class ExperimentRecords:
    def __init__(self, path=RECORD_FILE):
        self.path = Path(path)
        self.groups = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else []
        interrupted = False
        for group in self.groups:
            if group['status'] == '检测中':
                group['status'] = '未完成，请复核'
                interrupted = True
        if interrupted:
            self.save()

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.groups, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.path)

    def begin(self, paths, model):
        group = {'id': str(uuid.uuid4()), 'number': max((g['number'] for g in self.groups), default=0)+1,
                 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 'paths': list(paths), 'model': model, 'status': '检测中', 'reports': []}
        self.groups.append(group)
        self.save()
        return group['id']

    def update(self, group_id, report=None, status=None):
        group = next(g for g in self.groups if g['id'] == group_id)
        if report is not None:
            group['reports'].append(report)
        if status is not None:
            group['status'] = status
        self.save()

    def rows(self):
        rows = []
        for group in self.groups:
            for report in group['reports']:
                # New reports retain detection scores even when center fitting fails.
                bores = report.get('selected_bores', report.get('centers', []))
                scores = {b['hole_id']: float(b['confidence']) for b in bores}
                values = list(scores.values())
                row = {'group': f"第{group['number']}组", 'time': group['time'],
                       'photo': Path(report['image']).name,
                       'count': report.get('bore_selected_count', len(bores)),
                       'fit_count': len(report.get('centers', [])),
                       'mean': f'{sum(values)/len(values):.4f}' if values else '',
                       'minimum': f'{min(values):.4f}' if values else '',
                       'part': f"{report.get('part_max_confidence', 0):.4f}",
                       'constraint': '已执行' if report.get('part_constraint_applied') else '已跳过',
                       'status': group['status'], 'warnings': '；'.join(report.get('warnings', [])),
                       'mode':{'own':'当前模型','friend':'朋友孔模型','fusion':'双模型融合试验'}.get(report.get('bore_mode','own'),'当前模型'),
                       'model': report.get('model', group['model']), 'image': report['image'],
                       'result_image': report.get('result_image', ''),
                       'part_model': report.get('part_model') or ''}
                row.update({f'hole{i}': f'{scores[i]:.4f}' if i in scores else '' for i in range(1, 5)})
                for estimate in report.get('camera_3d',[]):
                    i=int(estimate['id'][1:])
                    for axis,value in zip(('x','y','z'),estimate['center_camera_mm']):row[f'hole{i}_{axis}']=f'{value:.3f}'
                    row[f'hole{i}_depth_quality']=f"需复核；覆盖 {estimate['depth_coverage']:.0%}；平面残差 {estimate['plane_rmse_mm']:.2f} mm；圆残差 {estimate['circle_rmse_mm']:.2f} mm"
                rows.append(row)
        return rows

    def export(self, destination):
        with Path(destination).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow([label for key, label in COLUMNS])
            for row in self.rows():
                writer.writerow([row.get(key, '') for key, label in COLUMNS])
