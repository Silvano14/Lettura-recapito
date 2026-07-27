#!/usr/bin/env python3
"""
calibra.py - crea il TEMPLATE di un nuovo modello di busta. Da eseguire su un PC con schermo.

Uso:
    python calibra.py foto_di_un_riquadro.jpg

Procedura guidata:
  1) Selezioni col mouse il rettangolo del riquadro (il bordo dello sticker/box) e premi INVIO.
     Viene salvato come immagine di RIFERIMENTO, portata a 600x400.
  2) Clicchi al centro di ogni casella, una alla volta. Dopo ogni clic, in console scrivi
     l'etichetta (es. "Destinatario - Irreperibile") e la categoria (es. "destinatario").
  3) Premi 'q' quando hai finito. Vengono salvati modelli/<id>.json e modelli/<id>_ref.png.

Suggerimento: scatta la foto di riferimento ben dritta e ben inquadrata: tutte le buste di
quel modello verranno poi allineate a questa immagine, quindi piu' e' pulita, meglio e'.
"""
import json, os, sys
import cv2

CANON = (600, 400)
BASE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(BASE, "modelli"); os.makedirs(MOD, exist_ok=True)

def main():
    if len(sys.argv) < 2:
        print("uso: python calibra.py foto.jpg"); return
    img = cv2.imread(sys.argv[1])
    if img is None:
        print("immagine non leggibile"); return

    mid = input("id modello (senza spazi, es. mod24b): ").strip()
    nome = input("nome leggibile (es. Mod. 24B): ").strip() or mid
    codice = input("codice stampato sul riquadro (opzionale, es. 24B): ").strip()

    # 1) ritaglio del riquadro -> riferimento canonico
    print("\nSeleziona il rettangolo del riquadro, poi premi INVIO o SPAZIO.")
    r = cv2.selectROI("Seleziona il riquadro", img, showCrosshair=True)
    cv2.destroyWindow("Seleziona il riquadro")
    x, y, w, h = map(int, r)
    if w == 0 or h == 0:
        print("nessuna selezione"); return
    ref = cv2.resize(img[y:y+h, x:x+w], CANON)
    ref_name = f"{mid}_ref.png"
    cv2.imwrite(os.path.join(MOD, ref_name), ref)

    # 2) clic sulle caselle
    caselle = []
    disp = ref.copy()
    def on_click(ev, cx, cy, flags, param):
        if ev == cv2.EVENT_LBUTTONDOWN:
            cv2.circle(disp, (cx, cy), 6, (0, 0, 255), 2)
            cv2.imshow("Caselle (clic = aggiungi, q = fine)", disp)
            et = input(f"  casella #{len(caselle)+1} - etichetta: ").strip()
            cat = input("  categoria (destinatario/indirizzo/altro): ").strip() or "altro"
            cid = input("  id breve (es. dest_irreperibile): ").strip() or f"c{len(caselle)+1}"
            caselle.append({"id": cid, "categoria": cat, "etichetta": et,
                            "x": round(cx / CANON[0], 3), "y": round(cy / CANON[1], 3)})
            print(f"  -> aggiunta ({caselle[-1]['x']},{caselle[-1]['y']})\n")

    print("\nClicca al centro di ogni casella. 'q' per finire.")
    cv2.imshow("Caselle (clic = aggiungi, q = fine)", disp)
    cv2.setMouseCallback("Caselle (clic = aggiungi, q = fine)", on_click)
    while True:
        if cv2.waitKey(20) & 0xFF == ord('q'):
            break
    cv2.destroyAllWindows()

    if not caselle:
        print("nessuna casella: annullo"); return
    tpl = {"modello": nome, "codice": codice, "riferimento": ref_name,
           "dim_riferimento": list(CANON), "caselle": caselle}
    with open(os.path.join(MOD, f"{mid}.json"), "w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False, indent=2)
    print(f"\nSalvato modelli/{mid}.json con {len(caselle)} caselle e riferimento {ref_name}.")

if __name__ == "__main__":
    main()
