#!/usr/bin/env python3
"""
banco.py - banco di prova sintetico per il riconoscimento del mancato recapito.

Serve a rispondere con dei numeri alla domanda "funziona?", invece che a occhio su una foto.
Genera foto realistiche del riquadro partendo dal MODULO VUOTO del modello, ci disegna sopra
un segno a mano di stile variabile e applica i degradi di una foto scattata col telefono
(prospettiva, rotazione, sfocatura, illuminazione disomogenea, riflesso, rumore, JPEG e
ritaglio impreciso della cornice-guida). Poi confronta la proposta con la verita' nota.

    python banco.py                      # banco standard sul modello predefinito
    python banco.py --modello mod24b
    python banco.py --casi 40            # piu' casi per casella (piu' lento, piu' stabile)
    python banco.py --salva-errori dir/  # scrive le foto sbagliate per guardarle

ONESTA' DEL BANCO: le foto derivano dalla stessa immagine usata come riferimento, quindi
condividono texture di stampa e resa della carta. I numeri qui sono un LIMITE SUPERIORE:
sul campo ci si aspetta qualcosa di meno. Serve per confrontare due versioni del codice
sullo stesso metro, non per promettere una percentuale all'operatore.
"""
from __future__ import annotations
import argparse, glob, json, os, sys
import cv2
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
STILI = ("x", "spunta", "barra", "scarabocchio", "esce", "leggero", "pennarello")


def _segno(img, c, W, H, cw, ch, stile, rng):
    """Disegna un segno a mano plausibile dentro la casella."""
    x, y = int(c["x"] * W), int(c["y"] * H)
    a, b = int(cw * W * 0.34), int(ch * H * 0.34)       # semi-ampiezza dentro il quadratino
    sp = max(1, int(cw * W * 0.075))
    col = int(rng.uniform(25, 70))
    jx, jy = int(rng.uniform(-a * 0.2, a * 0.2)), int(rng.uniform(-b * 0.2, b * 0.2))
    x, y = x + jx, y + jy
    ink = (col, col, col + 6)
    if stile == "leggero":
        ink = (135, 135, 140); sp = max(1, sp - 1)
    elif stile == "pennarello":
        sp += 2
    elif stile == "esce":
        a, b = int(a * 1.9), int(b * 1.9)

    if stile in ("x", "esce", "leggero", "pennarello"):
        cv2.line(img, (x - a, y - b), (x + a, y + b), ink, sp, cv2.LINE_AA)
        cv2.line(img, (x - a, y + b), (x + a, y - b), ink, sp, cv2.LINE_AA)
    elif stile == "spunta":
        cv2.polylines(img, [np.int32([[x - a, y], [x - a // 3, y + b], [x + a, y - b]])],
                      False, ink, sp, cv2.LINE_AA)
    elif stile == "barra":
        cv2.line(img, (x - a, y + b), (x + a, y - b), ink, sp, cv2.LINE_AA)
    elif stile == "scarabocchio":
        pts = np.int32([[x - a, y - b // 2], [x + a // 3, y + b], [x - a // 2, y + b],
                        [x + a, y - b], [x - a // 4, y + b]])
        cv2.polylines(img, [pts], False, ink, sp, cv2.LINE_AA)
    return img


def _degrada(img, sev, rng):
    """Degradi di una foto col telefono. sev in 0..1 = quanto e' brutta la foto."""
    h, w = img.shape[:2]
    big = cv2.resize(img, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)
    bh, bw = big.shape[:2]

    d = np.tan(np.radians(12 * sev)) * bw * 0.5
    src = np.float32([[0, 0], [bw, 0], [bw, bh], [0, bh]])
    dst = np.float32([[d * rng.uniform(.2, 1), d * rng.uniform(0, .5)],
                      [bw - d * rng.uniform(0, .8), d * rng.uniform(0, .5)],
                      [bw - d * rng.uniform(.2, 1), bh - d * rng.uniform(0, .4)],
                      [d * rng.uniform(0, .8), bh - d * rng.uniform(0, .4)]])
    out = cv2.warpPerspective(big, cv2.getPerspectiveTransform(src, dst), (bw, bh),
                              borderValue=(235, 235, 235))
    rot = rng.uniform(-7, 7) * sev
    out = cv2.warpAffine(out, cv2.getRotationMatrix2D((bw / 2, bh / 2), rot, 1.0), (bw, bh),
                         borderValue=(235, 235, 235))

    # ritaglio impreciso della cornice-guida: l'operatore non centra mai perfettamente
    m = 0.09 * sev
    dx, dy = int(m * bw), int(m * bh)
    if dx > 1 and dy > 1:
        x0 = max(0, dx + int(rng.uniform(-dx, dx))); y0 = max(0, dy + int(rng.uniform(-dy, dy)))
        x1 = min(bw, bw - dx + int(rng.uniform(-dx, dx))); y1 = min(bh, bh - dy + int(rng.uniform(-dy, dy)))
        if x1 - x0 > bw * 0.5 and y1 - y0 > bh * 0.5:
            out = out[y0:y1, x0:x1]

    hh, ww = out.shape[:2]
    f = out.astype(np.float32)
    # illuminazione disomogenea + ombra della mano
    gx = np.linspace(1 - .3 * sev, 1 + .3 * sev, ww)[None, :]
    gy = np.linspace(1 + .18 * sev, 1 - .18 * sev, hh)[:, None]
    f *= (gx * gy)[:, :, None]
    if sev > .4:
        ox, oy = int(rng.uniform(0, ww * .6)), int(rng.uniform(0, hh * .6))
        sh = np.ones((hh, ww), np.float32)
        cv2.ellipse(sh, (ox, oy), (int(ww * .35), int(hh * .5)), 0, 0, 360, 1 - .28 * sev, -1)
        f *= cv2.GaussianBlur(sh, (0, 0), 40)[:, :, None]
    # riflesso speculare
    if sev > .55:
        rx, ry = int(rng.uniform(0, ww)), int(rng.uniform(0, hh))
        gl = np.zeros((hh, ww), np.float32)
        cv2.ellipse(gl, (rx, ry), (int(ww * .16), int(hh * .1)), rng.uniform(0, 180), 0, 360, 1, -1)
        f += cv2.GaussianBlur(gl, (0, 0), 25)[:, :, None] * 70 * sev
    f *= rng.uniform(0.80, 1.20)                     # esposizione complessiva
    out = np.clip(f, 0, 255).astype(np.uint8)

    out = cv2.GaussianBlur(out, (0, 0), max(0.4, 2.4 * sev))
    if sev > .5:                                      # mosso
        k = max(3, int(5 * sev) | 1)
        ker = np.zeros((k, k), np.float32); ker[k // 2, :] = 1.0 / k
        out = cv2.filter2D(out, -1, cv2.warpAffine(
            ker, cv2.getRotationMatrix2D((k / 2, k / 2), rng.uniform(0, 180), 1), (k, k)))
    out = np.clip(out.astype(np.int16) + rng.normal(0, 3 + 4 * sev, out.shape).astype(np.int16),
                  0, 255).astype(np.uint8)
    q = int(90 - 30 * sev)
    return cv2.imdecode(cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, q])[1], cv2.IMREAD_COLOR)


def genera(modello_json, per_casella=8, seed=12345):
    """Dataset deterministico: (immagine, insieme delle caselle davvero barrate)."""
    with open(modello_json, encoding="utf-8") as f:
        mod = json.load(f)
    base = os.path.dirname(modello_json)
    vuoto = cv2.imread(os.path.join(base, mod.get("template") or mod["riferimento"]))
    W, H = mod.get("dim_riferimento", [vuoto.shape[1], vuoto.shape[0]])
    vuoto = cv2.resize(vuoto, (W, H))
    cw = mod.get("cella_w") or 0.037
    ch = mod.get("cella_h") or 0.077

    rng = np.random.RandomState(seed)
    casi = []
    for c in mod["caselle"]:
        for i in range(per_casella):
            st = STILI[i % len(STILI)]
            sev = (i % 4) / 3.0                      # da foto pulita a foto pessima
            im = _segno(vuoto.copy(), c, W, H, cw, ch, st, rng)
            casi.append((_degrada(im, sev, rng), {c["id"]}, st, round(sev, 2)))
    # nessun segno: il sistema NON deve proporre
    for i in range(max(2, per_casella)):
        casi.append((_degrada(vuoto.copy(), (i % 4) / 3.0, rng), set(), "vuoto", round((i % 4) / 3.0, 2)))
    # due segni: il sistema deve avvisare, non scegliere per conto suo
    dest = [c for c in mod["caselle"] if c["categoria"] == "destinatario"]
    ind = [c for c in mod["caselle"] if c["categoria"] != "destinatario"]
    for i in range(max(2, per_casella)):
        if not dest or not ind:
            break
        a, b = dest[i % len(dest)], ind[i % len(ind)]
        im = _segno(_segno(vuoto.copy(), a, W, H, cw, ch, "x", rng), b, W, H, cw, ch, "spunta", rng)
        casi.append((_degrada(im, (i % 3) / 3.0, rng), {a["id"], b["id"]}, "doppio", round((i % 3) / 3.0, 2)))
    return casi, mod


def valuta(casi, tpl, ric, salva_errori=None):
    ok = sbagliate = nessuna = 0
    per_stile, per_sev = {}, {}
    if salva_errori:
        os.makedirs(salva_errori, exist_ok=True)
    for i, (img, veri, stile, sev) in enumerate(casi):
        r = ric.analizza(img, tpl)
        p = r.get("proposta")
        if len(veri) == 1:
            esito = "ok" if p in veri else ("sbagliata" if p else "nessuna")
        else:                       # 0 o 2 segni: qualunque proposta e' un errore
            esito = "sbagliata" if p else "ok"
        if esito == "ok": ok += 1
        elif esito == "sbagliata": sbagliate += 1
        else: nessuna += 1
        per_stile.setdefault(stile, [0, 0, 0])[{"ok": 0, "sbagliata": 1, "nessuna": 2}[esito]] += 1
        per_sev.setdefault(sev, [0, 0, 0])[{"ok": 0, "sbagliata": 1, "nessuna": 2}[esito]] += 1
        if salva_errori and esito != "ok":
            cv2.imwrite(os.path.join(salva_errori, f"{i:04d}_{stile}_{esito}_{p}.jpg"), img)
    return {"ok": ok, "sbagliate": sbagliate, "nessuna": nessuna, "tot": len(casi),
            "per_stile": per_stile, "per_sev": per_sev}


def _stampa(nome, s):
    t = s["tot"]
    print(f"\n{nome}: {t} foto")
    print(f"  corrette          {s['ok']:4d}  ({100*s['ok']/t:5.1f}%)")
    print(f"  PROPOSTE SBAGLIATE{s['sbagliate']:4d}  ({100*s['sbagliate']/t:5.1f}%)   <- il caso pericoloso")
    print(f"  nessuna proposta  {s['nessuna']:4d}  ({100*s['nessuna']/t:5.1f}%)   <- ricade sull'operatore")
    print("  per stile di segno:")
    for k in sorted(s["per_stile"]):
        o, w, n = s["per_stile"][k]
        print(f"    {k:14s} corrette {100*o/(o+w+n):5.1f}%  sbagliate {w:3d}  nessuna {n:3d}")
    print("  per severita' del degrado (0 = foto pulita, 1 = pessima):")
    for k in sorted(s["per_sev"]):
        o, w, n = s["per_sev"][k]
        print(f"    {k:<14} corrette {100*o/(o+w+n):5.1f}%  sbagliate {w:3d}  nessuna {n:3d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modello", default=None, help="id del modello (default: il predefinito)")
    ap.add_argument("--casi", type=int, default=8, help="foto per casella (default 8)")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--salva-errori", default=None, help="cartella dove salvare le foto sbagliate")
    a = ap.parse_args()

    modelli = {os.path.splitext(os.path.basename(p))[0]: p
               for p in glob.glob(os.path.join(BASE, "modelli", "*.json"))}
    mid = a.modello
    if not mid:
        for k, p in sorted(modelli.items()):
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("predefinito"):
                    mid = k; break
        mid = mid or sorted(modelli)[0]
    if mid not in modelli:
        print(f"modello sconosciuto: {mid}. Disponibili: {', '.join(sorted(modelli))}"); return 2

    import riconoscimento as ric
    casi, _ = genera(modelli[mid], a.casi, a.seed)
    tpl = ric.carica_template(modelli[mid])
    _stampa(f"modello {mid}", valuta(casi, tpl, ric, a.salva_errori))
    return 0


if __name__ == "__main__":
    sys.exit(main())
