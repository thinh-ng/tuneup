"""Domain exceptions raised across the tuneup pipelines."""


class TuneupError(Exception):
    """Base class for every failure this package raises deliberately."""


class UnsupportedContainer(TuneupError):
    """The file extension has no adapter in :mod:`tuneup.audiofile`."""


class UnreadableAudio(TuneupError):
    """The file exists but mutagen could not parse it as audio."""


class HarvestMissing(TuneupError):
    """The tagger was asked to run before the sanitizer wrote its snapshot."""


class ModelUnavailable(TuneupError):
    """An Essentia model or its label metadata is absent from the model dir."""


class AnalysisUnavailable(TuneupError):
    """Essentia is not importable, so audio analysis cannot run."""
