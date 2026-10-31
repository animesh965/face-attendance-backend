import threading 
import time
import cv2

from app.core.config import settings


class cameracapture:
    def __init__(self):
        self.camera = None
        self.frame = None
        self.running = False
        self.lock = threading.Lock()  # ek time par ek hi banda frame touch karega.

    def connect(self):
        print("camera connecting...")

        source = (
            settings.RTSP_URL
            if settings.RTSP_URL
            else 0
        )

        self.camera = cv2.VideoCapture(
            source,
            cv2.CAP_FFMPEG if settings.RTSP_URL else cv2.CAP_DSHOW
        )

        if not self.camera.isOpened():
            raise RuntimeError("unable to connect to camera")

        print("camera connected")

    def start(self):
        self.connect()

        self.running = True

        threading.Thread(
            target=self.update,
            daemon=True
        ).start()

    def update(self):
    
        while self.running:
    
            success, frame = self.camera.read()
    
            if not success:
    
                print("[Camera] Lost connection")
    
                time.sleep(1)
    
                self.connect()
    
                continue
    
            with self.lock:   # teacher writes and finish than student write in notebook
    
                self.frame = frame  # 2nd frame

    def get_frame(self):
        with self.lock:
            if self.frame is None:
                return None

            return self.frame.copy()

    def stop(self):
        self.running = False

        if self.camera:
            self.camera.release()

    

