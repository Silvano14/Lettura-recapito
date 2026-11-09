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

Dove sta il codice: il passo 1 in registrazione.py, i passi 2-3 in misura_caselle.py, le
soglie in soglie.py. Questo modulo resta l'unica porta d'ingresso (carica_template, analizza,
qualita_aggancio, le soglie ri-esportate): server.py e banco.py importano solo da qui.
"""
from __future__ import annotations
import json, os
import cv2
import numpy as np

# Ri-esportate: server.py legge R.AUTO_MIN, e chi tara il riconoscimento le trova anche qui.
from soglie import (ABS_MIN, MARGINE, CONTRASTO_MIN, MIN_INLIER,  # noqa: F401
                    RESIDUO_MAX, AUTO_MIN, SCALA_ORB)
from registrazione import _grigio, _orb, _clahe, _registra, qualita_aggancio  # noqa: F401
from misura_caselle import _ancora, _inchiostro, _misura


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
