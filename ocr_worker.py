"""OCR worker - runs in subprocess to avoid torch/PyQt5 DLL conflict."""
import sys, json, cv2, numpy as np
import easyocr

_reader = None

def get_reader():
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _reader

def ocr_image(path):
    img = cv2.imread(path)
    if img is None:
        return ""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    invert = cv2.bitwise_not(bw)
    reader = get_reader()
    results = reader.readtext(invert, detail=0, paragraph=False)
    return " ".join(results)

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "ocr":
        path = sys.argv[2]
        text = ocr_image(path)
        print(text, flush=True)
    elif cmd == "ready":
        get_reader()
        print("ready", flush=True)