from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.retrieval.category_fact_contracts import (
    Capability,
    SourceClass,
)
from app.guide.retrieval.category_profiles import CategoryProfile


_SCHEMA_VERSION = "merchant-ocr-claims-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOCATOR = re.compile(
    r"^urn:xiaoro:merchant-description-ocr:"
    r"pid:[1-9][0-9]*:"
    r"source-sha256:[0-9a-f]{64}:"
    r"record-sha256:[0-9a-f]{64}$"
)
_HYPE = re.compile(
    r"(?:NO\.?\s*1|爆款|直播间|领券|百亿补贴|立即抢购|明星同款)",
    re.IGNORECASE,
)


class MerchantClaimAssetIntegrityError(RuntimeError):
    pass


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MerchantClaim(_StrictFrozenModel):
    claim_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_id: int = Field(gt=0)
    category_profile: CategoryProfile
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    normalized_value: str = Field(min_length=1, max_length=128)
    display_claim: str = Field(min_length=1, max_length=160)
    claim_scope: Literal["ordinary", "safety_transcript"]
    source_class: Literal[
        SourceClass.MERCHANT_DESCRIPTION_OCR
    ] = SourceClass.MERCHANT_DESCRIPTION_OCR
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: str = Field(min_length=1, max_length=512)
    review_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_rationale: str = Field(min_length=1, max_length=512)
    capabilities: frozenset[Capability]

    @field_validator("category_profile", mode="before")
    @classmethod
    def parse_profile(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return CategoryProfile(value)
            except ValueError:
                return value
        return value

    @field_validator("source_class", mode="before")
    @classmethod
    def parse_source_class(cls, value: object) -> object:
        if value == SourceClass.MERCHANT_DESCRIPTION_OCR.value:
            return SourceClass.MERCHANT_DESCRIPTION_OCR
        return value

    @field_validator("capabilities", mode="before")
    @classmethod
    def freeze_capabilities(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @model_validator(mode="after")
    def validate_claim(self) -> Self:
        if _LOCATOR.fullmatch(self.source_locator) is None:
            raise ValueError("merchant claim source locator is invalid")
        if _HYPE.search(self.display_claim):
            raise ValueError("merchant claim contains hype-only text")
        if self.claim_scope == "ordinary":
            if (
                not {"evidence", "display"} <= self.capabilities
                or "hard_filter" in self.capabilities
            ):
                raise ValueError("ordinary merchant claim capabilities are invalid")
        elif self.capabilities != frozenset({"evidence", "display"}):
            raise ValueError("safety transcript capabilities are invalid")
        if (
            self.claim_scope == "safety_transcript"
            and self.field_key != "safety_claim"
        ):
            raise ValueError("safety transcript requires safety_claim field")
        if self.claim_id != merchant_claim_id(
            self.model_dump(
                mode="json",
                exclude={"claim_id"},
            )
        ):
            raise ValueError("merchant claim ID mismatch")
        return self


class MerchantClaimManifest(_StrictFrozenModel):
    schema_version: Literal[
        "merchant-ocr-claims-v1"
    ] = _SCHEMA_VERSION
    asset_id: Literal[
        "guide-merchant-ocr-claims-v1"
    ] = "guide-merchant-ocr-claims-v1"
    asset_version: str = Field(min_length=1)
    claims_file: str = Field(min_length=1, max_length=255)
    claims_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_count: int = Field(ge=0)
    product_count: int = Field(ge=0)
    source_file_count: int = Field(ge=0)
    source_file_sha256s: tuple[str, ...]
    review_file_count: int = Field(ge=0)
    review_file_sha256s: tuple[str, ...]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "source_file_sha256s",
        "review_file_sha256s",
        mode="before",
    )
    @classmethod
    def freeze_source_hashes(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if (
            self.source_file_sha256s
            != tuple(sorted(set(self.source_file_sha256s)))
            or len(self.source_file_sha256s) != self.source_file_count
            or any(_SHA256.fullmatch(value) is None for value in self.source_file_sha256s)
            or self.review_file_sha256s
            != tuple(sorted(set(self.review_file_sha256s)))
            or len(self.review_file_sha256s) != self.review_file_count
            or any(
                _SHA256.fullmatch(value) is None
                for value in self.review_file_sha256s
            )
        ):
            raise ValueError("merchant claim source hash inventory is invalid")
        return self


class MerchantClaimAssets(_StrictFrozenModel):
    manifest: MerchantClaimManifest
    claims: tuple[MerchantClaim, ...]

    @field_validator("claims", mode="before")
    @classmethod
    def freeze_claims(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


def merchant_claim_id(payload: dict[str, object]) -> str:
    normalized = dict(payload)
    capabilities = normalized.get("capabilities")
    if isinstance(capabilities, (list, tuple, set, frozenset)):
        normalized["capabilities"] = sorted(capabilities)
    return hashlib.sha256(
        _canonical_json(normalized).encode("utf-8")
    ).hexdigest()


def load_merchant_claim_assets(
    *,
    manifest_path: str | Path,
    claims_path: str | Path,
    expected_manifest_sha256: str | None = None,
) -> MerchantClaimAssets:
    manifest_file = Path(manifest_path)
    claims_file = Path(claims_path)
    try:
        manifest_payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MerchantClaimAssetIntegrityError(
            "merchant claim manifest is invalid"
        ) from exc
    if not isinstance(manifest_payload, dict):
        raise MerchantClaimAssetIntegrityError(
            "merchant claim manifest must be an object"
        )
    unsigned = {
        key: value
        for key, value in manifest_payload.items()
        if key != "manifest_sha256"
    }
    actual_manifest_sha = hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()
    if manifest_payload.get("manifest_sha256") != actual_manifest_sha:
        raise MerchantClaimAssetIntegrityError(
            "merchant claim manifest SHA mismatch"
        )
    if (
        expected_manifest_sha256 is not None
        and (
            _SHA256.fullmatch(expected_manifest_sha256) is None
            or actual_manifest_sha != expected_manifest_sha256
        )
    ):
        raise MerchantClaimAssetIntegrityError(
            "merchant claim manifest lock mismatch"
        )
    try:
        manifest = MerchantClaimManifest.model_validate(
            manifest_payload,
            strict=True,
        )
    except ValueError as exc:
        raise MerchantClaimAssetIntegrityError(
            "merchant claim manifest contract is invalid"
        ) from exc
    if manifest.claims_file != claims_file.name:
        raise MerchantClaimAssetIntegrityError(
            "merchant claim claims_file mismatch"
        )
    try:
        claims_bytes = claims_file.read_bytes()
    except OSError as exc:
        raise MerchantClaimAssetIntegrityError(
            "merchant claim JSONL is unavailable"
        ) from exc
    if hashlib.sha256(claims_bytes).hexdigest() != manifest.claims_sha256:
        raise MerchantClaimAssetIntegrityError(
            "merchant claim JSONL SHA mismatch"
        )
    expected_name = f"merchant_claims_v1.{manifest.claims_sha256}.jsonl"
    if claims_file.name != expected_name:
        raise MerchantClaimAssetIntegrityError(
            "merchant claim JSONL is not content addressed"
        )
    claims: list[MerchantClaim] = []
    for line_number, line in enumerate(
        claims_bytes.decode("utf-8").splitlines(),
        start=1,
    ):
        if not line:
            raise MerchantClaimAssetIntegrityError(
                f"blank merchant claim JSONL line {line_number}"
            )
        try:
            claim = MerchantClaim.model_validate_json(line, strict=True)
        except ValueError as exc:
            raise MerchantClaimAssetIntegrityError(
                f"invalid merchant claim line {line_number}"
            ) from exc
        claims.append(claim)
    if (
        len(claims) != manifest.claim_count
        or len({claim.claim_id for claim in claims}) != len(claims)
        or [claim.claim_id for claim in claims]
        != sorted(claim.claim_id for claim in claims)
        or len({claim.product_id for claim in claims})
        != manifest.product_count
        or not {
            claim.source_sha256 for claim in claims
        }.issubset(set(manifest.source_file_sha256s))
    ):
        raise MerchantClaimAssetIntegrityError(
            "merchant claim manifest counts or ordering mismatch"
        )
    return MerchantClaimAssets(manifest=manifest, claims=tuple(claims))


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "MerchantClaim",
    "MerchantClaimAssetIntegrityError",
    "MerchantClaimAssets",
    "MerchantClaimManifest",
    "load_merchant_claim_assets",
    "merchant_claim_id",
]
