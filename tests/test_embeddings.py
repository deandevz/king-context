"""Tests for embedding dependencies."""

import pytest
from packaging import version


class TestEmbeddingDependencies:
    """Tests to verify embedding dependencies are installed."""

    def test_sentence_transformers_can_be_imported(self):
        """Verify sentence-transformers library can be imported."""
        from sentence_transformers import SentenceTransformer

        # Verify the class is available
        assert SentenceTransformer is not None

    def test_sentence_transformers_version(self):
        """Verify sentence-transformers meets minimum version requirement."""
        import sentence_transformers

        installed_version = version.parse(sentence_transformers.__version__)
        minimum_version = version.parse("2.2.0")
        assert installed_version >= minimum_version, (
            f"sentence-transformers version {installed_version} is below minimum {minimum_version}"
        )

    def test_numpy_can_be_imported(self):
        """Verify numpy library can be imported."""
        import numpy as np

        # Verify numpy is functional
        assert np is not None
        # Basic sanity check
        arr = np.array([1, 2, 3])
        assert arr.shape == (3,)

    def test_numpy_version(self):
        """Verify numpy meets minimum version requirement."""
        import numpy as np

        installed_version = version.parse(np.__version__)
        minimum_version = version.parse("1.24.0")
        assert installed_version >= minimum_version, (
            f"numpy version {installed_version} is below minimum {minimum_version}"
        )
