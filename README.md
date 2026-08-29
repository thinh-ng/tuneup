# tuneup

Repairs and re-tags a music library that an auto-tagger has damaged: wrong titles,
inconsistent artist spellings, and a genre list with no room for regional categories.

Every decision is a Unicode rule, a lookup table, or a fixed audio model. No LLM, no
network in the default path, same result on every run.

## Tags

```
Tag       Values                                   Source
--------  ---------------------------------------  ----------------------------
Language  Vietnamese, English, Chinese, Korean,    Unicode blocks and Vietnamese
          Japanese, Instrumental                   diacritics in title/artist
Genre     16 fixed values, incl. Bolero            Essentia Discogs-EffNet
Mood      Happy, Sad, Relaxed, Aggressive,         Essentia mood models
          Party, Neutral
Decade    1950s-2020s, Unknown                     Original release year
Duration  Under 10 min, Over 10 min                Stream length
```

All single-valued. Title, Artist, Album and cover art are kept; every other tag is
cleared.

## Usage

```
tuneup-sanitize <library>    repair titles and artists, wipe other tags
tuneup-tag <library>         write the five tags
```

Sanitize first — the tagger reads Title and Artist as text to decide Language.

Both default to a dry run and write a JSON report to `.tuneup/` in the library. Review
it, then re-run with `--apply`.

```
pip install -e .                          # sanitizer, runs natively on Windows
docker compose build                      # tagger, needs Essentia

tuneup-sanitize "D:\Music"
tuneup-sanitize "D:\Music" --apply --backup-confirmed

set TUNEUP_LIBRARY=D:\Music
docker compose run --rm tuneup /library --apply
```

`--apply` on the sanitizer also requires `--backup-confirmed`. The wipe is
irreversible.

Other flags: `--limit N` for a trial run, `--no-audio` to skip Essentia (Language,
Decade and Duration only), `--fetch-missing-art` to look up covers online.

`.tuneup/` holds `report.json` (title and artist changes), `artists.json` (the
spelling map), `harvest.json` (pre-wipe audit record) and `tags.json`.

## Which half of a filename is the artist

Downloads use both `Artist - Title` and `Title - Artist`, so it is decided per file:

```
1. the embedded artist tag matches one half
2. one half is production junk ("Official MV")
3. artist pool - which half does the rest of the library know as an artist
4. an unbracketed "feat." or "x" credit marker
5. otherwise assume Artist - Title
```

Step 3 carries most of the work: artists repeat across a library and titles do not.
Combined credits are split, so `Nguyen Hai Phong, Pmar` also vouches for
`Nguyen Hai Phong` alone. Every choice is recorded as `artist_source` in the report.

## Configuration

`src/tuneup/config.py` — `DISCOGS_PARENT_TO_GENRE` shapes the taxonomy,
`GENRE_ARTIST_OVERRIDES` assigns genres the Discogs model cannot produce (Bolero,
Nhạc Trữ Tình), and the confidence thresholds live there.

## Limits

- Bolero and Nhạc Trữ Tình are not in the Discogs taxonomy; assign them by artist.
- A Vietnamese title with no tone marks carries no language signal. It is filled from
  the artist's other tracks when those agree, otherwise it falls back to English.
- A file with no year anywhere becomes `Unknown`. Audio-based era estimation is not
  reliable enough to use.
- A one-off artist in a `Title - Artist` filename can stay swapped when nothing in the
  library corroborates it. Look for `artist_source: filename` in the report.
- Filenames with no separators cannot be repaired.
- Ogg and Opus lose cover art on rewrite. MP3, FLAC and M4A keep it.
- Artist casing is never changed — `BTS` and `ABBA` write their own names.

## The container

`essentia-tensorflow` bundles a full TensorFlow runtime, so the image is ~1.3 GB —
574 MB of that is TensorFlow, the eight models are 23 MB. Essentia has no Windows
wheels, which is why the tagger runs in Docker while the sanitizer runs natively.
