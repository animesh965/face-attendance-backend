import threading
import time

from app.core.face_analyzer import face_analyzer
from app.models.detection import Detection


class DetectionWorker:

    def __init__(self, camera):

        # CameraCapture object
        self.camera = camera
        self.running = False

        self.lock = threading.Lock()

        self.faces = []

        self.frame = None

        self.last_detection_time = 0

        # detect twice every second
        self.DETECTION_INTERVAL = 0.5

# start worker
    def start(self):

        self.running = True # worker on now

        threading.Thread(
            target=self.detect_loop,
            daemon=True
        ).start()

    def detect_loop(self):

        while self.running:
            # poori image frame s milti hai

            frame = self.camera.get_frame()

            if frame is None:

                continue

            # current_time = time.time()

            # Run detector in every 0.5 second
            # if (
            #     current_time - self.last_detection_time
            #     < self.DETECTION_INTERVAL
            # ):
            #     continue

            # self.last_detection_time = current_time

            start = time.time()

            faces = face_analyzer.get(frame)
            detections = []

            for face in faces:
            
                x1, y1, x2, y2 = map(int, face.bbox)

            # ye sirf face crop karta hai
            
                face_crop = frame[y1:y2, x1:x2].copy()
            
                detections.append(
                    Detection(
                        bbox=face.bbox,
                        confidence=float(face.det_score),
                        embedding=face.embedding,
                        landmarks=face.kps,
                        face_image=face_crop,
                    )
                )
                

            # detections = []
            
            # for face in faces:
            
            #     detections.append(
            #         Detection(
            #             bbox=face.bbox,
            #             confidence=float(face.det_score),
            #             embedding=face.embedding,
            #             landmarks=face.kps,
            #         )
            #     )

            

            end = time.time()

            print(
                f"[Detection] {len(faces)} faces | "
                f"{end-start:.3f} sec"
            )

# save detected face 
            with self.lock:
# why copy so that it not point same frame as read by camera
                self.frame = frame.copy() # frame save and 

                self.faces = detections

                # self.faces = faces # image save (image data)

                


# dusra part (jaise API, UI, dashboard) ye data kaise lega? 
# yaha se

    def get_faces(self):

        with self.lock:

            return self.frame, self.faces

    def stop(self):

        self.running = False