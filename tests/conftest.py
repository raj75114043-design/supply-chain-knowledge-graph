import logging
import os

import pytest

os.environ["LLM_PROVIDER"] = "none"
os.environ.setdefault("API_KEYS", "test-key")
logging.disable(logging.INFO)


@pytest.fixture(scope="session")
def b():
    from sckg.pipeline import get_build
    return get_build()
