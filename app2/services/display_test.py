import cv2
import time

from app.core.face_analyzer import face_analyzer


class CameraService:

    @staticmethod
    def start():

        print("[INFO] Starting camera...")

        camera = cv2.VideoCapture(
            0,
            cv2.CAP_MSMF
        )

        print("[INFO] Camera object created")

        if not camera.isOpened():
            print("[ERROR] Unable to open webcam.")
            return

        print("[INFO] Webcam connected successfully")

        frame_count = 0

        while True:

            print("\n[INFO] Reading frame...")

            success, frame = camera.read()

            print("[INFO] Frame received:", success)

            if not success:
                print("[ERROR] Failed to receive frame")
                break


            print("[INFO] Original frame size:", frame.shape)


            frame = cv2.resize(
                frame,
                (640, 360)
            )

            print("[INFO] Frame resized")


            frame_count += 1

            print("[INFO] Frame count:", frame_count)


            if frame_count % 3 == 0:

                print("[INFO] Running face analyzer...")

                start_time = time.time()

                faces = face_analyzer.get(frame)

                end_time = time.time()


                print(
                    "[INFO] Face analyzer finished in:",
                    round(end_time - start_time, 3),
                    "seconds"
                )


                print(
                    "[INFO] Faces detected:",
                    len(faces)
                )


                for index, face in enumerate(faces):

                    print(
                        "[INFO] Processing face:",
                        index
                    )

                    print(
                        "[INFO] Face bbox:",
                        face.bbox
                    )


                    x1, y1, x2, y2 = map(
                        int,
                        face.bbox
                    )


                    cv2.rectangle(
                        frame,
                        (x1, y1),
                        (x2, y2),
                        (0, 255, 0),
                        2
                    )

                    print("[INFO] Rectangle drawn")


            print("[INFO] Showing frame")

            cv2.imshow(
                "Live Face Analyzer",
                frame
            )


            key = cv2.waitKey(1)

            if key & 0xFF == ord("q"):

                print("[INFO] Q pressed. Closing.")

                break


        print("[INFO] Releasing camera")

        camera.release()

        cv2.destroyAllWindows()

        print("[INFO] Camera closed")