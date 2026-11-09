// ---- Auto-scansione: sonda continua l'aggancio e scatta da sola quando e' stabile ----
// STABLE fotogrammi buoni di fila -> scatto. Il riarmo ("è arrivata una busta nuova") è
// espresso come FRAZIONE della soglia comunicata dal server, non come numero fisso: così
// resta valido se la soglia cambia, e non capita più che con un foglio stampato qualsiasi
// davanti all'obiettivo l'auto-scatto non si riarmi mai.
const POLL_MS=350, STABLE=3, ARM_FRAZ=0.35;
let auto={on:true, busy:false, hits:0, armed:false, timer:null, giro:0, errori:0};

function setGuida(stato, info){
  const g=$('.guide'), b=$('#badge');
  g.classList.remove('vicino','lock','attesa');
  if(!auto.on || !stream){ b.textContent = stream ? 'Auto OFF — usa "Scatta e analizza"' : ''; return; }
  const n = info ? '  ('+info+')' : '';      // livello di aggancio, es. (14/18), utile per tarare
  if(stato==='attesa'){ g.classList.add('attesa'); b.textContent='Togli la busta e metti la prossima…'; }
  else if(stato==='lock'){ g.classList.add('lock'); b.textContent='Aggancio stabile — scansione…'+n; }
  else if(stato==='vicino'){ g.classList.add('vicino'); b.textContent='Quasi… tieni fermo'+n; }
  else { b.textContent='Inquadra il riquadro nella cornice'+n; }
}

function aggiornaStato(r){
  const inl=r.inlier||0, ok=r.ok, soglia=r.soglia||1, info=inl+'/'+soglia;
  const armaSotto=Math.max(3, Math.round(soglia*ARM_FRAZ));
  if(!auto.armed){                         // dopo uno scatto aspetto che il frame torni "vuoto"
    auto.hits=0;
    if(inl < armaSotto){ auto.armed=true; setGuida('pronto', info); }
    else setGuida('attesa');
    return;
  }
  if(ok){
    auto.hits++; setGuida('lock', info);
    if(auto.hits>=STABLE){ auto.hits=0; auto.armed=false; cattura(); }   // scatto automatico
  }else{
    auto.hits=0; setGuida(inl>=armaSotto ? 'vicino' : 'pronto', info);
  }
}

async function probe(){
  if(!auto.on || auto.busy || !modello || !stream || document.hidden) return;
  if($('#fase1').classList.contains('hidden')) return;     // siamo nella verifica: non sondare
  const v=$('#video'); if(!v.videoWidth) return;
  auto.busy=true;
  const giro=auto.giro;                            // marca il ciclo a cui appartiene questa sonda
  try{
    const c=ritagliaGuidaProbe(v);
    scanQRFromVideo(v);                            // QR letto dal fotogramma intero (finché non riesce)
    const blob=await new Promise(res=>c.toBlob(res,'image/jpeg',0.6));
    if(!blob) return;
    const fd=new FormData(); fd.append('foto',blob,'p.jpg'); fd.append('modello',modello.id);
    const resp=await fetch('/aggancio',{method:'POST',body:fd});
    const r=await resp.json().catch(()=>null);
    // Una risposta arrivata in ritardo appartiene a un ciclo già chiuso: agire su di essa
    // faceva scattare una foto durante la verifica, cancellando la scelta dell'operatore.
    if(giro!==auto.giro || $('#fase1').classList.contains('hidden')) return;
    if(!r || !resp.ok){ throw new Error('aggancio'); }
    auto.errori=0; banner('');
    aggiornaStato(r);
  }catch(e){
    // il catch non è più muto: se il server smette di rispondere l'operatore deve saperlo,
    // altrimenti resta davanti a una cornice grigia che non spiega nulla
    if(++auto.errori===5) banner('Il server non risponde: lo scatto automatico è fermo. '+
                                 'Puoi comunque usare <b>Scatta e analizza</b>.', true);
  }
  finally{ auto.busy=false; }
}

function avviaAuto(){
  if(!stream) return;
  fermaAuto();
  auto.hits=0; auto.armed=false; auto.busy=false;   // riparte: serve un frame vuoto per riarmarsi
  setGuida('attesa');
  applyFrame();                                     // il layout può essere cambiato mentre eravamo in verifica
  auto.timer=setInterval(probe, POLL_MS);
}
function fermaAuto(){ auto.giro++; if(auto.timer){ clearInterval(auto.timer); auto.timer=null; } }

$('#autoBtn').onclick = ()=>{
  auto.on=!auto.on;
  $('#autoBtn').textContent='Auto: '+(auto.on?'ON':'OFF');
  $('#autoBtn').classList.toggle('off', !auto.on);
  if(auto.on) avviaAuto(); else { fermaAuto(); setGuida('off'); }
};
