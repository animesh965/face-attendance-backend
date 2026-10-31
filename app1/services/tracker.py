import numpy as np
import supervision as sv
from app.models.detection import TrackedFace

# ByteTrack originally object tracking ke liye bana hai:

class Tracker:

    def __init__(self):

        self.tracker = sv.ByteTrack()

    def update(self, detections):

        if len(detections) == 0:

            return []

        xyxy = np.array(

            [d.bbox for d in detections],

            dtype=np.float32 # ai lib use float32 that's why

        )

        confidence = np.array(

            [d.confidence for d in detections],

            dtype=np.float32

        )

# ByteTrack originally object tracking ke liye bana hai: 
# and har object ka class hota hai but Lekin hum sirf faces track kar rahe hain.
# To sabko ek hi class de dete hain.

        classes = np.zeros(

            len(detections),

            dtype=np.int32

        )

# why - Supervision library apna format expect karti hai.

        sv_detections = sv.Detections(

            xyxy=xyxy,

            confidence=confidence,

            class_id=classes

        )

# actual tracking

        tracks = self.tracker.update_with_detections(

            sv_detections

        )

        # return tracks

        # Ye set yaad rakhega ki kaunsi detection pehle hi kisi track ko assign ho chuki hai.
        used_detection_indices = set()

        tracked_faces = []

        for track_bbox, track_id in zip(
            tracks.xyxy,
            tracks.tracker_id
        ):

        # Ab sirf detection hi nahi, uska index bhi yaad rakhna hai.
            best_detection = None
            best_index = None
            best_iou = 0.0

        # Agar Detection A pehle hi Track 5 ko mil chuki hai, to Track 6 usko use nahi karega.
            for index, detection in enumerate(detections):
            
                if index in used_detection_indices:
                    continue
            
                iou = calculate_iou(
                    track_bbox,
                    detection.bbox
                )
        # Taaki baad mein us detection ko used mark kar sakein.
                if iou > best_iou:
                
                    best_iou = iou
                    best_detection = detection
                    best_index = index
        
            # Ignore if no reasonable match found
            if best_detection is None or best_iou < 0.5:
                continue

            used_detection_indices.add(best_index)
        
            tracked_faces.append(
        
                TrackedFace(
        
                    track_id=int(track_id),
        
                    bbox=track_bbox,
        
                    detection=best_detection
        
                )
        
            )
        
        return tracked_faces
        
        # for i in range(len(tracks.xyxy)):
        
        #     tracked_faces.append(
        
        #         {
        #             "track_id": int(tracks.tracker_id[i]),
        
        #             "bbox": tracks.xyxy[i],
        
        #             "detection": detections[i]
        #         }
        
        #     )
        
        # return tracked_faces


# Hum index se mapping nahi karenge.
# Hum Bounding Box (IoU) se mapping karenge.

def calculate_iou(box1, box2):

    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    intersection = max(0, x2 - x1) * max(0, y2 - y1)

    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])

    union = area1 + area2 - intersection

    if union == 0:
        return 0.0

    return intersection / union