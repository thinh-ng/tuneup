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
Decade and Duration only), `--fetch-missing-art` to look up covers online,
`--lookup-years` to recover missing years from MusicBrainz.

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

## Unknown decades

A year that is not in the file has to come from somewhere else, and on this
library nothing reliable does. Measured on 836 files where 123 had no year:

```
Album siblings agree on a year   0    the yearless files have no album either
Year in the filename             6    5 are false ("The International 2018")
MusicBrainz, unverified          123  fills everything, frequently wrong
MusicBrainz, verified            26   and roughly half of those are wrong too
```

`--lookup-years` exists and is off by default. Do not turn it on expecting
correct years. Spot-checked against tracks whose release year is not in doubt,
it returned 2023 for Daft Punk's *Beyond* (2013), 2005 for Green Day's
*Holiday* (2004), 1992 for *November Rain* (1991) and 1984 for *Piano Man*
(1973).

The cause is structural, not a tuning problem. A MusicBrainz *recording* is one
recorded performance, and a text search matches whichever recording sits on a
reissue, compilation, live album or broadcast. The search response carries only
a partial release list and no `first-release-date`, so there is nothing in the
result that identifies the original release. Filtering by release-group type and
re-querying the recording in full both failed to fix it.

Years recovered this way are marked `year_source: musicbrainz` in the report, so
they can be found and reverted.

What would actually work is audio fingerprinting: AcoustID identifies the exact
recording from the audio rather than guessing from its name. It needs the
`fpcalc` binary and an API key, and it is not wired in.

Many of the 123 have no release year in existence -- they are uploads that were
never commercially released. `Unknown` is the true answer for those.
