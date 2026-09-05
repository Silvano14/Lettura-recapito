#!/usr/bin/env python3
"""
server.py - server locale (rete chiusa) per il riconoscimento del mancato recapito.

Avvio:
    pip install flask opencv-python-headless numpy
    python server.py                       # http://<ip-del-pc>:8000  (in LAN)
    python server.py --https               # https con certificato autofirmato (serve: pip install pyopenssl)

La fotocamera del telefono (getUserMedia, per avere la guida sovrapposta) richiede un
contesto sicuro: usa --https oppure apri da localhost. In alternativa l'interfaccia
ripiega sullo scatto con la fotocamera nativa (senza guida) e lo DICE all'operatore.

Endpoint:
    GET  /              pagina di acquisizione (mobile)
    GET  /modelli       elenco dei modelli calibrati disponibili
    GET  /riferimento/<id>  immagine di riferimento del modello (sagoma-guida sulla camera)
    POST /analizza      form-data: foto=<jpg>, modello=<id>  -> JSON proposta+caselle+anteprima
    POST /aggancio      form-data: foto=<jpg>, modello=<id>  -> JSON {inlier, ok}  (sonda auto-scansione)
    POST /salva         JSON: {codice, modello, casella_id, etichetta}  -> registra a DB
"""
import argparse, base64, datetime, glob, json, logging, os, sqlite3
import cv2
import numpy as np
from flask import Flask, request, jsonify, render_template, send_from_directory

import riconoscimento as R

BASE = os.path.dirname(os.path.abspath(__file__))
MODELLI_DIR = os.path.join(BASE, "modelli")
DB = os.path.join(BASE, "recapiti.db")
LOG_ESITI = os.path.join(BASE, "esiti.jsonl")

MAX_UPLOAD = 12 * 1024 * 1024     # una foto di telefono sta ampiamente sotto
MAX_PIXEL  = 40_000_000           # difesa contro immagini-bomba (PNG piccolo, decompresso enorme)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD
log = logging.getLogger("recapiti")

_cache = {}   # id_modello -> (mtime, template caricato)


def _templates():
    out = {}
    for p in glob.glob(os.path.join(MODELLI_DIR, "*.json")):
        out[os.path.splitext(os.path.basename(p))[0]] = p
    return out


def _get_template(mid):
    """Template caricato, con cache invalidata quando il file cambia: dopo una ricalibrazione
    il server non deve continuare a servire le caselle vecchie."""
    path = _templates().get(mid)
    if not path:
        return None
    mt = os.path.getmtime(path)
    hit = _cache.get(mid)
    if not hit or hit[0] != mt:
        _cache[mid] = (mt, R.carica_template(path))
    return _cache[mid][1]


def _leggi_foto(req):
    """(immagine, errore). Nessun input dal telefono deve poter far cadere il server."""
    f = req.files.get("foto")
    mid = req.form.get("modello")
    if not f or not mid:
        return None, None, "foto o modello mancanti"
    try:
        raw = f.read()
    except Exception:
        return None, mid, "upload interrotto"
    if not raw:
        return None, mid, "foto vuota"
    try:
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        img = None
    if img is None:
        return None, mid, "immagine non leggibile"
    if img.shape[0] * img.shape[1] > MAX_PIXEL:
        return None, mid, "immagine troppo grande"
    return img, mid, None


def _init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS recapiti(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, codice TEXT, modello TEXT, casella_id TEXT, etichetta TEXT, qr TEXT)""")
    cols = {r[1] for r in con.execute("PRAGMA table_info(recapiti)")}
    if "qr" not in cols:
        con.execute("ALTER TABLE recapiti ADD COLUMN qr TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_recapiti_ts ON recapiti(ts)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_recapiti_codice ON recapiti(codice)")
    con.commit(); con.close()


def _traccia(evento, dati):
    """Traccia l'esito di ogni analisi, senza immagini e senza dati del destinatario: serve a
    capire un fallimento sul campo, che altrimenti non lascia nessuna traccia (e' successo)."""
    try:
        with open(LOG_ESITI, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                "evento": evento, **dati}, ensure_ascii=False) + "\n")
    except OSError:
        pass


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/modelli")
def modelli():
    """Un modello con il JSON rotto non deve rendere inutilizzabile tutta l'applicazione:
    si salta quello e si servono gli altri."""
    out = []
    for mid, path in _templates().items():
        try:
            with open(path, encoding="utf-8") as f:
                t = json.load(f)
            out.append({"id": mid, "nome": t.get("modello", mid),
                        "predefinito": bool(t.get("predefinito", False)),
                        "leggi_qr": bool(t.get("leggi_qr", False)),
                        "dim_riferimento": t.get("dim_riferimento"),   # il client ne ricava il rapporto della cornice
                        "caselle": [{"id": c["id"], "etichetta": c["etichetta"],
                                     "categoria": c["categoria"]} for c in t["caselle"]]})
        except (ValueError, KeyError, OSError) as e:
            log.warning("modello %s illeggibile, lo salto: %s", mid, e)
    return jsonify(sorted(out, key=lambda x: x["nome"]))


@app.get("/riferimento/<mid>")
def riferimento(mid):
    """Immagine di riferimento del modello: serve al client come sagoma-guida
    semitrasparente sovrapposta alla fotocamera (aiuta a centrare la busta)."""
    path = _templates().get(mid)
    if not path:
        return "", 404
    try:
        with open(path, encoding="utf-8") as f:
            nome = json.load(f)["riferimento"]
    except (ValueError, KeyError, OSError):
        return "", 404
    return send_from_directory(MODELLI_DIR, nome)


@app.post("/analizza")
def analizza():
    img, mid, err = _leggi_foto(request)
    if err:
        return jsonify({"errore": err}), 400
    tpl = _get_template(mid)
    if tpl is None:
        return jsonify({"errore": f"modello sconosciuto: {mid}"}), 400

    try:
        res = R.analizza(img, tpl, include_aligned=True)
    except Exception:
        log.exception("analisi fallita")
        return jsonify({"errore": "analisi fallita sul server"}), 500

    _traccia("analizza", {"modello": mid, "px": f"{img.shape[1]}x{img.shape[0]}",
                          "inlier": res.get("inlier"), "residuo": res.get("residuo"),
                          "livello": res.get("livello"), "proposta": res.get("proposta"),
                          "illeggibili": res.get("illeggibili"),
                          "punteggi": res.get("punteggi")})

    if os.environ.get("DBG_OMR", "0") == "1":
        try:
            cv2.imwrite(os.path.join(BASE, "_dbg_crop.jpg"), img)
            al = res.get("_aligned")
            if al is not None:
                dbg = al.copy(); H, W = dbg.shape[:2]
                cw, ch = tpl.get("_cella") or (0.037, 0.077)
                hw, hh = int(cw * W / 2), int(ch * H / 2)
                for c in tpl["caselle"]:
                    cx, cy = int(c["x"] * W), int(c["y"] * H)
                    sc = res["punteggi"].get(c["id"], 0)
                    col = (0, 0, 255) if c["id"] == res.get("proposta") else (0, 170, 0)
                    cv2.rectangle(dbg, (cx - hw, cy - hh), (cx + hw, cy + hh), col, 1)
                    cv2.putText(dbg, f"{sc:.2f}", (cx - hw, cy - hh - 3),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.35, col, 1)
                cv2.imwrite(os.path.join(BASE, "_dbg_aligned.png"), dbg)
        except Exception:
            pass

    anteprima = None
    al = res.pop("_aligned", None)
    if al is not None:
        if al.shape[1] > 900:                      # l'anteprima viaggia su rete mobile
            al = cv2.resize(al, (900, int(al.shape[0] * 900 / al.shape[1])))
        ok, buf = cv2.imencode(".jpg", al, [cv2.IMWRITE_JPEG_QUALITY, 70])
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
    img, mid, err = _leggi_foto(request)
    if err:
        return jsonify({"inlier": 0, "ok": False, "soglia": R.AUTO_MIN, "errore": err}), 400
    tpl = _get_template(mid)
    if tpl is None:
        return jsonify({"inlier": 0, "ok": False, "soglia": R.AUTO_MIN,
                        "errore": f"modello sconosciuto: {mid}"}), 400
    try:
        inl = R.qualita_aggancio(img, tpl)
    except Exception:
        log.exception("sonda fallita")
        return jsonify({"inlier": 0, "ok": False, "soglia": R.AUTO_MIN}), 200
    return jsonify({"inlier": inl, "ok": inl >= R.AUTO_MIN, "soglia": R.AUTO_MIN})


@app.post("/salva")
def salva():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify({"errore": "richiesta non valida"}), 400
    mid = str(d.get("modello", ""))
    cid = str(d.get("casella_id", ""))
    if not cid:
        return jsonify({"errore": "nessuna casella selezionata"}), 400

    tpl = _get_template(mid)
    if tpl is None:
        return jsonify({"errore": f"modello sconosciuto: {mid}"}), 400
    valide = {c["id"]: c for c in tpl["caselle"]}
    if cid not in valide:
        return jsonify({"errore": f"casella non valida per il modello {mid}"}), 400

    try:
        con = sqlite3.connect(DB)
        con.execute("INSERT INTO recapiti(ts,codice,modello,casella_id,etichetta,qr) VALUES(?,?,?,?,?,?)",
                    (datetime.datetime.now().isoformat(timespec="seconds"),
                     str(d.get("codice", ""))[:64], mid, cid,
                     valide[cid]["etichetta"], str(d.get("qr", ""))[:64]))
        con.commit(); con.close()
    except sqlite3.Error:
        log.exception("salvataggio fallito")
        return jsonify({"errore": "salvataggio fallito"}), 500

    _traccia("salva", {"modello": mid, "casella_id": cid, "con_qr": bool(d.get("qr"))})
    return jsonify({"ok": True})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--https", action="store_true", help="HTTPS autofirmato (per la fotocamera con la guida)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _init_db()
    if not args.https:
        log.warning("avviato in HTTP: da telefono la fotocamera con guida e auto-scatto NON "
                    "sara' disponibile (i browser la concedono solo in HTTPS o su localhost). "
                    "Usa --https.")
    app.run(host=args.host, port=args.port, ssl_context="adhoc" if args.https else None,
            debug=False, threaded=True)
