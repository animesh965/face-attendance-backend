from app.services.track_manager import TrackManager
from app.services.recognizer import Recognizer


class RecognitionWorker:

    def __init__(self):

        self.track_manager = TrackManager()

# ye function = Ye tracker se saare tracked faces leta hai.
# Phir ek-ek karke recognize karta hai.
    async def process(self, tracked_faces):
        # Har processing cycle ke start mein purane tracks hata do.
        self.track_manager.cleanup()

        for tracked_face in tracked_faces:

            track_id = tracked_face.track_id

            # Already recognized?
            cached = self.track_manager.get(track_id)

            if cached:
                # update the last track seen -> update
                # self.track_manager.seen(track_id)

                continue

            result = await Recognizer.recognize_embedding(
                tracked_face.detection.embedding
            )

            # if result["recognized"]:
            if result.get("recognized"):

                self.track_manager.update(
                    track_id=track_id,
                    user=result["user"],
                    similarity=result["similarity"]
                )
            else:
            
                self.track_manager.update(
                    track_id=track_id,
                    user={
                        "name": "Unknown"
                    },
                    similarity=0.0
                )

# Ye baad mein tracker_test.py aur FastAPI API dono mein use hoga.

    def get_track(self, track_id):
    
        return self.track_manager.get(track_id)


# Ek aur production issue bacha hai 

# # Ye code functional hai, lekin ek subtle bug abhi bhi hai: 
# agar recognition fail ho (recognized=False), to same face har frame database mein dobara search hoga. 
# Production systems iske liye negative caching ya retry cooldown use karte hain (jaise 2–5 seconds tak dubara 
# recognize na karo). Main recommend karunga ki pehle current pipeline ko end-to-end chala lo, uske baad hum us 
# optimization ko add karenge.