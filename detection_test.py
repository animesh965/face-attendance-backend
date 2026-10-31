import cv2

from app.services.camera_capture import cameracapture
from app.services.detection_worker import DetectionWorker


camera = cameracapture()

camera.start()


detector = DetectionWorker(camera)

detector.start()


while True:

    frame, faces = detector.get_faces()

    if frame is None:

        continue

    for face in faces:

        x1, y1, x2, y2 = map(
            int,
            face.bbox
        )

        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            (0,255,0),
            2
        )

    frame = cv2.resize(
        frame,
        (640,360)
    )

    cv2.imshow(
        "Detection Worker",
        frame
    )

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


detector.stop()

camera.stop()

cv2.destroyAllWindows()