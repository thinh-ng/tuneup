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
          Japanese, Spanish, French, German,       diacritics in title/artist,
          Italian, Hindi, Hebrew, Lao,             then a per-track override
          Instrumental
Genre     15 fixed values, incl. Bolero and        Essentia Discogs-EffNet
          Nhạc Trữ Tình                            scored by strongest style
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

`src/tuneup/config.py` — `DISCOGS_PARENT_TO_GENRE` shapes the taxonomy and
`DISCOGS_STYLE_TO_GENRE` overrides it for a style whose parent would send it to the
wrong genre. `GENRE_ARTIST_OVERRIDES` assigns genres the Discogs model cannot
produce (Bolero, Nhạc Trữ Tình). `LANGUAGE_TRACK_OVERRIDES` and
`GENRE_TRACK_OVERRIDES` are keyed `artist - title`, for a catalogue that crosses
languages or repertoires: Andrea Bocelli records in Italian, Spanish and English,
and no artist-level entry can say that. The confidence thresholds live there too.

## Limits

- Bolero and Nhạc Trữ Tình are not in the Discogs taxonomy; assign them by artist.
  They mean the Vietnamese repertoires only. Discogs has its own `Latin---Bolero`
  style for the Cuban and Spanish form, and that goes to Folk: the two share an
  ancestor rhythm and nothing else.
  Check the artist against a pre-1975 or hải ngoại discography before adding one:
  Hoàng Trang, for instance, is both a nhạc vàng composer and a modern indie singer,
  and only the track list says which one a file holds.
- A Vietnamese title with no tone marks carries no language signal. It is filled from
  the artist's other tracks when those agree, otherwise it falls back to English.
- A file with no year anywhere becomes `Unknown`. Audio-based era estimation is not
  reliable enough to use.
- A one-off artist in a `Title - Artist` filename can stay swapped when nothing in the
  library corroborates it. Look for `artist_source: filename` in the report.
- Filenames with no separators cannot be repaired.
- Ogg and Opus lose cover art on rewrite. MP3, FLAC and M4A keep it.
- A download that captured the metadata and cover art but none of the audio still
  tags cleanly. Such a file is tagged, then named in a warning at the end of the
  run and flagged `looks_empty` in `tags.json`, because on disk it looks the
  right size -- almost all of it is the embedded image.
- Genre is a claim about how a recording sounds, so it holds no region or language
  labels. Discogs' `Latin` parent collapses 35 styles from mariachi to reggaeton
  into one bucket that only says the singer was Latin American, which the Language
  tag already records; it maps to Folk, and Reggaeton, MPB and Bossanova are named
  individually.
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

## How a language is decided

Three sources, strongest first. A weaker one only fills what the stronger ones
left empty, and never overrides them.

```
1. Script and diacritics in the title   decisive, never wrong
2. Other tracks by the same performers  strong; evidence is gathered per
                                        performer, so a track credited to four
                                        rappers inherits from any of them
3. The artist's country (--lookup-languages)   weak, opt-in
```

Step 3 exists for the case the other two cannot reach: a Vietnamese song with an
English title, by artists whose every other track in the library is also
English-titled. It reads the artist's country from MusicBrainz and maps VN, KR,
JP, CN, TW and HK to a language.

Artist search is fuzzy, so the returned name must match exactly before its
country is believed: searching `Lil Wuyn` returns `Lil Wayne` first with a
perfect score, and accepting that would file a Vietnamese rap cypher as
American. Each performer in a credit is looked up separately, since a credit
naming four artists matches no single entry.

Know what step 3 asserts: an English-language song by a Vietnamese artist will
be tagged Vietnamese. That is a judgement about the artist, not the recording.
Leave the flag off if you want the language of the words being sung.

## Filenames with no spaces

Some uploads arrive as `CoChutNgotNgao-UongToLangSilenceWangBY2-3710201.mp3`:
title, artist and an upload id run together with no spaces. Three rules recover
them — strip a trailing numeric id, split a run of words on its capitals, then
promote a bare dash to a separator. The embedded artist tag settles which half is
which, and restores the diacritics the filename dropped.

That last rule is the dangerous one, because a hyphen is far more often part of a
name than a separator. It fires only when all four of these hold:

```
no spaced " - " in the stem   the split point is already known; a second
                              one can only break a name
exactly one bare dash         a separator appears once, but
                              `Spider-Man Across the Spider-Verse` repeats
both sides multi-word         what keeps `Jay-Z` and `BY2` intact
next word opens like a name   romanised `Te-ze` is not a boundary
```

On this library that is one filename in 836. Without the first two conditions it
was nine, and it turned `The All-American Rejects` into an artist called
`The All`, `Anne-Marie` into `Anne - Marie`, and `Sơn Tùng M-TP` into `Son Tung M`
— which then escaped the spelling unifier and split him into two artists.

## The limit

A class of file defeats every rule here: a Chinese song republished with both
its title and its artist transliterated into Vietnamese. `Dap An Cua Ban` by
`A Nhũng (Rong)` is 你的答案 by 阿冗, but nothing in the file says so. Every string
in it is Vietnamese text, so the language detector calls it Vietnamese or
English, and MusicBrainz indexes the artist only under 阿冗, which the file does
not contain. There is no signal to find.

Audio fingerprinting (AcoustID) is the answer to this and to most of the
remaining unknown years, because it identifies a recording from the audio and
never sees the text at all. It needs the `fpcalc` binary and an API key.
