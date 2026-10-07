"""Local photo review without changing detection results or physical hole identity."""
import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QHBoxLayout, QVBoxLayout, QPushButton


def review_summary(result):
    if not result:
        return '待检测', False
    expected = int(result.get('expected', 4))
    detected = int(result.get('detections', 0))
    reliable = int(result.get('reliable_center_count', sum(bool(h.get('reliable_center')) for h in result.get('detected_holes', []))))
    notes = []
    if result.get('errors'):
        notes.append('检测异常，请查看诊断信息')
    if detected < expected:
        notes.append(f'预期 {expected} 个孔，识别 {detected} 个，少 {expected - detected} 个，请复核原图')
    elif detected > expected:
        notes.append(f'识别 {detected} 个孔，超过预期 {expected} 个，请复核误检')
    if reliable < detected:
        notes.append(f'{detected - reliable} 个孔暂无可靠圆心，请点击孔号复核')
    if not result.get('part_constraint_applied'):
        notes.append('箱体位置约束未执行，请复核')
    if result.get('warnings') and not notes:
        notes.append('检测存在提示，请查看诊断信息并复核')
    return ('；'.join(notes), True) if notes else ('孔数符合预期，圆心通过当前算法检查，点击孔号可放大复核', False)


def review_crop(image, hole):
    h, w = image.shape[:2]
    box = hole.get('box_xyxy')
    if box is None and hole.get('ellipse'):
        e = hole['ellipse'];cx, cy = e['center'];radius = max(e['width'], e['height']) * .6
        box = [cx-radius, cy-radius, cx+radius, cy+radius]
    if box is None or len(box) != 4 or not np.isfinite(box).all():
        return image.copy(), (0, 0), False
    x1, y1, x2, y2 = map(float, box)
    pad = max(20, (max(x2-x1, y2-y1)) * .2)
    x1, y1 = max(0, int(x1-pad)), max(0, int(y1-pad))
    x2, y2 = min(w, int(x2+pad)), min(h, int(y2+pad))
    if x2 <= x1 or y2 <= y1:
        return image.copy(), (0, 0), False
    return image[y1:y2, x1:x2].copy(), (x1, y1), True


class HoleReviewDialog(QDialog):
    def __init__(self, original, hole, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"孔放大复核 · {hole['id']}")
        self.resize(1000, 650)
        layout = QVBoxLayout(self)
        center = hole.get('center_px')
        coordinate = f'{center[0]:.2f}, {center[1]:.2f} px' if center else '未提供圆心'
        note = QLabel(f"{hole['id']}　置信度 {hole['confidence']:.4f}　圆心 {coordinate}\n" +
                      ('当前算法判定圆心可用' if hole.get('reliable_center') else '圆心需人工复核') +
                      '。孔号按图像位置排序，不代表固定物理孔。')
        note.setWordWrap(True);layout.addWidget(note)
        crop, offset, local = review_crop(original, hole)
        overlay = crop.copy()
        e = hole.get('ellipse')
        if e:
            cx, cy = e['center'];x, y = offset
            cv2.ellipse(overlay, ((cx-x, cy-y),(e['width'],e['height']),e['angle']), (0,255,255), 2)
        if center:
            cv2.drawMarker(overlay,(round(center[0]-offset[0]),round(center[1]-offset[1])),(0,0,255),cv2.MARKER_CROSS,24,2)
        images = QHBoxLayout();self._previews=[]
        for title, photo in [('原始照片局部' if local else '原始照片（旧结果未保存局部范围）',crop),('拟合椭圆与像素圆心',overlay)]:
            column=QVBoxLayout();column.addWidget(QLabel(title));label=QLabel();label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumSize(200,200);column.addWidget(label,1);images.addLayout(column,1)
            rgb=cv2.cvtColor(photo,cv2.COLOR_BGR2RGB);hh,ww=rgb.shape[:2]
            pixmap=QPixmap.fromImage(QImage(rgb.data,ww,hh,rgb.strides[0],QImage.Format.Format_RGB888).copy())
            self._previews.append((label,pixmap))
        layout.addLayout(images,1)
        details=[]
        for key,title in [('fit_median_residual_px','拟合残差 px'),('contour_support','轮廓支持度'),('edge_support','边缘支持度'),('source_rotation_deg','补检旋转角度')]:
            value=hole.get(key)
            if value is not None:details.append(f'{title}：{value:.3f}')
        detail_label=QLabel('　'.join(details) or '此结果未保存拟合诊断数据');detail_label.setWordWrap(True);layout.addWidget(detail_label)
        layout.addWidget(QLabel('本窗口用于查看，不会修改检测结果。三维坐标与实际测量精度仍需标定验证。'))
        close=QPushButton('关闭');close.clicked.connect(self.close);layout.addWidget(close)
        self._resize_previews()

    def _resize_previews(self):
        for label,pixmap in getattr(self,'_previews',[]):
            label.setPixmap(pixmap.scaled(label.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self,event):
        super().resizeEvent(event);self._resize_previews()
