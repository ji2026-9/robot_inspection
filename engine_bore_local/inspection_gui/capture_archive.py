"""Lossless capture evidence. Never overwrite an earlier capture."""
from pathlib import Path
from datetime import datetime
import hashlib,json,os,uuid
import cv2

def save_capture(root, frame, metadata=None):
    now=datetime.now().astimezone();folder=Path(root)/now.strftime('%Y-%m-%d');folder.mkdir(parents=True,exist_ok=True)
    identifier=now.strftime('capture_%Y%m%d_%H%M%S_%f')+'_'+uuid.uuid4().hex[:8]
    photo=folder/(identifier+'.png');info=folder/(identifier+'.json')
    ok,encoded=cv2.imencode('.png',frame)
    if not ok:raise OSError('原图编码失败，没有创建留样')
    pixels=encoded.tobytes()
    with photo.open('xb') as f:f.write(pixels);f.flush();os.fsync(f.fileno())
    data=dict(metadata or {})
    data.update({'capture_id':identifier,'saved_at':now.isoformat(),'image':photo.name,
        'width_px':int(frame.shape[1]),'height_px':int(frame.shape[0]),'encoding':'lossless_png',
        'image_sha256':hashlib.sha256(pixels).hexdigest(),'retention':'原图留样，不自动覆盖或删除',
        'time_note':'拍摄时间记录为电脑接收帧时间，未取得相机硬件曝光时间。'})
    try:
        with info.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    except Exception as error:
        raise OSError(f'原图已保留在 {photo}，拍摄信息保存失败，暂停进入检测：{error}') from error
    return photo,info,data

def capture_information(photo):
    p=Path(photo);sidecar=p.with_suffix('.json')
    if not sidecar.is_file():return None
    try:
        data=json.loads(sidecar.read_text(encoding='utf-8'))
        if data.get('capture_id') and data.get('image')==p.name:return data
    except (OSError,ValueError):pass
    return None
