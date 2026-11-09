// Cornice-guida espressa in FRAZIONI DEL FOTOGRAMMA (non del riquadro a schermo): è
// esattamente la porzione di video che viene ritagliata e mandata ad analizzare, quindi
// ciò che l'operatore vede dentro la cornice è ciò che il server riceve.
let FRAME = {x:0.05, y:0.25, w:0.90, h:0.50};

// Rettangolo (in px del riquadro a schermo) realmente occupato dal fotogramma: con
// object-fit:contain il video è interamente visibile e nessuna parte del sensore va persa,
// così la cornice può mappare tutta la larghezza disponibile invece di ~un terzo.
function rettVideo(){
  const cam = $('.camArea'), v = $('#video');
  const CW = cam.clientWidth, CH = cam.clientHeight, VW = v.videoWidth, VH = v.videoHeight;
  if(!CW || !CH || !VW || !VH) return null;
  const s = Math.min(CW/VW, CH/VH);
  return {x:(CW - VW*s)/2, y:(CH - VH*s)/2, w:VW*s, h:VH*s, s};
}

// Cornice-guida con il rapporto del modello scelto, iscritta nel fotogramma e disegnata
// esattamente sopra la porzione di video corrispondente. FRAME è in frazioni del fotogramma:
// una sola grandezza descrive sia ciò che si vede sia ciò che si ritaglia, e le due non
// possono più divergere.
function applyFrame(){
  const g = $('#ghost'), v = $('#video');
  const rv = rettVideo();
  if(!rv){ return; }
  const modRatio = rapportoModello();
  const boxRatio = (g.naturalWidth && g.naturalHeight) ? g.naturalWidth/g.naturalHeight : modRatio;
  const rel = boxRatio / (v.videoWidth / v.videoHeight);
  let fw, fh;
  if(rel >= 1){ fw = 0.94; fh = 0.94/rel; }
  else        { fh = 0.94; fw = 0.94*rel; }
  FRAME = {x:(1-fw)/2, y:(1-fh)/2, w:fw, h:fh};

  const root = document.documentElement.style;
  root.setProperty('--fx', (rv.x + FRAME.x*rv.w).toFixed(1)+'px');
  root.setProperty('--fy', (rv.y + FRAME.y*rv.h).toFixed(1)+'px');
  root.setProperty('--fw', (FRAME.w*rv.w).toFixed(1)+'px');
  root.setProperty('--fh', (FRAME.h*rv.h).toFixed(1)+'px');
  // il QR si legge dal fotogramma intero (vedi scanQRFromVideo): mostro il badge se il modello lo prevede
  $('#qrbadge').classList.toggle('hidden', !(modello && modello.leggi_qr) || !stream);
}

// Rapporto del riquadro del modello, noto anche prima che la sagoma sia scaricata: senza
// questo la cornice nasceva con un rapporto arbitrario e il ritaglio partiva deformato.
function rapportoModello(){
  const d = modello && modello.dim_riferimento;
  return (d && d[0] && d[1]) ? d[0]/d[1] : 2.25;
}

// La cornice è già in frazioni del fotogramma: passare ai pixel del video è una moltiplicazione.
function rettangoloVideo(video, fr){
  return {x: fr.x*video.videoWidth,  y: fr.y*video.videoHeight,
          w: fr.w*video.videoWidth,  h: fr.h*video.videoHeight};
}

function ritagliaGuida(video){
  // ritaglio la cornice-guida (= il riquadro) per l'analisi
  const r=rettangoloVideo(video, FRAME);
  const w=Math.max(1,Math.round(r.w)), h=Math.max(1,Math.round(r.h));
  const c=document.createElement('canvas'); c.width=w; c.height=h;
  c.getContext('2d').drawImage(video, r.x,r.y,r.w,r.h, 0,0,w,h);
  return c;
}

function ritagliaGuidaProbe(video){
  // come ritagliaGuida ma ridotto: la sonda misura l'aggancio sul riquadro.
  // Il server normalizza la scala prima di agganciare, quindi la misura della sonda e quella
  // dell'analisi sono confrontabili anche se le risoluzioni differiscono.
  const r=rettangoloVideo(video, FRAME);
  const scale=Math.min(1, 900/Math.max(1,r.w));
  const cw=Math.max(1,Math.round(r.w*scale)), ch=Math.max(1,Math.round(r.h*scale));
  const c=document.createElement('canvas'); c.width=cw; c.height=ch;
  c.getContext('2d').drawImage(video, r.x,r.y,r.w,r.h, 0,0,cw,ch);
  return c;
}
