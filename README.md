# Riconoscimento mancato recapito

Strumento locale e **gratuito** (solo OpenCV, nessun modello generativo, nessuna connessione
a internet) per riconoscere quale casella ha barrato il postino nel riquadro di mancato
recapito delle raccomandate, partendo da una foto scattata col telefono.

Il sistema **propone** il motivo già pre-selezionato, ma **non salva mai da solo**:
la conferma dell'operatore è sempre richiesta. Così gli errori restano sotto controllo.

## Come funziona (in breve)

1. La fotocamera è sempre attiva e funziona **sia in verticale sia in orizzontale**: la cornice
   e il ritaglio si adattano da soli all'orientamento e alle proporzioni del modello. Sul display
   appare la **sagoma semitrasparente del riquadro del modello** scelto; l'operatore avvicina la
   busta finché il riquadro stampato combacia con la sagoma. L'interfaccia riempie lo schermo e
   in fase di verifica scorre internamente, senza scroll di pagina.
2. Quando l'aggancio è stabile per qualche fotogramma di fila, il sistema **scatta da solo**
   e invia la foto. La cornice diventa arancione ("quasi") poi verde ("scansione") per dare
   feedback visivo; il badge mostra il livello di aggancio numerico (es. `16/18`).
3. La foto viene **allineata all'immagine di riferimento** del modello (ORB + omografia):
   assorbe inquadratura imprecisa, scala, rotazione e prospettiva.
4. Su ogni casella si legge il **segno del postino**. Due metodi:
   - **Sottrazione-template** (consigliato, campo `"template"` nel modello): si sottrae il
     modulo stampato *vuoto* e si misura solo l'inchiostro **aggiunto a mano**. Robusto anche
     con riquadri piccoli e segni sottili, dove il contorno stampato falserebbe la misura.
   - **Densità** (fallback, se il modello non ha un template vuoto): quanto inchiostro scuro
     c'è nella finestra. Funziona bene solo con riquadri grandi/segni netti.
5. Si propone la casella con un livello di confidenza. Se l'aggancio è debole (foto di un
   altro modello, mossa o storta), il sistema **non propone** e invita a scegliere a mano.
   Le caselle si confermano su una **griglia compatta** che imita la busta: destinatario a
   sinistra, indirizzo a destra.
6. **Codice QR → codice raccomandata** (modelli con `"leggi_qr": true`): il QR viene letto
   **lato client** (jsQR, offline) dal **fotogramma intero** — basta che sia nell'inquadratura,
   non serve una zona dedicata. Si prova di continuo finché ci riesce, così un riflesso
   momentaneo non blocca (basta inclinare un attimo). Il valore popola il **campo "Codice
   raccomandata"**, **non modificabile a mano**. Se non è stato letto durante l'inquadratura,
   in verifica c'è **"Scansiona QR"**: riapre la sola lettura del QR senza ri-analizzare né
   cambiare il mancato recapito già scelto. Salvato nel campo `codice` (e in `qr`).

## Requisiti

    pip install flask opencv-python-headless numpy pyopenssl

(`pyopenssl` è richiesto per HTTPS, necessario per la fotocamera attiva con sagoma.)

## Avvio del server

    python server.py --https

**HTTPS è obbligatorio** per la fotocamera attiva (sagoma + auto-scatto): i browser
permettono l'accesso alla camera solo in un contesto sicuro (HTTPS o localhost).
Senza `--https` l'interfaccia ricade sulla fotocamera nativa del telefono (scatto manuale,
niente sagoma, niente auto-scatto).

Dal telefono (stessa rete chiusa) apri `https://<ip-del-pc>:8000`.  
La prima volta compare un avviso "certificato non attendibile" (autofirmato): tocca
*Avanzate → Procedi* una sola volta per dispositivo.

## Uso quotidiano (l'operatore)

1. In alto scegli il **modello** della pila di buste (es. *Mod. 24B*). È cambiabile in
   qualsiasi momento con un tap: per i lotti misti basta cambiarlo quando serve.
2. Avvicina la busta alla fotocamera allineando il **bordo del riquadro stampato** alla
   sagoma semitrasparente. Quando la cornice diventa verde e il badge dice
   "Aggancio stabile", la **foto parte da sola**.  
   - Se preferisci scattare a mano: tocca **Scatta e analizza** (oppure disattiva **Auto**
     con l'apposito pulsante in alto).
   - Se hai un lettore QR/barcode, inserisci il codice nel campo apposito prima o dopo.
3. Il sistema mostra l'anteprima e **pre-evidenzia** il motivo proposto (in verde).
   - Se è giusto → tocca **Conferma e salva**.
   - Se è sbagliato o non c'è proposta → tocca la casella corretta, poi **Conferma e salva**.
4. Togli la busta: il sistema si riarma automaticamente per la successiva.  
   I dati confermati finiscono in `recapiti.db` (SQLite).

La conferma è **sempre** richiesta: una foto storta o anomala non produce mai un dato
sbagliato in silenzio, al massimo diventa una scelta manuale.

## Aggiungere un nuovo modello di busta

Serve un PC con schermo. Scatta/usa una foto ben dritta e ben inquadrata del riquadro:

    python calibra.py foto_di_un_riquadro.jpg

Selezioni il rettangolo del riquadro, poi clicchi al centro di ogni casella inserendo
etichetta e categoria. Vengono salvati `modelli/<id>.json` e `modelli/<id>_ref.png`.
Da quel momento il modello compare nel menù sul telefono.

Già inclusi e calibrati:
- **SD24C6** (`modelli/sd24c6.json`) — busta standard, è il **modello predefinito** (campo
  `"predefinito": true`). Riquadro largo ~2,25:1 con caselle piccole: usa la **sottrazione-template**
  (`"template": "sd24c6_tpl.png"`, immagine del modulo *vuoto*) per leggere solo il segno a mano.
- **Mod. 24B** (`modelli/mod24b.json`) — sticker 3:2, resta selezionabile dal menù (metodo densità).

**Per un modello con caselle piccole** aggiungi al JSON un `"template"` che punti a una foto del
riquadro **completamente vuoto**, allineata alla stessa cornice del riferimento: è ciò che rende
la lettura del segno affidabile.

Il modello predefinito (quello mostrato all'avvio) è quello con `"predefinito": true`; in mancanza,
il primo in ordine alfabetico.

## Limiti onesti

- Buste **senza riquadro stampato** (postino che barra a mano la finestra) o segni molto
  ambigui → vanno a inserimento manuale. È atteso.
- Un **modello mai calibrato** non viene riconosciuto: prima va aggiunto con `calibra.py`.
- Le soglie (`ABS_MIN`, `MARGIN`, `MIN_INLIER` in `riconoscimento.py`) sono un punto di
  partenza: conviene ritoccarle dopo le prime centinaia di buste reali.
- La soglia dell'**auto-scatto** (`AUTO_MIN` in `riconoscimento.py`, default 18) va tarata
  sul campo: il badge mostra il livello di aggancio in tempo reale (es. `14/18`). Se lo
  scatto non parte mai → abbassa `AUTO_MIN`; se parte con buste storte → alzalo.

## Privacy

La foto contiene nome e indirizzo del destinatario. Lo strumento salva a database solo
codice + motivo (+ eventuale codice QR), non l'immagine. Se in futuro vorrai conservare i ritagli per migliorare la
calibrazione, ritaglia il solo riquadro e tieni il minimo indispensabile (principio GDPR).

## File del progetto

    server.py            server locale + endpoint
    riconoscimento.py    registrazione + OMR + confidenza (cuore CV)
    calibra.py           helper per creare nuovi template di modello
    templates/index.html interfaccia mobile (guida, selettore modello, lettura QR, conferma)
    static/jsQR.js       libreria QR (offline, lato client)
    modelli/             modelli: json + riferimento ORB (_ref) + template modulo vuoto (_tpl)
    recapiti.db          database SQLite (creato all'avvio; colonna qr per il codice QR)

Debug OMR: avviando il server con `DBG_OMR=1` salva `_dbg_crop.jpg` e `_dbg_aligned.png`
(ultima analisi, con finestre e punteggi disegnati) per capire un eventuale caso che fallisce.
