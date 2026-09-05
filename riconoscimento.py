#!/usr/bin/env python3
"""
riconoscimento.py - riconoscimento del MOTIVO DI MANCATO RECAPITO. Offline, solo OpenCV/numpy, CPU.

Pipeline:
  1) REGISTRAZIONE: la foto viene allineata al MODULO VUOTO del modello (ORB + omografia).
     L'omografia viene VALIDATA (niente ribaltamenti, scale assurde, matrici degeneri) e la
     qualita' dell'allineamento viene misurata davvero, come RESIDUO IN PIXEL sui bordi delle
     caselle: il numero di inlier da solo non dice se l'immagine e' allineata bene.
  2) ANCORAGGIO LOCALE: per ogni casella si ritrova il QUADRATINO STAMPATO nell'immagine
     allineata, cercandolo in un intorno della posizione nominale. Cosi' un residuo di qualche
     pixel dell'omografia non sposta piu' la finestra di misura: e' il singolo punto che rende
     la lettura robusta a inquadrature imperfette.
  3) MISURA: dentro il quadratino trovato (con un margine di sicurezza che esclude il bordo
     stampato) si conta l'inchiostro. La soglia non e' un valore assoluto: si ricava dal
     contrasto LOCALE fra la carta attorno alla casella e il bordo stampato della casella
     stessa, che e' sempre presente. Esposizione, ombre e colore della carta si annullano.
  4) DECISIONE: si propone la casella piu' marcata solo se stacca la seconda di un margine
     ASSOLUTO. NON si decide mai da soli: la conferma dell'operatore e' sempre richiesta.

Se l'allineamento e' debole o il residuo e' alto, non si propone nulla e si spiega perche'.
"""
from __future__ import annotations
import json, os
import cv2
import numpy as np

# --- Decisione. Scala del punteggio: frazione dell'interno della casella coperta da inchiostro
#     a mano. Una casella vuota sta sotto 0.03, una barrata sta tipicamente fra 0.20 e 0.60. ---
ABS_MIN    = 0.10   # sotto questo la casella e' considerata VUOTA. Tarato sul banco di prova
                    # (banco.py): fra 0.08 e 0.12 il risultato non cambia, quindi il valore
                    # sta al centro di un intervallo largo e non e' critico.
MARGINE    = 0.05   # la migliore deve battere la seconda di questa DIFFERENZA.
                    # Differenza e non rapporto: il punteggio ha un fondo additivo (rumore di
                    # carta e di stampa), e su un fondo additivo il rapporto e' instabile.
CONTRASTO_MIN = 25  # differenza minima carta-inchiostro perche' la casella sia misurabile

# --- Registrazione. Le soglie sono espresse nella cornice canonica del modello, quindi
#     restano valide se un giorno si alza la risoluzione del riferimento. ---
MIN_INLIER = 25     # inlier RANSAC minimi per fidarsi dell'allineamento
RESIDUO_MAX = 2.5   # errore residuo massimo (px canonici) sui bordi delle caselle
AUTO_MIN   = 45     # inlier per considerare l'aggancio "buono" e far scattare l'auto-scansione.
                    # Ritoccala se l'auto-scatto parte troppo presto (alza) o mai (abbassa).
SCALA_ORB  = 1.4    # la foto viene normalizzata a questa frazione della larghezza canonica:
                    # ORB non e' invariante alla scala oltre un fattore ~2 e senza questo
                    # una foto ad alta risoluzione perde la maggior parte degli aggganci.

_orb = cv2.ORB_create(4000, scaleFactor=1.15, nlevels=12)
_bf  = cv2.BFMatcher(cv2.NORM_HAMMING)
_clahe = cv2.createCLAHE(2.0, (8, 8))


def _grigio(img_bgr):
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr


def _stima_cella(gray, caselle, W, H):
    """Misura la dimensione del quadratino stampato direttamente sul riferimento, cercandolo
    attorno a ogni casella. Serve ai modelli calibrati prima che il JSON avesse cella_w/cella_h:
    cosi' non vanno ricalibrati a mano."""
    ws, hs = [], []
    r = int(0.045 * W)
    for c in caselle:
        cx, cy = int(c["x"] * W), int(c["y"] * H)
        roi = gray[max(0, cy - r):cy + r, max(0, cx - r):cx + r]
        if roi.size == 0:
            continue
        bw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for k in cnts:
            x, y, w, h = cv2.boundingRect(k)
            if 0.4 * r < w < 1.6 * r and 0.4 * r < h < 1.6 * r and abs(w - h) < 0.5 * r:
                d = abs(x + w / 2 - r) + abs(y + h / 2 - r)
                if best is None or d < best[0]:
                    best = (d, w, h)
        if best:
            ws.append(best[1]); hs.append(best[2])
    if len(ws) < max(2, len(caselle) // 3):
        return None
    return float(np.median(ws)) / W, float(np.median(hs)) / H


def carica_template(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        t = json.load(f)
    base = os.path.dirname(path)
    ref_path = os.path.join(base, t["riferimento"])
    ref = cv2.imread(ref_path)
    if ref is None:
        raise FileNotFoundError(f"immagine di riferimento mancante: {ref_path}")
    w, h = t.get("dim_riferimento", [ref.shape[1], ref.shape[0]])
    t["_ref"] = cv2.resize(ref, (w, h))
    t["_ref_g"] = _grigio(t["_ref"])
    t["_kp"], t["_des"] = _orb.detectAndCompute(_clahe.apply(t["_ref_g"]), None)

    # Geometria della casella stampata: dal JSON se c'e', altrimenti misurata sul riferimento.
    cw, ch = t.get("cella_w"), t.get("cella_h")
    if not (cw and ch):
        stima = _stima_cella(t["_ref_g"], t["caselle"], w, h)
        if stima:
            cw, ch = stima
    t["_cella"] = (cw, ch) if (cw and ch) else None

    # Ritaglio del quadratino VUOTO preso dal riferimento: e' la sagoma usata per ritrovare
    # la casella nella foto (ancoraggio locale). Il riferimento E' il modulo vuoto.
    t["_sagome"] = {}
    if t["_cella"]:
        pw, ph = int(cw * w), int(ch * h)
        mx, my = int(pw * 0.30), int(ph * 0.30)
        for c in t["caselle"]:
            cx, cy = int(c["x"] * w), int(c["y"] * h)
            x0, y0 = max(0, cx - pw // 2 - mx), max(0, cy - ph // 2 - my)
            x1, y1 = min(w, cx + pw // 2 + mx), min(h, cy + ph // 2 + my)
            s = t["_ref_g"][y0:y1, x0:x1]
            if s.size:
                t["_sagome"][c["id"]] = (s, cx - x0, cy - y0)   # sagoma + centro dentro la sagoma
    return t


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


def analizza(img_bgr, template, debug=False, include_aligned=False):
    aligned, diag = _registra(img_bgr, template)
    caselle = template["caselle"]
    by_id = {c["id"]: c for c in caselle}

    if aligned is None:
        return {"marcato": False, "proposta": None, "etichetta": None, "categoria": None,
                "confidenza": 0.0, "livello": "nessuna", "inlier": diag["inlier"],
                "residuo": None,
                "avviso_coerenza": "Non riesco ad agganciare il riquadro: " +
                                   (diag["motivo"] or "inquadratura non utilizzabile") +
                                   ". Scegli a mano.",
                "punteggi": {}}

    gray = _grigio(aligned)
    H, W = gray.shape
    residuo = diag["residuo"]

    punteggi, illeggibili = {}, []
    if template["_cella"]:
        spess = max(1, int(0.09 * template["_cella"][1] * H))
        ink = _inchiostro(gray, template["_cella"][1] * H * 1.4)
        for c in caselle:
            box = _ancora(gray, template, c, W, H)
            v = _misura(ink, box, spess) if box else None
            if v is None:
                illeggibili.append(c["id"]); punteggi[c["id"]] = 0.0
            else:
                punteggi[c["id"]] = v
    else:
        illeggibili = [c["id"] for c in caselle]
        punteggi = {c["id"]: 0.0 for c in caselle}

    rank = sorted(punteggi.items(), key=lambda kv: kv[1], reverse=True)
    best_id, best_v = rank[0]
    second_v = rank[1][1] if len(rank) > 1 else 0.0

    marcato = best_v >= ABS_MIN
    stacca = (best_v - second_v) >= MARGINE
    buona = marcato and stacca

    # Due caselle barrate (capita: una per il destinatario, una per l'indirizzo). Proporne una
    # sola nasconderebbe l'altra, e nessuno se ne accorgerebbe: meglio non proporre e dirlo.
    # Vale anche quando una delle due stacca nettamente l'altra: e' proprio il caso in cui
    # una proposta sicura di se' farebbe perdere il secondo segno in silenzio.
    forti = [cid for cid, v in punteggi.items() if v >= ABS_MIN]
    doppia = len(forti) > 1

    avviso = None
    if len(illeggibili) > len(caselle) // 2:
        avviso = "Molte caselle non sono leggibili: foto sfocata o riflesso. Rifai la foto."
    elif doppia:
        avviso = ("Sembrano barrate piu' caselle (" +
                  ", ".join(by_id[c]["etichetta"].split(" - ")[-1] for c in forti) +
                  "): scegli tu quella giusta.")
        buona = False
    elif residuo is not None and residuo > RESIDUO_MAX:
        avviso = "Allineamento impreciso: tieni il telefono piu' fermo e parallelo alla busta."
        buona = False
    elif diag["inlier"] < MIN_INLIER * 2:
        avviso = "Aggancio debole: verifica che il modello selezionato sia giusto."

    # Confidenza monotona: quanto la migliore stacca la seconda, in unita' di MARGINE.
    conf = 0.0
    if marcato:
        conf = round(float(min(1.0, max(0.0, (best_v - second_v) / MARGINE))), 2)

    res = {
        "marcato": bool(marcato),
        "proposta": best_id if buona else None,
        "etichetta": by_id[best_id]["etichetta"] if buona else None,
        "categoria": by_id[best_id]["categoria"] if buona else None,
        "confidenza": conf if buona else 0.0,
        "livello": "buona" if buona else ("incerta" if marcato else "nessuna"),
        "inlier": diag["inlier"],
        "residuo": round(residuo, 2) if residuo is not None else None,
        "illeggibili": illeggibili,
        "avviso_coerenza": avviso,
        "punteggi": {k: round(v, 3) for k, v in punteggi.items()},
    }
    if debug:
        cv2.imwrite("_aligned_debug.png", aligned)
    if include_aligned:
        res["_aligned"] = aligned
    return res


if __name__ == "__main__":
    import sys
    img = cv2.imread(sys.argv[1])
    tpl = carica_template(sys.argv[2])
    print(json.dumps({k: v for k, v in analizza(img, tpl, debug=True).items()
                      if not k.startswith("_")}, ensure_ascii=False, indent=2))
