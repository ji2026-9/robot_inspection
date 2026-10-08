"""Exercise update boundaries without training or replacing the user's models."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from types import SimpleNamespace
from PIL import Image
import dataset_update as update


def pair(folder, name, color):
    folder.mkdir(parents=True, exist_ok=True)
    image = folder/(name+'.jpg')
    Image.new('RGB',(64,64),(color,20,30)).save(image)
    shapes = [{'label':'part','shape_type':'polygon','points':[[1,1],[63,1],[63,63],[1,63]]}]
    for x,y in ((10,10),(30,10),(10,30),(30,30)):
        shapes.append({'label':'bore','shape_type':'polygon','points':[[x,y],[x+7,y],[x+7,y+7],[x,y+7]]})
    image.with_suffix('.json').write_text(json.dumps({'imageWidth':64,'imageHeight':64,'shapes':shapes}),encoding='utf-8')
    return image


def main():
    score = {'bore_map':.8811852548036759,'part_iou':.9554078507563603,
             'part_min_iou':.8849030802978752}
    lower_bore = dict(score,bore_map=.8741918963389551)
    assert not update.gates_pass(score,lower_bore), 'latest lower-scoring bore model accepted'
    assert update.gates_pass(score,score), 'equal model rejected'
    assert update.gates_pass(score,dict(score,bore_map=score['bore_map']+.01,
                                      part_iou=score['part_iou']+.001)), 'improved model rejected'
    assert not update.gates_pass(score,dict(score,part_iou=score['part_iou']-.001)), 'lower mean part IoU accepted'
    assert update.gates_pass(score,dict(score,bore_map=score['bore_map']-.5e-6,
                                      part_iou=score['part_iou']-.5e-6)), 'floating point tolerance rejected'
    assert not update.gates_pass(score,dict(score,bore_map=score['bore_map']-2e-6)), 'bore tolerance exceeded'
    assert not update.gates_pass(score,dict(score,part_iou=score['part_iou']-2e-6)), 'part tolerance exceeded'
    assert update.gates_pass(score,dict(score,part_min_iou=score['part_min_iou']-.049)), 'part minimum safeguard changed'
    assert not update.gates_pass(score,dict(score,part_min_iou=score['part_min_iou']-.051)), 'part minimum degradation accepted'
    with tempfile.TemporaryDirectory(prefix='workflow_check_',dir=update.BASE) as temporary:
        root = Path(temporary)
        seed, incoming = root/'seed', root/'incoming'
        for index in range(1,26):
            pair(seed,f'{index:03d}',index*7)
        for index in range(5):
            pair(incoming,f'new_{index}',200+index*10)
        plan = update.prepare(incoming,root/'prepared',seed,{'bore':'old.pt','part':'old-part.pt','entries':[]})
        assert plan['new_count']==5 and plan['train_count']==24 and plan['val_count']==6
        assert (root/'prepared'/'part'/'labels'/'train').is_dir()
        assert all(len(p.read_text(encoding='utf-8').splitlines())==1 for p in (root/'prepared'/'part'/'labels'/'train').glob('*.txt'))
        assert all(len(p.read_text(encoding='utf-8').splitlines())==5 for p in (root/'prepared'/'bore'/'labels'/'train').glob('*.txt'))
        try:
            update.prepare(incoming,root/'duplicate',seed,dict(plan['previous'],entries=plan['entries']))
            raise AssertionError('duplicate batch accepted')
        except ValueError as error:
            assert '无需' in str(error)
        pair(incoming,'unlabeled',253).with_suffix('.json').unlink()
        try:
            update.prepare(incoming,root/'incomplete',seed,plan['previous'])
            raise AssertionError('unlabeled image accepted')
        except ValueError as error:
            assert '尚未保存' in str(error)
        (incoming/'unlabeled.jpg').unlink()
        active = root/'active.json'
        old = {'bore':'old.pt','part':'old-part.pt','entries':[]}
        update.write_json(active,old)
        class FakeYOLO:
            def __init__(self,path): pass
            def add_callback(self,*args): pass
            def train(self,**kwargs):
                best=Path(kwargs['project'])/kwargs['name']/'weights'/'best.pt'
                best.parent.mkdir(parents=True)
                best.write_bytes(b'test-only')
                self.trainer=SimpleNamespace(best=str(best))
        actual_prepare = update.prepare
        def prepare_test(folder,job):
            return actual_prepare(folder,job,seed,old)
        with patch.object(update,'ACTIVE',active), patch.object(update,'prepare',prepare_test), \
             patch('ultralytics.YOLO',FakeYOLO),patch('torch.cuda.is_available',return_value=True), \
             patch.object(update,'evaluate',side_effect=[score,lower_bore]):
            update.run(incoming,root/'rejected',1)
            assert json.loads(active.read_text(encoding='utf-8'))==old
            assert json.loads((root/'rejected'/'status.json').read_text(encoding='utf-8'))['stage']=='rejected'
        with patch.object(update,'ACTIVE',active),patch.object(update,'prepare',prepare_test), \
             patch('ultralytics.YOLO',FakeYOLO),patch('torch.cuda.is_available',return_value=True), \
             patch.object(update,'evaluate',side_effect=[score,score]):
            update.run(incoming,root/'accepted',1)
            accepted=json.loads(active.read_text(encoding='utf-8'))
            assert accepted['version']=='accepted' and len(accepted['entries'])==30
            assert json.loads((root/'accepted'/'previous_active_models.json').read_text(encoding='utf-8'))==old
    print('PASS: nondecreasing validation gate, merge, YOLO export, fixed holdout, duplicate filtering, incomplete labels, validation rejection, atomic activation')


if __name__=='__main__':
    main()
