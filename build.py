#!/usr/bin/env python3
"""
Guida TV: Film e Documentari (oggi + 5 giorni)
Scarica i dati da Teleboy (API JSON pubblica del frontend) e La Vanguardia
(HTML statico), filtra, traduce i titoli e genera un sito statico in ./docs.

Uso:  python build.py            (genera docs/)
      python build.py --offline  (riusa cache/raw_*.json senza scaricare)
"""
import argparse, datetime as dt, html, json, math, os, re, sys, time, unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
OUT = ROOT / "docs"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
BOT_UA = "tv-film-guide/1.0 (static TV guide prototype; https://github.com/)"

S = requests.Session()
S.headers["User-Agent"] = UA


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- helpers
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def kw_regex(words, prefix=False):
    """Regex che trova le parole chiave come parole intere (o come prefisso)."""
    parts = []
    for w in words:
        e = re.escape(w)
        left = r"(?<!\w)" if w[:1].isalnum() else ""
        if prefix and len(w) >= 5:
            right = ""
        else:
            right = r"(?!\w)" if w[-1:].isalnum() else ""
        parts.append(left + e + right)
    return re.compile("|".join(parts), re.I) if parts else None


def lower_set(xs):
    return {str(x).lower() for x in (xs or [])}


def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def save_json(p, data):
    Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True))


# ---------------------------------------------------------------- Teleboy
def teleboy_key(cfg):
    key = (os.environ.get("TELEBOY_API_KEY") or "").strip()
    if key:
        log("  chiave Teleboy da variabile d'ambiente")
        return key
    kf = CACHE / "teleboy_key.txt"
    try:
        r = S.get(cfg["teleboy"]["page_for_key"], timeout=30)
        log(f"  pagina Teleboy: HTTP {r.status_code}, {len(r.text)} byte")
        m = re.search(r"tvapiKey:\s*'([0-9a-f]{20,})'", r.text)
        if not m:
            log(f"! chiave non trovata nella pagina (HTTP {r.status_code}, {len(r.text)} byte)")
        if m:
            kf.write_text(m.group(1))
            return m.group(1)
    except Exception as e:
        log("! impossibile leggere la chiave Teleboy dalla pagina:", e)
    if kf.exists():
        return kf.read_text().strip()
    raise SystemExit("Chiave pubblica Teleboy non trovata")


def teleboy_fetch(cfg, key, genre, start, end):
    """Tutte le trasmissioni del genere tra start e end (paginazione 300)."""
    base = cfg["teleboy"]["api_base"]
    ps = cfg["teleboy"].get("page_size", 300)
    hdr = {"x-teleboy-apikey": key, "Origin": "https://www.teleboy.ch", "Referer": "https://www.teleboy.ch/"}
    out, day = {}, start
    while day < end:
        nxt = min(day + dt.timedelta(days=1), end)
        skip = 0
        while True:
            params = {"begin": day.strftime("%Y-%m-%d %H:%M:%S"), "end": nxt.strftime("%Y-%m-%d %H:%M:%S"),
                      "genre": genre, "expand": "flags,station", "limit": ps, "skip": skip}
            for attempt in range(4):
                try:
                    r = S.get(base + "/epg/broadcasts", params=params, headers=hdr, timeout=40)
                    r.raise_for_status()
                    data = r.json()["data"]
                    break
                except Exception as e:
                    log(f"  retry {attempt+1} genre={genre} {params['begin']} skip={skip}: {e}")
                    time.sleep(2 + attempt * 3)
            else:
                raise SystemExit("Teleboy API non raggiungibile")
            for it in data["items"]:
                out[it["id"]] = it
            skip += ps
            if skip >= data["total"] or not data["items"]:
                break
        day = nxt
    return list(out.values())


def teleboy_genres(cfg, key):
    r = S.get(cfg["teleboy"]["api_base"] + "/epg/genres", timeout=30, headers={
        "x-teleboy-apikey": key, "Origin": "https://www.teleboy.ch", "Referer": "https://www.teleboy.ch/"})
    if r.status_code != 200 or not r.text.lstrip().startswith("{"):
        raise SystemExit(f"Teleboy API: risposta non valida HTTP {r.status_code} "
                         f"server={r.headers.get('server')} cf-ray={r.headers.get('cf-ray')} "
                         f"testo={re.sub(r'\s+', ' ', BeautifulSoup(r.text, 'html.parser').get_text(' '))[:600]!r}")
    names = {}
    for g in r.json()["data"]["items"]:
        names[g["id"]] = g.get("name_it") or g["name"]
        for sg in g.get("sub_genres", []):
            names[sg["id"]] = sg.get("name_it") or sg["name"]
    # nomi italiani più naturali
    names.update({18: "Giallo / Poliziesco", 22: "Horror", 32: "Romantico", 31: "Musical",
                  33: "Fantascienza", 1: "Film (altro)", 30: "Commedia"})
    return names


# ---------------------------------------------------------------- La Vanguardia
ES_GENRES = {"accion": "Azione", "aventuras": "Avventura", "animacion": "Animazione", "comedia": "Commedia",
             "drama": "Dramma", "thriller": "Thriller", "terror": "Horror", "ciencia-ficcion": "Fantascienza",
             "fantasia": "Fantasy", "romance": "Romantico", "romantica": "Romantico", "western": "Western",
             "belica": "Guerra", "musical": "Musical", "documental": "Documentario", "crimen": "Giallo / Poliziesco",
             "misterio": "Mistero", "historia": "Storico", "familia": "Famiglia", "infantil": "Bambini",
             "suspense": "Thriller", "biografia": "Biografico", "deporte": "Sport", "intriga": "Thriller",
             "policiaca": "Giallo / Poliziesco", "cine-negro": "Noir"}


def lavanguardia_fetch(cfg):
    r = S.get(cfg["lavanguardia"]["url"], timeout=40)
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
            tags = [a.get("href", "").rstrip("/").split("/")[-1] for a in li.select("a.event__tag")]
            a = t.select_one("a") if t else None
            age = li.select_one(".event__age")
            syn = li.select_one(".event__syn")
            items.append({
                "title": t.get_text(" ", strip=True),
                "channel": ch.get_text(" ", strip=True) if ch else "?",
                "begin": li["data-s"], "end": li["data-e"], "year": year, "lv_rating": rating,
                "genres_es": tags, "age": age.get_text(strip=True) if age else None,
                "url": a["href"] if a else None,
                "desc": syn.get_text(" ", strip=True) if syn else "",
            })
        except Exception as e:
            log("  LV parse:", e)
    return items


# ---------------------------------------------------------------- Wikidata / traduzioni
class Translator:
    def __init__(self, cfg):
        self.cfg = cfg["translation"]
        self.imdb = load_json(CACHE / "wikidata_imdb.json", {})      # tt -> {"it":..}
        self.search = load_json(CACHE / "wikidata_search.json", {})  # key -> {"it":.., "imdb":..} | {}
        self.mt = load_json(CACHE / "mymemory.json", {})             # "de|text" -> it
        self.searches = 0
        self.mt_chars = 0
        self.mt_quota_hit = False
        self.ws = requests.Session()
        self.ws.headers["User-Agent"] = BOT_UA

    def save(self):
        save_json(CACHE / "wikidata_imdb.json", self.imdb)
        save_json(CACHE / "wikidata_search.json", self.search)
        save_json(CACHE / "mymemory.json", self.mt)

    @staticmethod
    def _clean_it(label):
        return re.sub(r"\s*\((film|serie televisiva|documentario|miniserie)[^)]*\)\s*$", "", label or "").strip() or None

    def by_imdb(self, ids):
        """Titoli italiani per ID IMDb, in blocchi, via SPARQL (senza chiave)."""
        if not self.cfg.get("wikidata"):
            return
        todo = sorted({i for i in ids if i and i not in self.imdb})
        for k in range(0, len(todo), 80):
            chunk = todo[k:k + 80]
            q = ("SELECT ?imdb ?it ?itw WHERE { VALUES ?imdb {%s} ?item wdt:P345 ?imdb. "
                 "OPTIONAL{?item rdfs:label ?it FILTER(lang(?it)='it')} "
                 "OPTIONAL{?a schema:about ?item; schema:isPartOf <https://it.wikipedia.org/>; schema:name ?itw} }"
                 % " ".join(f'"{i}"' for i in chunk))
            try:
                r = self.ws.get("https://query.wikidata.org/sparql", params={"query": q},
                                headers={"Accept": "application/sparql-results+json"}, timeout=60)
                r.raise_for_status()
                found = {}
                for b in r.json()["results"]["bindings"]:
                    i = b["imdb"]["value"]
                    lab = self._clean_it(b.get("itw", {}).get("value")) or b.get("it", {}).get("value")
                    if lab and i not in found:
                        found[i] = lab
                for i in chunk:
                    self.imdb[i] = {"it": found.get(i)}
            except Exception as e:
                log("  wikidata sparql:", e)
            time.sleep(0.5)

    def by_search(self, title, year, lang):
        """Cerca un FILM su Wikidata per titolo+anno (wbsearchentities); restituisce {it, imdb}."""
        if not self.cfg.get("wikidata") or not title:
            return {}
        key = f"{lang}|{norm(title)}|{year}"
        if key in self.search:
            return self.search[key]
        if self.searches >= self.cfg.get("wikidata_max_searches_per_run", 200):
            return {}
        self.searches += 1
        res = {}
        try:
            r = self.ws.get("https://www.wikidata.org/w/api.php", timeout=30, params={
                "action": "wbsearchentities", "search": title, "language": lang, "uselang": "en",
                "type": "item", "format": "json", "limit": 7})
            cands = []
            for c in r.json().get("search", []):
                d = (c.get("description") or "").lower()
                if "film" not in d or "series" in d:
                    continue
                if norm(c.get("match", {}).get("text")) != norm(title):
                    continue
                ys = [int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", d)]
                if year and ys and not any(abs(y - year) <= 1 for y in ys):
                    continue
                if year and not ys:
                    continue
                cands.append(c["id"])
            if cands:
                r = self.ws.get("https://www.wikidata.org/w/api.php", timeout=30, params={
                    "action": "wbgetentities", "ids": cands[0], "props": "labels|claims|sitelinks",
                    "languages": "it", "format": "json"})
                e = r.json()["entities"][cands[0]]
                it = self._clean_it(e.get("sitelinks", {}).get("itwiki", {}).get("title")) \
                    or e.get("labels", {}).get("it", {}).get("value")
                imdb = None
                for cl in e.get("claims", {}).get("P345", []):
                    imdb = cl["mainsnak"].get("datavalue", {}).get("value")
                    break
                res = {"it": it, "imdb": imdb, "qid": cands[0]}
        except Exception as e:
            log("  wikidata search:", e)
            return {}
        self.search[key] = res
        time.sleep(0.2)
        return res

    def machine(self, text, lang):
        """Traduzione automatica it via MyMemory (senza chiave). Solo per i titoli dei documentari."""
        if not self.cfg.get("machine_translation") or not text or lang == "it":
            return None
        key = f"{lang}|{text}"
        if key in self.mt:
            return self.mt[key]
        if self.mt_quota_hit or self.mt_chars + len(text) > self.cfg.get("machine_translation_max_chars_per_run", 4500):
            return None
        self.mt_chars += len(text)
        try:
            p = {"q": text, "langpair": f"{lang}|it"}
            if self.cfg.get("mymemory_email"):
                p["de"] = self.cfg["mymemory_email"]
            r = self.ws.get("https://api.mymemory.translated.net/get", params=p, timeout=30)
            j = r.json()
            if j.get("quotaFinished") or str(j.get("responseStatus")) == "429":
                self.mt_quota_hit = True
                return None
            t = html.unescape(j["responseData"]["translatedText"] or "").strip()
            if not t or "MYMEMORY WARNING" in t.upper() or "QUERY LENGTH LIMIT" in t.upper():
                self.mt_quota_hit = "WARNING" in t.upper()
                return None
            self.mt[key] = t
            time.sleep(0.15)
            return t
        except Exception as e:
            log("  mymemory:", e)
            return None


# ---------------------------------------------------------------- normalizzazione
OWN_COUNTRY = {
    "de": ["deutschland", "osterreich", "schweiz", "germany", "austria", "switzerland", "brd", "ddr",
           "allemagne", "autriche", "suisse", "germania", "svizzera"],
    "fr": ["france", "frankreich", "belgique", "belgien", "suisse", "schweiz", "francia", "luxembourg",
           "canada", "kanada", "quebec"],
}


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
    """Badge DOPPIO AUDIO: lista canali dell'utente (sempre) + flag Teleboy (secondario)."""
    def __init__(self, cfg):
        da = cfg["dual_audio"]
        self.cfg = da
        self.map = {}
        for entry in da.get("channels", []):
            for alias in entry:
                self.map[chan_key(str(alias))] = str(entry[0])
        self.never = {chan_key(str(x)) for x in da.get("never_channels", [])}
        self.never_lang = lower_set(da.get("never_languages"))
        self.flag_lang = lower_set(da.get("teleboy_flag_languages"))

    def listed(self, channel):
        return self.map.get(chan_key(channel))

    def decide(self, channel, lang, b=None):
        k = chan_key(channel)
        if k in self.never or (lang or "").lower() in self.never_lang:
            return None
        if k in self.map:
            return "sì"
        if b is not None and self.cfg.get("use_teleboy_flag_on_other_channels") and lang in self.flag_lang \
                and b.get("is_dual_audio") and is_foreign(b):
            return "teleboy"
        return None


def clean_title(t):
    t = re.sub(r"^(FILM|MOVIE|FILMS?|Spielfilm)\s*:\s*", "", t or "", flags=re.I)
    t = re.sub(r"\s*\((19|20)\d{2}\)\s*$", "", t)
    return t.strip()


def is_foreign(b):
    lang = b["station"]["language"]
    ot, t = b.get("original_title") or "", b.get("title") or ""
    if ot and norm(ot) != norm(t):
        return True
    c = norm(b.get("country") or "")
    if not c:
        return False
    return not any(w in c for w in OWN_COUNTRY.get(lang, []))


def build_items(cfg, raw, genre_names, kind, tz, tr):
    """Applica filtri e trasforma le trasmissioni Teleboy in elementi per la pagina."""
    ex_lang = lower_set(cfg.get("exclude_station_languages"))
    kids = cfg["kids"]
    kid_ch, kid_gen = lower_set(kids["channels"]), set(kids["genre_ids"])
    kid_kw = kw_regex(kids["title_keywords"])
    sect = cfg["docs" if kind == "doc" else "films"]
    blk_ch = lower_set(sect.get("blocked_channels"))
    blk_kw = kw_regex(sect.get("blocked_title_keywords", []))
    med = lower_set(cfg["mediaset"]["channels"]) - lower_set(cfg["mediaset"]["keep_docs_on"])
    mindur = sect.get("min_duration_minutes", 0)
    stats = {"totale": len(raw)}

    def drop(reason):
        stats[reason] = stats.get(reason, 0) + 1

    out = []
    for b in raw:
        st = b["station"]
        lab = (b.get("station_label") or st["label"]).lower()
        title = clean_title(b.get("title"))
        text = " ".join([title, b.get("subtitle") or "", b.get("original_title") or ""])
        if st.get("language") in ex_lang:
            drop("lingua canale esclusa"); continue
        if lab in kid_ch or b.get("genre_id") in kid_gen or (kid_kw and kid_kw.search(text)):
            drop("bambini"); continue
        if kind == "film" and b.get("genre_id") == 17 and kids.get("exclude_animation_max_age") is not None \
                and (b.get("age") is None or b["age"] <= kids["exclude_animation_max_age"]):
            drop("bambini (animazione)"); continue
        if kind == "doc" and lab in med:
            drop("Mediaset (non Focus)"); continue
        if lab in blk_ch:
            drop("canale bloccato"); continue
        if blk_kw and blk_kw.search(text):
            drop("parola bloccata"); continue
        if (b.get("duration") or 0) < mindur:
            drop("troppo breve"); continue
        begin = dt.datetime.strptime(b["begin"], "%Y-%m-%dT%H:%M:%S%z").astimezone(tz)
        end = dt.datetime.strptime(b["end"], "%Y-%m-%dT%H:%M:%S%z").astimezone(tz)
        lang = st.get("language")
        dual = DA.decide(b.get("station_label") or st["label"], lang, b)
        out.append({
            "id": b["id"], "kind": kind, "title": title, "orig": b.get("original_title") or None,
            "sub": b.get("subtitle") or None, "ch": b.get("station_label") or st["label"], "lang": lang,
            "cc": st.get("country"), "begin": begin.isoformat(), "end": end.isoformat(),
            "dur": b.get("duration"), "genre": genre_names.get(b.get("genre_id"), "Altro") if kind == "film" else None,
            "year": b.get("year"), "imdb": b.get("imdb_rating"), "votes": b.get("imdb_vote_count"),
            "imdb_id": b.get("imdb_id"), "dual": dual, "tip": bool(b.get("flags", {}).get("is_tip")),
            "age": b.get("age"), "country": b.get("country"),
            "desc": (b.get("short_description") or "")[:260] or None,
            "url": f"https://www.teleboy.ch/en/tv-guide/{st.get('slug')}/{b['id']}/{b.get('slug') or 'x'}",
            "src": "teleboy",
        })
    stats["tenuti"] = len(out)
    return out, stats


def build_es_items(cfg, raw, tz, imdb_ratings):
    kids = cfg["kids"]
    kid_ch, kid_kw = lower_set(kids["channels"]), kw_regex(kids["title_keywords"])
    out, stats = [], {"totale": len(raw)}
    for b in raw:
        if b["channel"].lower() in kid_ch or (kid_kw and kid_kw.search(b["title"])) or "infantil" in b["genres_es"] \
                or ("animacion" in b["genres_es"] and "familia" in b["genres_es"]):
            stats["bambini"] = stats.get("bambini", 0) + 1
            continue
        begin = dt.datetime.fromisoformat(b["begin"].replace("Z", "+00:00")).astimezone(tz)
        end = dt.datetime.fromisoformat(b["end"].replace("Z", "+00:00")).astimezone(tz)
        genres = [ES_GENRES.get(g, g.replace("-", " ").capitalize()) for g in b["genres_es"]]
        out.append({"id": "lv" + b["begin"] + norm(b["channel"]), "kind": "es", "title": b["title"], "orig": None,
                    "sub": None, "ch": b["channel"], "lang": "es", "cc": "es", "begin": begin.isoformat(),
                    "end": end.isoformat(), "dur": int((end - begin).total_seconds() // 60),
                    "genre": genres[0] if genres else "Altro", "genres": genres, "year": b["year"],
                    "imdb": None, "votes": None, "imdb_id": None, "lv": b["lv_rating"],
                    "dual": DA.decide(b["channel"], "es"),
                    "tip": False, "desc": (b["desc"] or "")[:260] or None, "url": b["url"], "src": "lavanguardia"})
    stats["tenuti"] = len(out)
    return out, stats


def translate_all(items, tr, imdb_map=None):
    """Aggiunge 'it' (titolo italiano) e 'it_src' (wikidata | auto).
    1) ID IMDb -> Wikidata SPARQL (etichetta italiana / titolo it.wikipedia)
    2) film senza ID IMDb: ricerca Wikidata per titolo + anno (prima Spagna e prima serata)
    3) titoli rimasti senza italiano: traduzione automatica MyMemory (prima serata/clou prima)"""
    tr.by_imdb([i["imdb_id"] for i in items if i.get("imdb_id") and i["lang"] != "it"])
    for i in items:
        if i["lang"] != "it" and i.get("imdb_id"):
            it = (tr.imdb.get(i["imdb_id"]) or {}).get("it")
            if it and norm(it) != norm(i["title"]):
                i["it"], i["it_src"] = it, "wikidata"
    todo = [i for i in items if i["kind"] in ("film", "es") and i["lang"] != "it" and not i.get("imdb_id")
            and not i.get("it") and i.get("year")]
    todo.sort(key=lambda i: (i["kind"] != "es", not i.get("_prime"), i["begin"]))
    seen = set()
    for i in todo:
        k = (norm(i["title"]), i["year"])
        if k in seen and not tr.search.get(f"{i['lang']}|{k[0]}|{k[1]}"):
            continue
        seen.add(k)
        it = None
        for cand, lang in ((i.get("orig"), "en"), (i["title"], i["lang"] or "de")):
            if not cand:
                continue
            res = tr.by_search(cand, i["year"], lang)
            if res.get("imdb") and not i.get("imdb_id"):
                i["imdb_id"] = res["imdb"]
                if imdb_map and res["imdb"] in imdb_map:
                    i["imdb"], i["votes"] = imdb_map[res["imdb"]]
            if res.get("it"):
                it = res["it"]
                break
        if it and norm(it) != norm(i["title"]):
            i["it"], i["it_src"] = it, "wikidata"
    # traduzione automatica (titoli senza italiano), prima serata e giorni vicini per primi
    rest = [i for i in items if i["lang"] not in ("it",) and not i.get("it")]
    rest.sort(key=lambda i: (not i.get("_prime"), i["begin"][:10], i["kind"] != "doc", i["begin"]))
    for i in rest:
        lang = i["lang"] if i["lang"] in ("de", "fr", "en", "es") else None
        if not lang:
            continue
        t = tr.machine(i["title"], lang)
        if t and norm(t) != norm(i["title"]):
            i["it"], i["it_src"] = t, "auto"


# ---------------------------------------------------------------- raggruppamento
def tv_day(begin, day_start_min):
    d = dt.datetime.fromisoformat(begin)
    if d.hour * 60 + d.minute < day_start_min:
        d -= dt.timedelta(days=1)
    return d.date().isoformat()


def classify_topic(i, topic_res):
    # prima titolo/sottotitolo, poi (se nulla) la descrizione
    for text in (" ".join(filter(None, [i.get("it"), i["title"], i.get("sub"), i.get("orig")])), i.get("desc") or ""):
        for name, rx in topic_res:
            if text and rx.search(text):
                return name
    return "Altro"


def merge_repeats(items, prime_fn):
    """Unisce le repliche dello stesso titolo nello stesso giorno TV: una scheda + 'Altre messe in onda'."""
    groups = {}
    for i in items:
        k = (i["day"], norm(i.get("orig") or i["title"]) if i["kind"] != "doc" else norm(i["title"]),
             (i.get("year") or "") if i["kind"] != "doc" else norm(i.get("sub") or ""))
        groups.setdefault(k, []).append(i)
    out = []
    for g in groups.values():
        g.sort(key=lambda x: (not prime_fn(x), not x.get("dual"), x["begin"]))
        main = dict(g[0])
        main["also"] = [{"ch": x["ch"], "begin": x["begin"], "dual": x.get("dual"), "url": x.get("url")}
                        for x in sorted(g[1:], key=lambda x: x["begin"])]
        # se una replica ha il voto IMDb e la principale no, copialo
        for x in g[1:]:
            if not main.get("imdb") and x.get("imdb"):
                main["imdb"], main["votes"] = x["imdb"], x.get("votes")
        out.append(main)
    out.sort(key=lambda x: x["begin"])
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="usa i dati grezzi in cache/")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = ap.parse_args()
    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    CACHE.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "assets").mkdir(exist_ok=True)
    tz = ZoneInfo(cfg["timezone"])
    now = dt.datetime.now(tz)
    ds = hm(cfg["day_starts_at"])
    today = (now - dt.timedelta(minutes=ds)).date()
    start = dt.datetime.combine(today, dt.time(ds // 60, ds % 60), tz)
    end = start + dt.timedelta(days=cfg["days_ahead"] + 1)
    fetch_start = max(start, now - dt.timedelta(hours=4)).replace(minute=0, second=0, microsecond=0)

    raw_path = CACHE / "raw.json"
    if args.offline and raw_path.exists():
        raw = json.loads(raw_path.read_text())
    else:
        key = teleboy_key(cfg)
        log("Teleboy: generi")
        genres = teleboy_genres(cfg, key)
        log("Teleboy: film", fetch_start, "→", end)
        films = teleboy_fetch(cfg, key, cfg["teleboy"]["film_genre_id"], fetch_start, end)
        docs = []
        for g in cfg["teleboy"]["doc_genre_ids"]:
            log("Teleboy: documentari genere", g)
            docs += teleboy_fetch(cfg, key, g, fetch_start, end)
        es = []
        if cfg["lavanguardia"].get("enabled"):
            log("La Vanguardia: film")
            try:
                es = lavanguardia_fetch(cfg)
            except Exception as e:
                log("! La Vanguardia non disponibile:", e)
        raw = {"genres": {str(k): v for k, v in genres.items()}, "films": films, "docs": docs, "es": es}
        raw_path.write_text(json.dumps(raw, ensure_ascii=False))
    genres = {int(k): v for k, v in raw["genres"].items()}
    log(f"grezzi: film={len(raw['films'])} doc={len(raw['docs'])} es={len(raw['es'])}")

    global DA
    DA = DualAudio(cfg)
    tr = Translator(cfg)
    films, fstats = build_items(cfg, raw["films"], genres, "film", tz, tr)
    docs, dstats = build_items(cfg, raw["docs"], genres, "doc", tz, tr)
    imdb_map = {i["imdb_id"]: (i["imdb"], i["votes"]) for i in films if i.get("imdb_id") and i.get("imdb")}
    es, estats = build_es_items(cfg, raw["es"], tz, imdb_map)

    pt = (hm(cfg["prime_time"]["from"]), hm(cfg["prime_time"]["to"]))
    pte = (hm(cfg["prime_time_es"]["from"]), hm(cfg["prime_time_es"]["to"]))

    def prime(i):
        d = dt.datetime.fromisoformat(i["begin"])
        lo, hi = pte if i["kind"] == "es" else pt
        return lo <= d.hour * 60 + d.minute <= hi

    days = [(today + dt.timedelta(days=k)).isoformat() for k in range(cfg["days_ahead"] + 1)]
    allitems = []
    for i in films + docs + es:
        i["day"] = tv_day(i["begin"], ds)
        if i["day"] not in days:
            continue
        i["_prime"] = prime(i)
        allitems.append(i)

    # documentari: tieni solo quelli "importanti"
    dc = cfg["docs"]
    qual0 = lower_set(dc["quality_channels"])
    req = set(dc.get("require_one_of") or [])
    if req:
        before = sum(1 for i in allitems if i["kind"] == "doc")
        def important(i):
            return (("quality_channel" in req and i["ch"].lower() in qual0
                     and (i.get("dur") or 0) >= dc.get("quality_channel_min_duration", 0))
                    or ("imdb" in req and (i.get("imdb") or 0) >= dc.get("important_min_imdb", 7.0))
                    or ("tip" in req and i.get("tip"))
                    or ("prime_time" in req and i["_prime"]))
        allitems = [i for i in allitems if i["kind"] != "doc" or important(i)]
        dstats["non importanti (scartati)"] = before - sum(1 for i in allitems if i["kind"] == "doc")

    log("Traduzioni (Wikidata / MyMemory)…")
    translate_all(allitems, tr, imdb_map)
    tr.save()

    topic_res = [(name, kw_regex([str(w) for w in words], prefix=True)) for name, words in cfg["doc_topics"].items()]
    c = cfg["clou"]
    qual = lower_set(cfg["docs"]["quality_channels"])
    for i in allitems:
        i["prime"] = i.pop("_prime")
        if i["kind"] == "doc":
            i["genre"] = classify_topic(i, topic_res)
        r, v = i.get("imdb") or 0, i.get("votes") or 0
        if i["kind"] == "film":
            i["clou"] = bool((r >= c["film_min_rating"] and v >= c["film_min_votes"])
                             or (v >= c["film_famous_votes"] and r >= c["film_famous_min_rating"])
                             or (i["tip"] and r >= 6.5))
            i["score"] = round(r + min(math.log10(v + 1), 6) / 3, 3) if r else 0
        elif i["kind"] == "doc":
            i["clou"] = bool(r >= c["doc_min_rating"] or (i["prime"] and i["ch"].lower() in qual and (i["dur"] or 0) >= 45)
                             or (i["tip"] and i["ch"].lower() in qual))
            i["score"] = round(r + (1.5 if i["ch"].lower() in qual else 0) + (1 if i["tip"] else 0) + (0.5 if i["prime"] else 0), 3)
        else:
            lr = i.get("lv") or 0
            i["clou"] = bool(lr >= 7.0 or (r >= c["film_min_rating"] and v >= c["film_min_votes"]))
            i["score"] = r or lr

    out_days, counts = [], []
    wd = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    mo = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
          "ottobre", "novembre", "dicembre"]
    keep = ["id", "kind", "title", "it", "it_src", "orig", "sub", "ch", "lang", "begin", "end", "dur", "genre",
            "year", "imdb", "votes", "imdb_id", "lv", "dual", "tip", "desc", "url", "prime", "clou", "score", "also"]
    for k, d in enumerate(days):
        dd = dt.date.fromisoformat(d)
        label = "Oggi" if k == 0 else "Domani" if k == 1 else wd[dd.weekday()]
        entry = {"date": d, "label": label, "long": f"{wd[dd.weekday()]} {dd.day} {mo[dd.month-1]}"}
        for kind, name in (("film", "films"), ("doc", "docs"), ("es", "es")):
            its = merge_repeats([i for i in allitems if i["day"] == d and i["kind"] == kind], prime)
            entry[name] = [{x: i[x] for x in keep if i.get(x) not in (None, [], "")} for i in its]
        counts.append({"giorno": d, "film": len(entry["films"]), "documentari": len(entry["docs"]),
                       "film_spagna": len(entry["es"]),
                       "film_prima_serata": sum(1 for i in entry["films"] if i.get("prime")),
                       "doc_prima_serata": sum(1 for i in entry["docs"] if i.get("prime"))})
        out_days.append(entry)

    def cov(items, f):
        return f"{sum(1 for i in items if f(i))}/{len(items)}"
    fl = [i for i in allitems if i["kind"] == "film"]
    dl = [i for i in allitems if i["kind"] == "doc"]
    el = [i for i in allitems if i["kind"] == "es"]
    report = {
        "generato": now.isoformat(timespec="minutes"),
        "conteggi_per_giorno (dopo unione repliche)": counts,
        "filtri_film": fstats, "filtri_documentari": dstats, "filtri_spagna": estats,
        "copertura": {
            "film_con_imdb": cov(fl, lambda i: i.get("imdb")), "doc_con_imdb": cov(dl, lambda i: i.get("imdb")),
            "film_doppio_audio_sì": cov(fl, lambda i: i.get("dual") == "sì"),
            "film_doppio_audio_teleboy_flag": cov(fl, lambda i: i.get("dual") == "teleboy"),
            "spagna_doppio_audio": cov(el, lambda i: i.get("dual")),
            "doc_doppio_audio_sì": cov(dl, lambda i: i.get("dual") == "sì"),
            "doc_doppio_audio_teleboy_flag": cov(dl, lambda i: i.get("dual") == "teleboy"),
            "film_non_it_con_titolo_it": cov([i for i in fl if i["lang"] != "it"], lambda i: i.get("it")),
            "doc_non_it_con_titolo_it": cov([i for i in dl if i["lang"] != "it"], lambda i: i.get("it")),
            "doc_trad_automatica": cov(dl, lambda i: i.get("it_src") == "auto"),
            "spagna_con_titolo_it": cov(el, lambda i: i.get("it")),
            "spagna_con_imdb": cov(el, lambda i: i.get("imdb")),
        },
        "wikidata_ricerche_nuove": tr.searches, "mymemory_caratteri": tr.mt_chars, "mymemory_quota": bool(tr.mt_quota_hit),
    }
    data = {"generated": now.isoformat(timespec="minutes"), "days": out_days,
            "prime": cfg["prime_time"], "prime_es": cfg["prime_time_es"]}
    js = "window.GUIDE=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    (OUT / "assets" / "data.js").write_text(js, encoding="utf-8")
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    log(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
