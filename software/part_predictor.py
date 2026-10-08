"""Decode the single part mask without clipping it to an inaccurate detection box."""
import cv2
import numpy as np
import torch
import torch.nn.functional as F
from ultralytics.models.yolo.segment.predict import SegmentationPredictor
from ultralytics.engine.results import Results
from ultralytics.utils import ops

class FullPartPredictor(SegmentationPredictor):
    def construct_result(self, pred, img, orig_img, img_path, proto):
        masks = None
        if len(pred):
            c,h,w = proto.shape
            logits = (pred[:,6:] @ proto.float().view(c,-1)).view(-1,h,w)
            binary = F.interpolate(logits[None],img.shape[2:],mode='bilinear',align_corners=False)[0] > 0
            cleaned = []
            for mask, box in zip(binary, pred[:,:4]):
                a = mask.cpu().numpy().astype(np.uint8)
                count, labels, stats, _ = cv2.connectedComponentsWithStats(a,8)
                if count > 1:
                    x1,y1,x2,y2 = box.detach().cpu().numpy().astype(int)
                    x1,y1 = max(0,x1),max(0,y1)
                    x2,y2 = min(a.shape[1],x2),min(a.shape[0],y2)
                    inside = np.bincount(labels[y1:y2,x1:x2].reshape(-1),minlength=count)
                    inside[0] = 0
                    chosen = int(np.argmax(inside))
                    a = (labels==chosen).astype(np.uint8) if inside[chosen] else np.zeros_like(a)
                cleaned.append(torch.from_numpy(a).to(pred.device))
            masks = torch.stack(cleaned)
            pred[:,:4] = ops.scale_boxes(img.shape[2:],pred[:,:4],orig_img.shape)
        return Results(orig_img,path=img_path,names=self.model.names,boxes=pred[:,:6],masks=masks)
