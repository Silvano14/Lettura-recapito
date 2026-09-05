#!/usr/bin/env python3
"""
calibra.py - crea il TEMPLATE di un nuovo modello di busta. Da eseguire su un PC con schermo.

Uso:
    python calibra.py foto_del_riquadro_VUOTO.jpg

IMPORTANTE: usa la foto di un riquadro **completamente vuoto** (nessuna casella barrata) e
scattata bene dritta. Quell'immagine diventa il riferimento con cui tutte le buste verranno
allineate ed e' anche la sagoma-guida mostrata all'operatore: se contiene un segno a penna,
quel segno finisce dentro il modello.

Procedura guidata:
  1) Selezioni col mouse il rettangolo del riquadro (il bordo dello sticker/box) e premi INVIO.
  2) Clicchi al centro di ogni casella, una alla volta. Il clic viene RICENTRATO da solo sul
     quadratino stampato piu' vicino, quindi non serve precisione: basta cliccarci dentro.
     Dopo ogni clic, in console scrivi etichetta, categoria e id.
  3) Premi 'q' quando hai finito. Vengono salvati modelli/<id>.json e modelli/<id>_ref.png.

Verifica il risultato con:  python banco.py --modello <id>
"""
import json, os, sys
import cv2
import numpy as np

LARGHEZZA = 1200          # larghezza canonica: con caselle di ~40 px l'errore di allineamento
                          # residuo pesa poco. Sotto i ~1000 px la lettura diventa fragile.
BASE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(BASE, "modelli"); os.makedirs(MOD, exist_ok=True)


def _quadratino(gray, cx, cy, raggio):
    """Quadratino stampato piu' vicino al punto cliccato: (centro_x, centro_y, larghezza, altezza)."""
    x0, y0 = max(0, cx - raggio), max(0, cy - raggio)
    roi = gray[y0:cy + raggio, x0:cx + raggio]
    if roi.size == 0:
        return None
    bw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for k in cnts:
        x, y, w, h = cv2.boundingRect(k)
        if 0.25 * raggio < w < 1.4 * raggio and 0.25 * raggio < h < 1.4 * raggio and abs(w - h) < 0.6 * raggio:
            d = abs(x + w / 2 - (cx - x0)) + abs(y + h / 2 - (cy - y0))
            if best is None or d < best[0]:
                best = (d, x0 + x + w / 2, y0 + y + h / 2, w, h)
    return best[1:] if best else None


def main():
    if len(sys.argv) < 2:
        print("uso: python calibra.py foto_del_riquadro_VUOTO.jpg"); return
    img = cv2.imread(sys.argv[1])
    if img is None:
        print("immagine non leggibile"); return

    mid = input("id modello (senza spazi, es. mod24b): ").strip()
    nome = input("nome leggibile (es. Mod. 24B): ").strip() or mid
    codice = input("codice stampato sul riquadro (opzionale, es. 24B): ").strip()

    print("\nSeleziona il rettangolo del riquadro, poi premi INVIO o SPAZIO.")
    r = cv2.selectROI("Seleziona il riquadro", img, showCrosshair=True)
    cv2.destroyWindow("Seleziona il riquadro")
    x, y, w, h = map(int, r)
    if w == 0 or h == 0:
        print("nessuna selezione"); return

    canon = (LARGHEZZA, max(1, int(round(LARGHEZZA * h / w))))
    ref = cv2.resize(img[y:y + h, x:x + w], canon, interpolation=cv2.INTER_CUBIC)
    if min(img.shape[0], img.shape[1]) < 600:
        print("ATTENZIONE: la foto di partenza e' piccola; il riferimento sara' sgranato.")
    ref_name = f"{mid}_ref.png"
    cv2.imwrite(os.path.join(MOD, ref_name), ref)
    gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    raggio = max(12, int(0.045 * canon[0]))

    caselle, celle = [], []
    disp = ref.copy()
    finestra = "Caselle (clic = aggiungi, q = fine)"

    def on_click(ev, cx, cy, flags, param):
        if ev != cv2.EVENT_LBUTTONDOWN:
            return
        q = _quadratino(gray, cx, cy, raggio)
        if q:
            fx, fy, cw, chh = q
            cv2.rectangle(disp, (int(fx - cw / 2), int(fy - chh / 2)),
                          (int(fx + cw / 2), int(fy + chh / 2)), (0, 200, 0), 2)
            print(f"  quadratino trovato a ({int(fx)},{int(fy)}), {int(cw)}x{int(chh)} px")
        else:
            fx, fy, cw, chh = cx, cy, 0, 0
            cv2.circle(disp, (cx, cy), 6, (0, 0, 255), 2)
            print("  nessun quadratino riconosciuto qui: uso il punto cliccato")
        cv2.imshow(finestra, disp)
        et = input(f"  casella #{len(caselle)+1} - etichetta: ").strip()
        cat = input("  categoria (destinatario/indirizzo/altro): ").strip() or "altro"
        cid = input("  id breve (es. dest_irreperibile): ").strip() or f"c{len(caselle)+1}"
        caselle.append({"id": cid, "categoria": cat, "etichetta": et,
                        "x": round(fx / canon[0], 4), "y": round(fy / canon[1], 4)})
        if cw:
            celle.append((cw, chh))
        print(f"  -> aggiunta ({caselle[-1]['x']},{caselle[-1]['y']})\n")

    print("\nClicca dentro ogni casella (il clic viene ricentrato da solo). 'q' per finire.")
    cv2.imshow(finestra, disp)
    cv2.setMouseCallback(finestra, on_click)
    while True:
        if cv2.waitKey(20) & 0xFF == ord('q'):
            break
    cv2.destroyAllWindows()

    if not caselle:
        print("nessuna casella: annullo"); return

    tpl = {"modello": nome, "codice": codice, "riferimento": ref_name,
           "dim_riferimento": list(canon), "caselle": caselle}
    if celle:
        tpl["cella_w"] = round(float(np.median([c[0] for c in celle])) / canon[0], 4)
        tpl["cella_h"] = round(float(np.median([c[1] for c in celle])) / canon[1], 4)
        print(f"\ncella stampata: {tpl['cella_w']:.4f} x {tpl['cella_h']:.4f} "
              f"({int(tpl['cella_w']*canon[0])}x{int(tpl['cella_h']*canon[1])} px)")
    else:
        print("\nNessun quadratino riconosciuto: la dimensione della casella verra' stimata "
              "all'avvio del server. Se la lettura risulta incerta, rifai la calibrazione "
              "con una foto piu' nitida.")

    with open(os.path.join(MOD, f"{mid}.json"), "w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False, indent=2)
    print(f"\nSalvato modelli/{mid}.json con {len(caselle)} caselle e riferimento {ref_name}.")
    print(f"Verifica subito la qualita' con:  python banco.py --modello {mid}")


if __name__ == "__main__":
    main()
