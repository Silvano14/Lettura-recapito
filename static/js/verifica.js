// Scatto, invio a /analizza, schermata di verifica e salvataggio confermato dall'operatore.

function eseguiAnalisi(canvas){
  canvas.toBlob(async (blob)=>{
    if(!blob){ erroreAcquisizione('Fotogramma non valido, riprova.'); return; }
    canvasBlob = blob;
    try{
      const fd=new FormData(); fd.append('foto',blob,'box.jpg'); fd.append('modello',modello.id);
      const resp = await fetch('/analizza',{method:'POST',body:fd});
      const r = await resp.json().catch(()=>({}));
      if(!resp.ok){ erroreAcquisizione(r.errore || ('Errore del server ('+resp.status+').')); return; }
      mostraVerifica(r);
    }catch(e){
      // senza questo un errore di rete lasciava l'app viva ma ferma: sonda spenta,
      // nessun messaggio e il pulsante apparentemente morto
      erroreAcquisizione('Server non raggiungibile. Controlla la connessione.');
    }
  },'image/jpeg',0.85);
}

function erroreAcquisizione(msg){
  banner('<b>Analisi non riuscita:</b> '+msg, true);
  $('#fase2').classList.add('hidden'); $('#fase1').classList.remove('hidden');
  if(auto.on) avviaAuto();               // si riparte, invece di restare bloccati
}

async function cattura(){
  if(!modello){ banner('Nessun modello calibrato: controlla la cartella modelli/.', true); return; }
  fermaAuto();                                   // niente sonde mentre analizziamo/verifichiamo
  let canvas;
  if(stream){
    const v=$('#video');
    if(!v.videoWidth){ banner('La fotocamera non è ancora pronta, riprova fra un istante.', true);
                       if(auto.on) avviaAuto(); return; }
    canvas = ritagliaGuida(v); scanQRFromVideo(v);   // analisi=solo riquadro; QR=frame intero
  }
  else if($('#file').files[0]){
    let img;
    try{
      // imageOrientation: senza questo la foto della fotocamera nativa arriva ruotata
      // rispetto a come l'operatore la vede
      img = await createImageBitmap($('#file').files[0], {imageOrientation:'from-image'});
    }catch(e){ banner('Immagine non leggibile.', true); return; }
    canvas=document.createElement('canvas'); canvas.width=img.width; canvas.height=img.height;
    canvas.getContext('2d',{willReadFrequently:true}).drawImage(img,0,0);
    scanQRCanvas(canvas);                          // da file: cerco il QR su tutta l'immagine
    $('#file').value='';                           // senza questo il prossimo scatto rianalizza questa foto
  } else { $('#file').click(); return; }
  eseguiAnalisi(canvas);
}
$('#scatta').onclick = cattura;
$('#file').onchange = cattura;

function mostraVerifica(r){
  $('#fase1').classList.add('hidden'); $('#fase2').classList.remove('hidden');
  $('#prev').src = r.anteprima || '';
  const av=$('#avviso');
  if(r.avviso_coerenza){ av.textContent='⚠ '+r.avviso_coerenza; av.classList.remove('hidden'); }
  else av.classList.add('hidden');

  // codice raccomandata = QR letto (solo per i modelli che hanno un QR). Campo non editabile a mano:
  // se non è stato letto durante l'inquadratura, si usa "Scansiona QR" senza toccare la scelta.
  $('#codiceRow').classList.toggle('hidden', !modello.leggi_qr);
  if(modello.leggi_qr) $('#codice').value = qrValue || '';

  // griglia unica: destinatario a sinistra, indirizzo a destra (come sulla busta).
  // pre-evidenzio la proposta, ma niente salvataggio automatico: conferma sempre richiesta.
  scelta = r.proposta || null;
  const cats={};
  modello.caselle.forEach(c=> (cats[c.categoria]=cats[c.categoria]||[]).push(c));
  const ordine = ['destinatario','indirizzo'].concat(Object.keys(cats).filter(c=>c!=='destinatario'&&c!=='indirizzo'));
  const colonna = cat => !cats[cat] ? '' :
    `<div class="col"><h4>${cat}</h4>` +
      cats[cat].map(c=>{
        const isProp = c.id===r.proposta;
        return `<button class="opt ${isProp?'proposta sel':''}" data-id="${c.id}" data-et="${c.etichetta}">`+
               `${c.etichetta.split(' - ').pop()}${isProp?' <span class="tag">●</span>':''}</button>`;
      }).join('') + `</div>`;
  $('#opzioni').innerHTML = '<div class="opzioni-grid">' + ordine.map(colonna).join('') + '</div>';
  $('#opzioni').querySelectorAll('.opt').forEach(b=> b.onclick=()=>{
    $('#opzioni').querySelectorAll('.opt').forEach(x=>x.classList.remove('sel'));
    b.classList.add('sel'); scelta=b.dataset.id;
  });

  // diagnostica: se NON c'è una proposta sicura, spiego perché (livello, aggancio, punteggi top)
  const diag=$('#diag');
  if(!r.proposta && r.punteggi && Object.keys(r.punteggi).length){
    const etich={}; modello.caselle.forEach(c=> etich[c.id]=c.etichetta.split(' - ').pop());
    const ord=Object.entries(r.punteggi).sort((a,b)=>b[1]-a[1]);
    const top=ord.slice(0,3).map(([id,v])=>`${etich[id]||id} ${v.toFixed(2)}`).join(' · ');
    const forti=ord.filter(([,v])=>v>=0.10).length;
    const motivo = forti>1 ? 'più caselle sembrano barrate'
                 : r.livello==='nessuna' ? 'nessun segno abbastanza marcato'
                 : 'segno trovato ma troppo vicino agli altri';
    let extra='';
    if(r.residuo!=null && r.residuo>2.5) extra+=' · allineamento impreciso ('+r.residuo+' px)';
    if(r.illeggibili && r.illeggibili.length) extra+=' · '+r.illeggibili.length+' caselle non leggibili';
    diag.innerHTML = `Nessuna proposta sicura: <b>${motivo}</b>.<br>`+
      `aggancio ${r.inlier} riscontri${extra} · punteggi: ${top}<br>`+
      `Tocca tu la casella giusta e conferma.`;
    diag.classList.remove('hidden');
  } else diag.classList.add('hidden');
}

$('#conferma').onclick = async ()=>{
  if(!scelta){ alert('Seleziona una casella prima di confermare.'); return; }
  const et = $('#opzioni').querySelector(`[data-id="${scelta}"]`).dataset.et;
  const btn=$('#conferma'); btn.disabled=true;
  try{
    const resp = await fetch('/salva',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({codice:$('#codice').value, modello:modello.id, casella_id:scelta, etichetta:et, qr:qrValue})});
    const r = await resp.json().catch(()=>({}));
    // il toast "Salvato ✓" prima compariva anche quando il salvataggio falliva, e il dato
    // era perso senza che nessuno lo sapesse
    if(!resp.ok || !r.ok){ alert('NON salvato: '+(r.errore||('errore '+resp.status))+'\nRiprova.'); return; }
    toast(); reset();
  }catch(e){
    alert('NON salvato: server non raggiungibile.\nRiprova senza chiudere la pagina.');
  }finally{ btn.disabled=false; }
};
$('#rifai').onclick = reset;

function reset(){
  $('#fase2').classList.add('hidden'); $('#fase1').classList.remove('hidden');
  $('#codice').value=''; scelta=null; canvasBlob=null;
  qrValue=''; aggiornaQrBadge();        // nuova busta: dimentico il QR letto e riprendo a scandire
  // la cornice va ricalcolata qui: mentre eravamo in verifica il riquadro della camera aveva
  // dimensione zero, e una rotazione dello schermo l'avrebbe lasciata tarata sul layout vecchio
  applyFrame();
  if(auto.on) avviaAuto();             // riarma l'auto-scansione per la busta successiva
}
function toast(){ const t=$('#toast'); t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),1200); }
