import cv2
import asyncio

from app.core.database import connect_database, close_database

from app.services.camera_capture import cameracapture
from app.services.detection_worker import DetectionWorker
from app.services.tracker import Tracker
from app.services.recognition_worker import RecognitionWorker


async def main():

    # 1. Database initialize
    await connect_database()


    # 2. Camera start
    camera = cameracapture()
    camera.start()


    # 3. Detection start
    detector = DetectionWorker(camera)
    detector.start()


    # 4. Tracker + Recognition
    tracker = Tracker()
    recognition_worker = RecognitionWorker()


    while True:

        frame, detections = detector.get_faces()

        if frame is None:
            continue


        tracked_faces = tracker.update(
            detections
        )


        # yaha asyncio.run nahi hoga
        await recognition_worker.process(
            tracked_faces
        )


        for tracked_face in tracked_faces:

            x1, y1, x2, y2 = map(
                int,
                tracked_face.bbox
            )

            track_id = tracked_face.track_id


            cached = recognition_worker.get_track(
                track_id
            )


            if cached:
                text = cached["user"]["name"]
            else:
                text = f"ID {track_id}"


            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0,255,0),
                2
            )


            cv2.putText(
                frame,
                text,
                (x1,y1-10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0,255,0),
                2
            )


        cv2.imshow(
            "ByteTrack Test",
            frame
        )


        if cv2.waitKey(1) & 0xFF == ord("q"):
            break



    detector.stop()
    camera.stop()

    await close_database()

    cv2.destroyAllWindows()



if __name__ == "__main__":

    asyncio.run(main())






































# import cv2

# from app.services.camera_capture import cameracapture
# from app.services.detection_worker import DetectionWorker
# from app.services.tracker import Tracker
# import asyncio

# from app.services.recognition_worker import RecognitionWorker
# from app.core.database import connect_database

# # Database first
# # asyncio.run(
# #     connect_database()
# # )

# async def main():

#     await connect_database()

#     camera = cameracapture()
#     camera.start()

#     detector = DetectionWorker(camera)
#     detector.start()

#     tracker = Tracker()
#     recognition_worker = RecognitionWorker()


#     while True:

#         frame, detections = detector.get_faces()

#         if frame is None:
#             continue


#         tracked_faces = tracker.update(detections)


#         await recognition_worker.process(
#             tracked_faces
#         )


#         # display code


# asyncio.run(main())

# camera = cameracapture()
# camera.start()

# detector = DetectionWorker(camera)
# detector.start()

# tracker = Tracker()
# recognition_worker = RecognitionWorker()

# while True:

#     frame, detections = detector.get_faces()

#     if frame is None:
#         continue

#     tracked_faces = tracker.update(detections)

#     # Ye technically chalega, lekin production mein ideal nahi hai, 
#     # kyunki asyncio.run() har call par naya event loop banata aur band karta hai

#     # asyncio.run(
#     #     recognition_worker.process(tracked_faces)
#     # )

#     # asyncio.run(main())

#     for tracked_face in tracked_faces:

#         x1, y1, x2, y2 = map(
#             int,
#             tracked_face.bbox
#         )
        
#         track_id = tracked_face.track_id
        
#         #Cache se user nikalo
#         cached = recognition_worker.get_track(track_id)

#         if cached:
        
#             text = cached["user"]["name"]
        
#         else:
        
#             text = f"ID {track_id}"

#         cv2.rectangle(
#             frame,
#             (x1, y1),
#             (x2, y2),
#             (0, 255, 0),
#             2
#         )

#         cv2.putText(
#             frame,
#             text,
#             (x1, y1 - 10),
#             cv2.FONT_HERSHEY_SIMPLEX,
#             0.7,
#             (0, 255, 0),
#             2
#         )

#     frame = cv2.resize(frame, (640, 360))

#     cv2.imshow(
#         "ByteTrack Test",
#         frame
#     )

#     if cv2.waitKey(1) & 0xFF == ord("q"):
#         break

# detector.stop()
# camera.stop()

# cv2.destroyAllWindows()