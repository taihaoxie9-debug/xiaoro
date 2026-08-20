"""Extract bounded evidence from real saved Tmall and JD product pages."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Literal
from urllib.parse import urlsplit


_DIGITS = re.compile(r"^[0-9]+$")
_TMALL_ASSIGNMENT = "var b"
_HTML_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_JD_PARAMETER_GROUP_CLASSES = frozenset(
    {
        "specification-group",
        "specification-series-layout",
    }
)
_JD_PARAMETER_LABEL_CLASSES = frozenset(
    {
        "layout-label",
        "specification-group-label",
    }
)


class SavedPageError(ValueError):
    """Raised when a saved page cannot be bound and parsed safely."""


@dataclass(frozen=True, slots=True)
class SavedReview:
    feed_id: str
    sku_id: str
    content: str


@dataclass(frozen=True, slots=True)
class SavedPageEvidence:
    platform: Literal["tmall", "taobao", "jd"]
    item_id: str
    sku_ids: tuple[str, ...]
    title: str
    parameters: dict[str, tuple[str, ...]]
    reviews: tuple[SavedReview, ...]
    source_sha256: str

    @property
    def review_count(self) -> int:
        return len(self.reviews)


@dataclass(slots=True)
class _TextCapture:
    tag: str
    depth: int
    parts: list[str]


@dataclass(slots=True)
class _JdParameterGroup:
    tag: str
    depth: int
    name: str | None
    values: list[str]


class _SavedPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self._dom_tags: list[str] = []
        self._script_capture: _TextCapture | None = None
        self._parameter_capture: _TextCapture | None = None
        self._ptable_depth: int | None = None
        self._pending_parameter_name: str | None = None
        self._jd_excluded_depth: int | None = None
        self._jd_excluded_tag: str | None = None
        self._jd_product_depth: int | None = None
        self._jd_product_tag: str | None = None
        self._jd_group: _JdParameterGroup | None = None
        self._jd_selected_depth: int | None = None
        self._jd_selected_tag: str | None = None
        self._jd_title_capture: _TextCapture | None = None
        self._jd_parameter_name_capture: _TextCapture | None = None
        self._jd_parameter_value_capture: _TextCapture | None = None
        self._jd_attribute_depth: int | None = None
        self._jd_attribute_tag: str | None = None
        self._jd_attribute_item_depth: int | None = None
        self._jd_attribute_item_tag: str | None = None
        self._jd_attribute_name: str | None = None
        self._jd_attribute_value: str | None = None
        self._jd_attribute_label_pending = False
        self._jd_attribute_value_pending = False
        self.scripts: list[tuple[dict[str, str], str]] = []
        self.parameters: dict[str, list[str]] = {}
        self.jd_item_ids: set[str] = set()
        self.jd_titles: list[str] = []
        self.jd_parameters: dict[str, list[str]] = {}
        self.jd_shape_invalid = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.depth += 1
        normalized_tag = tag.casefold()
        attributes = {
            key.casefold(): value or ""
            for key, value in attrs
        }
        classes = {
            token.casefold()
            for token in attributes.get("class", "").split()
        }
        dom_depth = len(self._dom_tags) + 1
        self._handle_jd_start(
            normalized_tag,
            attributes,
            classes,
            depth=dom_depth,
        )
        if normalized_tag not in _HTML_VOID_ELEMENTS:
            self._dom_tags.append(normalized_tag)
        if self._ptable_depth is None and "ptable" in classes:
            self._ptable_depth = self.depth
        if normalized_tag == "script":
            self._script_capture = _TextCapture(
                tag=normalized_tag,
                depth=self.depth,
                parts=[],
            )
            self._script_attributes = attributes
        if (
            self._ptable_depth is not None
            and normalized_tag in {"dt", "dd", "th", "td"}
        ):
            self._parameter_capture = _TextCapture(
                tag=normalized_tag,
                depth=self.depth,
                parts=[],
            )

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized_tag = tag.casefold()
        attributes = {
            key.casefold(): value or ""
            for key, value in attrs
        }
        classes = {
            token.casefold()
            for token in attributes.get("class", "").split()
        }
        depth = len(self._dom_tags) + 1
        self._handle_jd_start(
            normalized_tag,
            attributes,
            classes,
            depth=depth,
        )
        self._close_jd_element(normalized_tag, depth)

    def handle_data(self, data: str) -> None:
        if self._script_capture is not None:
            self._script_capture.parts.append(data)
        if self._parameter_capture is not None:
            self._parameter_capture.parts.append(data)
        for capture in (
            self._jd_title_capture,
            self._jd_parameter_name_capture,
            self._jd_parameter_value_capture,
        ):
            if capture is not None:
                capture.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        self._close_jd_to(normalized_tag)
        capture = self._parameter_capture
        if (
            capture is not None
            and capture.depth == self.depth
            and capture.tag == normalized_tag
        ):
            value = _normalize_text("".join(capture.parts))
            if normalized_tag in {"dt", "th"}:
                self._pending_parameter_name = value or None
            elif self._pending_parameter_name and value:
                self.parameters.setdefault(
                    self._pending_parameter_name,
                    [],
                ).append(value)
                self._pending_parameter_name = None
            self._parameter_capture = None

        script = self._script_capture
        if (
            script is not None
            and script.depth == self.depth
            and normalized_tag == "script"
        ):
            self.scripts.append(
                (
                    dict(self._script_attributes),
                    "".join(script.parts),
                )
            )
            self._script_capture = None

        if (
            self._ptable_depth is not None
            and self.depth == self._ptable_depth
        ):
            self._ptable_depth = None
            self._pending_parameter_name = None
            self._parameter_capture = None
        self.depth = max(0, self.depth - 1)

    def _handle_jd_start(
        self,
        tag: str,
        attributes: dict[str, str],
        classes: set[str],
        *,
        depth: int,
    ) -> None:
        if (
            tag == "meta"
            and attributes.get("http-equiv", "").casefold()
            == "mobile-agent"
        ):
            item_id = _jd_mobile_item_id(attributes.get("content", ""))
            if item_id is not None:
                self.jd_item_ids.add(item_id)

        if (
            self._jd_excluded_depth is None
            and _jd_excluded_node(attributes, classes)
        ):
            self._jd_excluded_depth = depth
            self._jd_excluded_tag = tag
        if self._jd_excluded_depth is not None:
            return

        self._handle_jd_attribute_start(
            tag,
            attributes,
            classes,
            depth=depth,
        )

        if (
            "sku-title-name" in classes
            and self._jd_title_capture is None
        ):
            self._jd_title_capture = _TextCapture(
                tag=tag,
                depth=depth,
                parts=[],
            )

        if (
            self._jd_product_depth is None
            and "page-right-spec" in classes
        ):
            self._jd_product_depth = depth
            self._jd_product_tag = tag
        elif (
            self._jd_product_depth is not None
            and self._jd_group is None
            and classes.intersection(_JD_PARAMETER_GROUP_CLASSES)
        ):
            self._jd_group = _JdParameterGroup(
                tag=tag,
                depth=depth,
                name=None,
                values=[],
            )

        group = self._jd_group
        if group is None:
            return
        if (
            classes.intersection(_JD_PARAMETER_LABEL_CLASSES)
            and self._jd_parameter_name_capture is None
        ):
            self._jd_parameter_name_capture = _TextCapture(
                tag=tag,
                depth=depth,
                parts=[],
            )
        if (
            "specification-series-item--selected" in classes
            and self._jd_parameter_value_capture is None
        ):
            self._jd_parameter_value_capture = _TextCapture(
                tag=tag,
                depth=depth,
                parts=[],
            )
        if "specification-item-sku--selected" in classes:
            self._jd_selected_depth = depth
            self._jd_selected_tag = tag
        elif (
            self._jd_selected_depth is not None
            and "specification-item-sku-text" in classes
            and self._jd_parameter_value_capture is None
        ):
            self._jd_parameter_value_capture = _TextCapture(
                tag=tag,
                depth=depth,
                parts=[],
            )

    def _handle_jd_attribute_start(
        self,
        tag: str,
        attributes: dict[str, str],
        classes: set[str],
        *,
        depth: int,
    ) -> None:
        if self._jd_attribute_depth is None:
            if "attribute" in classes:
                self._jd_attribute_depth = depth
                self._jd_attribute_tag = tag
            return
        if (
            self._jd_attribute_item_depth is None
            and "item" in classes
        ):
            self._jd_attribute_item_depth = depth
            self._jd_attribute_item_tag = tag
            self._jd_attribute_name = None
            self._jd_attribute_value = None
            self._jd_attribute_label_pending = False
            self._jd_attribute_value_pending = False
            return
        if self._jd_attribute_item_depth is None:
            return
        if "label" in classes:
            self._jd_attribute_label_pending = True
            return
        if "value" in classes:
            self._jd_attribute_value_pending = True
            title = _normalize_text(attributes.get("title", ""))
            if title and self._jd_attribute_value is None:
                self._jd_attribute_value = title
            return
        if "text" in classes:
            title = _normalize_text(attributes.get("title", ""))
            if (
                self._jd_attribute_label_pending
                and title
                and self._jd_attribute_name is None
            ):
                self._jd_attribute_name = title

    def _close_jd_attribute_element(self, tag: str, depth: int) -> None:
        if (
            self._jd_attribute_item_depth == depth
            and self._jd_attribute_item_tag == tag
        ):
            name = self._jd_attribute_name
            value = self._jd_attribute_value
            if name and value:
                self.jd_parameters.setdefault(name, []).append(value)
            self._jd_attribute_item_depth = None
            self._jd_attribute_item_tag = None
            self._jd_attribute_name = None
            self._jd_attribute_value = None
            self._jd_attribute_label_pending = False
            self._jd_attribute_value_pending = False
        if (
            self._jd_attribute_depth == depth
            and self._jd_attribute_tag == tag
        ):
            self._jd_attribute_depth = None
            self._jd_attribute_tag = None

    def _close_jd_to(self, tag: str) -> None:
        try:
            matching_index = len(self._dom_tags) - 1 - (
                self._dom_tags[::-1].index(tag)
            )
        except ValueError:
            return
        for index in range(len(self._dom_tags) - 1, matching_index - 1, -1):
            self._close_jd_element(self._dom_tags[index], index + 1)
        del self._dom_tags[matching_index:]

    def _close_jd_element(self, tag: str, depth: int) -> None:
        self._close_jd_attribute_element(tag, depth)
        title = self._jd_title_capture
        if (
            title is not None
            and title.tag == tag
            and title.depth == depth
        ):
            value = _normalize_text("".join(title.parts))
            if value:
                self.jd_titles.append(value)
            self._jd_title_capture = None

        name = self._jd_parameter_name_capture
        if (
            name is not None
            and name.tag == tag
            and name.depth == depth
        ):
            value = _normalize_text("".join(name.parts))
            if value and self._jd_group is not None:
                if (
                    self._jd_group.name is not None
                    and self._jd_group.name != value
                ):
                    self.jd_shape_invalid = True
                self._jd_group.name = value
            self._jd_parameter_name_capture = None

        parameter_value = self._jd_parameter_value_capture
        if (
            parameter_value is not None
            and parameter_value.tag == tag
            and parameter_value.depth == depth
        ):
            value = _normalize_text("".join(parameter_value.parts))
            if value and self._jd_group is not None:
                self._jd_group.values.append(value)
            self._jd_parameter_value_capture = None

        if (
            self._jd_selected_depth == depth
            and self._jd_selected_tag == tag
        ):
            self._jd_selected_depth = None
            self._jd_selected_tag = None

        group = self._jd_group
        if group is not None and group.tag == tag and group.depth == depth:
            if group.name:
                for value in group.values:
                    self.jd_parameters.setdefault(
                        group.name,
                        [],
                    ).append(value)
            self._jd_group = None
            self._jd_parameter_name_capture = None
            self._jd_parameter_value_capture = None
            self._jd_selected_depth = None
            self._jd_selected_tag = None

        if (
            self._jd_product_depth == depth
            and self._jd_product_tag == tag
        ):
            self._jd_product_depth = None
            self._jd_product_tag = None

        if (
            self._jd_excluded_depth == depth
            and self._jd_excluded_tag == tag
        ):
            self._jd_excluded_depth = None
            self._jd_excluded_tag = None


def extract_saved_page_evidence(
    path: str | Path,
) -> SavedPageEvidence:
    """Parse one stable UTF-8 saved page without using its filename."""

    content = _read_regular_bytes(Path(path))
    return extract_saved_page_evidence_bytes(content)


def extract_saved_page_evidence_bytes(
    content: bytes,
) -> SavedPageEvidence:
    """Parse already-validated saved page bytes."""

    source_sha256 = hashlib.sha256(content).hexdigest()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SavedPageError("saved page must be UTF-8") from exc
    parser = _SavedPageParser()
    try:
        parser.feed(text)
        parser.close()
    except (AssertionError, ValueError) as exc:
        raise SavedPageError("saved page HTML is invalid") from exc

    tmall = _extract_tmall(
        parser.scripts,
        source_sha256=source_sha256,
    )
    if tmall is not None:
        return tmall
    jd = _extract_jd(
        parser.scripts,
        parser.parameters,
        item_ids=parser.jd_item_ids,
        titles=parser.jd_titles,
        dom_parameters=parser.jd_parameters,
        dom_shape_invalid=parser.jd_shape_invalid,
        source_sha256=source_sha256,
    )
    if jd is not None:
        return jd
    raise SavedPageError("saved page item identity could not be bound")


def _extract_tmall(
    scripts: list[tuple[dict[str, str], str]],
    *,
    source_sha256: str,
) -> SavedPageEvidence | None:
    for _, script in scripts:
        payload = _decode_tmall_assignment(script)
        if payload is None:
            continue
        resource = _nested_mapping(
            payload,
            "loaderData",
            "home",
            "data",
            "res",
        )
        if resource is None:
            continue
        item = _mapping(resource.get("item"))
        sku_base = _mapping(resource.get("skuBase"))
        if item is None or sku_base is None:
            raise SavedPageError("Tmall item identity is invalid")
        item_id = _numeric_id(item.get("itemId"), label="Tmall item")
        title = _required_text(item.get("title"), label="Tmall title")
        sku_ids = _tmall_sku_ids(sku_base)
        parameters = _tmall_parameters(resource)
        reviews = _tmall_reviews(resource)
        return SavedPageEvidence(
            platform="tmall",
            item_id=item_id,
            sku_ids=sku_ids,
            title=title,
            parameters=parameters,
            reviews=reviews,
            source_sha256=source_sha256,
        )
    return None


def _decode_tmall_assignment(script: str) -> dict[str, object] | None:
    cursor = 0
    decoder = json.JSONDecoder()
    while True:
        marker = script.find(_TMALL_ASSIGNMENT, cursor)
        if marker < 0:
            return None
        equals = script.find("=", marker + len(_TMALL_ASSIGNMENT))
        if equals < 0:
            return None
        start = equals + 1
        while start < len(script) and script[start].isspace():
            start += 1
        try:
            value, _ = decoder.raw_decode(script, start)
        except json.JSONDecodeError:
            cursor = marker + len(_TMALL_ASSIGNMENT)
            continue
        if isinstance(value, dict):
            return value
        cursor = marker + len(_TMALL_ASSIGNMENT)


def _tmall_sku_ids(sku_base: dict[str, object]) -> tuple[str, ...]:
    raw_skus = sku_base.get("skus")
    if not isinstance(raw_skus, list) or not raw_skus:
        raise SavedPageError("Tmall SKU identity is invalid")
    sku_ids = {
        _numeric_id(
            raw_sku.get("skuId") if isinstance(raw_sku, dict) else None,
            label="Tmall SKU",
        )
        for raw_sku in raw_skus
    }
    return tuple(sorted(sku_ids))


def _tmall_parameters(
    resource: dict[str, object],
) -> dict[str, tuple[str, ...]]:
    plus_view = _mapping(resource.get("plusViewVO"))
    industry = (
        _mapping(plus_view.get("industryParamVO"))
        if plus_view is not None
        else None
    )
    if industry is None:
        return {}
    values: dict[str, list[str]] = {}
    for collection_key in ("basicParamList", "enhanceParamList"):
        records = industry.get(collection_key, [])
        if not isinstance(records, list):
            raise SavedPageError("Tmall parameter list is invalid")
        for record in records:
            if not isinstance(record, dict):
                raise SavedPageError("Tmall parameter record is invalid")
            name = _required_text(
                record.get("propertyName"),
                label="Tmall parameter name",
            )
            for value in _parameter_values(record.get("valueName")):
                values.setdefault(name, []).append(value)
    return _freeze_parameters(values)


def _tmall_reviews(
    resource: dict[str, object],
) -> tuple[SavedReview, ...]:
    rate = _mapping(resource.get("rateVO"))
    if rate is None:
        components = _mapping(resource.get("componentsVO"))
        rate = (
            _mapping(components.get("rateVO"))
            if components is not None
            else None
        )
    group = _mapping(rate.get("group")) if rate is not None else None
    raw_items = group.get("items", []) if group is not None else []
    if not isinstance(raw_items, list):
        raise SavedPageError("Tmall review list is invalid")
    reviews: list[SavedReview] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise SavedPageError("Tmall review record is invalid")
        feed_id = _required_text(
            raw_item.get("feedId"),
            label="Tmall review feed",
        )
        content = _required_text(
            raw_item.get("content"),
            label="Tmall review content",
        )
        raw_sku_id = raw_item.get("skuId", raw_item.get("skuInfo", ""))
        sku_id = (
            str(raw_sku_id)
            if _DIGITS.fullmatch(str(raw_sku_id))
            else ""
        )
        reviews.append(
            SavedReview(
                feed_id=feed_id,
                sku_id=sku_id,
                content=content,
            )
        )
    return tuple(reviews)


def _extract_jd(
    scripts: list[tuple[dict[str, str], str]],
    parameters: dict[str, list[str]],
    *,
    item_ids: set[str],
    titles: list[str],
    dom_parameters: dict[str, list[str]],
    dom_shape_invalid: bool,
    source_sha256: str,
) -> SavedPageEvidence | None:
    products: list[dict[str, object]] = []
    for attributes, script in scripts:
        if attributes.get("type", "").casefold() != "application/ld+json":
            continue
        try:
            payload = json.loads(script)
        except json.JSONDecodeError as exc:
            raise SavedPageError("JD Product JSON-LD is invalid") from exc
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            raw_type = candidate.get("@type")
            types = raw_type if isinstance(raw_type, list) else [raw_type]
            if any(
                isinstance(value, str)
                and value.casefold() == "product"
                for value in types
            ):
                products.append(candidate)
    if products:
        if len(products) != 1:
            raise SavedPageError("JD Product identity is ambiguous")
        product = products[0]
        sku_id = _numeric_id(product.get("sku"), label="JD SKU")
        item_id = _numeric_id(
            product.get("productID", sku_id),
            label="JD item",
        )
        title = _required_text(product.get("name"), label="JD title")
        explicit_parameters = parameters
    else:
        # Current JD pageConfig only carries endpoint configuration.
        if not item_ids:
            return None
        if len(item_ids) != 1:
            raise SavedPageError("JD Product identity is ambiguous")
        normalized_titles = {
            _required_text(value, label="JD title")
            for value in titles
        }
        if len(normalized_titles) != 1 or dom_shape_invalid:
            raise SavedPageError("JD Product structure is ambiguous")
        item_id = next(iter(item_ids))
        sku_id = item_id
        title = next(iter(normalized_titles))
        explicit_parameters = dom_parameters
    return SavedPageEvidence(
        platform="jd",
        item_id=item_id,
        sku_ids=(sku_id,),
        title=title,
        parameters=_freeze_parameters(explicit_parameters),
        reviews=(),
        source_sha256=source_sha256,
    )


def _jd_mobile_item_id(value: str) -> str | None:
    mobile_url = None
    for directive in value.split(";"):
        key, separator, raw_value = directive.strip().partition("=")
        if separator and key.casefold() == "url":
            mobile_url = raw_value.strip()
            break
    if not mobile_url:
        return None
    parsed = urlsplit(mobile_url)
    if parsed.hostname != "item.m.jd.com":
        return None
    parts = PurePosixPath(parsed.path).parts
    if len(parts) < 2 or parts[-2] != "product":
        return None
    filename = parts[-1]
    if not filename.endswith(".html"):
        return None
    item_id = filename.removesuffix(".html")
    if _DIGITS.fullmatch(item_id) is None:
        return None
    return item_id


def _jd_excluded_node(
    attributes: dict[str, str],
    classes: set[str],
) -> bool:
    tokens = set(classes)
    tokens.update(attributes.get("id", "").casefold().split())
    return any(
        token.startswith("comment")
        or token.startswith("recommend")
        or token.startswith("guess")
        for token in tokens
    )


def _parameter_values(value: object) -> tuple[str, ...]:
    raw_values = value if isinstance(value, list) else [value]
    normalized = {
        _required_text(item, label="parameter value")
        for item in raw_values
    }
    return tuple(sorted(normalized))


def _freeze_parameters(
    values: dict[str, list[str]],
) -> dict[str, tuple[str, ...]]:
    return {
        name: tuple(sorted(set(items)))
        for name, items in sorted(values.items())
        if name and items
    }


def _nested_mapping(
    value: object,
    *keys: str,
) -> dict[str, object] | None:
    current = value
    for key in keys:
        mapping = _mapping(current)
        if mapping is None:
            return None
        current = mapping.get(key)
    return _mapping(current)


def _mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return value


def _numeric_id(value: object, *, label: str) -> str:
    normalized = str(value)
    if _DIGITS.fullmatch(normalized) is None:
        raise SavedPageError(f"{label} identity is invalid")
    return normalized


def _required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise SavedPageError(f"{label} is invalid")
    normalized = _normalize_text(value)
    if not normalized:
        raise SavedPageError(f"{label} is invalid")
    return normalized


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _read_regular_bytes(path: Path) -> bytes:
    descriptor = -1
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
            metadata.st_mode
        ):
            raise SavedPageError("saved page must be a regular file")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            raise SavedPageError("saved page must be a stable regular file")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            content = source.read()
        observed = path.lstat()
        if (
            observed.st_dev != metadata.st_dev
            or observed.st_ino != metadata.st_ino
            or observed.st_size != metadata.st_size
            or observed.st_mtime_ns != metadata.st_mtime_ns
        ):
            raise SavedPageError("saved page changed while reading")
        return content
    except SavedPageError:
        raise
    except OSError as exc:
        raise SavedPageError("saved page could not be read") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
