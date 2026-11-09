// fotocamera con guida (richiede contesto sicuro). Fallback: input file nativo.
let stream=null;
function banner(html, errore){
  const b=$('#statoCam');
  if(!html){ b.classList.add('hidden'); return; }
  b.innerHTML=html; b.classList.toggle('err', !!errore); b.classList.remove('hidden');
}

function modalitaRidotta(motivo){
  // Niente fotocamera con guida: si scatta con la fotocamera nativa. Funziona, ma senza
  // sagoma e senza auto-scatto. Prima questo avveniva in silenzio e l'operatore non poteva
  // sapere perché l'app si comportava in modo diverso: ora lo diciamo, con il rimedio.
  $('.camArea').classList.add('hidden');
  $('#file').classList.remove('hidden');
  $('#autoBtn').classList.add('hidden');
  auto.on=false; fermaAuto();
  $('#scatta').textContent='Scegli o scatta la foto';
  const https = location.protocol==='https:';
  banner('<b>Modalità ridotta:</b> '+motivo+'<br>Si scatta a mano, senza sagoma e senza scatto automatico.'+
         (https ? '' : ' Il browser concede la fotocamera solo in <b>HTTPS</b>: riavvia il server con <b>--https</b> e riapri la pagina in https://'), true);
}

async function initCamera(){
  // Nessun blocco di orientamento: funziona sia in verticale sia in orizzontale.
  // La cornice-guida e il ritaglio si adattano da soli (applyFrame + rettangoloVideo).
  if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
    modalitaRidotta(window.isSecureContext===false
      ? 'la pagina non è in un contesto sicuro, quindi il browser non espone la fotocamera.'
      : 'questo browser non espone la fotocamera alle pagine web.');
    return;
  }
  try{
    stream = await navigator.mediaDevices.getUserMedia({video:{
      facingMode:{ideal:'environment'},
      width:{ideal:1920},          // chiedo comunque buona risoluzione
      height:{ideal:1080},
      // su Android senza questi il fotogramma arriva spesso molle o riscalato da un formato
      // più piccolo; sono "advanced", quindi vengono ignorati dove non sono supportati
      advanced:[{focusMode:'continuous'},{resizeMode:'none'}]
    }});
    $('#video').srcObject = stream;
    $('#video').addEventListener('loadedmetadata', applyFrame);   // noto il rapporto reale della camera → ricalcolo
    // se un'altra app si prende la fotocamera il video si congela: senza questo l'auto-scatto
    // continuerebbe ad analizzare un fotogramma morto
    stream.getVideoTracks().forEach(t=>{
      t.addEventListener('ended', ()=>modalitaRidotta('la fotocamera è stata chiusa da un\'altra app.'));
      t.addEventListener('mute', ()=>banner('Fotocamera momentaneamente sospesa…', true));
      t.addEventListener('unmute', ()=>banner(''));
    });
    banner('');
    avviaAuto();                       // fotocamera viva: parte la sonda dell'auto-scansione
  }catch(e){
    const nome=(e && e.name)||'';
    modalitaRidotta(
      nome==='NotAllowedError' ? 'il permesso della fotocamera è stato negato.' :
      nome==='NotFoundError'   ? 'nessuna fotocamera disponibile.' :
      nome==='NotReadableError'? 'la fotocamera è occupata da un\'altra app.' :
      'la fotocamera non è disponibile ('+(nome||'errore sconosciuto')+').');
  }
}
