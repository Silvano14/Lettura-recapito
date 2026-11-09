// ---- Lettura QR (jsQR, lato client): robusta a riflesso/posizione, prova molti fotogrammi ----
function aggiornaQrBadge(){
  const b=$('#qrbadge');
  if(qrValue){ b.textContent='QR ✓ '+qrValue; b.classList.add('ok'); }
  else { b.textContent='Inquadra anche il QR (in alto)'; b.classList.remove('ok'); }
}
// normalizza il contenuto del QR: toglie prefissi-schema tipo "tel:", "sms:", "mailto:"
// (i QR numerici vengono spesso generati come "tel:12345") e spazi → resta solo il valore
function pulisciQr(s){
  if(!s) return '';
  return String(s).trim().replace(/^(tel|sms|smsto|mailto)\s*:\s*(\/\/)?/i, '').trim();
}
function scanQRCanvas(canvas){
  // scandisce solo se il modello prevede il QR e non l'ho già letto per questa busta
  if(typeof jsQR!=='function' || qrValue || !modello || !modello.leggi_qr) return false;
  try{
    const im = canvas.getContext('2d',{willReadFrequently:true}).getImageData(0,0,canvas.width,canvas.height);
    const code = jsQR(im.data, im.width, im.height, {inversionAttempts:'attemptBoth'});
    if(code && code.data){ qrValue = pulisciQr(code.data); aggiornaQrBadge(); return true; }
  }catch(e){ /* frame non leggibile: riprovo al prossimo */ }
  return false;
}
function scanQRFromVideo(video){
  // il QR si legge dal fotogramma INTERO (ovunque sia), disaccoppiato dal ritaglio d'analisi
  if(typeof jsQR!=='function' || qrValue || !modello || !modello.leggi_qr || !video.videoWidth) return false;
  const w=Math.min(1000, video.videoWidth), h=Math.round(video.videoHeight*w/video.videoWidth);
  const c=document.createElement('canvas'); c.width=w; c.height=h;
  c.getContext('2d',{willReadFrequently:true}).drawImage(video,0,0,w,h);
  return scanQRCanvas(c);
}

// ---- Scansione del SOLO codice QR (in verifica): riempie il codice raccomandata
//      senza toccare la scelta del mancato recapito ----
function impostaQr(val){ val=pulisciQr(val); qrValue=val; $('#codice').value=val; aggiornaQrBadge(); }
let qrScanTimer=null;
function openQrScan(){
  if(typeof jsQR!=='function'){ alert('Lettore QR non disponibile.'); return; }
  if(!stream){ $('#qrfile').click(); return; }   // niente camera: scelgo un'immagine del QR
  const d=$('#dlgQr'), v=$('#qrvideo'), st=$('#qrStatus');
  st.textContent='Inquadra il QR nel riquadro azzurro…';
  v.srcObject=stream;                            // stesso stream della camera principale
  d.showModal();
  qrScanTimer=setInterval(()=>{
    if(!v.videoWidth) return;
    const w=Math.min(800, v.videoWidth), h=Math.round(v.videoHeight*w/v.videoWidth);
    const c=document.createElement('canvas'); c.width=w; c.height=h;
    const ctx=c.getContext('2d',{willReadFrequently:true}); ctx.drawImage(v,0,0,w,h);
    try{
      const im=ctx.getImageData(0,0,w,h);
      const code=jsQR(im.data, im.width, im.height, {inversionAttempts:'attemptBoth'});
      if(code && code.data){ impostaQr(code.data); st.textContent='QR ✓ '+qrValue; setTimeout(closeQrScan,700); }
    }catch(e){}
  }, 150);
}
function closeQrScan(){
  if(qrScanTimer){ clearInterval(qrScanTimer); qrScanTimer=null; }
  $('#qrvideo').srcObject=null;                  // sgancio il video (NON fermo i track: servono alla camera)
  const d=$('#dlgQr'); if(d.open) d.close();
}
$('#scanQrBtn').onclick = openQrScan;
$('#qrAnnulla').onclick = closeQrScan;
$('#dlgQr').addEventListener('close', closeQrScan);   // anche con Esc: ferma la sonda QR
$('#qrfile').onchange = async ()=>{
  const f=$('#qrfile').files[0]; if(!f) return;
  const img=await createImageBitmap(f);
  const c=document.createElement('canvas'); c.width=img.width; c.height=img.height;
  const ctx=c.getContext('2d',{willReadFrequently:true}); ctx.drawImage(img,0,0);
  try{
    const im=ctx.getImageData(0,0,c.width,c.height);
    const code=jsQR(im.data, im.width, im.height, {inversionAttempts:'attemptBoth'});
    if(code && code.data) impostaQr(code.data); else alert('Nessun QR riconosciuto nell\'immagine.');
  }catch(e){ alert('Immagine non leggibile.'); }
  $('#qrfile').value='';
};
