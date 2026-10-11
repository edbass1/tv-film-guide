# Film e Documentari in TV

Pagina web statica (GitHub Pages) con i **film** e i **documentari** in TV oggi e nei giorni successivi,
aggiornata automaticamente ogni 6 ore da GitHub Actions. Sfondo nero, caratteri grandi, alto contrasto,
pulsanti A−/A+ per la dimensione del testo; funziona anche sul telefono.

Pagina: https://edbass1.github.io/tv-film-guide/

## Sezioni
Due sezioni: **FILM** (inclusi i film dei canali spagnoli) e **DOCUMENTARI**. Per ogni giorno:
* **Prima serata** (inizio 20:00–22:30; Spagna 20:00–23:00), prima i più importanti (voto IMDb, notorietà, canale)
* **Per genere** (documentari: **per argomento**), con il gruppo **Classici** = film fino al 1985
* **Per voto** IMDb
* **Tutti per orario**

Ogni scheda: titolo (italiano se esiste), canale, ora/data, genere, voto IMDb, anno, durata, descrizione,
badge **DOPPIO AUDIO**, repliche sugli altri canali.

## Fonti (gratuite, senza chiavi)
| Dato | Fonte |
|---|---|
| Guida TV DE/AT/CH/FR/IT/UK | file XMLTV di [epgshare01.online](https://epgshare01.online/epgshare01/) (`epg_ripper_DE1/CH1/FR1/IT1/UK1`) |
| Film sui canali spagnoli | [La Vanguardia](https://www.lavanguardia.com/television/programacion-tv/peliculas) |
| Voti, anno, generi, titoli italiani ufficiali | dataset pubblici IMDb (datasets.imdbws.com) |
| Titoli italiani mancanti | Wikidata (SPARQL tramite ID IMDb) |
| Traduzione tedesco/francese/spagnolo → italiano | modelli offline Helsinki-NLP opus-mt (de-it, tc-big-itc-itc per il francese, es-it) |

Traduzioni: si traducono **solo** titoli (se manca il titolo italiano ufficiale) e descrizioni in tedesco,
francese e spagnolo; l'inglese resta in originale. Le traduzioni automatiche sono segnate
“traduzione automatica” e salvate in `cache/translations.json` (non vengono rifatte).

## Filtri (tutti in `config.yaml`)
* niente programmi per bambini (categorie, titoli, canali, film IMDb Animazione+Famiglia)
* canali di lingua tedesca: solo quelli con doppio audio (Das Erste, ZDF, Arte, ZDFneo, ONE, 3sat, ORF 1, ORF 2, ORF III) – opzione `german_language_only_listed`
* documentari Mediaset esclusi, tranne Focus
* documentari esclusi: docu-reality/docusoap, natura/animali, casa/giardino/cucina/lifestyle
  (`docs.blocked_category_keywords`, `docs.blocked_title_keywords`, `docs.blocked_desc_keywords`)
* DOPPIO AUDIO: lista canali `dual_audio.channels` (mai su canali inglesi o italiani)

## Uso locale
```
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python build.py              # scarica tutto e genera docs/
python build.py --offline    # riusa i file già scaricati in raw/
python build.py --no-translate
```
Il risultato è in `docs/` (`index.html`, `assets/`, `report.json` con conteggi e copertura).

## Limiti
* epgshare01 pubblica circa 4 giorni di programmi: i giorni oltre non compaiono.
* La Vanguardia pubblica circa 3 giorni.
* I documentari raramente hanno un voto IMDb; il clou dei documentari usa anche canale e prima serata.
* Il DOPPIO AUDIO è per canale: non tutti i programmi hanno davvero la seconda lingua.
