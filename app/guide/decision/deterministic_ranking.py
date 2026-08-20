from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Generic, Literal, Mapping, Sequence, TypeVar


T = TypeVar("T", bound=Mapping[str, object])
Direction = Literal["asc", "desc"]
_NUMERIC_ID = re.compile(r"[1-9][0-9]*")


class DeterministicRankingError(ValueError):
    pass


class InvalidProductIdError(DeterministicRankingError):
    pass


class DuplicateProductIdError(DeterministicRankingError):
    pass


@dataclass(frozen=True)
class DeterministicSortResult(Generic[T]):
    items: list[T]
    tie_reason_by_id: dict[int, dict[str, object]]


@dataclass(frozen=True)
class _Prepared(Generic[T]):
    item: T
    product_id: int
    business_key: tuple[object, ...]


def normalize_product_id(item: Mapping[str, object], *, chain: str) -> int:
    raw_values = [
        item[field]
        for field in ("id", "product_id")
        if field in item and item[field] not in (None, "")
    ]
    if not raw_values:
        raise InvalidProductIdError(f"{chain}: missing product ID")

    normalized = [
        _normalize_raw_product_id(value, chain=chain)
        for value in raw_values
    ]
    if len(set(normalized)) != 1:
        raise InvalidProductIdError(
            f"{chain}: conflicting id/product_id values {raw_values!r}"
        )
    return normalized[0]


def _normalize_raw_product_id(value: object, *, chain: str) -> int:
    if isinstance(value, bool):
        raise InvalidProductIdError(
            f"{chain}: boolean product ID is invalid"
        )
    if isinstance(value, int):
        product_id = value
    elif isinstance(value, str) and _NUMERIC_ID.fullmatch(value.strip()):
        text = value.strip()
        product_id = int(text)
        if str(product_id) != text:
            raise InvalidProductIdError(
                f"{chain}: ambiguous product ID {value!r}"
            )
    else:
        raise InvalidProductIdError(
            f"{chain}: invalid product ID {value!r}"
        )

    if product_id <= 0:
        raise InvalidProductIdError(
            f"{chain}: invalid product ID {value!r}"
        )
    return product_id


def sort_product_candidates(
    items: Sequence[T],
    *,
    business_key: Callable[[T], tuple[object, ...]],
    directions: Sequence[Direction],
    business_key_names: Sequence[str],
    chain: str,
) -> DeterministicSortResult[T]:
    if len(directions) != len(business_key_names):
        raise DeterministicRankingError(
            f"{chain}: directions and business_key_names differ"
        )

    prepared: list[_Prepared[T]] = []
    seen_ids: set[int] = set()
    for item in items:
        product_id = normalize_product_id(item, chain=chain)
        if product_id in seen_ids:
            raise DuplicateProductIdError(
                f"{chain}: duplicate product ID {product_id}"
            )
        seen_ids.add(product_id)

        keys = tuple(business_key(item))
        if len(keys) != len(directions):
            raise DeterministicRankingError(
                f"{chain}: business key width {len(keys)} "
                f"!= {len(directions)}"
            )
        prepared.append(_Prepared(item, product_id, keys))

    try:
        prepared.sort(key=lambda row: row.product_id)
        for index in reversed(range(len(directions))):
            prepared.sort(
                key=lambda row, field=index: row.business_key[field],
                reverse=directions[index] == "desc",
            )
    except TypeError as exc:
        raise DeterministicRankingError(
            f"{chain}: incomparable business key"
        ) from exc

    tie_reason_by_id: dict[int, dict[str, object]] = {}
    start = 0
    while start < len(prepared):
        end = start + 1
        while (
            end < len(prepared)
            and prepared[end].business_key == prepared[start].business_key
        ):
            end += 1

        group = prepared[start:end]
        if len(group) > 1:
            tied_ids = sorted(row.product_id for row in group)
            reason: dict[str, object] = {
                "kind": "product_id",
                "chain": chain,
                "business_keys": list(business_key_names),
                "direction": "ascending",
                "selected_product_id": tied_ids[0],
                "tied_product_ids": tied_ids,
            }
            for row in group:
                tie_reason_by_id[row.product_id] = dict(reason)
        start = end

    return DeterministicSortResult(
        items=[row.item for row in prepared],
        tie_reason_by_id=tie_reason_by_id,
    )
