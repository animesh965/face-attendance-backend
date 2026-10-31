import cv2

print("Starting camera")

camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)

print("Camera opened:", camera.isOpened())

while True:

    ret, frame = camera.read()

    print("Frame received:", ret)

    if not ret:
        print("Cannot get frame")
        break

    print(frame.shape)

    cv2.imshow("Camera Test", frame)

    key = cv2.waitKey(1)

    if key == ord("q"):
        break


camera.release()
cv2.destroyAllWindows()