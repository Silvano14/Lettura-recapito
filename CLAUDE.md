# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

Tutto il codice, i commenti, i docstring, i nomi di identificatori, il JSON dei modelli e
l'interfaccia sono **in italiano**. Il codice nuovo deve seguire la stessa convenzione.
I commenti esistenti spiegano *perché* una scelta è stata fatta (spesso citando il bug che
evitano): mantenere quello stile invece di descrivere cosa fa la riga.

## Comandi

Ambiente: Python 3.12 in un venv `.venv`, **non versionato**: va creato su ogni macchina (serve
un Python 3.12 installato). Non esiste `requirements.txt`; le dipendenze sono quelle del README:

```bash
python -m venv .venv
```

```bash
.venv/bin/python -m pip install flask opencv-python-headless numpy pyopenssl pymysql
```

(`pymysql` serve solo se `config.json` configura MySQL; senza, il server non lo importa.)

L'interprete del venv è `.venv/bin/python` su Linux/macOS e `.venv\Scripts\python.exe` su
Windows; gli esempi sotto usano la forma POSIX. Va sempre richiamato per percorso: lo stato della
shell non persiste fra un comando e l'altro, e su Windows `python` fuori dal venv può essere
l'alias del Microsoft Store invece di un interprete vero.

```bash
.venv/bin/python server.py --https          # server; HTTPS obbligatorio per camera+sagoma da telefono
```

```bash
.venv/bin/python banco.py                   # banco di prova: è la suite di regressione del progetto
```

Il banco è l'unico test automatico. Varianti utili:

```bash
.venv/bin/python banco.py --modello mod24b --casi 40 --salva-errori <cartella>
```

**Il banco esce sempre con codice 0**: non è un pass/fail, vanno lette le tre percentuali che
stampa. Default: `--seed 12345`, `--casi 8` (foto per casella). Oltre ai casi con un segno genera
casi con **nessun segno** e con **due segni** (uno destinatario + uno indirizzo): lì l'unico esito
corretto è "nessuna proposta" e qualunque proposta conta come sbagliata. È così che il banco
verifica l'invariante di sicurezza descritto sotto.

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

Controllo di `config.json` contro la tabella MySQL vera, senza avviare il server (elenca le
colonne, segnala quelle inesistenti o obbligatorie non compilate; esce con 1 se qualcosa non va):

```bash
.venv/bin/python verifica_mysql.py
```

`.claude/launch.json` avvia il server in **HTTP** sulla porta 8732: utile per provare gli
endpoint, ma da telefono non dà camera con sagoma né auto-scatto. Ha due configurazioni con lo
stesso server: `rilevatore` (`.venv/bin/python`, Linux/macOS) e `rilevatore-windows`
(`.venv\Scripts\python.exe`). Nel pannello browser di Claude la fotocamera è bloccata, quindi la
pagina parte in modalità ridotta: si prova il giro analisi → verifica → salvataggio, non
l'auto-scatto.

## Architettura

Server Flask locale (`server.py`) + interfaccia mobile a pagina singola + cuore di computer
vision (`riconoscimento.py` e moduli collegati). Tutto offline, solo OpenCV/numpy su CPU:
nessun modello generativo, nessuna chiamata di rete.

L'interfaccia è `templates/index.html` (solo markup) + `static/app.css` + script **classici** in
`static/js/` (niente moduli ES né build): condividono l'ambito globale, quindi lo stato (`modello`,
`stream`, `auto`, `FRAME`, `qrValue`…) è visibile da tutti. L'ordine dei `<script>` conta solo per
il codice eseguito al caricamento: `stato.js` (stato e `$`) per primo, `avvio.js` (avvia modelli e
fotocamera) per ultimo. Una variabile di primo livello va dichiarata in **un solo** file: una
seconda dichiarazione con `let`/`const` è un SyntaxError che blocca l'intero script.

### Il modello di busta è il contratto centrale

Un modello = `modelli/<id>.json` + un PNG del **modulo vuoto**. Il JSON contiene le caselle in
**coordinate normalizzate** (`x`,`y` in 0..1 sul riferimento), `dim_riferimento` e
`cella_w`/`cella_h` (dimensione del quadratino stampato, anch'essa normalizzata).
Il modello predefinito (selezionato all'avvio e usato da `banco.py` senza `--modello`) è quello
con `"predefinito": true`; in mancanza, il primo in ordine alfabetico (per nome visualizzato
nell'interfaccia, per id del file in `banco.py`).

**Quale PNG conta davvero**: `server.py` e `riconoscimento.py` usano solo il file indicato nel
campo `riferimento` (per i modelli inclusi `*_modulo.png`). `banco.py` usa `template` se
presente, altrimenti `riferimento`, come base per le foto sintetiche. I file `*_ref.png` e
`*_tpl.png` in `modelli/` non sono referenziati da nessun JSON né codice: modificarli non ha
effetto. Attenzione però: `calibra.py` scrive `<id>_ref.png` e lo mette in `riferimento`, quindi
per un modello nuovo il file usato sarà quello.

`R.carica_template()` arricchisce il dict con campi derivati (prefisso `_`, mai serializzati):
`_ref`/`_ref_g` (riferimento ridimensionato a `dim_riferimento`), `_kp`/`_des` (ORB del
riferimento), `_cella` (dal JSON o stimata con `_stima_cella` per i modelli calibrati prima
che il campo esistesse), `_sagome` (ritaglio del quadratino vuoto per ogni casella).

**Il PNG di riferimento fa tre lavori insieme**: riferimento per l'omografia, sagoma-guida
semitrasparente mostrata all'operatore (`GET /riferimento/<id>`), e sagoma con cui si ritrova
il quadratino nell'ancoraggio locale. Per questo *deve* essere un modulo completamente vuoto:
un segno a penna nel riferimento degrada tutte e tre le cose. `calibra.py` porta il riferimento
a 1200 px di larghezza (`LARGHEZZA`) — le soglie di `soglie.py` sono espresse in questi
pixel canonici.

### Pipeline di riconoscimento

`riconoscimento.py` è l'unica porta d'ingresso (`carica_template`, `analizza`, `qualita_aggancio`,
soglie ri-esportate): `server.py` e `banco.py` importano solo da lì. Il passo 1 sta in
`registrazione.py`, i passi 2-3 in `misura_caselle.py`, la decisione in `riconoscimento.analizza`.

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

Tutte le soglie (`ABS_MIN`, `MARGINE`, `CONTRASTO_MIN`, `MIN_INLIER`, `RESIDUO_MAX`, `AUTO_MIN`,
`SCALA_ORB`) vivono **solo** in `soglie.py`; `riconoscimento.py` le ri-esporta. `AUTO_MIN` arriva
al client nella risposta di `/aggancio` (campo `soglia`), quindi il JS non la duplica.
**Eccezione da ricordare**: la riga diagnostica in `static/js/verifica.js` (`mostraVerifica`)
contiene copie fisse di `ABS_MIN` (`0.10`) e `RESIDUO_MAX` (`2.5`): se si ritoccano quelle soglie,
vanno aggiornate anche lì.

### Invariante di sicurezza: nessun salvataggio automatico

`analizza` restituisce `proposta: None` (e un `avviso_coerenza` che spiega il perché) quando
l'aggancio è debole, il residuo è alto, troppe caselle sono illeggibili, o **sembrano barrate
più caselle** — quest'ultimo caso vale anche se una stacca netta l'altra, perché una proposta
sicura di sé farebbe perdere il secondo segno in silenzio. Il salvataggio richiede sempre la
conferma dell'operatore, e `POST /salva` rivalida `casella_id` contro il template.

### Ciclo client/server dell'auto-scatto

`FRAME` (in `static/js/cornice.js`) è espresso in **frazioni del fotogramma**, non in pixel a schermo:
una sola grandezza descrive sia la cornice che l'operatore vede sia il ritaglio inviato al
server, e le due non possono divergere. `applyFrame()` la ricalcola dal rapporto del modello
(`dim_riferimento`) e dal rettangolo realmente occupato dal video.

- `POST /aggancio` viene chiamato ogni `POLL_MS` (350 ms) con lo stesso ritaglio ridotto a
  900 px: risponde solo `{inlier, ok, soglia}` senza warp né lettura caselle. La normalizzazione
  di scala lato server rende confrontabili sonda e analisi a piena risoluzione.
- `STABLE` (3) fotogrammi `ok` di fila → scatto automatico e `POST /analizza`.
- Il **riarmo** richiede che gli inlier scendano sotto `ARM_FRAZ` della soglia (busta tolta):
  senza questo si riscatterebbe di continuo sulla stessa busta.
- `auto.giro` (in `static/js/auto.js`, come tutto il ciclo della sonda) invalida le risposte in
  ritardo: una sonda di un ciclo già chiuso non deve poter far scattare una foto durante la
  verifica, cancellando la scelta dell'operatore.

Il QR (`static/jsQR.js`, offline) si legge **lato client dal fotogramma intero**, in modo
continuo finché non riesce; popola un campo non modificabile a mano. Solo per i modelli con
`"leggi_qr": true`.

### Server

Cache dei template invalidata per `mtime` (`_get_template`): dopo una ricalibrazione il server
non deve continuare a servire le caselle vecchie. `GET /modelli` salta i JSON rotti invece di
far cadere l'applicazione. Difese sull'upload: `MAX_UPLOAD`, `MAX_PIXEL`, e `_leggi_foto` che
non lascia passare nessun input capace di far cadere il server.

### Salvataggio (`archivio.py`)

`POST /salva` scrive **solo** tramite `archivio.salva(rec)`, che risponde con la destinazione
(`mysql` / `in_attesa` / `locale`, anche nel campo `destinazione` della risposta).

- **Senza `config.json`** (o senza la sezione `"mysql"`): SQLite, tabella `recapiti` di
  `recapiti.db`, come prima di MySQL. `config.json` non è versionato (contiene la password);
  il modello è `config.esempio.json`.
- **Con MySQL**: la tabella **esiste già e l'app non la crea**. La mappatura `colonne` (campo
  dell'app → colonna) sta nel config apposta: la struttura della tabella vera non è ancora nota,
  e adattarsi deve voler dire cambiare il config, non il codice. `config_mysql.py` ammette nei
  nomi di tabella/colonna solo `[A-Za-z0-9_]` perché finiscono interpolati nell'SQL (i valori
  invece sono parametri). Un `config.json` presente ma errato **ferma l'avvio** del server:
  meglio che lavorare un giorno credendo di salvare su MySQL.
- **MySQL che non risponde** non è un errore per l'operatore: il recapito va nella coda
  `in_attesa` di `recapiti.db` (JSON con tutti i `CAMPI`) e un thread la svuota ogni
  `INTERVALLO_REINVIO` secondi. Finché MySQL risulta giù (`_giu`) i nuovi recapiti si accodano
  subito, senza aspettare `TIMEOUT_S` a ogni busta e rispettando l'ordine. Errori con codice
  ≥ 2000 o di rete = connessione (si riprova); codici 1000-1999 = il server rifiuta **quella**
  riga (colonna inesistente, dato troppo lungo): resta in coda, si segnala una volta e non
  blocca le altre. Le righe storiche di `recapiti` non vengono mai inviate a MySQL.

Il banco non tocca l'archivio. Per provarlo senza un MySQL vero basta un host irraggiungibile
(`127.0.0.1:1`) e un `archivio.DB` temporaneo: **mai** provare con MySQL configurato sul
`recapiti.db` reale, perché i recapiti di prova rimasti in coda finirebbero nel database vero.

## Privacy (vincolo di progetto)

La foto contiene nome e indirizzo del destinatario. `recapiti.db` (tabella e coda) e la tabella
MySQL salvano **solo** i `CAMPI` di `config_mysql.py` (data/ora, codice, modello, casella,
etichetta, QR) — **mai l'immagine**. `esiti.jsonl` (`_traccia`) registra solo numeri
(inlier, residuo, punteggi) e nessun dato del destinatario. Non introdurre persistenza di
immagini o di dati personali senza che sia una richiesta esplicita.

## Note sulla modifica del riconoscimento

Prima e dopo qualsiasi cambio al riconoscimento (`riconoscimento.py`, `registrazione.py`,
`misura_caselle.py`, `soglie.py`), eseguire `banco.py` sullo stesso seed e
confrontare le tre percentuali: corrette / **proposte sbagliate** (il caso pericoloso) /
nessuna proposta. I numeri del banco sono un **limite superiore** — le foto derivano dalla
stessa immagine usata come riferimento — quindi servono a confrontare due versioni sullo stesso
metro, non a promettere una percentuale sul campo.

`mod24b` parte già più basso di `sd24c6` (circa 80% di corrette contro 90%, nessuna proposta
sbagliata; i valori esatti cambiano un po' con la versione di OpenCV): il suo
riferimento è stato ricavato da una foto con una casella barrata. È un limite noto del modello,
non una regressione; si risolve ricalibrandolo con `calibra.py` su un modulo vuoto.
