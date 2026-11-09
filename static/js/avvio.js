// Avvio della pagina: va caricato per ULTIMO, quando tutti gli altri script hanno già
// dichiarato funzioni e stato (initCamera arriva fino a avviaAuto e fermaAuto).

// la dimensione del camArea cambia con rotazione/resize: ricalcolo la cornice
window.addEventListener('resize', applyFrame);
window.addEventListener('orientationchange', ()=>setTimeout(applyFrame, 300));

initModelli(); initCamera();
