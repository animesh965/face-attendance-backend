import time


class TrackManager:

    def __init__(self):

        self.tracks = {}

        # Remove track after 5 seconds if not seen
        self.track_timeout = 5

    def get(self, track_id):

        track = self.tracks.get(track_id)
        if track:
            track["last_seen"] = time.time()
        
        return track

    def update(self, track_id, user, similarity):
    
        current_time = time.time()
    
        self.tracks[track_id] = {
            "user": user,
            "similarity": similarity,
            "recognized_at": current_time,
            "last_seen": current_time,
        }

    def seen(self, track_id):

        if track_id in self.tracks:

            self.tracks[track_id]["last_seen"] = time.time()

    def cleanup(self):

        current = time.time()

        remove = []

        for track_id, value in self.tracks.items():

            if current - value["last_seen"] > self.track_timeout:

                remove.append(track_id)

        for track_id in remove:

            del self.tracks[track_id]