#!/usr/bin/env python3
"""
verifica_mysql.py - controlla config.json contro la tabella MySQL vera, senza avviare il server.

    python verifica_mysql.py

Prova la connessione, elenca le colonne della tabella indicando quale campo dell'app compila
ciascuna, e segnala le incoerenze (colonna inesistente, colonna obbligatoria non compilata).
Serve a compilare la mappatura "colonne" quando si guarda la tabella per la prima volta.
Esce con 1 se qualcosa non va.
"""
import os, sqlite3, sys

import archivio, config_mysql


def main():
    try:
        cfg = config_mysql.leggi()
    except config_mysql.ConfigErrata as e:
        print(f"config.json non valido: {e}")
        return 1
    if cfg is None:
        print("MySQL non configurato (manca config.json o la sezione 'mysql'): "
              f"i recapiti vanno in {archivio.DB}")
        return 0
    try:
        archivio.configura(cfg)
    except config_mysql.ConfigErrata as e:
        print(e)
        return 1

    print(f"Connessione a {cfg['host']}:{cfg['porta']}/{cfg['database']} "
          f"come '{cfg['utente']}'...")
    try:
        con = archivio.connetti()
    except Exception as e:
        print(f"  NON riuscita: {e}")
        return 1
    try:
        colonne = archivio.colonne_tabella(con)
    except Exception as e:
        print(f"  connessione ok, ma la tabella '{cfg['tabella']}' non e' leggibile: {e}")
        return 1
    finally:
        archivio.chiudi(con)

    campo_di = {col.lower(): campo for campo, col in cfg["mappa"]}
    print(f"  ok. Colonne della tabella '{cfg['tabella']}' (<- campo dell'app che la compila):")
    for nome, tipo, null, _chiave, _default, _extra in colonne:
        campo = campo_di.get(nome.lower())
        print(f"    {nome:24s} {tipo:22s} {'NULL' if null == 'YES' else 'NOT NULL':9s}"
              f"{'  <- ' + campo if campo else ''}")
    problemi = archivio.problemi(colonne)
    for p in problemi:
        print(f"  PROBLEMA: {p}")
    if not problemi:
        print("  Mappatura coerente con la tabella.")
    if os.path.exists(archivio.DB):
        try:
            print(f"  Recapiti nella coda locale, in attesa di invio: {archivio.in_coda()}")
        except sqlite3.Error:
            pass   # recapiti.db di una versione senza coda: il server la crea al primo avvio
    return 1 if problemi else 0


if __name__ == "__main__":
    sys.exit(main())
