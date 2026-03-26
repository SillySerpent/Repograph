"""Unit tests for confidence scoring."""
from __future__ import annotations

import math
import pytest
from repograph.core.confidence import geometric_mean_confidence, path_confidence


class TestGeometricMeanConfidence:
    def test_empty_returns_zero(self):
        assert geometric_mean_confidence([]) == 0.0

    def test_single_value(self):
        assert geometric_mean_confidence([0.9]) == pytest.approx(0.9)

    def test_uniform_values(self):
        assert geometric_mean_confidence([0.8, 0.8, 0.8]) == pytest.approx(0.8)

    def test_more_conservative_than_arithmetic(self):
        values = [1.0, 0.9, 0.7, 0.9, 0.8]
        arith = sum(values) / len(values)
        geom = geometric_mean_confidence(values)
        assert geom < arith  # geometric is more conservative

    def test_weak_link_penalty(self):
        # One weak confidence pulls down the whole pathway
        high = geometric_mean_confidence([1.0, 1.0, 1.0, 1.0])
        with_weak = geometric_mean_confidence([1.0, 1.0, 1.0, 0.3])
        assert with_weak < high
        assert with_weak < 0.75

    def test_all_ones(self):
        assert geometric_mean_confidence([1.0, 1.0, 1.0]) == pytest.approx(1.0)

    def test_known_value(self):
        # geometric mean of [1.0, 0.9, 0.7, 0.9, 0.8] ≈ 0.848
        result = geometric_mean_confidence([1.0, 0.9, 0.7, 0.9, 0.8])
        expected = (1.0 * 0.9 * 0.7 * 0.9 * 0.8) ** (1 / 5)
        assert result == pytest.approx(expected, rel=0.001)
