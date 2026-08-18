
import os
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(BASE, "models")
os.makedirs(MODELS, exist_ok=True)

FILES = {
    "face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}

for name, url in FILES.items():
    path = os.path.join(MODELS, name)
    if os.path.exists(path):
        print("Already exists:", name)
        continue
    print("Downloading:", name)
    urllib.request.urlretrieve(url, path)
    print("Saved:", path)

print("Models ready.")
