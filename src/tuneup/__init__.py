"""Deterministic repair and tagging for a personal music library.

Layering, lowest first. A module never imports one above it.

    config      constants and pure resolution functions
    errors      domain exceptions
    track       dataclasses shared by both pipelines
    audiofile   mutagen adapters for MP3, FLAC and MP4 containers
    artists     artist name clustering and canonical selection
    titles      title repair rules
    harvest     pre-wipe snapshot of existing metadata
    sanitize    CLI: repair titles and artists, wipe the rest
    language    script and diacritic based language detection
    analysis    Essentia inference for genre, mood and instrumental
    tag         CLI: write the five classification tags

Decade and duration are pure functions on a year and a length, so they live in
``config`` beside the thresholds that define them rather than in modules of
their own.
"""
