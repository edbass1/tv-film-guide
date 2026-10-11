#!/usr/bin/env python3
"""
Guida TV: Film e Documentari (oggi + giorni successivi)

Fonti (tutte gratuite, senza chiave, raggiungibili da GitHub Actions):
  * epgshare01.online      guide XMLTV per paese (DE, AT, CH, FR, IT, UK)
  * La Vanguardia          film sui canali spagnoli (HTML)
  * datasets.imdbws.com    voti IMDb + titoli localizzati (titoli italiani)
  * Wikidata               titoli italiani mancanti (SPARQL)
  * Helsinki-NLP opus-mt   traduzione automatica offline de/fr/es -> it

Uso:  python build.py [--offline] [--no-translate]
"""
import argparse, datetime as dt, gzip, hashlib, json, math, os, re, string, sys, time, unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
RAW = ROOT / "raw"            # file scaricati (non salvati nel repository)
OUT = ROOT / "docs"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
BOT_UA = "tv-film-guide/2.0 (static TV guide; github.com/edbass1/tv-film-guide)"
S = requests.Session()
S.headers["User-Agent"] = UA
T0 = time.time()


def log(*a):
    print(f"[{time.time()-T0:6.1f}s]", *a, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ utilità
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


_PUNCT = {ord(c): " " for c in string.punctuation + "–—‘’“”«»…·¿¡"}


def fkey(s):
    """Chiave veloce per confrontare titoli (minuscole, senza punteggiatura)."""
    s = unicodedata.normalize("NFKD", (s or "").casefold().translate(_PUNCT))
    return " ".join("".join(ch for ch in s if not unicodedata.combining(ch)).split())


def kw_regex(words, prefix=True):
    parts = []
    for w in words or []:
        w = str(w)
        e = re.escape(w)
        left = r"(?<!\w)" if w[:1].isalnum() else ""
        right = "" if (prefix and len(w) >= 5) else (r"(?!\w)" if w[-1:].isalnum() else "")
        parts.append(left + e + right)
    return re.compile("|".join(parts), re.I) if parts else None


def lower_set(xs):
    return {str(x).lower() for x in (xs or [])}


def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(p, data):
    Path(p).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8")


def download(url, dest, offline=False, tries=4):
    dest = Path(dest)
    if offline and dest.exists():
        return dest
    for k in range(tries):
        try:
            with S.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
            return dest
        except Exception as e:
            log(f"  download {url} tentativo {k+1}: {e}")
            time.sleep(3 + 5 * k)
    if dest.exists():
        log(f"  ! uso la copia precedente di {dest.name}")
        return dest
    raise SystemExit(f"download fallito: {url}")


# ------------------------------------------------------------------ EPG (XMLTV)
def parse_xmltv(path, wanted_ids):
    """Programmi dei soli canali richiesti: {channel_id: [prog,...]}"""
    out = defaultdict(list)
    with gzip.open(path) as f:
        for ev, el in ET.iterparse(f, events=("end",)):
            if el.tag != "programme":
                if el.tag == "channel":
                    el.clear()
                continue
            ch = el.get("channel")
            if ch in wanted_ids:
                try:
                    b = dt.datetime.strptime(el.get("start"), "%Y%m%d%H%M%S %z")
                    e = dt.datetime.strptime(el.get("stop"), "%Y%m%d%H%M%S %z")
                except Exception:
                    el.clear(); continue
                date = (el.findtext("date") or "").strip()[:4]
                out[ch].append({
                    "begin": b, "end": e,
                    "title": (el.findtext("title") or "").strip(),
                    "sub": (el.findtext("sub-title") or "").strip() or None,
                    "desc": (el.findtext("desc") or "").strip() or None,
                    "year": int(date) if date.isdigit() else None,
                    "cats": [c.text.strip() for c in el.findall("category") if c.text],
                    "ep": (el.findtext("episode-num") or "").strip() or None,
                })
            el.clear()
    return out


def merge_sources(lists):
    """Prima lista non vuota = principale; le altre completano anno/categorie/descrizione per lo stesso orario."""
    lists = [l for l in lists if l]
    if not lists:
        return []
    primary = [dict(p) for p in lists[0]]
    for l in lists[1:]:
        starts = sorted(l, key=lambda q: q["begin"])
        for p in primary:
            best = None
            for q in starts:
                d = abs((q["begin"] - p["begin"]).total_seconds())
                if d <= 600 and (best is None or d < best[0]):
                    best = (d, q)
            if not best:
                continue
            q = best[1]
            if norm(q["title"])[:6] != norm(p["title"])[:6] and best[0] > 120:
                continue
            if not p["year"] and q["year"]:
                p["year"] = q["year"]
            if q["cats"]:
                if not p["cats"]:
                    p["cats"] = list(q["cats"])
                else:
                    p.setdefault("cats2", []).extend(q["cats"])
            if not p["desc"] and q["desc"]:
                p["desc"] = q["desc"]
            if not p["ep"] and q["ep"]:
                p["ep"] = q["ep"]
    # programmi oltre la fine della guida principale: presi dalle fonti secondarie
    last = max(p["end"] for p in primary)
    for l in lists[1:]:
        extra = [dict(q) for q in l if q["begin"] >= last]
        if extra:
            primary += extra
            last = max(q["end"] for q in extra)
    return primary


# ------------------------------------------------------------------ La Vanguardia
ES_GENRES = {"accion": "Azione", "aventuras": "Avventura", "animacion": "Animazione", "comedia": "Commedia",
             "drama": "Dramma", "thriller": "Thriller", "terror": "Horror", "ciencia-ficcion": "Fantascienza",
             "fantasia": "Fantasy", "romance": "Romantico", "romantica": "Romantico", "western": "Western",
             "belica": "Guerra", "musical": "Musical", "documental": "Documentario", "crimen": "Giallo / Poliziesco",
             "misterio": "Mistero", "historia": "Storico", "familia": "Famiglia", "infantil": "Bambini",
             "suspense": "Thriller", "biografia": "Biografico", "deporte": "Sport", "intriga": "Thriller",
             "policiaca": "Giallo / Poliziesco", "cine-negro": "Noir"}


def lavanguardia_fetch(cfg):
    r = S.get(cfg["lavanguardia"]["url"], timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for li in soup.select("li.event"):
        try:
            t = li.select_one(".event__title")
            ch = li.select_one(".event__ch")
            meta = li.select_one(".event__meta")
            year = None
            if meta:
                txt = "".join(x for x in meta.contents if isinstance(x, str))
                m = re.search(r"\b(19|20)\d{2}\b", txt)
                year = int(m.group(0)) if m else None
            rating = None
            rt = li.select_one(".event__rating")
            if rt:
                m = re.search(r"(\d+)[,.](\d)", rt.get_text())
                rating = float(f"{m.group(1)}.{m.group(2)}") if m else None
            a = t.select_one("a") if t else None
            syn = li.select_one(".event__syn")
            items.append({
                "title": t.get_text(" ", strip=True), "channel": ch.get_text(" ", strip=True) if ch else "?",
                "begin": li["data-s"], "end": li["data-e"], "year": year, "lv_rating": rating,
                "tags": [x.get("href", "").rstrip("/").split("/")[-1] for x in li.select("a.event__tag")],
                "url": a["href"] if a else None, "desc": syn.get_text(" ", strip=True) if syn else None})
        except Exception as e:
            log("  LV parse:", e)
    return items


# ------------------------------------------------------------------ DOPPIO AUDIO
SUFFIXES = ("hd", "deutsch", "tve", "suisse", "schweiz", "europe", "francais", "fr", "de", "ch", "at")


def chan_key(name):
    k = norm(name).replace(" ", "")
    changed = True
    while changed:
        changed = False
        for suf in SUFFIXES:
            if k.endswith(suf) and len(k) > len(suf) + 1:
                k, changed = k[: -len(suf)], True
    return k


class DualAudio:
    def __init__(self, cfg):
        da = cfg["dual_audio"]
        self.map = {chan_key(str(a)): str(e[0]) for e in da.get("channels", []) for a in e}
        self.never = {chan_key(str(x)) for x in da.get("never_channels", [])}
        self.never_lang = lower_set(da.get("never_languages"))

    def listed(self, ch):
        return chan_key(ch) in self.map

    def decide(self, ch, lang):
        k = chan_key(ch)
        if k in self.never or (lang or "").lower() in self.never_lang:
            return None
        return "sì" if k in self.map else None


# ------------------------------------------------------------------ IMDb
FILM_TYPES = {"movie", "tvMovie", "video", "tvSpecial"}
DOC_TYPES = {"movie", "tvMovie", "tvSeries", "tvMiniSeries", "tvSpecial", "video"}


class IMDb:
    def __init__(self, cfg, offline):
        self.cfg = cfg["imdb"]
        self.offline = offline
        self.by_key = defaultdict(set)   # fkey -> {tconst}
        self.it = {}                     # tconst -> titolo italiano
        self.info = {}                   # tconst -> (type, year, primary, original, genres)
        self.rating = {}                 # tconst -> (rating, votes)

    def load(self, keys):
        if not self.cfg.get("enabled"):
            return
        RAW.mkdir(exist_ok=True)
        base = self.cfg["base"]
        files = {}
        for n in ("title.akas.tsv.gz", "title.basics.tsv.gz", "title.ratings.tsv.gz"):
            files[n] = download(f"{base}/{n}", RAW / n, self.offline)
        regions = set(self.cfg.get("aka_regions", [])) | {"\\N"}
        log(f"IMDb: akas ({len(keys)} titoli da cercare)")
        ids = set()
        it_titles = {}
        cur, block = None, []

        def flush(tid, rows):
            hit = False
            for region, title, types in rows:
                if region in regions or region == "IT":
                    k = fkey(title)
                    if k in keys:
                        self.by_key[k].add(tid)
                        hit = True
            if hit:
                ids.add(tid)
                its = [(0 if "imdbDisplay" in types else 1 if types == "\\N" else 2, title)
                       for region, title, types in rows if region == "IT" and "working" not in types]
                if its:
                    it_titles[tid] = sorted(its)[0][1]

        with gzip.open(files["title.akas.tsv.gz"], "rt", encoding="utf-8", errors="replace") as f:
            next(f)
            for line in f:
                p = line.split("\t", 6)
                tid = p[0]
                if tid != cur:
                    if block:
                        flush(cur, block)
                    cur, block = tid, []
                block.append((p[3], p[2], p[5]))
            if block:
                flush(cur, block)
        log(f"IMDb: {len(ids)} titoli candidati; basics")
        with gzip.open(files["title.basics.tsv.gz"], "rt", encoding="utf-8", errors="replace") as f:
            next(f)
            for line in f:
                tid = line[: line.find("\t")]
                if tid in ids:
                    p = line.rstrip("\n").split("\t")
                    if p[4] == "1":   # isAdult
                        continue
                    self.info[tid] = (p[1], int(p[5]) if p[5].isdigit() else None, p[2], p[3],
                                      [] if p[8] == "\\N" else p[8].split(","))
                    for k in (fkey(p[2]), fkey(p[3])):
                        if k in keys:
                            self.by_key[k].add(tid)
        with gzip.open(files["title.ratings.tsv.gz"], "rt", encoding="utf-8") as f:
            next(f)
            for line in f:
                tid = line[: line.find("\t")]
                if tid in self.info:
                    p = line.split("\t")
                    self.rating[tid] = (float(p[1]), int(p[2]))
        self.it = {k: v for k, v in it_titles.items() if k in self.info}
        log(f"IMDb: info={len(self.info)} voti={len(self.rating)} titoli_it={len(self.it)}")

    def match(self, keys, year, kind, dur):
        cands = set()
        for k in keys:
            cands |= self.by_key.get(k, set())
        best = None
        for tid in cands:
            inf = self.info.get(tid)
            if not inf:
                continue
            typ, y, _, _, genres = inf
            r, v = self.rating.get(tid, (None, 0))
            isdoc = "Documentary" in genres
            if kind == "film":
                if typ not in FILM_TYPES or isdoc:
                    continue
                if year and y and abs(y - year) > 1:
                    continue
                if not year and v < self.cfg.get("min_votes_without_year", 20000):
                    continue
                if not (year and y) and v < 1000:
                    continue
            elif kind == "doc":
                if typ not in DOC_TYPES or not isdoc:
                    continue
                if typ in FILM_TYPES and year and y and abs(y - year) > 1 and year < dt.date.today().year - 1:
                    continue
                if v < 50:
                    continue
            else:   # sconosciuto: solo film con anno coincidente
                if typ not in FILM_TYPES or not (year and y and abs(y - year) <= 1) or v < 500:
                    continue
                if dur and dur < 70 and not isdoc:
                    continue
            if best is None or v > best[1]:
                best = (tid, v)
        return best[0] if best else None


def title_keys(t):
    t = re.sub(r"\s*\((\d+/\d+|19\d\d|20\d\d|[^)]{0,3})\)\s*$", "", t or "")
    ks = {fkey(t)}
    for sep in (" - ", " – ", ": "):
        if sep in t:
            ks.add(fkey(t.split(sep)[0]))
    return {k for k in ks if len(k) >= 2}


# ------------------------------------------------------------------ Wikidata
def wikidata_it(ids, cache):
    todo = sorted({i for i in ids if i and i not in cache})
    ses = requests.Session(); ses.headers["User-Agent"] = BOT_UA
    for k in range(0, len(todo), 80):
        chunk = todo[k:k + 80]
        q = ("SELECT ?imdb ?it ?itw WHERE { VALUES ?imdb {%s} ?item wdt:P345 ?imdb. "
             "OPTIONAL{?item rdfs:label ?it FILTER(lang(?it)='it')} "
             "OPTIONAL{?a schema:about ?item; schema:isPartOf <https://it.wikipedia.org/>; schema:name ?itw} }"
             % " ".join(f'"{i}"' for i in chunk))
        try:
            r = ses.get("https://query.wikidata.org/sparql", params={"query": q},
                        headers={"Accept": "application/sparql-results+json"}, timeout=60)
            r.raise_for_status()
            found = {}
            for b in r.json()["results"]["bindings"]:
                lab = b.get("itw", {}).get("value") or b.get("it", {}).get("value")
                if lab:
                    lab = re.sub(r"\s*\((film|serie televisiva|documentario|miniserie)[^)]*\)\s*$", "", lab).strip()
                    found.setdefault(b["imdb"]["value"], lab)
            for i in chunk:
                cache[i] = found.get(i)
        except Exception as e:
            log("  wikidata:", e)
        time.sleep(0.3)


# ------------------------------------------------------------------ traduzione automatica
class Translator:
    """Traduzione offline con modelli Helsinki-NLP (opus-mt); cache in cache/translations.json."""
    def __init__(self, cfg, enabled=True):
        self.cfg = cfg["translation"]
        self.enabled = enabled
        self.cache = load_json(CACHE / "translations.json", {})
        self.models = {}
        self.deadline = time.time() + self.cfg.get("max_seconds_per_run", 2400)
        self.new = 0
        self.skipped = 0
        self.failed = None
        self.bad = set()

    @staticmethod
    def key(lang, text):
        return lang + ":" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]

    def get(self, lang, text):
        return self.cache.get(self.key(lang, text))

    def _model(self, lang):
        if lang not in self.models:
            from transformers import MarianMTModel, MarianTokenizer
            import torch
            torch.set_num_threads(max(1, os.cpu_count() or 2))
            name = self.cfg["models"][lang]
            log(f"  carico modello {name}")
            self.models[lang] = (MarianTokenizer.from_pretrained(name), MarianMTModel.from_pretrained(name).eval(),
                                 ">>ita<< " if "itc" in name else "")
        return self.models[lang]

    @staticmethod
    def sentences(text):
        parts = re.split(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-Þ0-9«\"'(])", text.strip())
        return [p for p in parts if p.strip()]

    def translate_many(self, lang, texts):
        """Traduce (in blocchi di frasi) i testi non ancora in cache."""
        todo = [t for t in dict.fromkeys(texts) if t and self.key(lang, t) not in self.cache]
        if not todo or not self.enabled or lang in self.bad:
            self.skipped += len(todo) if todo else 0
            return
        try:
            import torch
            tok, model, prefix = self._model(lang)
        except Exception as e:
            self.failed = f"{lang}: {type(e).__name__}: {str(e)[:200]}"
            self.bad.add(lang)
            log("  ! traduzione non disponibile:", self.failed)
            self.skipped += len(todo)
            return
        B = 24
        for i in range(0, len(todo), B):
            if time.time() > self.deadline:
                self.skipped += len(todo) - i
                log("  tempo di traduzione esaurito; il resto alla prossima esecuzione")
                return
            chunk = todo[i:i + B]
            sents, owners = [], []
            for j, t in enumerate(chunk):
                for s in self.sentences(t):
                    sents.append(prefix + s); owners.append(j)
            outs = []
            for k in range(0, len(sents), 32):
                batch = sents[k:k + 32]
                with torch.no_grad():
                    enc = tok(batch, return_tensors="pt", padding=True, truncation=True, max_length=256)
                    gen = model.generate(**enc, num_beams=3, max_new_tokens=300, max_length=None)
                outs += tok.batch_decode(gen, skip_special_tokens=True)
            res = defaultdict(list)
            for j, o in zip(owners, outs):
                res[j].append(o.strip())
            for j, t in enumerate(chunk):
                self.cache[self.key(lang, t)] = " ".join(res[j])
                self.new += 1
            if (i // B) % 10 == 0:
                log(f"  traduzioni {lang}: {i+len(chunk)}/{len(todo)}")
                self.save()

    def save(self):
        save_json(CACHE / "translations.json", self.cache)


def shorten(text, n):
    text = re.sub(r"\s+", " ", (text or "").replace("\\n", " ")).strip()
    if len(text) <= n:
        return text
    cut = text[:n]
    m = list(re.finditer(r"[.!?…](?=\s)", cut))
    if m and m[-1].end() > n * 0.45:
        return cut[: m[-1].end()]
    return cut.rsplit(" ", 1)[0] + "…"


# ------------------------------------------------------------------ classificazione
RX_FILM_CAT = re.compile(r"^(film|spielfilm|fernsehfilm|cinéma|cinema|téléfilm|movie|tv movie|película|cine)\b|"
                         r"\b(spielfilm|fernsehfilm|kinofilm|actionfilm|abenteuerfilm|liebesfilm|horrorfilm|"
                         r"kriminalfilm|fantasyfilm|musicalfilm|science-fiction-film|kriegsfilm|heimatfilm|"
                         r"film (drame|policier|comedie|comédie|de suspense|d'aventures|d'horreur|de science fiction|fantastique|dramatique|d'action|historique|de guerre|musical|biographique))", re.I)
RX_DE_GENRE = re.compile(r"(krimi|thriller|drama|komödie|action|abenteuer|western|horror|sci-fi|science-fiction|"
                         r"fantasy|romanze|liebes|melodram|tragikomödie|historien|kriegs|musical|biograf|mystery|"
                         r"satire|parodie|heimat|road ?movie|liebeskomödie|psycho)", re.I)
RX_SERIES = re.compile(r"(serie|série|series|sitcom|soap|feuilleton|telenovela|episod|telefilm\b)", re.I)
RX_DOC_CAT = re.compile(r"(dokument|doku|documentar|documentaire|documentary|documental|docu|reportage)", re.I)
RX_EROTIC = re.compile(r"(erotik|sex film|adult|érotique|erotico|x\b)", re.I)
RX_NEWS_TITLE = re.compile(r"\b(news|newsnight|weather|breakfast|tagesschau|heute|journal|telegiornale|tg\d?)\b", re.I)

GENRE_IT = [  # (genere IMDb, nome italiano) in ordine di priorità
    ("Western", "Western"), ("War", "Guerra"), ("Sci-Fi", "Fantascienza"), ("Horror", "Horror"),
    ("Animation", "Animazione"), ("Fantasy", "Fantasy"), ("Musical", "Musical"), ("Music", "Musicale"),
    ("Thriller", "Thriller"), ("Crime", "Giallo / Poliziesco"), ("Mystery", "Giallo / Poliziesco"),
    ("Romance", "Romantico"), ("Comedy", "Commedia"), ("Adventure", "Avventura"), ("Action", "Azione"),
    ("Biography", "Biografico"), ("History", "Storico"), ("Sport", "Sport"), ("Family", "Famiglia"),
    ("Drama", "Dramma")]
CAT_GENRE = [  # parole nelle categorie EPG -> genere italiano
    (r"western", "Western"), (r"krieg|guerre|guerra|war\b|bélic", "Guerra"),
    (r"sci-?fi|science.?fiction|fantascienza|ciencia", "Fantascienza"), (r"horror|horreur|terror", "Horror"),
    (r"fantasy|fantastique|fantastico", "Fantasy"), (r"musical", "Musical"),
    (r"thriller|suspense|spannung|psycho", "Thriller"), (r"krimi|policier|crime|giallo|poliz|polic|criminal", "Giallo / Poliziesco"),
    (r"romant|liebe|romance|sentiment", "Romantico"), (r"komödie|comédie|comedie|commedia|comedy|comedia|satire|parodie", "Commedia"),
    (r"abenteuer|aventure|avventura|adventure|aventura", "Avventura"), (r"action|azione|acción", "Azione"),
    (r"biogra", "Biografico"), (r"histor|storic", "Storico"), (r"drama|drame|dramma|dramatique|dramático", "Dramma")]


def film_genre(imdb_genres, cats):
    for g, it in GENRE_IT:
        if g in (imdb_genres or []):
            return it
    txt = " ".join(cats or [])
    for rx, it in CAT_GENRE:
        if re.search(rx, txt, re.I):
            return it
    return "Altro"


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="riusa i file già scaricati in raw/")
    ap.add_argument("--no-translate", action="store_true")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()
    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    for d in (CACHE, RAW, OUT, OUT / "assets"):
        d.mkdir(exist_ok=True)
    tz = ZoneInfo(cfg["timezone"])
    now = dt.datetime.now(tz)
    ds = hm(cfg["day_starts_at"])
    today = (now - dt.timedelta(minutes=ds)).date()
    win_start = dt.datetime.combine(today, dt.time(ds // 60, ds % 60), tz)
    win_end = win_start + dt.timedelta(days=cfg["max_days"])
    DA = DualAudio(cfg)
    stats = defaultdict(lambda: defaultdict(int))

    # ---------- 1. EPG
    chans = cfg["channels"]
    if cfg.get("german_language_only_listed"):
        before = len(chans)
        chans = [c for c in chans if c["lang"] != "de" or DA.listed(c["name"])]
        if before != len(chans):
            log(f"canali tedeschi non in lista DOPPIO AUDIO rimossi: {before-len(chans)}")
    need = defaultdict(set)
    for c in chans:
        for s in c["sources"]:
            f, cid = s.split(":", 1)
            need[f].add(cid)
    progs = {}
    for f, ids in sorted(need.items()):
        p = download(cfg["epg_base"].format(file=f), RAW / f"epg_{f}.xml.gz", args.offline)
        log(f"EPG {f}: leggo {len(ids)} canali")
        for cid, l in parse_xmltv(p, ids).items():
            progs[f"{f}:{cid}"] = l
    items = []
    epg_last = None
    for c in chans:
        lst = merge_sources([progs.get(s) for s in c["sources"]])
        if not lst:
            log(f"  ! nessun dato per {c['name']}")
            stats["canali"]["senza dati"] += 1
            continue
        for p in lst:
            if p["end"] <= win_start or p["begin"] >= win_end:
                continue
            epg_last = max(epg_last or p["begin"], p["begin"])
            p.update(ch=c["name"], lang=c["lang"], cc=c["cc"], src="epg",
                     dur=int((p["end"] - p["begin"]).total_seconds() // 60))
            items.append(p)
    log(f"EPG: {len(items)} programmi nella finestra, ultimo inizio {epg_last}")

    # ---------- 2. La Vanguardia (film Spagna)
    if cfg["lavanguardia"].get("enabled"):
        try:
            lv = lavanguardia_fetch(cfg)
            for b in lv:
                beg = dt.datetime.fromisoformat(b["begin"].replace("Z", "+00:00")).astimezone(tz)
                end = dt.datetime.fromisoformat(b["end"].replace("Z", "+00:00")).astimezone(tz)
                if end <= win_start or beg >= win_end:
                    continue
                items.append({"begin": beg, "end": end, "title": b["title"], "sub": None, "desc": b["desc"],
                              "year": b["year"], "cats": ["Cine"] + b["tags"], "ep": None, "ch": b["channel"],
                              "lang": "es", "cc": "ES", "src": "lv", "lv": b["lv_rating"], "url": b["url"],
                              "dur": int((end - beg).total_seconds() // 60), "es_tags": b["tags"]})
            log(f"La Vanguardia: {len(lv)} film")
        except Exception as e:
            log("! La Vanguardia non disponibile:", e)

    # ---------- canali esclusi del tutto
    blk = [norm(x).replace(" ", "") for x in cfg.get("blocked_channels") or []]
    if blk:
        n0 = len(items)
        items = [p for p in items if not any(norm(p["ch"]).replace(" ", "").startswith(b) for b in blk)]
        stats["programmi"]["canale escluso (blocked_channels)"] = n0 - len(items)

    # ---------- 3. pre-classificazione con le categorie EPG
    kids = cfg["kids"]
    rx_kid_cat, rx_kid_title = kw_regex(kids["category_keywords"]), kw_regex(kids["title_keywords"])
    kid_ch = lower_set(kids["channels"])
    for p in items:
        cats = p["cats"] + p.get("cats2", [])
        # UK: "News & Documentary" -> documentario solo se non è un notiziario
        cats = ["Documentary" if c == "News & Documentary" and (p["dur"] >= 40 and not RX_NEWS_TITLE.search(p["title"]))
                else ("News" if c == "News & Documentary" else c) for c in cats]
        p["cats_all"] = cats
        ctxt = " | ".join(cats)
        p["c_film"] = any(RX_FILM_CAT.search(c) for c in cats) or p["src"] == "lv"
        p["c_doc"] = bool(RX_DOC_CAT.search(ctxt)) and not re.search(r"dokumentarfilm", ctxt, re.I) or \
            bool(re.search(r"dokumentarfilm|film documentaire|documentaire", ctxt, re.I))
        if re.search(r"dokumentarfilm|documental", ctxt, re.I):
            p["c_film"] = False
        p["c_series"] = bool(RX_SERIES.search(ctxt)) and not p["c_film"]
        if p["lang"] == "it" and re.search(r"\btelefilm\b", ctxt, re.I):
            p["c_series"], p["c_film"] = True, False
        p["c_de_genre"] = p["lang"] == "de" and bool(RX_DE_GENRE.search(ctxt)) and not re.search(r"serie|dok|magazin|show|talk", ctxt, re.I)
        p["c_kids"] = bool(rx_kid_cat and rx_kid_cat.search(ctxt)) or bool(rx_kid_title and rx_kid_title.search(p["title"])) \
            or p["ch"].lower() in kid_ch or "infantil" in p.get("es_tags", [])
        p["c_erotic"] = bool(RX_EROTIC.search(ctxt)) and bool(re.search(r"erotik|sex|adult|érot|erotic", ctxt, re.I))
        # alcune guide (es. DE1 per i canali BBC) mettono "Film: " davanti al titolo
        p["title"] = re.sub(r"^(Film|Spielfilm|Movie)\s*:\s*", "", p["title"]).strip() or p["title"]
        p["keys"] = title_keys(p["title"])
        m = re.search(r"\((19\d\d|20[0-3]\d)\)\s*$", p["title"])
        if m:
            p["year"] = int(m.group(1))
            p["title"] = p["title"][: m.start()].strip()

    # ---------- 4. IMDb
    imdb = IMDb(cfg, args.offline)
    cand_keys = set()
    for p in items:
        if p["c_kids"] or p["dur"] < 35:
            continue
        if p["c_film"] or p["c_doc"] or p["c_de_genre"] or (not p["c_series"] and p["dur"] >= 40):
            cand_keys |= p["keys"]
    try:
        imdb.load(cand_keys)
    except SystemExit as e:
        log("! IMDb non disponibile:", e)

    # ---------- 5. classificazione finale + filtri
    films_cfg, docs_cfg = cfg["films"], cfg["docs"]
    rx_f_title = kw_regex(films_cfg.get("blocked_title_keywords"))
    rx_d_title = kw_regex(docs_cfg.get("blocked_title_keywords"))
    rx_d_cat = kw_regex(docs_cfg.get("blocked_category_keywords"))
    rx_d_desc = kw_regex(docs_cfg.get("blocked_desc_keywords"))
    rx_all_title = kw_regex(cfg.get("blocked_title_keywords"))
    rx_crime = kw_regex(cfg.get("crime_series_title_keywords"))
    med = lower_set(cfg["mediaset"]["channels"]) - lower_set(cfg["mediaset"]["keep_docs_on"])
    kid_combo = set(kids.get("imdb_genre_combo") or [])
    kept = []
    dropped = []

    def drop(p, why):
        stats["programmi"][why] += 1
        if os.environ.get("TVDEBUG"):
            dropped.append({"why": why, "ch": p["ch"], "b": p["begin"].isoformat(), "t": p["title"], "cats": p["cats_all"]})
    for p in items:
        st = stats["programmi"]
        st["totale"] += 1
        if p["c_kids"]:
            drop(p, "bambini"); continue
        if p["c_erotic"]:
            drop(p, "erotici"); continue
        kind, tid = None, None
        if p["c_doc"]:
            kind = "doc"
            tid = imdb.match(p["keys"], p["year"], "doc", p["dur"])
        elif p["c_film"] or p["c_de_genre"]:
            tid = imdb.match(p["keys"], p["year"], "film", p["dur"])
            if not tid and p["year"]:   # anno EPG a volte sbagliato (es. anno di restauro/messa in onda)
                tid = imdb.match(p["keys"], None, "film", p["dur"])
            if tid or p["c_film"] or (p["c_de_genre"] and p["dur"] >= 80):
                kind = "film"
            if not tid:
                dtid = imdb.match(p["keys"], p["year"], "doc", p["dur"])
                if dtid and imdb.info[dtid][0] in FILM_TYPES:
                    kind, tid = "doc", dtid
        elif not p["c_series"] and p["dur"] >= 70:
            tid = imdb.match(p["keys"], p["year"], "any", p["dur"])
            if tid:
                kind = "doc" if "Documentary" in imdb.info[tid][4] else "film"
        if not kind:
            drop(p, "non film/doc"); continue
        if kind == "doc" and rx_d_desc and len({m.group(0).lower() for m in rx_d_desc.finditer(p.get("desc") or "")}) >= 2:
            drop(p, "doc natura/lifestyle (descrizione)"); continue
        genres = imdb.info[tid][4] if tid else []
        text = " ".join(filter(None, [p["title"], p.get("sub")]))
        if rx_all_title and rx_all_title.search(text):
            drop(p, "titolo escluso (blocked_title_keywords)"); continue
        if kind == "film" and rx_crime and rx_crime.search(p["title"]) and \
                not (tid and imdb.info[tid][0] in FILM_TYPES and imdb.rating.get(tid)):
            drop(p, "episodio serie poliziesca"); continue
        ctxt = " | ".join(p["cats_all"])
        if kind == "film":
            if kid_combo and kid_combo <= set(genres):
                drop(p, "bambini (IMDb)"); continue
            if p["dur"] < films_cfg.get("min_duration_minutes", 0) and p["src"] != "lv":
                drop(p, "film troppo breve"); continue
            if rx_f_title and rx_f_title.search(text):
                drop(p, "film parola bloccata"); continue
            if p["c_series"] and not tid:
                drop(p, "serie"); continue
        else:
            if p["ch"].lower() in med:
                drop(p, "doc Mediaset (non Focus)"); continue
            if p["dur"] < docs_cfg.get("min_duration_minutes", 0):
                drop(p, "doc troppo breve"); continue
            if rx_d_cat and rx_d_cat.search(ctxt) and not re.search(r"wissenschaft|geschicht|histo|storia", ctxt, re.I):
                drop(p, "doc categoria esclusa"); continue
            if rx_d_title and rx_d_title.search(text):
                drop(p, "doc parola esclusa"); continue
            if set(genres) & {"Reality-TV", "Game-Show", "Talk-Show", "News"}:
                drop(p, "doc reality (IMDb)"); continue
        p["kind"] = kind
        p["tid"] = tid
        p["genres"] = genres
        if tid:
            typ, y, prim, orig, _ = imdb.info[tid]
            p["imdb"], p["votes"] = imdb.rating.get(tid, (None, None))
            p["orig"] = orig if fkey(orig) != fkey(p["title"]) else None
            if kind == "film" and y:
                p["year"] = y
            if typ in FILM_TYPES and y and kind == "doc":
                p["year"] = y
        st["tenuti " + kind] += 1
        kept.append(p)
    if os.environ.get("TVDEBUG"):
        save_json(RAW / "dropped.json", dropped)
    log(f"Classificati: film={sum(1 for p in kept if p['kind']=='film')} doc={sum(1 for p in kept if p['kind']=='doc')}")

    # ---------- 6. titoli italiani
    wd = load_json(CACHE / "wikidata_it.json", {})
    if cfg["translation"].get("wikidata_titles"):
        wikidata_it([p["tid"] for p in kept if p.get("tid") and p["lang"] != "it" and p["tid"] not in imdb.it], wd)
        save_json(CACHE / "wikidata_it.json", wd)
    for p in kept:
        if p["lang"] == "it" or not p.get("tid"):
            continue
        it = imdb.it.get(p["tid"]) or wd.get(p["tid"])
        if it and fkey(it) != fkey(p["title"]):
            p["it"], p["it_src"] = it, "ufficiale"

    # ---------- 7. traduzioni automatiche (titoli e descrizioni de/fr/es; inglese escluso)
    tr = Translator(cfg, enabled=not args.no_translate)
    langs = set(cfg["translation"]["languages"])
    nmax = cfg["translation"].get("max_desc_chars", 420)
    prime = (hm(cfg["prime_time"]["from"]), hm(cfg["prime_time"]["to"]))
    prime_es = (hm(cfg["prime_time_es"]["from"]), hm(cfg["prime_time_es"]["to"]))

    def is_prime(p):
        lo, hi = prime_es if p["lang"] == "es" else prime
        m = p["begin"].hour * 60 + p["begin"].minute
        return lo <= m <= hi

    for p in kept:
        p["prime"] = is_prime(p)
        if p.get("desc"):
            p["desc"] = shorten(p["desc"], nmax)
    order = sorted(kept, key=lambda p: (not p["prime"], p["begin"]))
    for lang in sorted(langs):
        titles = [p["title"] for p in order if p["lang"] == lang and not p.get("it")]
        descs = [p["desc"] for p in order if p["lang"] == lang and p.get("desc")]
        tr.translate_many(lang, titles + descs)
        tr.save()
    for p in kept:
        if p["lang"] in langs and not p.get("it"):
            t = tr.get(p["lang"], p["title"])
            if t and fkey(t) != fkey(p["title"]):
                p["it"], p["it_src"] = t, "auto"
        if p["lang"] in langs and p.get("desc"):
            t = tr.get(p["lang"], p["desc"])
            if t:
                p["desc_orig_lang"] = p["lang"]
                p["desc"], p["desc_auto"] = t, True

    # ---------- 8. generi, argomenti, clou
    c = cfg["clou"]
    topics = [(n, kw_regex(w)) for n, w in docs_cfg["topics"].items()]
    qual = lower_set(docs_cfg["quality_channels"])
    for p in kept:
        p["dual"] = DA.decide(p["ch"], p["lang"])
        r, v = p.get("imdb") or 0, p.get("votes") or 0
        if p["kind"] == "film":
            if p["src"] == "lv" and not p["genres"]:
                g = [ES_GENRES.get(t) for t in p.get("es_tags", []) if ES_GENRES.get(t)]
                p["genre"] = g[0] if g else "Altro"
            else:
                p["genre"] = film_genre(p["genres"], p["cats_all"])
            p["clou"] = bool((r >= c["film_min_rating"] and v >= c["film_min_votes"]) or
                             (v >= c["film_famous_votes"] and r >= c["film_famous_min_rating"]) or
                             (not r and (p.get("lv") or 0) >= 7.5))
            p["score"] = round(r + min(math.log10(v + 1), 6) / 3, 3) if r else round((p.get("lv") or 0) * 0.9, 3)
        else:
            text = " ".join(filter(None, [p.get("it"), p["title"], p.get("sub"), " ".join(p["cats_all"])]))
            p["genre"] = next((n for n, rx in topics if rx and rx.search(text)), None) or \
                next((n for n, rx in topics if rx and p.get("desc") and rx.search(p["desc"])), "Altro")
            q = p["ch"].lower() in qual
            p["clou"] = bool((r >= c["doc_min_rating"] and v >= c["doc_min_votes"]) or (p["prime"] and q and p["dur"] >= 50))
            p["score"] = round(r * (1 if v >= 100 else 0.6) + (1.5 if q else 0) + (0.5 if p["prime"] else 0), 3)

    # ---------- 9. giorni, repliche, output
    def tv_day(b):
        return (b - dt.timedelta(minutes=ds)).date().isoformat()

    by_day = defaultdict(lambda: {"films": [], "docs": []})
    for p in kept:
        by_day[tv_day(p["begin"])]["films" if p["kind"] == "film" else "docs"].append(p)
    wd_names = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    mo = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
          "ottobre", "novembre", "dicembre"]

    def pack(p):
        o = {"t": p["title"], "ch": p["ch"], "cc": p["cc"], "lang": p["lang"], "b": p["begin"].isoformat(),
             "e": p["end"].isoformat(), "dur": p["dur"], "g": p.get("genre"), "y": p.get("year"),
             "prime": p["prime"], "clou": p["clou"], "score": p["score"]}
        for k_src, k in (("it", "it"), ("it_src", "its"), ("orig", "o"), ("sub", "sub"), ("imdb", "r"), ("votes", "v"),
                         ("tid", "id"), ("lv", "lv"), ("dual", "dual"), ("desc", "d"), ("desc_auto", "da"), ("url", "u")):
            if p.get(k_src) not in (None, "", [], False):
                o[k] = p[k_src]
        if p["kind"] == "doc" and p.get("year") and p.get("tid") is None:
            o.pop("y", None)   # per i documentari l'anno EPG è spesso quello di messa in onda
        return o

    def merge(lst):
        groups = defaultdict(list)
        for p in lst:
            k = ("id", p["tid"]) if p.get("tid") and p["kind"] == "film" else \
                (fkey(p.get("it") or p["title"]), fkey(p.get("sub") or "") if p["kind"] == "doc" else (p.get("year") or ""))
            groups[k].append(p)
        out = []
        for g in groups.values():
            g.sort(key=lambda x: (not x["prime"], not x.get("dual"), x["begin"]))
            m = pack(g[0])
            if len(g) > 1:
                m["also"] = [{"ch": x["ch"], "cc": x["cc"], "b": x["begin"].isoformat(), "e": x["end"].isoformat(),
                              "prime": x["prime"], "dual": x.get("dual")} for x in
                             sorted(g[1:], key=lambda x: x["begin"])]
            out.append(m)
        return sorted(out, key=lambda o: o["b"])

    days, counts = [], []
    for k in range(cfg["max_days"]):
        d = today + dt.timedelta(days=k)
        e = by_day.get(d.isoformat())
        if not e or (len(e["films"]) + len(e["docs"]) < 10):
            continue
        label = "Oggi" if k == 0 else "Domani" if k == 1 else wd_names[d.weekday()]
        day = {"date": d.isoformat(), "label": label, "long": f"{wd_names[d.weekday()]} {d.day} {mo[d.month-1]}",
               "films": merge(e["films"]), "docs": merge(e["docs"])}
        days.append(day)
        counts.append({"giorno": d.isoformat(), "film": len(day["films"]), "documentari": len(day["docs"]),
                       "film_spagna": sum(1 for x in day["films"] if x["lang"] == "es"),
                       "film_prima_serata": sum(1 for x in day["films"] if x["prime"]),
                       "doc_prima_serata": sum(1 for x in day["docs"] if x["prime"])})

    allf = [x for d in days for x in d["films"]]
    alld = [x for d in days for x in d["docs"]]

    def cov(l, f):
        return f"{sum(1 for x in l if f(x))}/{len(l)}"
    report = {
        "generato": now.isoformat(timespec="minutes"), "durata_secondi": round(time.time() - T0),
        "conteggi_per_giorno": counts, "filtri": {k: dict(v) for k, v in stats.items()},
        "copertura": {
            "film_con_imdb": cov(allf, lambda x: x.get("r")),
            "film_epg_con_imdb": cov([x for x in allf if x["lang"] != "es"], lambda x: x.get("r")),
            "film_spagna_con_imdb": cov([x for x in allf if x["lang"] == "es"], lambda x: x.get("r")),
            "doc_con_imdb": cov(alld, lambda x: x.get("r")),
            "film_doppio_audio": cov(allf, lambda x: x.get("dual")), "doc_doppio_audio": cov(alld, lambda x: x.get("dual")),
            "film_titolo_it_ufficiale(non it)": cov([x for x in allf if x["lang"] != "it"], lambda x: x.get("its") == "ufficiale"),
            "titoli_de_fr_es_in_italiano": cov([x for x in allf + alld if x["lang"] in langs], lambda x: x.get("it")),
            "titoli_de_fr_es_traduzione_automatica": cov([x for x in allf + alld if x["lang"] in langs], lambda x: x.get("its") == "auto"),
            "descrizioni_de_fr_es_tradotte": cov([x for x in allf + alld if x["lang"] in langs and x.get("d")], lambda x: x.get("da")),
        },
        "traduzioni": {"nuove": tr.new, "rimandate": tr.skipped, "errore": tr.failed, "in_cache": len(tr.cache)},
        "epg_ultimo_inizio": epg_last.isoformat() if epg_last else None,
    }
    data = {"generated": now.isoformat(timespec="minutes"), "days": days, "prime": cfg["prime_time"],
            "prime_es": cfg["prime_time_es"], "classic": c["classic_max_year"]}
    (OUT / "assets" / "data.js").write_text("window.GUIDE=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";",
                                            encoding="utf-8")
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    log(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
