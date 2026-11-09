// Elenco dei modelli calibrati, scelta del modello e sagoma-guida corrispondente.
async function initModelli(){
  MODELLI = await (await fetch('/modelli')).json();
  if(MODELLI.length){ setModello(MODELLI.find(m=>m.predefinito) || MODELLI[0]); }
  $('#modelloBtn').onclick = apriDialogModelli;
}
function setModello(m){
  modello = m;
  $('#modelloBtn').textContent = 'Modello: ' + m.nome;
  const g = $('#ghost');
  g.onload = applyFrame;                         // appena arriva il riferimento ne conosco il rapporto
  g.onerror = ()=>{ g.removeAttribute('src'); applyFrame(); };   // senza sagoma la cornice usa comunque il rapporto del modello
  g.src = '/riferimento/' + m.id;                // sagoma-guida del modello scelto
}

function apriDialogModelli(){
  const d = $('#dlgModelli');
  d.innerHTML = '<h3 style="margin-top:0">Scegli il modello</h3>' +
    MODELLI.map(m=>`<button class="opt" data-id="${m.id}">${m.nome}</button>`).join('') +
    '<button class="big" id="chiudiDlg" style="background:#374151">Annulla</button>';
  d.querySelectorAll('.opt').forEach(b=> b.onclick=()=>{ setModello(MODELLI.find(x=>x.id===b.dataset.id)); d.close(); });
  $('#chiudiDlg').onclick=()=>d.close();
  d.showModal();
}
