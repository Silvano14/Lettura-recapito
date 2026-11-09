"""
registrazione.py - passo 1 della pipeline: allinea la foto al MODULO VUOTO del modello
(ORB + omografia), valida l'omografia e ne misura la qualita' come residuo in pixel.
Usato da riconoscimento.py; la sonda dell'auto-scansione passa da qualita_aggancio.
"""
from __future__ import annotations
import cv2
import numpy as np

from soglie import MIN_INLIER, SCALA_ORB

# Oggetti OpenCV condivisi anche da carica_template (riconoscimento.py): il riferimento e la
# foto devono passare dallo STESSO ORB e dallo stesso CLAHE, o i descrittori non combaciano.
_orb = cv2.ORB_create(4000, scaleFactor=1.15, nlevels=12)
_bf  = cv2.BFMatcher(cv2.NORM_HAMMING)
_clahe = cv2.createCLAHE(2.0, (8, 8))


def _grigio(img_bgr):
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr


def _valida_omografia(Hm, W, H) -> bool:
    """Un'omografia va usata solo se e' geometricamente plausibile. findHomography restituisce
    volentieri ribaltamenti e matrici quasi singolari quando i match sono sporchi, e senza
    questo controllo diventano proposte confidenti sulla casella sbagliata."""
    if Hm is None or not np.all(np.isfinite(Hm)):
        return False
    A = Hm[:2, :2]
    det = float(np.linalg.det(A))
    if det <= 0:                          # ribaltamento: la busta non si legge allo specchio
        return False
    sv = np.linalg.svd(A, compute_uv=False)
    if sv[1] < 1e-6 or sv[0] / sv[1] > 4.0:     # troppo schiacciata / degenere
        return False
    if not (0.15 < np.sqrt(det) < 6.0):         # scala assurda
        return False
    # i 4 angoli del riferimento devono provenire da un quadrilatero convesso e non minuscolo
    inv = np.linalg.inv(Hm)
    ang = cv2.perspectiveTransform(
        np.float32([[[0, 0]], [[W, 0]], [[W, H]], [[0, H]]]), inv).reshape(-1, 2)
    if not np.all(np.isfinite(ang)):
        return False
    area = cv2.contourArea(ang.astype(np.float32))
    return area > 0.02 * W * H and cv2.isContourConvex(ang.astype(np.float32))


def _residuo(al_g, ref_g, caselle, W, H) -> float:
    """Errore residuo di allineamento in pixel canonici, misurato dove conta davvero: attorno
    alle caselle. E' la grandezza che il conteggio di inlier NON misura."""
    errs = []
    r = int(0.05 * W)
    for c in caselle:
        x, y = int(c["x"] * W), int(c["y"] * H)
        a = ref_g[max(0, y - r):y + r, max(0, x - r):x + r].astype(np.float32)
        b = al_g[max(0, y - r):y + r, max(0, x - r):x + r].astype(np.float32)
        if a.shape != b.shape or a.size == 0:
            continue
        try:
            (dx, dy), _ = cv2.phaseCorrelate(a, b)
            errs.append(float(np.hypot(dx, dy)))
        except cv2.error:
            pass
    return float(np.median(errs)) if errs else 99.0


def _registra(img_bgr, template, warp=True):
    """Allinea img al riferimento. Ritorna (immagine_allineata_BGR, diagnostica).
    Con warp=False salta la deformazione prospettica (costosa) e ritorna (None, diagnostica):
    serve alla sonda dell'auto-scansione, che ha bisogno solo della qualita' dell'aggancio."""
    ref = template["_ref"]; H, W = ref.shape[:2]
    diag = {"inlier": 0, "residuo": None, "motivo": None}

    g = _grigio(img_bgr)
    # Normalizzazione di scala: ORB regge male oltre ~2x di differenza dal riferimento.
    k = (SCALA_ORB * W) / max(g.shape[1], 1)
    if k < 0.95:
        g = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    else:
        k = 1.0
    g = _clahe.apply(g)

    kp, des = _orb.detectAndCompute(g, None)
    if des is None or template["_des"] is None or len(des) < 8:
        diag["motivo"] = "pochi dettagli nella foto (sfocata o troppo scura)"
        return None, diag

    matches = _bf.knnMatch(des, template["_des"], k=2)
    good = [a for a, b in (m for m in matches if len(m) == 2) if a.distance < 0.75 * b.distance]
    if len(good) < 8:
        diag["motivo"] = "il riquadro non somiglia al modello scelto"
        return None, diag

    src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2) / k
    dst = np.float32([template["_kp"][m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    Hm, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if not _valida_omografia(Hm, W, H):
        diag["motivo"] = "allineamento geometricamente impossibile"
        return None, diag

    inl = int(mask.sum())
    diag["inlier"] = inl
    # Il controllo sugli inlier RANSAC e' il punto chiave: prima veniva confrontato solo il
    # numero di match grezzi, e omografie con pochissimi inlier passavano come buone.
    if inl < MIN_INLIER:
        diag["motivo"] = f"aggancio troppo debole ({inl} riscontri, ne servono {MIN_INLIER})"
        return None, diag
    if not warp:
        return None, diag

    aligned = cv2.warpPerspective(img_bgr, Hm, (W, H), flags=cv2.INTER_CUBIC,
                                  borderValue=(255, 255, 255))
    diag["residuo"] = _residuo(_grigio(aligned), template["_ref_g"], template["caselle"], W, H)
    return aligned, diag


def qualita_aggancio(img_bgr, template) -> int:
    """Quanti inlier ORB aggancia il fotogramma sul modello. Veloce (niente warp ne' misura):
    e' la sonda usata dall'auto-scansione per decidere quando far scattare la foto."""
    _, d = _registra(img_bgr, template, warp=False)
    return d["inlier"]
