#!/usr/bin/env python3
"""
riconoscimento.py - riconoscimento del MOTIVO DI MANCATO RECAPITO. Offline, solo OpenCV/numpy, CPU.

Pipeline:
  1) REGISTRAZIONE: la foto del riquadro viene allineata a un'IMMAGINE DI RIFERIMENTO
     del modello (ORB + omografia). Assorbe spostamento, scala, rotazione e prospettiva
     lieve: cosi' l'inquadratura dell'operatore non deve essere precisa, basta che il
     riquadro sia dentro la guida e ragionevolmente dritto.
  2) MISURA (OMR): su ogni casella (a posizioni fisse nel riferimento) si misura quanto
     inchiostro scuro contiene. Indipendente dallo stile del segno (X, spunta, scarabocchio).
  3) DECISIONE: si propone la casella piu' marcata con un livello di confidenza.
     NON si decide mai da soli: la conferma dell'operatore e' sempre richiesta a valle.

Se la registrazione e' debole (pochi inlier), molto probabilmente la foto NON e' del
modello selezionato (o e' inquadrata male): si segnala e non si propone nulla.
"""
from __future__ import annotations
import json, os
import cv2
import numpy as np

ABS_MIN   = 0.18    # riempimento minimo per "casella marcata" (metodo densità)
ABS_MIN_SUB = 0.04  # idem per il metodo a sottrazione-template (il segno a mano supera questo)
MARGIN    = 1.6     # la migliore deve battere la seconda di questo fattore
WIN_W     = 0.030   # mezza finestra di campionamento (frazione larghezza riferimento)
WIN_H     = 0.022
TPL_ERODE = 7       # dilata (min-filter) il template vuoto: tollera micro-disallineamenti dei bordi
TPL_DELTA = 45      # quanto più scura dev'essere la foto rispetto al template per contare come inchiostro
MIN_INLIER = 12     # inlier ORB minimi per fidarsi della registrazione
AUTO_MIN   = 16     # inlier per considerare l'aggancio "buono" e far scattare l'auto-scansione
                    # (= MIN_INLIER + 6, la stessa soglia oltre cui l'aggancio non e' piu' "debole").
                    # Ritoccala se l'auto-scatto parte troppo presto (alza) o non parte mai (abbassa).

_orb = cv2.ORB_create(1500)
_bf  = cv2.BFMatcher(cv2.NORM_HAMMING)


def carica_template(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        t = json.load(f)
    base = os.path.dirname(path)
    ref_path = os.path.join(base, t["riferimento"])
    t["_ref"] = cv2.imread(ref_path)
    if t["_ref"] is None:
        raise FileNotFoundError(f"immagine di riferimento mancante: {ref_path}")
    w, h = t.get("dim_riferimento", [t["_ref"].shape[1], t["_ref"].shape[0]])
    t["_ref"] = cv2.resize(t["_ref"], (w, h))
    t["_kp"], t["_des"] = _orb.detectAndCompute(cv2.cvtColor(t["_ref"], cv2.COLOR_BGR2GRAY), None)

    # Template del modulo VUOTO (opzionale) per la lettura a sottrazione: deve essere nella
    # stessa cornice del riferimento (600x400 ecc.). Se presente, si legge il SOLO segno a mano
    # (foto - modulo stampato) invece della densità di inchiostro: molto più robusto sui
    # riquadri piccoli, dove il contorno stampato falserebbe la misura.
    if t.get("template"):
        tp = cv2.imread(os.path.join(base, t["template"]))
        if tp is not None:
            tg = cv2.cvtColor(cv2.resize(tp, (w, h)), cv2.COLOR_BGR2GRAY)
            t["_tpl_min"] = cv2.erode(tg, np.ones((TPL_ERODE, TPL_ERODE), np.uint8))
    return t


def _registra(img_bgr, template, warp=True):
    """Allinea img al riferimento. Ritorna (immagine_allineata_BGR, n_inlier).
    Con warp=False salta la deformazione prospettica (costosa) e ritorna (None, n_inlier):
    serve alla sonda dell'auto-scansione, che ha bisogno solo della qualita' dell'aggancio."""
    ref = template["_ref"]; H, W = ref.shape[:2]
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    kp, des = _orb.detectAndCompute(g, None)
    if des is None or template["_des"] is None:
        return None, 0
    matches = _bf.knnMatch(des, template["_des"], k=2)
    good = [a for a, b in (m for m in matches if len(m) == 2) if a.distance < 0.75 * b.distance]
    if len(good) < MIN_INLIER:
        return None, len(good)
    src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([template["_kp"][m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    Hm, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if Hm is None:
        return None, 0
    inl = int(mask.sum())
    if not warp:
        return None, inl
    aligned = cv2.warpPerspective(img_bgr, Hm, (W, H), borderValue=(255, 255, 255))
    return aligned, inl


def qualita_aggancio(img_bgr, template) -> int:
    """Quanti inlier ORB aggancia il fotogramma sul modello. Veloce (niente warp ne' OMR):
    e' la sonda usata dall'auto-scansione per decidere quando far scattare la foto."""
    _, inl = _registra(img_bgr, template, warp=False)
    return inl


def _riempimento(gray, nx, ny, win_w=WIN_W, win_h=WIN_H):
    H, W = gray.shape
    thr = np.percentile(gray, 55) * 0.6        # adattivo al colore della carta (bianco o verde)
    x, y = int(nx * W), int(ny * H)
    hw, hh = max(4, int(win_w * W)), max(4, int(win_h * H))
    p = gray[max(0, y - hh):y + hh, max(0, x - hw):x + hw]
    return float((p < thr).mean()) if p.size else 0.0


def _segno(gray, tpl_min, nx, ny, win_w=WIN_W, win_h=WIN_H, delta=TPL_DELTA):
    """Frazione di 'inchiostro aggiunto a mano' = quanto la foto e' piu' scura del template
    del modulo vuoto. Il riquadro stampato (presente in entrambi) si annulla: resta il segno.
    Cosi' una casella vuota da ~0 e una barrata spicca, anche con contorni stampati spessi."""
    H, W = gray.shape
    x, y = int(nx * W), int(ny * H)
    hw, hh = max(4, int(win_w * W)), max(4, int(win_h * H))
    g = gray[max(0, y - hh):y + hh, max(0, x - hw):x + hw].astype(np.int16)
    t = tpl_min[max(0, y - hh):y + hh, max(0, x - hw):x + hw].astype(np.int16)
    return float(((t - g) > delta).mean()) if g.size else 0.0


def analizza(img_bgr, template, debug=False, include_aligned=False):
    aligned, inl = _registra(img_bgr, template)

    if aligned is None:
        return {"marcato": False, "proposta": None, "etichetta": None, "categoria": None,
                "confidenza": 0.0, "livello": "nessuna", "inlier": inl,
                "avviso_coerenza": "Non riesco ad agganciare il riquadro: la foto potrebbe "
                                   "essere di un altro modello, mossa o inquadrata male. Scegli a mano.",
                "punteggi": {}}

    gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    ww = template.get("win_w", WIN_W); wh = template.get("win_h", WIN_H)
    if "_tpl_min" in template:                 # lettura a sottrazione-template (solo segno a mano)
        abs_min = template.get("abs_min", ABS_MIN_SUB)
        punteggi = {c["id"]: _segno(gray, template["_tpl_min"], c["x"], c["y"], ww, wh)
                    for c in template["caselle"]}
    else:                                       # lettura per densità di inchiostro (fallback)
        abs_min = template.get("abs_min", ABS_MIN)
        punteggi = {c["id"]: _riempimento(gray, c["x"], c["y"], ww, wh) for c in template["caselle"]}
    rank = sorted(punteggi.items(), key=lambda kv: kv[1], reverse=True)
    best_id, best_v = rank[0]
    second_v = rank[1][1] if len(rank) > 1 else 0.0
    by_id = {c["id"]: c for c in template["caselle"]}

    marcato = best_v >= abs_min
    buona = marcato and (second_v <= 1e-6 or best_v >= MARGIN * second_v)

    avviso = None
    if inl < MIN_INLIER + 6:
        avviso = "Aggancio debole: verifica che il modello selezionato sia giusto."

    res = {
        "marcato": bool(marcato),
        "proposta": best_id if buona else None,
        "etichetta": by_id[best_id]["etichetta"] if buona else None,
        "categoria": by_id[best_id]["categoria"] if buona else None,
        "confidenza": round(min(1.0, best_v / max(second_v, abs_min) / MARGIN), 2) if marcato else 0.0,
        "livello": "buona" if buona else ("incerta" if marcato else "nessuna"),
        "inlier": inl,
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
