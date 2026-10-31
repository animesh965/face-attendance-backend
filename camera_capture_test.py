import cv2

from app.services.camera_capture import CameraCapture


camera = CameraCapture()

camera.start()


while True:

    frame = camera.get_frame()

    if frame is None:
        continue

    frame = cv2.resize(
        frame,
        (640,360)
    )

    cv2.imshow(
        "Camera",
        frame
    )

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


camera.stop()

cv2.destroyAllWindows()