# tuneup

Repairs and re-tags a personal music library without using an LLM and without
sending anything anywhere. Every decision is a Unicode rule, a lookup table, or
a fixed audio model, so the same library produces the same tags on every run.

Built for a library that a commercial auto-tagger has already damaged: wrong
titles, inconsistent artist spellings, and a genre taxonomy that has no room for
regional categories.

## The five tags

```
Tag       Values                              Source
--------  ----------------------------------  ---------------------------------
Language  Vietnamese, English, Chinese,        Unicode script blocks and
          Korean, Japanese, Instrumental,      Vietnamese diacritics in the
          Other                                title, with artist-level fill-in
Genre     16 fixed values, including Bolero    Essentia Discogs-EffNet,
          and Nhac Tru Tinh                    collapsed by parent genre
Mood      Happy, Sad, Relaxed, Aggressive,     Essentia mood models,
          Party                                highest-confidence winner
Decade    1950s to 2020s, Unknown              Original-release year if present,
                                               else the pressing year
Duration  Under 10 min, Over 10 min            Stream length
```

Every tag is single-valued. Title, Artist, Album and cover art are preserved as
identity metadata; everything else is cleared.

## Two scripts, in order

```
tuneup-sanitize   repair titles, unify artist spellings, wipe every other tag
tuneup-tag        write the five browsing tags
```

The sanitizer must run first. The tagger reads Title and Artist as text to
decide Language, so it needs those fields repaired before it runs.

## Which half of the filename is the artist

Downloaded filenames use both orders. Western rips are ``Artist - Title``;
Vietnamese, Chinese and Korean ones are just as often ``Title - Artist``. The
sanitizer decides per file, using the strongest evidence available, in order:

```
1. embedded artist matches one half        -> that half is the artist
2. one half is production junk             -> the other half is the title
3. artist pool: which half does the rest
   of the library know as an artist?       -> the better-known half wins
4. unbracketed "feat." / "ft." marker      -> that half is the artist
5. nothing decided it                      -> assume Artist - Title
```

Step 3 is the useful one. Artists repeat across a library and song titles do
not, so a name seen in an artist tag anywhere, or on one side of a dashed
filename more than once, is evidence. Combined credits are split, so
``Nguyen Hai Phong, Pmar`` also vouches for ``Nguyen Hai Phong`` alone.

Step 4 sits below step 3 deliberately: both ``Artist - Title feat. Guest`` and
``Title - Artist feat. Guest`` are common, so the marker only decides when
nothing better has. A ``(feat. ...)`` inside brackets is part of a title and is
ignored here.

The report records an ``artist_source`` per file, so every decision is
reviewable before you apply anything.

## Why the sanitizer keeps the year

Clearing all metadata would destroy the release year, and Decade cannot be
recovered from audio. The sanitizer therefore harvests the year and writes it
back with the identity tags. It prefers the *original* release year (`TDOR` /
`TORY` / `ORIGINALDATE`) over the pressing date, so a 2015 remaster of a 1968
song is filed under the 1960s rather than the 2010s.

Files whose two year fields disagree by more than five years are flagged
`looks_like_reissue` in the report, because those are the ones most likely to
have been misfiled already.

## Install

The sanitizer runs natively on Windows; only the tagger needs Essentia, which
has no Windows wheels.

```
pip install -e .              # sanitizer, native
docker compose build          # tagger, ~1.3 GB
```

The image is large because `essentia-tensorflow` bundles a complete
TensorFlow runtime:

```
essentia_tensorflow.libs   574 MB   bundled TensorFlow shared libraries
numpy (+ numpy.libs)        73 MB
essentia                    40 MB
the 8 models                23 MB
python:3.11-slim base      ~150 MB
```

The models are the small part. Nothing here is removable while inference runs
on TensorFlow; Essentia publishes ONNX copies of these same models, which
would cut the bulk, but that is a different inference path than the one this
code uses.

## Use

Both commands default to a dry run and write a JSON report into `.tuneup/`
inside the library. Review the report, then re-run with `--apply`.

```
tuneup-sanitize "D:\Music"
tuneup-sanitize "D:\Music" --apply --backup-confirmed

set TUNEUP_LIBRARY=D:\Music
docker compose run --rm tuneup /library
docker compose run --rm tuneup /library --apply
```

`--apply` on the sanitizer also requires `--backup-confirmed`. The wipe is
irreversible; back the library up first.

Useful flags:

```
--limit N              tag only the first N files, for a trial run
--no-audio             skip Essentia; produces Language, Decade and Duration only
--fetch-missing-art    look up cover art for files that have none (sanitizer)
```

## What lands in `.tuneup/`

```
report.json    per-file title and artist changes the sanitizer made
artists.json   the spelling-to-canonical map it used
harvest.json   every field as it was before the wipe, for rollback
tags.json      the five tags the tagger resolved per file
```

## Tuning it

`src/tuneup/config.py` holds everything you would want to change:

- `GENRES` and `DISCOGS_PARENT_TO_GENRE` — the genre list and how the model's
  400 Discogs styles collapse into it
- `GENRE_ARTIST_OVERRIDES` — force a genre for specific artists; this is how
  Bolero and Nhạc Trữ Tình get assigned, since the Discogs taxonomy has no
  equivalent
- `DURATION_SPLIT_SECONDS`, `MOOD_CONFIDENCE`, `INSTRUMENTAL_CONFIDENCE`

## Known limits

- **Bolero and Nhạc Trữ Tình are not in the Discogs taxonomy.** The audio model
  cannot produce them. Use `GENRE_ARTIST_OVERRIDES` to assign them by artist.
- **A Vietnamese title typed without tone marks carries no language signal.**
  The tagger fills these in from the artist's other tracks when those agree; an
  artist with no diacritics anywhere falls back to English.
- **Only the five languages actually in the library are detected.** Latin text
  with no Vietnamese tone marks yields no verdict rather than a guess, because
  no accent set separates the rest reliably enough to be worth a wrong answer.
- **A one-off artist in a ``Title - Artist`` filename can stay swapped.** If
  the artist appears nowhere else in the library, carries no usable artist
  tag, and the filename has no ``feat.`` or ``x`` credit marker, nothing
  deterministic distinguishes the two halves. These show up in the report with
  ``artist_source: filename``.
- **Filenames with no separators cannot be repaired.** A stem such as
  ``LanhLeoTamSinhTamTheThapLyDaoHoaOst-AskaYang`` has no word boundaries to
  work from and is left as it is.
- **Truncated downloads are flagged, not fixed.** A file whose stream reports
  zero length is logged as probably truncated and gets no duration tag.
- **A file with no year anywhere becomes `Unknown`.** There is no deterministic
  way to recover it, and audio-based era estimation is not reliable enough to
  use.
- **Ogg and Opus cover art is dropped** on rewrite. FLAC, MP3 and M4A keep it.
- **Genre is left untouched when audio analysis does not run.** A ``--no-audio``
  pass writes Language, Decade and Duration only, rather than stamping every
  file with a placeholder genre.
