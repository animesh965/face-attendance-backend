from dataclasses import dataclass
import numpy as np


# slots=True why ?
@dataclass(slots=True)
class Detection:

    bbox: np.ndarray

    confidence: float

    embedding: np.ndarray

    landmarks: np.ndarray

    face_image: np.ndarray | None = None



# to avoid runtime error from dictionary in python
@dataclass(slots=True)
class TrackedFace:

    track_id: int

    bbox: np.ndarray

    detection: Detection
















# from dataclasses import dataclass
# import numpy as np


# @dataclass
# class Detection:

#     bbox: np.ndarray

#     confidence: float

#     embedding: np.ndarray

#     landmarks: np.ndarray


