import numpy as np


def cosine_similarity(vec1, vec2):
    """
    Calculate cosine similarity between two face embeddings.

    Returns:
        float between -1 and 1
    """

    vec1 = np.array(vec1, dtype=np.float32)
    vec2 = np.array(vec2, dtype=np.float32)

    denominator = np.linalg.norm(vec1) * np.linalg.norm(vec2)

    if denominator == 0:
        return 0.0

    return float(np.dot(vec1, vec2) / denominator)