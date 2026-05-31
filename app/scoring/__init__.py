"""Scoring layer — composite score + signal tags from a metrics-filled row."""

from app.scoring.score import compute_score, derive_signals, score_row

__all__ = ["compute_score", "derive_signals", "score_row"]
