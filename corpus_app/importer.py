from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from .utils import (
    collapse_spaces,
    declared_xml_encoding,
    local_name,
    new_id,
    normalize_surface,
    ordered_unique,
    phonetic_key,
    xml_id,
)


TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


@dataclass(slots=True)
class DecodedXml:
    text: str
    declared_encoding: str | None
    actual_encoding: str
    warnings: list[str]


class ImportErrorWithContext(Exception):
    pass


class TeiImporter:
    def decode_xml_bytes(self, payload: bytes) -> DecodedXml:
        candidates = ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1251"]
        best: tuple[int, str, str] | None = None
        warnings: list[str] = []

        for encoding in candidates:
            try:
                text = payload.decode(encoding)
            except UnicodeDecodeError:
                continue
            score = 0
            if text.lstrip().startswith("<?xml"):
                score += 40
            if "<TEI" in text[:4000]:
                score += 80
            if 'http://www.tei-c.org/ns/1.0' in text[:4000]:
                score += 80
            score -= text.count("\ufffd") * 50
            if best is None or score > best[0]:
                best = (score, encoding, text)

        if best is None:
            raise ImportErrorWithContext(
                "Не удалось определить кодировку XML. Поддерживаются UTF-8, UTF-16 и CP1251."
            )

        _, actual_encoding, text = best
        declared = declared_xml_encoding(text)
        if declared and declared.lower() != actual_encoding.lower():
            warnings.append(
                f"Обнаружено расхождение кодировки: в декларации указано {declared}, фактически файл читается как {actual_encoding}."
            )
        return DecodedXml(
            text=text,
            declared_encoding=declared,
            actual_encoding=actual_encoding,
            warnings=warnings,
        )

    def import_document(
        self,
        *,
        file_name: str,
        source_bytes: bytes,
        display_name: str | None = None,
        source_label: str | None = None,
    ) -> dict[str, Any]:
        decoded = self.decode_xml_bytes(source_bytes)
        try:
            root = ET.fromstring(decoded.text)
        except ET.ParseError as exc:
            raise ImportErrorWithContext(f"XML разобран не полностью: {exc}") from exc

        title = (
            root.findtext('.//tei:title[@type="main"]', namespaces=TEI_NS)
            or root.findtext(".//tei:title", namespaces=TEI_NS)
            or file_name
        )
        body = root.find(".//tei:text/tei:body", TEI_NS)
        if body is None:
            raise ImportErrorWithContext("В XML-TEI отсутствует обязательный блок text/body.")

        doc_id = new_id("doc")
        sequence = 0
        word_sequence = 0
        state = {"sheet": None, "page": None, "line": 1, "column": 1}
        all_tokens: list[dict[str, Any]] = []
        words: list[dict[str, Any]] = []
        punctuation_buffer: list[dict[str, Any]] = []
        warnings = list(decoded.warnings)

        def collect_surface(node: ET.Element) -> tuple[str, list[dict[str, Any]]]:
            parts: list[str] = []
            breaks: list[dict[str, Any]] = []

            def walk(current: ET.Element) -> None:
                if current.text:
                    parts.append(current.text)
                for child in current:
                    name = local_name(child.tag)
                    if name == "fs":
                        pass
                    elif name in {"lb", "pb", "cb"}:
                        breaks.append({"type": name, "n": child.get("n")})
                    else:
                        walk(child)
                    if child.tail:
                        parts.append(child.tail)

            walk(node)
            return collapse_spaces("".join(parts)), breaks

        def extract_features(word_node: ET.Element) -> dict[str, Any]:
            features: dict[str, Any] = {}
            fs = word_node.find("tei:fs", TEI_NS)
            if fs is None:
                return features
            for feature in fs.findall("tei:f", TEI_NS):
                name = feature.get("name")
                if not name:
                    continue
                values = [symbol.get("value") for symbol in feature.findall("tei:symbol", TEI_NS) if symbol.get("value")]
                if values:
                    features[name] = values if len(values) > 1 else values[0]
            return features

        def push_token(token: dict[str, Any]) -> None:
            nonlocal sequence
            sequence += 1
            token["sequence"] = sequence
            all_tokens.append(token)

        def walk_children(parent: ET.Element) -> None:
            nonlocal word_sequence
            for child in parent:
                name = local_name(child.tag)

                if name == "milestone" and child.get("unit") == "sheet":
                    state["sheet"] = child.get("n")
                    state["column"] = 1
                    continue

                if name == "pb":
                    state["page"] = child.get("n")
                    state["line"] = 1
                    state["column"] = 1
                    continue

                if name == "lb":
                    state["line"] += 1
                    continue

                if name == "cb":
                    state["column"] += 1
                    continue

                if name == "pc":
                    text, embedded_breaks = collect_surface(child)
                    token = {
                        "token_id": xml_id(child.attrib) or new_id("pc"),
                        "kind": "pc",
                        "text": text,
                        "raw_xml_id": xml_id(child.attrib),
                        "sheet": state["sheet"],
                        "page": state["page"],
                        "line": state["line"],
                        "column": state["column"],
                        "type": child.get("type"),
                        "embedded_breaks": embedded_breaks,
                    }
                    push_token(token)
                    if text and (child.get("type") != "space") and text.strip():
                        punctuation_buffer.append(token)
                    for br in embedded_breaks:
                        if br["type"] == "pb":
                            state["page"] = br.get("n") or state["page"]
                            state["line"] = 1
                            state["column"] = 1
                        elif br["type"] == "lb":
                            state["line"] += 1
                        elif br["type"] == "cb":
                            state["column"] += 1
                    continue

                if name == "w":
                    text, embedded_breaks = collect_surface(child)
                    features = extract_features(child)
                    lemma = child.get("lemma")
                    word_sequence += 1
                    word = {
                        "token_id": xml_id(child.attrib) or new_id("w"),
                        "kind": "w",
                        "text": text,
                        "sequence": word_sequence,
                        "sheet": state["sheet"],
                        "page": state["page"],
                        "line": state["line"],
                        "column": state["column"],
                        "lemma": lemma,
                        "features": features,
                        "leading_punctuation": [item["text"] for item in punctuation_buffer if item.get("text")],
                        "leading_punctuation_ids": [item["token_id"] for item in punctuation_buffer],
                        "embedded_breaks": embedded_breaks,
                        "normalized": normalize_surface(text or lemma or ""),
                        "phonetic": phonetic_key(text or lemma or ""),
                    }
                    punctuation_buffer.clear()
                    push_token(word | {"raw_xml_id": xml_id(child.attrib)})
                    words.append(word)
                    for br in embedded_breaks:
                        if br["type"] == "pb":
                            state["page"] = br.get("n") or state["page"]
                            state["line"] = 1
                            state["column"] = 1
                        elif br["type"] == "lb":
                            state["line"] += 1
                        elif br["type"] == "cb":
                            state["column"] += 1
                    continue

                walk_children(child)

        walk_children(body)

        if not words:
            warnings.append("В документе не найдено ни одного тега <w>; загрузка выполнена, но выравнивание недоступно.")

        sheet_labels = ordered_unique(word.get("sheet") for word in words)

        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "display_name": display_name or re.sub(r"\.xml$", "", file_name, flags=re.IGNORECASE),
            "source_label": source_label or display_name or file_name,
            "title": title,
            "declared_encoding": decoded.declared_encoding,
            "actual_encoding": decoded.actual_encoding,
            "sheet_labels": sheet_labels,
            "word_count": len(words),
            "token_count": len(all_tokens),
            "warnings": warnings,
            "tokens": all_tokens,
            "words": words,
            "raw_preview": decoded.text[:1000],
            "metadata": {
                "title": title,
                "file_name": file_name,
                "sheet_labels": sheet_labels,
            },
        }

    def to_json(self, parsed_document: dict[str, Any]) -> str:
        return json.dumps(parsed_document, ensure_ascii=False, indent=2)

