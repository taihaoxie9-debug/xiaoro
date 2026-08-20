from pathlib import Path

import pytest

from app.guide.adapters.state import InMemoryConversationState
from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.seed_product_assets import (
    load_seed_product_assets,
)
from app.guide_runtime.composition import (
    compose_text_recommendation_orchestrator,
)
from tests.guide.semantic_test_port import exact_echo_understanding

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def real_reader() -> CanonicalProductReader:
    canonical = ROOT / "data" / "canonical"
    return CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )


@pytest.fixture
def real_product_assets():
    canonical = ROOT / "data" / "canonical"
    return load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=ROOT,
    )


@pytest.fixture
def conversation_state():
    return InMemoryConversationState()


@pytest.fixture
def orchestrator(
    real_reader,
    real_product_assets,
    conversation_state,
):
    return compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=exact_echo_understanding(),
    )


class BrokenReader:
    product_ids = frozenset({1})

    def get(self, product_id: int):
        raise RuntimeError(f"catalog failed for {product_id}")


@pytest.fixture
def broken_orchestrator(conversation_state):
    return compose_text_recommendation_orchestrator(
        BrokenReader(),
        conversation_state=conversation_state,
        understanding=exact_echo_understanding(),
    )
