# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

Tutto il codice, i commenti, i docstring, i nomi di identificatori, il JSON dei modelli e
l'interfaccia sono **in italiano**. Il codice nuovo deve seguire la stessa convenzione.
I commenti esistenti spiegano *perché* una scelta è stata fatta (spesso citando il bug che
evitano): mantenere quello stile invece di descrivere cosa fa la riga.

## Comandi

Ambiente: venv già presente in `.venv` (Python 3.12, Flask + opencv-python-headless + numpy +
pyOpenSSL). Non esiste `requirements.txt`; le dipendenze sono elencate nel README.

```bash
.venv/bin/python server.py --https          # server; HTTPS obbligatorio per camera+sagoma da telefono
```

```bash
.venv/bin/python banco.py                   # banco di prova: è la suite di regressione del progetto
```

Il banco è l'unico test automatico. Varianti utili:

```bash
.venv/bin/python banco.py --modello mod24b --casi 40 --salva-errori /tmp/errori
```

Analisi di **una singola foto** (il caso "run a single test"), stampa il JSON della decisione
e scrive `_aligned_debug.png`:

```bash
.venv/bin/python riconoscimento.py foto.jpg modelli/sd24c6.json
```

Debug OMR sul server: `DBG_OMR=1` salva `_dbg_crop.jpg` e `_dbg_aligned.png` (ultima analisi,
con finestre di misura e punteggi disegnati) — il modo più rapido per capire un caso che sbaglia.

Calibrazione di un nuovo modello (richiede uno schermo, usa finestre OpenCV):

```bash
.venv/bin/python calibra.py foto_del_riquadro_VUOTO.jpg
```

`.claude/launch.json` avvia il server in **HTTP** sulla porta 8732: utile per provare gli
endpoint, ma da telefono non dà camera con sagoma né auto-scatto.

## Architettura

Server Flask locale (`server.py`) + interfaccia mobile a pagina singola (`templates/index.html`)
+ cuore di computer vision (`riconoscimento.py`). Tutto offline, solo OpenCV/numpy su CPU:
nessun modello generativo, nessuna chiamata di rete.

### Il modello di busta è il contratto centrale

Un modello = `modelli/<id>.json` + un PNG del **modulo vuoto**. Il JSON contiene le caselle in
**coordinate normalizzate** (`x`,`y` in 0..1 sul riferimento), `dim_riferimento` e
`cella_w`/`cella_h` (dimensione del quadratino stampato, anch'essa normalizzata).

`R.carica_template()` arricchisce il dict con campi derivati (prefisso `_`, mai serializzati):
`_ref`/`_ref_g` (riferimento ridimensionato a `dim_riferimento`), `_kp`/`_des` (ORB del
riferimento), `_cella` (dal JSON o stimata con `_stima_cella` per i modelli calibrati prima
che il campo esistesse), `_sagome` (ritaglio del quadratino vuoto per ogni casella).

**Il PNG di riferimento fa tre lavori insieme**: riferimento per l'omografia, sagoma-guida
semitrasparente mostrata all'operatore (`GET /riferimento/<id>`), e sagoma con cui si ritrova
il quadratino nell'ancoraggio locale. Per questo *deve* essere un modulo completamente vuoto:
un segno a penna nel riferimento degrada tutte e tre le cose. `calibra.py` porta il riferimento
a 1200 px di larghezza (`LARGHEZZA`) — le soglie di `riconoscimento.py` sono espresse in questi
pixel canonici.

### Pipeline di riconoscimento (`riconoscimento.py`)

1. **`_registra`** — ORB + `findHomography` RANSAC verso il riferimento. La foto viene prima
   normalizzata a `SCALA_ORB * W` (ORB non regge oltre ~2x di differenza di scala).
   `_valida_omografia` scarta ribaltamenti, matrici degeneri e scale assurde. La qualità si
   misura come **residuo in pixel** (`_residuo`, phase correlation attorno alle caselle), non
   solo contando gli inlier.
2. **`_ancora`** — per ogni casella ritrova il quadratino stampato in un intorno *stretto* della
   posizione nominale, confrontando **ampiezze di gradiente** (il bordo stampato risalta, il
   segno a penna disturba poco), con penalità sullo spostamento dalla posizione nominale.
   È il passaggio che rende la lettura insensibile a un residuo di qualche pixel.
3. **`_inchiostro` + `_misura`** — il fondo della carta si stima per chiusura morfologica e si
   sottrae, così ombra/esposizione si annullano. La soglia è **relativa**, ricavata dal bordo
   stampato della casella stessa (l'inchiostro più nero disponibile in quel punto della foto);
   si misura solo l'interno, escludendo il bordo.
4. **decisione in `analizza`** — la migliore vince solo se supera `ABS_MIN` **e** stacca la
   seconda di `MARGINE` (differenza, non rapporto: il punteggio ha un fondo additivo).

Tutte le soglie (`ABS_MIN`, `MARGINE`, `MIN_INLIER`, `RESIDUO_MAX`, `AUTO_MIN`, `SCALA_ORB`)
vivono **solo** in cima a `riconoscimento.py`; `AUTO_MIN` arriva al client nella risposta di
`/aggancio` (campo `soglia`), quindi il JS non la duplica mai.

### Invariante di sicurezza: nessun salvataggio automatico

`analizza` restituisce `proposta: None` (e un `avviso_coerenza` che spiega il perché) quando
l'aggancio è debole, il residuo è alto, troppe caselle sono illeggibili, o **sembrano barrate
più caselle** — quest'ultimo caso vale anche se una stacca netta l'altra, perché una proposta
sicura di sé farebbe perdere il secondo segno in silenzio. Il salvataggio richiede sempre la
conferma dell'operatore, e `POST /salva` rivalida `casella_id` contro il template.

### Ciclo client/server dell'auto-scatto

`FRAME` (in `index.html`) è espresso in **frazioni del fotogramma**, non in pixel a schermo:
una sola grandezza descrive sia la cornice che l'operatore vede sia il ritaglio inviato al
server, e le due non possono divergere. `applyFrame()` la ricalcola dal rapporto del modello
(`dim_riferimento`) e dal rettangolo realmente occupato dal video.

- `POST /aggancio` viene chiamato ogni `POLL_MS` (350 ms) con lo stesso ritaglio ridotto a
  900 px: risponde solo `{inlier, ok, soglia}` senza warp né lettura caselle. La normalizzazione
  di scala lato server rende confrontabili sonda e analisi a piena risoluzione.
- `STABLE` (3) fotogrammi `ok` di fila → scatto automatico e `POST /analizza`.
- Il **riarmo** richiede che gli inlier scendano sotto `ARM_FRAZ` della soglia (busta tolta):
  senza questo si riscatterebbe di continuo sulla stessa busta.
- `auto.giro` invalida le risposte in ritardo: una sonda di un ciclo già chiuso non deve poter
  far scattare una foto durante la verifica, cancellando la scelta dell'operatore.

Il QR (`static/jsQR.js`, offline) si legge **lato client dal fotogramma intero**, in modo
continuo finché non riesce; popola un campo non modificabile a mano. Solo per i modelli con
`"leggi_qr": true`.

### Server

Cache dei template invalidata per `mtime` (`_get_template`): dopo una ricalibrazione il server
non deve continuare a servire le caselle vecchie. `GET /modelli` salta i JSON rotti invece di
far cadere l'applicazione. Difese sull'upload: `MAX_UPLOAD`, `MAX_PIXEL`, e `_leggi_foto` che
non lascia passare nessun input capace di far cadere il server.

## Privacy (vincolo di progetto)

La foto contiene nome e indirizzo del destinatario. `recapiti.db` salva **solo** codice, modello,
casella, etichetta e QR — **mai l'immagine**. `esiti.jsonl` (`_traccia`) registra solo numeri
(inlier, residuo, punteggi) e nessun dato del destinatario. Non introdurre persistenza di
immagini o di dati personali senza che sia una richiesta esplicita.

## Note sulla modifica del riconoscimento

Prima e dopo qualsiasi cambio a `riconoscimento.py`, eseguire `banco.py` sullo stesso seed e
confrontare le tre percentuali: corrette / **proposte sbagliate** (il caso pericoloso) /
nessuna proposta. I numeri del banco sono un **limite superiore** — le foto derivano dalla
stessa immagine usata come riferimento — quindi servono a confrontare due versioni sullo stesso
metro, non a promettere una percentuale sul campo.
