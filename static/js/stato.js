// Stato condiviso fra gli script della pagina. Sono script classici (niente moduli né build):
// le dichiarazioni di primo livello stanno nello stesso ambito globale, quindi l'ordine dei
// <script> in index.html conta solo per il codice eseguito al caricamento. Questo file va
// caricato per primo, e l'avvio (avvio.js) per ultimo.
let MODELLI = [], modello = null, scelta = null, canvasBlob = null, qrValue = '';

const $ = s => document.querySelector(s);
