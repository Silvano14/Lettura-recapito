#!/usr/bin/env python3
"""
server.py - server locale (rete chiusa) per il riconoscimento del mancato recapito.

Avvio:
    pip install flask opencv-python-headless numpy
    python server.py                       # http://<ip-del-pc>:8000  (in LAN)
    python server.py --https               # https con certificato autofirmato (serve: pip install pyopenssl)

La fotocamera del telefono (getUserMedia, per avere la guida sovrapposta) richiede un
contesto sicuro: usa --https oppure apri da localhost. In alternativa l'interfaccia
ripiega automaticamente sullo scatto con la fotocamera nativa (senza guida).

Endpoint:
    GET  /              pagina di acquisizione (mobile)
    GET  /modelli       elenco dei modelli calibrati disponibili
    GET  /riferimento/<id>  immagine di riferimento del modello (sagoma-guida sulla camera)
    POST /analizza      form-data: foto=<jpg>, modello=<id>  -> JSON proposta+caselle+anteprima
    POST /aggancio      form-data: foto=<jpg>, modello=<id>  -> JSON {inlier, ok}  (sonda auto-scansione)
    POST /salva         JSON: {codice, modello, casella_id, etichetta}  -> registra a DB
"""
import argparse, base64, glob, io, json, os, sqlite3, datetime
import cv2
import numpy as np
from flask import Flask, request, jsonify, render_template, send_from_directory

import riconoscimento as R

BASE = os.path.dirname(os.path.abspath(__file__))
MODELLI_DIR = os.path.join(BASE, "modelli")
DB = os.path.join(BASE, "recapiti.db")

app = Flask(__name__)
_cache = {}   # id_modello -> template caricato


def _templates():
    out = {}
    for p in glob.glob(os.path.join(MODELLI_DIR, "*.json")):
        mid = os.path.splitext(os.path.basename(p))[0]
        out[mid] = p
    return out


def _get_template(mid):
    if mid not in _cache:
        _cache[mid] = R.carica_template(_templates()[mid])
    return _cache[mid]


def _init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS recapiti(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, codice TEXT, modello TEXT, casella_id TEXT, etichetta TEXT, qr TEXT)""")
    # migrazione: aggiunge la colonna qr ai DB creati prima di questa versione
    cols = {r[1] for r in con.execute("PRAGMA table_info(recapiti)")}
    if "qr" not in cols:
        con.execute("ALTER TABLE recapiti ADD COLUMN qr TEXT")
    con.commit(); con.close()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/modelli")
def modelli():
    out = []
    for mid, path in _templates().items():
        with open(path, encoding="utf-8") as f:
            t = json.load(f)
        out.append({"id": mid, "nome": t.get("modello", mid),
                    "predefinito": bool(t.get("predefinito", False)),
                    "leggi_qr": bool(t.get("leggi_qr", False)),   # leggere il QR (dal fotogramma intero)
                    "caselle": [{"id": c["id"], "etichetta": c["etichetta"],
                                 "categoria": c["categoria"]} for c in t["caselle"]]})
    return jsonify(sorted(out, key=lambda x: x["nome"]))


@app.get("/riferimento/<mid>")
def riferimento(mid):
    """Immagine di riferimento del modello: serve al client come sagoma-guida
    semitrasparente sovrapposta alla fotocamera (aiuta a centrare la busta)."""
    path = _templates().get(mid)
    if not path:
        return "", 404
    with open(path, encoding="utf-8") as f:
        t = json.load(f)
    return send_from_directory(MODELLI_DIR, t["riferimento"])


@app.post("/analizza")
def analizza():
    f = request.files.get("foto")
    mid = request.form.get("modello")
    if not f or not mid:
        return jsonify({"errore": "foto o modello mancanti"}), 400
    data = np.frombuffer(f.read(), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"errore": "immagine non leggibile"}), 400

    tpl = _get_template(mid)
    res = R.analizza(img, tpl, include_aligned=True)

    # DEBUG temporaneo: salva ciò che il telefono ha mandato e come è stato allineato,
    # con le finestre OMR e i punteggi disegnati. File in questa cartella, sovrascritti ogni volta.
    if os.environ.get("DBG_OMR", "0") == "1":
        try:
            cv2.imwrite(os.path.join(BASE, "_dbg_crop.jpg"), img)
            al = res.get("_aligned")
            if al is not None:
                dbg = al.copy(); H, W = dbg.shape[:2]
                ww = tpl.get("win_w", R.WIN_W); wh = tpl.get("win_h", R.WIN_H)
                for c in tpl["caselle"]:
                    cx, cy = int(c["x"] * W), int(c["y"] * H)
                    hw, hh = int(ww * W), int(wh * H)
                    sc = res["punteggi"].get(c["id"], 0)
                    col = (0, 0, 255) if c["id"] == res.get("proposta") else (0, 170, 0)
                    cv2.rectangle(dbg, (cx - hw, cy - hh), (cx + hw, cy + hh), col, 1)
                    cv2.putText(dbg, f"{sc:.2f}", (cx - hw, cy - hh - 2),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.32, col, 1)
                cv2.imwrite(os.path.join(BASE, "_dbg_aligned.png"), dbg)
        except Exception:
            pass

    anteprima = None
    if "_aligned" in res:
        ok, buf = cv2.imencode(".jpg", res.pop("_aligned"), [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            anteprima = "data:image/jpeg;base64," + base64.b64encode(buf).decode()

    res["anteprima"] = anteprima
    res["caselle"] = [{"id": c["id"], "etichetta": c["etichetta"], "categoria": c["categoria"]}
                      for c in tpl["caselle"]]
    return jsonify({k: v for k, v in res.items() if not k.startswith("_")})


@app.post("/aggancio")
def aggancio():
    """Sonda leggera per l'auto-scansione: misura solo la qualita' dell'aggancio del
    fotogramma in diretta, senza lettura caselle ne' anteprima. Chiamata di continuo dal
    telefono mentre inquadra; quando 'ok' resta vero per qualche fotogramma, il client
    fa partire da solo /analizza a piena risoluzione."""
    f = request.files.get("foto")
    mid = request.form.get("modello")
    if not f or not mid:
        return jsonify({"errore": "foto o modello mancanti"}), 400
    data = np.frombuffer(f.read(), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"inlier": 0, "ok": False, "soglia": R.AUTO_MIN})
    inl = R.qualita_aggancio(img, _get_template(mid))
    return jsonify({"inlier": inl, "ok": inl >= R.AUTO_MIN, "soglia": R.AUTO_MIN})


@app.post("/salva")
def salva():
    d = request.get_json(force=True)
    if not d.get("casella_id"):
        return jsonify({"errore": "nessuna casella selezionata"}), 400
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO recapiti(ts,codice,modello,casella_id,etichetta,qr) VALUES(?,?,?,?,?,?)",
                (datetime.datetime.now().isoformat(timespec="seconds"),
                 d.get("codice", ""), d.get("modello", ""), d["casella_id"],
                 d.get("etichetta", ""), d.get("qr", "")))
    con.commit(); con.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--https", action="store_true", help="HTTPS autofirmato (per la fotocamera col guida)")
    args = ap.parse_args()
    _init_db()
    ssl = "adhoc" if args.https else None
    app.run(host=args.host, port=args.port, ssl_context=ssl, debug=False)
