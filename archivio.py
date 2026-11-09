"""
archivio.py - dove finiscono i recapiti confermati dall'operatore.

  - MySQL non configurato (vedi config_mysql.py): SQLite locale, recapiti.db tabella recapiti,
    esattamente come prima che esistesse MySQL;
  - MySQL configurato: ogni recapito va nella tabella MySQL. Se MySQL non risponde il recapito
    finisce nella CODA LOCALE (tabella in_attesa di recapiti.db) e un thread lo reinvia appena
    il database torna raggiungibile. L'operatore non perde mai un dato e non resta ad
    aspettare un database spento.
"""
from __future__ import annotations
import datetime, json, logging, os, sqlite3, threading, time

import config_mysql
from config_mysql import CAMPI, ConfigErrata

DB = os.path.join(config_mysql.BASE, "recapiti.db")
TIMEOUT_S = 3             # con MySQL spento l'operatore aspetta al massimo questo, poi si accoda
INTERVALLO_REINVIO = 60   # secondi fra due tentativi di svuotare la coda

log = logging.getLogger("recapiti.archivio")

_cfg = None          # configurazione MySQL validata; None = solo SQLite locale
_pymysql = None      # importato solo se serve: senza MySQL il pacchetto non e' richiesto
_giu = False         # MySQL risulta irraggiungibile: i nuovi recapiti vanno subito in coda
_segnalati = set()   # righe in coda gia' segnalate come rifiutate: niente errore ogni minuto


# ---------------------------------------------------------------- MySQL

def configura(cfg):
    global _cfg, _pymysql
    try:
        import pymysql
    except ImportError:
        raise ConfigErrata("config.json chiede MySQL ma manca il pacchetto: pip install pymysql")
    _pymysql, _cfg = pymysql, cfg


def connetti():
    c = _cfg
    return _pymysql.connect(host=c["host"], port=c["porta"], user=c["utente"],
                            password=c["password"], database=c["database"], charset="utf8mb4",
                            connect_timeout=TIMEOUT_S, read_timeout=TIMEOUT_S * 2,
                            write_timeout=TIMEOUT_S * 2)


def chiudi(con):
    try:
        con.close()
    except Exception:
        pass   # dopo una connessione caduta pymysql solleva "Already closed": nulla da fare


def colonne_tabella(con):
    with con.cursor() as cur:
        cur.execute(f"SHOW COLUMNS FROM {_cfg['tabella_sql']}")
        return cur.fetchall()     # (Field, Type, Null, Key, Default, Extra)


def problemi(colonne):
    """Incoerenze fra tabella e mappatura, da dire PRIMA che gli inserimenti falliscano."""
    nomi = {c[0].lower() for c in colonne}            # MySQL non distingue le maiuscole
    mappate = {col.lower() for _, col in _cfg["mappa"]}
    out = [f"la colonna '{col}' (per il campo '{campo}') non esiste nella tabella"
           for campo, col in _cfg["mappa"] if col.lower() not in nomi]
    for nome, _tipo, null, _chiave, default, extra in colonne:
        auto = any(s in (extra or "").lower() for s in ("auto_increment", "generated"))
        if null == "NO" and default is None and not auto and nome.lower() not in mappate:
            out.append(f"la colonna obbligatoria '{nome}' non viene compilata dall'app: "
                       "ogni inserimento verrebbe rifiutato")
    return out


def _inserisci(con, rec):
    valori = []
    for campo, _ in _cfg["mappa"]:
        v = rec.get(campo)
        if campo == "ts" and isinstance(v, str):
            v = datetime.datetime.fromisoformat(v)   # DATETIME vero, non testo
        valori.append(v)
    try:
        with con.cursor() as cur:
            cur.execute(_cfg["sql"], valori)
        con.commit()
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise


def _connessione_persa(e):
    """Errori di rete o lato client (codici 2000+: non connette, connessione caduta, timeout):
    riprovare piu' tardi ha senso. Gli errori del server (codici 1000-1999: colonna inesistente,
    dato troppo lungo, chiave duplicata) si ripeterebbero identici a ogni tentativo, quindi non
    devono far credere che MySQL sia spento."""
    if isinstance(e, (OSError, _pymysql.err.InterfaceError)):
        return True
    codice = e.args[0] if e.args and isinstance(e.args[0], int) else 0
    return codice >= 2000


def _segna_giu(e):
    global _giu
    if not _giu:
        log.warning("MySQL non raggiungibile (%s): i recapiti restano nella coda locale e "
                    "verranno reinviati in automatico", e)
    _giu = True


# ---------------------------------------------------------------- SQLite (locale e coda)

def _sqlite():
    return sqlite3.connect(DB, timeout=5)


def _init_sqlite():
    con = _sqlite()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS recapiti(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, codice TEXT, modello TEXT, casella_id TEXT, etichetta TEXT, qr TEXT)""")
        cols = {r[1] for r in con.execute("PRAGMA table_info(recapiti)")}
        if "qr" not in cols:
            con.execute("ALTER TABLE recapiti ADD COLUMN qr TEXT")
        con.execute("CREATE INDEX IF NOT EXISTS idx_recapiti_ts ON recapiti(ts)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_recapiti_codice ON recapiti(codice)")
        # Coda verso MySQL: tabella separata da recapiti, cosi' lo storico locale gia' presente
        # non viene scambiato per lavoro da inviare. Il record e' JSON intero (tutti i CAMPI):
        # se nel frattempo la mappatura cambia, la riga in coda ha ancora ogni dato.
        con.execute("""CREATE TABLE IF NOT EXISTS in_attesa(
            id INTEGER PRIMARY KEY AUTOINCREMENT, dati TEXT NOT NULL)""")
        con.commit()
    finally:
        con.close()


def _locale(rec):
    con = _sqlite()
    try:
        con.execute("INSERT INTO recapiti(ts,codice,modello,casella_id,etichetta,qr) "
                    "VALUES(?,?,?,?,?,?)", tuple(rec.get(k) for k in CAMPI))
        con.commit()
    finally:
        con.close()


def _accoda(rec):
    con = _sqlite()
    try:
        cur = con.execute("INSERT INTO in_attesa(dati) VALUES(?)",
                          (json.dumps({k: rec.get(k) for k in CAMPI}, ensure_ascii=False),))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def in_coda():
    con = _sqlite()
    try:
        return con.execute("SELECT COUNT(*) FROM in_attesa").fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------------------- API usata da server.py

def salva(rec):
    """Registra un recapito confermato (dict con i CAMPI, ts in ISO). Restituisce dove e'
    finito: 'mysql', 'in_attesa' (coda locale, partira' da solo) o 'locale' (MySQL non
    configurato). Solleva sqlite3.Error solo se fallisce anche il disco locale: e' l'unico
    caso in cui il dato non e' al sicuro, e l'operatore deve saperlo."""
    if _cfg is None:
        _locale(rec)
        return "locale"
    rifiutato = False
    # Con MySQL gia' noto come spento non si riprova qui: l'operatore aspetterebbe il timeout a
    # ogni busta. Ci pensa il thread di reinvio, che rispetta anche l'ordine della coda.
    if not _giu:
        try:
            con = connetti()
        except Exception as e:
            _segna_giu(e)
        else:
            try:
                _inserisci(con, rec)
                return "mysql"
            except Exception as e:
                if _connessione_persa(e):
                    _segna_giu(e)
                else:
                    rifiutato = True
                    log.error("MySQL ha rifiutato il recapito (%s): resta nella coda locale", e)
            finally:
                chiudi(con)
    rid = _accoda(rec)
    if rifiutato:
        _segnalati.add(rid)
    return "in_attesa"


def svuota_coda():
    """Reinvia la coda in ordine. Una riga rifiutata dal server resta in coda (segnalata una
    volta sola) e non blocca le successive; una connessione persa interrompe il giro.
    Se il processo muore fra il commit su MySQL e la cancellazione locale, quella riga verra'
    reinviata: un doppione e' preferibile a un recapito perso."""
    global _giu
    con_l = _sqlite()
    try:
        righe = con_l.execute("SELECT id, dati FROM in_attesa ORDER BY id").fetchall()
        if not righe and not _giu:
            return
        try:
            con = connetti()
        except Exception as e:
            _segna_giu(e)
            return
        inviate = 0
        try:
            for rid, dati in righe:
                try:
                    _inserisci(con, json.loads(dati))
                except Exception as e:
                    if _connessione_persa(e):
                        _segna_giu(e)
                        return
                    if rid not in _segnalati:
                        _segnalati.add(rid)
                        log.error("MySQL rifiuta il recapito in coda n. %s (%s): resta in "
                                  "locale finche' tabella o config.json non vengono corretti",
                                  rid, e)
                    continue
                con_l.execute("DELETE FROM in_attesa WHERE id=?", (rid,))
                con_l.commit()
                inviate += 1
        finally:
            chiudi(con)
        if _giu:
            log.info("MySQL di nuovo raggiungibile")
        _giu = False
        if inviate:
            log.info("reinviati a MySQL %d recapiti dalla coda locale", inviate)
    finally:
        con_l.close()


def _ciclo_reinvio():
    while True:
        try:
            svuota_coda()
        except Exception:
            log.exception("reinvio della coda fallito")   # il thread non deve morire
        time.sleep(INTERVALLO_REINVIO)


def avvia(path_config=None):
    """Da chiamare una volta all'avvio del server. Solleva ConfigErrata se config.json c'e'
    ma non e' utilizzabile; il config si valida prima di toccare il disco."""
    cfg = config_mysql.leggi(path_config)
    _init_sqlite()
    if cfg is None:
        log.info("MySQL non configurato: i recapiti si salvano in %s", DB)
        return
    configura(cfg)
    log.info("recapiti su MySQL %s:%s/%s, tabella %s", cfg["host"], cfg["porta"],
             cfg["database"], cfg["tabella"])
    try:
        con = connetti()
        try:
            for p in problemi(colonne_tabella(con)):
                log.warning("tabella MySQL: %s", p)
        finally:
            chiudi(con)
    except Exception as e:
        if _connessione_persa(e) or not isinstance(e, _pymysql.MySQLError):
            _segna_giu(e)
        else:
            log.warning("tabella MySQL non verificabile: %s", e)
    threading.Thread(target=_ciclo_reinvio, name="reinvio-mysql", daemon=True).start()
