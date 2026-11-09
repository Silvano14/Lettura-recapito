"""
config_mysql.py - lettura e validazione della sezione "mysql" di config.json.

config.json sta accanto a server.py e NON e' versionato (contiene la password); il modello da
copiare e' config.esempio.json. La tabella MySQL esiste gia' e non la crea l'app: la mappatura
"colonne" dice in quale colonna va ogni dato, cosi' adattarsi alla tabella vera non richiede di
toccare il codice.
"""
from __future__ import annotations
import json, os, re
from urllib.parse import unquote, urlsplit

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "config.json")

# I soli dati che l'app puo' salvare. Privacy: mai l'immagine ne' dati del destinatario.
CAMPI = ("ts", "codice", "modello", "casella_id", "etichetta", "qr")
_IDENT = re.compile(r"[A-Za-z0-9_]{1,64}")


class ConfigErrata(Exception):
    """config.json presente ma inutilizzabile. Deve fermare l'avvio: altrimenti si lavorerebbe
    una giornata intera credendo di salvare su MySQL."""


def _quota(nome, cosa, max_parti):
    """Nome di tabella/colonna fra backtick. I nomi non possono essere parametri della query,
    quindi passano da qui: ammessi solo lettere, numeri e _ (niente SQL dal config)."""
    parti = str(nome).split(".")
    if len(parti) > max_parti or not all(_IDENT.fullmatch(p) for p in parti):
        raise ConfigErrata(f"{cosa} non valido: {nome!r} (ammessi solo lettere, numeri e _)")
    return ".".join(f"`{p}`" for p in parti)


def leggi(path=None):
    """Configurazione MySQL validata, oppure None se MySQL non e' configurato (nessun file o
    nessuna sezione "mysql"): in quel caso si resta su SQLite locale come prima."""
    path = path or CONFIG
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError) as e:
        raise ConfigErrata(f"{path} illeggibile: {e}")
    m = c.get("mysql") if isinstance(c, dict) else None
    if not m:
        return None
    if not isinstance(m, dict):
        raise ConfigErrata("la sezione 'mysql' deve essere un oggetto")

    u = urlsplit(str(m.get("connessione", "")))
    if u.scheme not in ("mysql", "mysql+pymysql") or not u.hostname or not u.path.strip("/"):
        raise ConfigErrata("'connessione' deve avere la forma "
                           "mysql://utente:password@host:3306/database")
    try:
        porta = u.port or 3306
    except ValueError:
        raise ConfigErrata("porta non valida in 'connessione'")

    colonne = m.get("colonne")
    if not isinstance(colonne, dict):
        raise ConfigErrata("'colonne' deve associare i campi dell'app alle colonne della tabella")
    # le chiavi che iniziano con _ sono note per chi legge il file, non campi
    ignoti = [k for k in colonne if k not in CAMPI and not k.startswith("_")]
    if ignoti:
        raise ConfigErrata(f"campi sconosciuti in 'colonne': {', '.join(ignoti)} "
                           f"(validi: {', '.join(CAMPI)})")
    mappa = [(k, str(colonne[k])) for k in CAMPI if k in colonne]
    if not mappa:
        raise ConfigErrata("'colonne' non associa nessun campo: non ci sarebbe niente da salvare")
    if len({col.lower() for _, col in mappa}) != len(mappa):
        raise ConfigErrata("in 'colonne' due campi puntano alla stessa colonna")

    tabella = _quota(m.get("tabella", ""), "nome della tabella", 2)
    nomi = ", ".join(_quota(col, f"colonna per '{k}'", 1) for k, col in mappa)
    return {"host": u.hostname, "porta": porta, "database": unquote(u.path.strip("/")),
            "utente": unquote(u.username or ""), "password": unquote(u.password or ""),
            "tabella": str(m["tabella"]), "tabella_sql": tabella, "mappa": mappa,
            "sql": f"INSERT INTO {tabella} ({nomi}) VALUES ({', '.join(['%s'] * len(mappa))})"}
