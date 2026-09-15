"""Local rectangle proposals. Proposals never establish a card identity."""
import time
import os
import re
import shutil
import subprocess
import cv2

VERSION = 'rectangle-review-v2'


def detect(image_path):
    started = time.monotonic()
    cv2.setNumThreads(1)
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError('The preview is unavailable.')
    height, width = image.shape[:2]
    scale = min(1, 1400 / max(width, height))
    small = cv2.resize(image, (round(width * scale), round(height * scale)))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    sh, sw = small.shape[:2]
    boxes = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not .012 * sw * sh < area < .97 * sw * sh:
            continue
        approx = cv2.approxPolyDP(contour, .025 * cv2.arcLength(contour, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        x, y, w, h = cv2.boundingRect(approx)
        if not .38 < w / h < 2.65 or area / (w*h) < .72:
            continue
        boxes.append([x/sw, y/sh, min(w/sw, 1-x/sw), min(h/sh, 1-y/sh)])
    # Sleeves and glare can break edge contours. Color and dark-region passes
    # recover card bodies on a light tabletop without requiring four corners.
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    for value, saturation, kernel in ((120, 80, 3), (80, 80, 7), (120, 255, 3)):
        mask = ((hsv[:, :, 2] < value) | ((hsv[:, :, 1] > saturation) & (hsv[:, :, 2] < 250))).astype('uint8') * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kernel, kernel)))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if not .006 * sw * sh < area < .15 * sw * sh:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if not .38 < w / h < 2.65 or area / (w*h) < .5:
                continue
            left, top = max(0, (x-3)/sw), max(0, (y-3)/sh)
            boxes.append([left, top, min((w+6)/sw, 1-left), min((h+6)/sh, 1-top)])
    selected = []
    for box in sorted(boxes, key=lambda b: b[2]*b[3], reverse=True):
        x, y, w, h = box
        contained = False
        for sx, sy, sww, shh in selected:
            intersection = max(0, min(x+w, sx+sww)-max(x, sx))*max(0, min(y+h, sy+shh)-max(y, sy))
            if intersection / min(w*h, sww*shh) > .8 or intersection / (w*h+sww*shh-intersection) > .4:
                contained = True
        if not contained:
            selected.append(box)
    selected.sort(key=lambda b: (round(b[1], 1), b[0]))
    return {'status': 'detected' if selected else 'unresolved', 'cards': selected[:60], 'truncated': len(selected) > 60,
            'uncertainty': ['Check each rectangle. Add missed cards manually. Identity recognition is unavailable.'],
            'method': VERSION, 'duration_ms': round((time.monotonic()-started)*1000), 'model_cost_usd': 0}


def identify(crop_path):
    started = time.monotonic()
    result = {'status': 'unresolved', 'identity': {}, 'candidates': [], 'evidence_text': '',
              'uncertainty': ['Check extracted text against the card. OCR does not establish identity, grade, or condition.'],
              'metrics': {'model_cost_usd': 0, 'method': 'tesseract-local'}}
    if crop_path and shutil.which('tesseract'):
        try:
            run = subprocess.run(['tesseract', str(crop_path), 'stdout', '--psm', '11'],
                                 capture_output=True, text=True, timeout=12,
                                 env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
            if run.returncode == 0:
                extracted = run.stdout.strip()[:8000]
                result['evidence_text'] = extracted
                result['candidates'] = [{'field': 'year', 'value': year, 'status': 'unconfirmed'}
                                        for year in sorted(set(re.findall(r'\b(?:19|20)\d{2}\b', extracted)))]
            else:
                result['uncertainty'].append('Text extraction failed. Manual review remains available.')
        except (subprocess.TimeoutExpired, OSError):
            result['uncertainty'].append('Text extraction timed out or is unavailable.')
    else:
        result['uncertainty'].append('Local text extraction is unavailable.')
    result['metrics']['duration_ms'] = round((time.monotonic()-started)*1000)
    return result
