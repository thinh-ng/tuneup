"""Essentia inference for genre, mood and the instrumental check.

Every classification head here reads its class labels from the model's
companion JSON rather than hardcoding an order, so a model update cannot
silently swap two labels.

Essentia is an optional dependency: it has no Windows wheels, so this module
is expected to run inside the project's Linux container.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import (
    ANALYSIS_RESAMPLE_QUALITY,
    ANALYSIS_SAMPLE_RATE,
    DEFAULT_GENRE,
    DEFAULT_MOOD,
    DISCOGS_PARENT_TO_GENRE,
    EMBEDDING_MODEL,
    EMBEDDING_OUTPUT_NODE,
    GENRE_CONFIDENCE,
    GENRE_INPUT_NODE,
    GENRE_MODEL,
    GENRE_OUTPUT_NODE,
    HEAD_OUTPUT_NODE,
    MOOD_MODELS,
    VOICE_MODEL,
    model_path,
)
from .errors import AnalysisUnavailable, ModelUnavailable, UnreadableAudio

log = logging.getLogger(__name__)

DISCOGS_LABEL_SEPARATOR = "---"
NEGATIVE_LABEL_PREFIX = "non_"


@dataclass(frozen=True)
class AudioVerdict:
    """What the models concluded about one file."""

    genre: str
    mood: str
    instrumental_confidence: float


def _load_labels(name: str) -> list[str]:
    path = model_path(name, ".json")
    if not path.exists():
        raise ModelUnavailable(f"missing label metadata {str(path)!r}")
    metadata = json.loads(path.read_text(encoding="utf-8"))
    classes = metadata.get("classes")
    if not classes:
        raise ModelUnavailable(f"{str(path)!r} declares no classes")
    return list(classes)


def _graph(name: str) -> str:
    path = model_path(name, ".pb")
    if not path.exists():
        raise ModelUnavailable(f"missing model graph {str(path)!r}")
    return str(path)


def _positive_index(labels: list[str], hint: str) -> int:
    """Return the index of the affirmative class in a two-class head.

    Matches ``hint`` against the label text first, then falls back to the
    naming convention where Essentia calls the negative class ``non_<name>``.
    """
    wanted = hint.casefold()
    for index, label in enumerate(labels):
        lowered = label.casefold()
        if lowered == wanted or lowered.endswith(f"_{wanted}"):
            if not lowered.startswith(NEGATIVE_LABEL_PREFIX):
                return index
    for index, label in enumerate(labels):
        if not label.casefold().startswith(NEGATIVE_LABEL_PREFIX):
            return index
    raise ModelUnavailable(f"no affirmative class among {labels!r}")


def _instrumental_index(labels: list[str]) -> int:
    for index, label in enumerate(labels):
        if "instrumental" in label.lower():
            return index
    raise ModelUnavailable(f"no instrumental class among {labels!r}")


class Analyzer:
    """Holds the loaded Essentia graphs for the lifetime of one tagging run.

    Loading the graphs is the expensive part, so one instance is reused across
    the whole library rather than rebuilt per file.

    Essentia's per-frame network warnings are silenced on construction; they
    fire once per audio frame and would bury the run's own output.
    """

    def __init__(self) -> None:
        try:
            import essentia
            import numpy
            from essentia.standard import (
                MonoLoader,
                TensorflowPredict2D,
                TensorflowPredictEffnetDiscogs,
            )
        except ImportError as exc:
            raise AnalysisUnavailable(
                "essentia-tensorflow is not installed; run the tagger in the "
                "tuneup container"
            ) from exc

        essentia.log.warningActive = False
        self._numpy = numpy
        self._loader = MonoLoader
        self._embeddings = TensorflowPredictEffnetDiscogs(
            graphFilename=_graph(EMBEDDING_MODEL), output=EMBEDDING_OUTPUT_NODE
        )
        self._genre = TensorflowPredict2D(
            graphFilename=_graph(GENRE_MODEL),
            input=GENRE_INPUT_NODE,
            output=GENRE_OUTPUT_NODE,
        )
        self._genre_labels = _load_labels(GENRE_MODEL)
        self._voice = TensorflowPredict2D(
            graphFilename=_graph(VOICE_MODEL), output=HEAD_OUTPUT_NODE
        )
        self._voice_index = _instrumental_index(_load_labels(VOICE_MODEL))
        self._moods = {}
        for mood, name in MOOD_MODELS.items():
            head = TensorflowPredict2D(
                graphFilename=_graph(name), output=HEAD_OUTPUT_NODE
            )
            positive = _positive_index(_load_labels(name), mood)
            self._moods[mood] = (head, positive)
        log.info("loaded %d Essentia graphs", len(self._moods) + 3)

    def analyse(self, path: Path) -> AudioVerdict:
        """Return the genre, mood and instrumental confidence for one file.

        Raises UnreadableAudio when Essentia cannot decode the file.
        """
        embeddings = self._embed(path)
        if len(embeddings) == 0:
            raise UnreadableAudio(f"{str(path)!r} produced no audio frames")
        try:
            return self._verdict(embeddings)
        except RuntimeError as exc:
            raise UnreadableAudio(f"{str(path)!r}: {exc}") from exc

    def _verdict(self, embeddings) -> AudioVerdict:
        return AudioVerdict(
            genre=self._predict_genre(embeddings),
            mood=self._predict_mood(embeddings),
            instrumental_confidence=self._predict_instrumental(embeddings),
        )

    def _embed(self, path: Path):
        try:
            audio = self._loader(
                filename=str(path),
                sampleRate=ANALYSIS_SAMPLE_RATE,
                resampleQuality=ANALYSIS_RESAMPLE_QUALITY,
            )()
        except RuntimeError as exc:
            raise UnreadableAudio(f"essentia could not decode {str(path)!r}") from exc
        if len(audio) == 0:
            raise UnreadableAudio(f"{str(path)!r} decoded to an empty buffer")
        try:
            return self._embeddings(audio)
        except RuntimeError as exc:
            raise UnreadableAudio(f"{str(path)!r}: {exc}") from exc

    def _predict_genre(self, embeddings) -> str:
        averaged = self._numpy.mean(self._genre(embeddings), axis=0)
        totals: dict[str, float] = {}
        for label, score in zip(self._genre_labels, averaged, strict=True):
            parent = label.split(DISCOGS_LABEL_SEPARATOR)[0]
            totals[parent] = totals.get(parent, 0.0) + float(score)
        best_parent = max(totals, key=totals.get)
        if not totals[best_parent] >= GENRE_CONFIDENCE:
            return DEFAULT_GENRE
        return DISCOGS_PARENT_TO_GENRE.get(best_parent, DEFAULT_GENRE)

    def _predict_mood(self, embeddings) -> str:
        """Return the highest-scoring mood.

        The five heads are independent yes/no classifiers, so their scores are
        only meaningful against each other. Requiring an absolute confidence
        left a track with five middling scores unlabelled, which says less
        about it than simply naming the one that scored highest.

        Neutral survives only for a degenerate result -- every score absent or
        not a number -- which means the audio told the models nothing at all.
        """
        scores = {}
        for mood, (head, index) in self._moods.items():
            averaged = self._numpy.mean(head(embeddings), axis=0)
            value = float(averaged[index])
            if value == value:
                scores[mood] = value
        if not scores:
            return DEFAULT_MOOD
        return max(scores, key=scores.get)

    def _predict_instrumental(self, embeddings) -> float:
        averaged = self._numpy.mean(self._voice(embeddings), axis=0)
        return float(averaged[self._voice_index])
