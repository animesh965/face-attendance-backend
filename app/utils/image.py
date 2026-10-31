import cv2
import numpy as np

def validate_image_bytes(data: bytes, max_bytes: int) -> np.ndarray:
    if not data:
        raise ValueError("Empty image")
    if len(data) > max_bytes:
        raise ValueError("Image exceeds maximum allowed size")
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image file")
    return image

def quality(image, face, min_w, min_h, blur_threshold, min_brightness, max_brightness):
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    w, h = x2 - x1, y2 - y1
    if w < min_w or h < min_h:
        raise ValueError(f"Face is too small. Minimum size is {min_w}x{min_h}px")
    crop = image[max(0,y1):min(image.shape[0],y2), max(0,x1):min(image.shape[1],x2)]
    if crop.size == 0:
        raise ValueError("Invalid face crop")
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    if blur < blur_threshold:
        raise ValueError("Face image is too blurry")
    if brightness < min_brightness or brightness > max_brightness:
        raise ValueError("Face lighting is outside the accepted range")
    return {"face_width": w, "face_height": h, "blur_score": blur, "brightness": brightness}
