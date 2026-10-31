from insightface.app import FaceAnalysis
from app.core.logger import logger

# CPU is the safe production default. Set FACE_PROVIDERS in your deployment layer
# and adapt this file for onnxruntime-gpu if GPU inference is installed.
face_analyzer = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
face_analyzer.prepare(ctx_id=0, det_size=(640, 640))
logger.info("InsightFace buffalo_l initialized")
