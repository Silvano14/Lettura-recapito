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
   assorbe inquadratura imprecisa, scala, rotazione e prospettiva. L'omografia viene
   **validata** (niente ribaltamenti o scale assurde) e la qualità dell'allineamento è
   misurata come **residuo in pixel** sui bordi delle caselle, non solo contando i riscontri.
4. Su ogni casella si **ritrova il quadratino stampato** in un intorno della posizione attesa
   (ancoraggio locale) e si misura l'inchiostro **solo al suo interno**, escludendo il bordo.
   È il punto che rende la lettura insensibile a un allineamento imperfetto di qualche pixel.
   La soglia non è un valore assoluto: si ricava dal contrasto **locale**, con il fondo della
   carta stimato per morfologia, così ombra della mano, esposizione e colore della carta si
   annullano da soli.
5. Si propone la casella con un livello di confidenza. Se l'aggancio è debole, se il residuo
   è alto o se **sembrano barrate più caselle**, il sistema **non propone** e spiega perché.
   Le caselle si confermano su una **griglia compatta** che imita la busta: destinatario a
   sinistra, indirizzo a destra.
6. **Codice QR → codice raccomandata** (modelli con `"leggi_qr": true`): il QR viene letto
   **lato client** (jsQR, offline) dal **fotogramma intero** — basta che sia nell'inquadratura,
   non serve una zona dedicata. Si prova di continuo finché ci riesce, così un riflesso
   momentaneo non blocca (basta inclinare un attimo). Il valore popola il **campo "Codice
   raccomandata"**, **non modificabile a mano**. Se non è stato letto durante l'inquadratura,
   in verifica c'è **"Scansiona QR"**: riapre la sola lettura del QR senza ri-analizzare né
   cambiare il mancato recapito già scelto. Salvato nel campo `codice` (e in `qr`).

## Quanto è affidabile

`banco.py` genera foto sintetiche del riquadro (segni di stili diversi, prospettiva, mosso,
ombra, riflesso, JPEG, ritaglio impreciso) e confronta la proposta con la verità nota:

    python banco.py                    # modello predefinito
    python banco.py --modello mod24b
    python banco.py --salva-errori /tmp/errori     # per guardare i casi sbagliati

Sullo stesso banco di 150 foto, prima e dopo la revisione del riconoscimento:

| | prima | dopo |
|---|---|---|
| corrette | 55,3% | **90,0%** |
| proposte sbagliate | 5,3% | **1,3%** |
| nessuna proposta (scelta manuale) | 39,3% | 8,7% |

I numeri del banco sono un **limite superiore**: le foto derivano dalla stessa immagine usata
come riferimento, quindi condividono texture di stampa e resa della carta. Servono a
confrontare due versioni sullo stesso metro, non a promettere una percentuale all'operatore.

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
  `"predefinito": true`). Riquadro largo ~2,25:1 con caselle piccole. Riferimento:
  `sd24c6_modulo.png`, 1200×534, modulo vuoto.
- **Mod. 24B** (`modelli/mod24b.json`) — sticker 3:2. Riferimento: `mod24b_modulo.png`,
  1200×800. Il suo riferimento è stato ricavato da una foto che aveva una casella barrata:
  funziona (78% sul banco, nessuna proposta sbagliata), ma **rifare la foto del modulo vuoto**
  con `calibra.py` lo migliorerebbe.

**Usa la foto di un riquadro completamente vuoto.** Il riferimento è anche la sagoma-guida
mostrata all'operatore e la sagoma con cui si ritrova il quadratino: un segno a penna dentro
il riferimento sporca tutte e tre le cose.

Il riferimento viene portato a **1200 px di larghezza**: con caselle di ~40 px un errore di
allineamento di un pixel pesa poco. I campi `cella_w`/`cella_h` (dimensione del quadratino
stampato) sono misurati da `calibra.py`; se mancano, il server li stima da solo all'avvio,
così i modelli calibrati con la versione precedente continuano a funzionare.

Il modello predefinito (quello mostrato all'avvio) è quello con `"predefinito": true`; in mancanza,
il primo in ordine alfabetico.

## Limiti onesti

- Buste **senza riquadro stampato** (postino che barra a mano la finestra) o segni molto
  ambigui → vanno a inserimento manuale. È atteso.
- Un **modello mai calibrato** non viene riconosciuto: prima va aggiunto con `calibra.py`.
- Le soglie (`ABS_MIN`, `MARGINE`, `MIN_INLIER` in `riconoscimento.py`) sono tarate sul banco:
  fra 0,08 e 0,12 di `ABS_MIN` il risultato non cambia, quindi il valore non è critico.
  Dopo le prime centinaia di buste reali, `esiti.jsonl` dice se vanno ritoccate.
- La soglia dell'**auto-scatto** (`AUTO_MIN`, default 45) va tarata sul campo: il badge mostra
  il livello di aggancio in tempo reale (es. `38/45`). Se lo scatto non parte mai → abbassala;
  se parte con buste storte → alzala.
- Se il postino barra **due caselle**, il sistema non sceglie: lo segnala e lascia decidere.
- Su **Android** la fotocamera con sagoma e auto-scatto richiede HTTPS. Se non è disponibile
  l'app passa in **modalità ridotta** (scatto manuale con la fotocamera nativa) e lo dice in
  chiaro, con il motivo: prima lo faceva in silenzio e sembrava un malfunzionamento.

## Privacy

La foto contiene nome e indirizzo del destinatario. Lo strumento salva a database solo
codice + motivo (+ eventuale codice QR), non l'immagine. `esiti.jsonl` registra solo numeri
(riscontri, residuo, punteggi delle caselle) e nessun dato del destinatario. Se in futuro vorrai conservare i ritagli per migliorare la
calibrazione, ritaglia il solo riquadro e tieni il minimo indispensabile (principio GDPR).

## File del progetto

    server.py            server locale + endpoint
    riconoscimento.py    registrazione + ancoraggio + misura + decisione (cuore CV)
    banco.py             banco di prova sintetico: misura quanto è affidabile il riconoscimento
    calibra.py           helper per creare nuovi modelli
    templates/index.html interfaccia mobile (guida, selettore modello, lettura QR, conferma)
    static/jsQR.js       libreria QR (offline, lato client)
    modelli/             modelli: json + immagine del modulo vuoto (riferimento + sagoma-guida)
    recapiti.db          database SQLite (creato all'avvio; colonna qr per il codice QR)
    esiti.jsonl          traccia di ogni analisi (senza immagini): serve a capire i casi difficili

Debug OMR: avviando il server con `DBG_OMR=1` salva `_dbg_crop.jpg` e `_dbg_aligned.png`
(ultima analisi, con finestre e punteggi disegnati) per capire un eventuale caso che fallisce.
