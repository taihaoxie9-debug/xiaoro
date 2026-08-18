from itertools import permutations

import pytest

from app.guide.decision.deterministic_ranking import (
    DuplicateProductIdError,
    InvalidProductIdError,
    sort_product_candidates,
)


def _item(product_id, score=10.0, price=100.0):
    return {"id": product_id, "score": score, "price": price}


def test_equal_business_keys_use_numeric_product_id_for_every_permutation():
    candidates = [_item(10), _item(2), _item(7)]

    outputs = {
        tuple(
            item["id"]
            for item in sort_product_candidates(
                permutation,
                business_key=lambda item: (item["score"],),
                directions=("desc",),
                business_key_names=("score",),
                chain="kernel_test",
            ).items
        )
        for permutation in permutations(candidates)
    }

    assert outputs == {(2, 7, 10)}


def test_mixed_business_directions_precede_product_id():
    result = sort_product_candidates(
        [
            _item(9, score=90, price=120),
            _item(4, score=90, price=100),
            _item(2, score=90, price=100),
            _item(1, score=80, price=1),
        ],
        business_key=lambda item: (item["score"], item["price"]),
        directions=("desc", "asc"),
        business_key_names=("score", "price"),
        chain="kernel_test",
    )

    assert [item["id"] for item in result.items] == [2, 4, 9, 1]
    assert result.tie_reason_by_id[2] == {
        "kind": "product_id",
        "chain": "kernel_test",
        "business_keys": ["score", "price"],
        "direction": "ascending",
        "selected_product_id": 2,
        "tied_product_ids": [2, 4],
    }
    assert 9 not in result.tie_reason_by_id


@pytest.mark.parametrize(
    "bad_id",
    [None, "", True, False, 0, -1, "01", "2.0", "abc"],
)
def test_invalid_product_id_fails_closed(bad_id):
    with pytest.raises(InvalidProductIdError, match="kernel_test"):
        sort_product_candidates(
            [_item(bad_id)],
            business_key=lambda item: (item["score"],),
            directions=("desc",),
            business_key_names=("score",),
            chain="kernel_test",
        )


def test_conflicting_id_and_product_id_fails_closed():
    with pytest.raises(InvalidProductIdError, match="conflicting"):
        sort_product_candidates(
            [{"id": 2, "product_id": 3, "score": 1}],
            business_key=lambda item: (item["score"],),
            directions=("desc",),
            business_key_names=("score",),
            chain="kernel_test",
        )


def test_duplicate_product_id_fails_instead_of_keeping_first_input():
    with pytest.raises(DuplicateProductIdError, match="product ID 2"):
        sort_product_candidates(
            [_item(2), {**_item(2), "name": "conflict"}],
            business_key=lambda item: (item["score"],),
            directions=("desc",),
            business_key_names=("score",),
            chain="kernel_test",
        )
