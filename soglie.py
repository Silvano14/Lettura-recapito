"""
soglie.py - TUTTE le soglie del riconoscimento, in un solo posto.

Stanno qui e non dentro i singoli moduli perche' vanno tarate insieme, sullo stesso banco di
prova (banco.py), e cercarle sparse fra registrazione e misura porterebbe a ritoccarne una
dimenticando l'altra. riconoscimento.py le ri-esporta: server.py legge R.AUTO_MIN e la manda
al client, quindi il JS non la duplica mai.
"""

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
