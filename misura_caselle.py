"""
misura_caselle.py - passi 2 e 3 della pipeline, sull'immagine GIA' allineata:
ancoraggio locale del quadratino stampato e misura dell'inchiostro al suo interno.
La decisione (quale casella proporre) resta in riconoscimento.analizza.
"""
from __future__ import annotations
import cv2
import numpy as np

from soglie import CONTRASTO_MIN


def _ancora(gray, template, casella, W, H):
    """Ritrova il quadratino STAMPATO della casella nell'immagine allineata, cercandolo in un
    intorno della posizione nominale. Il confronto avviene sull'ampiezza del gradiente: il
    bordo stampato risalta, mentre il segno a penna dentro la casella disturba poco.
    Ritorna il rettangolo esterno del quadratino, o None."""
    cw, ch = template["_cella"]
    pw, ph = int(cw * W), int(ch * H)
    sag = template["_sagome"].get(casella["id"])
    if sag is None or pw < 6 or ph < 6:
        return None
    sg, sx, sy = sag
    cx, cy = int(casella["x"] * W), int(casella["y"] * H)
    # Raggio di ricerca stretto: serve solo ad assorbire il residuo dell'omografia, non a
    # cercare la casella lontano. Cercare largo rischia di agganciarsi al bordo del riquadro
    # grande o al testo accanto, e allora la finestra misurata ingloba il bordo stampato.
    rx, ry = max(2, int(pw * 0.35)), max(2, int(ph * 0.35))
    x0, y0 = max(0, cx - sx - rx), max(0, cy - sy - ry)
    x1, y1 = min(W, cx - sx + sg.shape[1] + rx), min(H, cy - sy + sg.shape[0] + ry)
    roi = gray[y0:y1, x0:x1]
    if roi.shape[0] < sg.shape[0] or roi.shape[1] < sg.shape[1]:
        return None

    def bordi(a):
        a = cv2.GaussianBlur(a, (0, 0), 1.0)
        gx = cv2.Sobel(a, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(a, cv2.CV_32F, 0, 1, ksize=3)
        return cv2.magnitude(gx, gy)

    try:
        r = cv2.matchTemplate(bordi(roi), bordi(sg), cv2.TM_CCOEFF_NORMED)
    except cv2.error:
        return None

    # A parita' di somiglianza vince la posizione piu' vicina a quella nominale: l'allineamento
    # e' gia' buono, quindi uno spostamento grande e' quasi sempre un aggancio sbagliato.
    ay, ax = np.ogrid[0:r.shape[0], 0:r.shape[1]]
    px_, py_ = (cx - sx) - x0, (cy - sy) - y0
    sig2 = 2.0 * (0.30 * max(pw, ph)) ** 2
    r = r - 0.35 * (1.0 - np.exp(-(((ax - px_) ** 2 + (ay - py_) ** 2) / sig2)))

    _, mx, _, loc = cv2.minMaxLoc(r)
    if mx < 0.15:                                     # nessun quadratino riconoscibile qui
        return None
    ccx, ccy = x0 + loc[0] + sx, y0 + loc[1] + sy      # centro del quadratino nella foto
    return (int(round(ccx - pw / 2)), int(round(ccy - ph / 2)),
            int(round(ccx + pw / 2)), int(round(ccy + ph / 2)))


def _inchiostro(gray, cella_px):
    """Mappa dell'inchiostro: quanto ogni pixel e' piu' scuro del FONDO LOCALE della carta.

    Il fondo si stima con una chiusura morfologica larga quanto la casella: l'operazione
    riempie i tratti scuri sottili (bordo stampato, segno a penna) e lascia solo la carta,
    con la sua ombra e il suo gradiente. Sottraendolo, illuminazione disomogenea, ombra della
    mano ed esposizione si annullano per costruzione. E' il punto che prima mancava: una
    soglia ricavata dal grigio assoluto faceva risultare barrata l'intera casella non appena
    ci passava sopra l'ombra della mano."""
    k = max(3, int(cella_px) | 1)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    fondo = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, ker)
    return cv2.subtract(fondo, gray)                    # > 0 dove c'e' inchiostro


def _misura(ink, box, spessore):
    """Frazione dell'interno del quadratino coperta da inchiostro a mano.
    La scala di riferimento e' il bordo stampato della casella stessa, che c'e' sempre: e'
    l'inchiostro piu' nero che ci si possa aspettare in quel punto della foto, quindi calibra
    la soglia senza dipendere da nessun valore assoluto."""
    x0, y0, x1, y1 = box
    H, W = ink.shape
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None

    d = spessore + max(1, int(0.10 * min(x1 - x0, y1 - y0)))   # esclude il bordo stampato
    if 2 * d >= min(x1 - x0, y1 - y0):
        return None
    inner = ink[y0 + d:y1 - d, x0 + d:x1 - d]
    if inner.size < 9:
        return None

    bordo = ink[y0:y1, x0:x1].copy()
    bordo[d:-d, d:-d] = 0                               # resta solo l'anello del bordo stampato
    vis = bordo[bordo > 0]
    riferimento = float(np.percentile(vis, 90)) if vis.size else 0.0
    if riferimento < CONTRASTO_MIN:
        return None                                     # casella non leggibile (sfocata/bruciata)

    soglia = max(12.0, 0.45 * riferimento)
    return float((inner > soglia).mean())
