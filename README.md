# Guida TV: Film e Documentari (oggi + 5 giorni)

Pagina web statica, pensata per **GitHub Pages**, che mostra i **film** e i **documentari** in onda in TV
oggi e nei 5 giorni successivi. Design per chi vede poco: **sfondo nero, caratteri grandi, alto contrasto**,
schede grandi, pulsanti A−/A+ per ingrandire ancora il testo. Funziona anche sul telefono.

La pagina si aggiorna da sola: una GitHub Action esegue lo script ogni 6 ore e salva la nuova versione in `docs/`.

## Cosa c'è nella pagina

* **Giorni**: Oggi, Domani e i 4 giorni successivi (pulsanti in alto).
* **Sezioni**: FILM · DOCUMENTARI · FILM SPAGNA (canali spagnoli).
* **Viste** per ogni sezione:
  * **Prima serata** (inizio tra le 20:00 e le 22:30; per la Spagna 20:00–23:00), mostrata per prima;
  * **Il clou**: i più importanti (voto IMDb alto + film molto conosciuti; per i documentari voto alto o canali di qualità in prima serata);
  * **Per genere** (film) / **Per argomento** (documentari);
  * **Per voto** (IMDb; per la Spagna il voto di La Vanguardia);
  * **Tutti per orario**.
* Ogni scheda: titolo (in italiano quando possibile), canale, ora e data, genere, voto IMDb, anno, durata,
  badge **DOPPIO AUDIO**, eventuali altre messe in onda (“Anche: …”), link alla scheda Teleboy.
* Filtri: “Solo DOPPIO AUDIO”, “Mostra anche quelli già finiti” (di default i programmi terminati sono nascosti).
* Link diretti: `index.html#kind=docs&view=clou&day=1` (kind = films | docs | es).

## Fonti dei dati

| Fonte | Come | Note |
|---|---|---|
| Teleboy (film, documentari) | API JSON pubblica usata dal sito: `https://api.teleboy.ch/epg/broadcasts?begin=…&end=…&genre=1|2&expand=flags,station&limit=300&skip=…` | Serve l'intestazione `x-teleboy-apikey`: è la chiave **pubblica** inserita nell'HTML di teleboy.ch (`tvapiKey`). Lo script la legge ogni volta dalla pagina, nessun login. Contiene voto/voti/ID IMDb, anno, titolo originale, flag `is_dual_audio`, lingua e paese del canale. |
| Teleboy generi | `https://api.teleboy.ch/epg/genres` | Nomi dei generi già in italiano. |
| La Vanguardia (Spagna) | HTML statico (sito Astro) `…/programacion-tv/peliculas`, elementi `li.event` | Non c'è un'API JSON; pubblica solo **~3 giorni**. Voto proprio di La Vanguardia, non IMDb. |
| Wikidata (traduzioni) | SPARQL `query.wikidata.org` per ID IMDb → titolo italiano (etichetta it / titolo di it.wikipedia); `wbsearchentities` per titolo+anno quando manca l'ID IMDb | **Gratuito, senza chiave.** (TMDB richiederebbe una chiave API, quindi non è usato.) |
| MyMemory (traduzione automatica) | `api.mymemory.translated.net` | Gratuito senza chiave, ma con limite (~5.000 caratteri/giorno anonimi, 50.000 con email in `config.yaml`). Usato solo per titoli senza versione italiana ufficiale; segnalato in pagina come “traduzione automatica”. Le traduzioni restano in `cache/`. |

## DOPPIO AUDIO

1. **Lista canali dell'utente** (`dual_audio.channels` in `config.yaml`): badge **sempre**, per film e documentari.
   Germania: Das Erste (ARD), ZDF, Arte, ZDFneo, ONE, 3sat · Francia: Arte, France 2, France 3, France 4, TF1, M6, W9,
   TMC, TFX, TF1 Séries Films, 6ter · Austria: ORF 1, ORF 2, ORF III · Spagna: La 1, La 2, Antena 3, Cuatro,
   Telecinco, laSexta, Neox, FDF, Divinity, Energy, Paramount Network.
   I nomi vengono confrontati in modo tollerante (maiuscole, spazi, “HD”, “Deutsch”, “TVE”… ignorati) e ogni voce ha varianti (es. `ORF1`, `ORF eins`).
2. **Mai badge** su RTL, ProSieben, Sat.1, ATV, Puls 4 e sui canali inglesi o italiani.
3. **Fonte secondaria**: sugli altri canali tedeschi/francesi (es. SRF, RTS, 3+) il badge compare se Teleboy segna
   il singolo programma con `is_dual_audio` **e** il film è straniero (su produzioni tedesche il “Zweikanalton” è quasi sempre audiodescrizione).

## Filtri

Tutto in `config.yaml`:
* **bambini** esclusi (generi Teleboy “Film per bambini”/“Bambini”, canali per ragazzi, animazione con età ≤ 6, parole chiave);
* **Mediaset**: documentari esclusi tranne il canale **Focus**;
* **documentari “importanti”**: canali bloccati (tv locali, religiosi, televendite, docu-reality come DMAX, Real Time…),
  parole bloccate (es. “Affari di famiglia”, “Pawn Stars”, “Storage Wars”, aste, banchi dei pegni, auto, dogane, polizia…),
  durata minima 40 min, e devono essere su un canale di qualità (≥45 min) **o** avere IMDb ≥ 7 **o** essere consigliati **o** in prima serata;
* lingue dei canali escluse (ucraino, turco, arabo, coreano, giapponese, portoghese, olandese).

## Uso in locale

```bash
pip install -r requirements.txt
python build.py              # scarica i dati e genera docs/
python build.py --offline    # rigenera usando i dati già scaricati (cache/raw.json)
```
Poi aprire `docs/index.html` nel browser. `docs/report.json` contiene conteggi e statistiche dell'ultima esecuzione.

## Pubblicazione su GitHub Pages

1. Creare un repository e caricare questi file.
2. *Settings → Pages*: “Deploy from a branch”, ramo `main`, cartella `/docs`.
3. *Settings → Actions → General → Workflow permissions*: “Read and write permissions”.
4. Il workflow `.github/workflows/update.yml` gira ogni 6 ore (e si può avviare a mano da *Actions*).

## Limiti noti

* La Vanguardia pubblica solo circa 3 giorni; nessun voto IMDb per i film spagnoli (salvo quando lo stesso film è anche su Teleboy).
* Il voto IMDb dei documentari spesso è quello della **serie**, non del singolo episodio.
* Molti film TV tedeschi non hanno un titolo italiano su Wikidata: si mostra il titolo originale (o una traduzione automatica se c'è ancora quota MyMemory).
* L'argomento dei documentari è stimato con parole chiave (Teleboy non lo fornisce): alcuni finiscono in “Altro”.
* L'API Teleboy non è documentata ufficialmente: se cambia, lo script va adattato.
