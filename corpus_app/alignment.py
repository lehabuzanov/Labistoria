from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .utils import new_id, now_iso, ordered_unique, similarity_ratio


GRAPHICAL = "графическое"
PHONETIC = "фонетическое"
MORPHOLOGICAL = "морфологическое"
SYNTACTIC = "синтаксическое"
LEXICAL = "лексическое"
MATCH = "совпадение"
VARIANT_TYPES = [GRAPHICAL, PHONETIC, MORPHOLOGICAL, SYNTACTIC, LEXICAL]

MORPH_FEATURE_KEYS = ("category", "case", "number", "gender", "person", "tense", "mood", "voice", "degree", "kind")
VISUAL_MARKS = {"҃", "꙯", "˜", "·", "·", "҇", "҆", "ⷣ", "ⷭ", "ⷮ", "ⷬ", "ⷯ", "ⷪ", "ⷢ", "ⷠ", "ⷱ", "ⷲ"}
VISUAL_EQUIVALENTS = str.maketrans(
    {
        "і": "и",
        "ї": "и",
        "ı": "и",
        "ꙇ": "и",
        "ѡ": "о",
        "ѻ": "о",
        "ꙋ": "у",
        "ѹ": "у",
        "ꙑ": "ы",
        "ѕ": "з",
        "ꙁ": "з",
        "ѿ": "от",
    }
)
BROAD_EQUIVALENTS = str.maketrans(
    {
        "ѣ": "е",
        "ѥ": "е",
        "є": "е",
        "ѫ": "у",
        "ѭ": "ю",
        "ѧ": "я",
        "ѩ": "я",
        "ꙗ": "я",
        "ѯ": "кс",
        "ѱ": "пс",
        "ѳ": "ф",
        "ѵ": "и",
    }
)
VOWELS = set("аеёиоуыэюяѣѥєѧѩѫѭꙗ")
REFLEXIVE_SUFFIXES = ("ся", "сѧ", "сꙗ", "сѩ")


@dataclass(slots=True)
class Segment:
    document_id: str
    display_name: str
    sheet_start: str | None
    sheet_end: str | None
    words: list[dict[str, Any]]


class AlignmentEngine:
    def __init__(self, storage) -> None:
        self.storage = storage

    def build_alignment(
        self,
        *,
        name: str,
        master_doc_id: str,
        master_sheet_start: str | None,
        master_sheet_end: str | None,
        witnesses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        master_doc = self.storage.load_parsed_document(master_doc_id)
        master_meta = self.storage.get_document(master_doc_id)
        master_segment = self._select_segment(
            parsed_doc=master_doc,
            display_name=master_meta["display_name"],
            sheet_start=master_sheet_start,
            sheet_end=master_sheet_end,
        )

        witness_segments: list[Segment] = []
        local_ranges: list[tuple[int, int]] = []
        for witness in witnesses:
            parsed_doc = self.storage.load_parsed_document(witness["document_id"])
            meta = self.storage.get_document(witness["document_id"])
            segment = self._select_segment(
                parsed_doc=parsed_doc,
                display_name=meta["display_name"],
                sheet_start=witness.get("sheet_start"),
                sheet_end=witness.get("sheet_end"),
            )
            witness_segments.append(segment)
            local = self._local_overlap(master_segment.words, segment.words)
            if local:
                local_ranges.append((local["master_start"], local["master_end"]))

        if local_ranges:
            master_start = min(item[0] for item in local_ranges)
            master_end = max(item[1] for item in local_ranges)
            master_words = master_segment.words[master_start:master_end]
        else:
            master_words = master_segment.words

        rows = [self._new_master_row(word, master_doc_id) for word in master_words]
        for segment in witness_segments:
            local = self._local_overlap(master_words, segment.words)
            witness_words = segment.words[local["witness_start"] : local["witness_end"]] if local else segment.words
            rows = self._integrate_witness(
                rows=rows,
                witness_doc_id=segment.document_id,
                witness_words=witness_words,
            )

        self._finalize_rows(rows)

        alignment_id = new_id("alignment")
        now = now_iso()
        state = {
            "alignment_id": alignment_id,
            "name": name,
            "master_doc_id": master_doc_id,
            "master_sheet_start": master_sheet_start,
            "master_sheet_end": master_sheet_end,
            "witnesses": witnesses,
            "visible_document_order": [master_doc_id] + [item["document_id"] for item in witnesses],
            "rows": rows,
            "created_at": now,
            "updated_at": now,
            "export_path": None,
        }
        return state

    def list_document_order(self, state: dict[str, Any]) -> list[str]:
        return state.get("visible_document_order") or ordered_unique(
            [state["master_doc_id"]] + [item["document_id"] for item in state.get("witnesses", [])]
        )

    def reclassify(self, state: dict[str, Any]) -> dict[str, Any]:
        cloned = copy.deepcopy(state)
        self._finalize_rows(cloned["rows"])
        return cloned

    def move_cell(self, state: dict[str, Any], *, row_index: int, document_id: str, delta: int) -> dict[str, Any]:
        cloned = copy.deepcopy(state)
        rows = cloned["rows"]
        target_index = row_index + delta
        if row_index < 0 or row_index >= len(rows) or target_index < 0 or target_index >= len(rows):
            return cloned
        rows[row_index]["cells"].setdefault(document_id, [])
        rows[target_index]["cells"].setdefault(document_id, [])
        rows[row_index]["cells"][document_id], rows[target_index]["cells"][document_id] = (
            rows[target_index]["cells"][document_id],
            rows[row_index]["cells"][document_id],
        )
        rows[row_index]["manual"] = True
        rows[target_index]["manual"] = True
        self._finalize_rows(rows)
        return cloned

    def insert_empty_row(self, state: dict[str, Any], *, row_index: int) -> dict[str, Any]:
        cloned = copy.deepcopy(state)
        doc_ids = self.list_document_order(cloned)
        new_row = {
            "row_id": new_id("row"),
            "row_index": row_index,
            "cells": {doc_id: [] for doc_id in doc_ids},
            "flags": {"transposed": False},
            "manual": True,
            "variant_type": SYNTACTIC,
            "variant_source": "manual",
            "notes": "",
        }
        cloned["rows"].insert(row_index, new_row)
        self._finalize_rows(cloned["rows"])
        return cloned

    def delete_row_if_empty(self, state: dict[str, Any], *, row_index: int) -> dict[str, Any]:
        cloned = copy.deepcopy(state)
        row = cloned["rows"][row_index]
        if any(row["cells"].values()):
            return cloned
        cloned["rows"].pop(row_index)
        self._finalize_rows(cloned["rows"])
        return cloned

    def merge_down(self, state: dict[str, Any], *, row_index: int, document_id: str) -> dict[str, Any]:
        cloned = copy.deepcopy(state)
        rows = cloned["rows"]
        if row_index < 0 or row_index >= len(rows) - 1:
            return cloned
        rows[row_index]["cells"].setdefault(document_id, [])
        rows[row_index + 1]["cells"].setdefault(document_id, [])
        rows[row_index]["cells"][document_id].extend(rows[row_index + 1]["cells"][document_id])
        rows[row_index + 1]["cells"][document_id] = []
        rows[row_index]["manual"] = True
        self._finalize_rows(rows)
        return cloned

    def set_variant_type(self, state: dict[str, Any], *, row_index: int, variant_type: str) -> dict[str, Any]:
        cloned = copy.deepcopy(state)
        cloned["rows"][row_index]["variant_type"] = variant_type
        cloned["rows"][row_index]["variant_source"] = "manual"
        cloned["rows"][row_index]["manual"] = True
        return cloned

    def _select_segment(
        self,
        *,
        parsed_doc: dict[str, Any],
        display_name: str,
        sheet_start: str | None,
        sheet_end: str | None,
    ) -> Segment:
        words = parsed_doc["words"]
        sheet_labels = parsed_doc["sheet_labels"]
        if not sheet_labels or not sheet_start or not sheet_end:
            return Segment(parsed_doc["doc_id"], display_name, sheet_start, sheet_end, words)
        order = {label: idx for idx, label in enumerate(sheet_labels)}
        if sheet_start not in order or sheet_end not in order:
            return Segment(parsed_doc["doc_id"], display_name, sheet_start, sheet_end, words)
        lo = min(order[sheet_start], order[sheet_end])
        hi = max(order[sheet_start], order[sheet_end])
        selected = [word for word in words if word.get("sheet") in order and lo <= order[word["sheet"]] <= hi]
        return Segment(parsed_doc["doc_id"], display_name, sheet_start, sheet_end, selected)

    def _new_master_row(self, word: dict[str, Any], master_doc_id: str) -> dict[str, Any]:
        row = {
            "row_id": new_id("row"),
            "row_index": 0,
            "cells": {master_doc_id: [self._word_ref(word)]},
            "flags": {"transposed": False},
            "manual": False,
            "variant_type": GRAPHICAL,
            "variant_source": "automatic",
            "notes": "",
        }
        return row

    def _word_ref(self, word: dict[str, Any]) -> dict[str, Any]:
        text = word["text"]
        lemma = word.get("lemma")
        return {
            "token_id": word["token_id"],
            "text": text,
            "lemma": lemma,
            "features": word.get("features", {}),
            "sheet": word.get("sheet"),
            "page": word.get("page"),
            "line": word.get("line"),
            "graphic": self._graphic_key(text or lemma or ""),
            "broad": self._broad_key(text or lemma or ""),
            "normalized": self._broad_key(text or lemma or ""),
            "phonetic": self._phonetic_key(text or lemma or ""),
        }

    def _representative_key(self, row: dict[str, Any]) -> dict[str, Any]:
        for cell in row["cells"].values():
            if cell:
                return cell[0]
        return {
            "token_id": None,
            "text": "",
            "lemma": None,
            "features": {},
            "normalized": "",
            "graphic": "",
            "broad": "",
            "phonetic": "",
        }

    def _surface_form(self, item: dict[str, Any]) -> str:
        return (item.get("text") or item.get("lemma") or "").lower()

    def _same_surface(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        return bool(self._surface_form(left) and self._surface_form(left) == self._surface_form(right))

    def _graphic_key(self, text: str) -> str:
        value = "".join(ch for ch in (text or "").lower() if ch not in VISUAL_MARKS)
        value = value.translate(VISUAL_EQUIVALENTS)
        return "".join(ch for ch in value if ch.isalnum())

    def _broad_key(self, text: str) -> str:
        value = self._graphic_key(text)
        return value.translate(BROAD_EQUIVALENTS)

    def _phonetic_key(self, text: str) -> str:
        value = self._broad_key(text)
        return (
            value.replace("о", "a")
            .replace("е", "i")
            .replace("ы", "и")
            .replace("я", "а")
            .replace("ю", "у")
            .replace("ъ", "")
            .replace("ь", "")
        )

    def _lemma_key(self, item: dict[str, Any]) -> str:
        return self._broad_key(item.get("lemma") or "")

    def _lexeme_key(self, item: dict[str, Any]) -> str:
        return self._strip_reflexive_suffix(self._broad_key(item.get("lemma") or item.get("text") or ""))

    def _core_features(self, item: dict[str, Any]) -> dict[str, str]:
        features = item.get("features", {}) or {}
        return {key: str(value) for key, value in features.items() if key in MORPH_FEATURE_KEYS and value not in (None, "")}

    def _shared_feature_agreement(self, left: dict[str, Any], right: dict[str, Any]) -> float:
        left_features = self._core_features(left)
        right_features = self._core_features(right)
        shared = set(left_features) & set(right_features)
        if not shared:
            return 1.0
        matches = sum(1 for key in shared if left_features[key] == right_features[key])
        return matches / len(shared)

    def _same_feature(self, left: dict[str, Any], right: dict[str, Any], feature_name: str) -> bool:
        left_value = self._core_features(left).get(feature_name)
        right_value = self._core_features(right).get(feature_name)
        return bool(left_value and right_value and left_value == right_value)

    def _same_lemma(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_key = self._lemma_key(left)
        right_key = self._lemma_key(right)
        return bool(left_key and right_key and left_key == right_key)

    def _strip_reflexive_suffix(self, value: str) -> str:
        for suffix in REFLEXIVE_SUFFIXES:
            if value.endswith(suffix):
                return value[: -len(suffix)]
        return value

    def _is_reflexive_pair(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_key = self._broad_key(left.get("lemma") or left.get("text") or "")
        right_key = self._broad_key(right.get("lemma") or right.get("text") or "")
        if not left_key or not right_key:
            return False
        return self._strip_reflexive_suffix(left_key) == self._strip_reflexive_suffix(right_key) and left_key != right_key

    def _same_lexeme_family(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        candidate_pairs = [
            (self._lexeme_key(left), self._lexeme_key(right)),
            (self._strip_reflexive_suffix(left.get("broad", "")), self._strip_reflexive_suffix(right.get("broad", ""))),
        ]
        for left_key, right_key in candidate_pairs:
            if not left_key or not right_key:
                continue
            if left_key == right_key:
                return True
            if self._same_feature(left, right, "category") or self._shared_feature_agreement(left, right) >= 0.8:
                ratio = similarity_ratio(left_key, right_key)
                if ratio >= 0.68:
                    return True
                if left_key[:2] and left_key[:2] == right_key[:2] and abs(len(left_key) - len(right_key)) <= 3:
                    return True
        return False

    def _consonant_skeleton(self, item: dict[str, Any]) -> str:
        return "".join(ch for ch in item.get("broad", "") if ch not in VOWELS and ch not in {"ъ", "ь"})

    def _is_subsequence(self, short: str, long: str) -> bool:
        if not short:
            return False
        iterator = iter(long)
        return all(char in iterator for char in short)

    def _has_abbreviation_mark(self, item: dict[str, Any]) -> bool:
        value = self._surface_form(item)
        return any(ch in VISUAL_MARKS for ch in value)

    def _abbreviation_like(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_graphic = left.get("graphic", "")
        right_graphic = right.get("graphic", "")
        left_skeleton = self._consonant_skeleton(left)
        right_skeleton = self._consonant_skeleton(right)
        has_marks = self._has_abbreviation_mark(left) or self._has_abbreviation_mark(right)
        if left_skeleton and right_skeleton and left_skeleton == right_skeleton and (has_marks or abs(len(left_graphic) - len(right_graphic)) >= 2):
            return True
        if has_marks:
            if len(left_graphic) < len(right_graphic):
                return self._is_subsequence(left_graphic, right_graphic)
            return self._is_subsequence(right_graphic, left_graphic)
        return False

    def _likely_morphological(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        if self._is_reflexive_pair(left, right):
            return True
        if not self._same_feature(left, right, "category") and self._core_features(left).get("category") and self._core_features(right).get("category"):
            return True
        shared_agreement = self._shared_feature_agreement(left, right)
        graphic_ratio = similarity_ratio(left.get("graphic", ""), right.get("graphic", ""))
        broad_ratio = similarity_ratio(left.get("broad", ""), right.get("broad", ""))
        if shared_agreement < 0.45 and graphic_ratio < 0.82:
            return True
        if shared_agreement < 0.7 and broad_ratio < 0.66 and not self._abbreviation_like(left, right):
            return True
        if self._same_feature(left, right, "category") and graphic_ratio < 0.62:
            return True
        return False

    def _score(self, left: dict[str, Any], right: dict[str, Any]) -> float:
        if not left or not right:
            return -2.0
        if left.get("lemma") and right.get("lemma") and left["lemma"] == right["lemma"]:
            if left.get("features") == right.get("features"):
                return 5.0
            return 4.0
        if left.get("normalized") == right.get("normalized") and left.get("normalized"):
            return 4.5
        if left.get("phonetic") == right.get("phonetic") and left.get("phonetic"):
            return 3.2
        ratio = similarity_ratio(left.get("normalized", ""), right.get("normalized", ""))
        if ratio > 0.88:
            return 2.5
        if ratio > 0.72:
            return 1.2
        return -2.4

    def _local_overlap(self, master_words: list[dict[str, Any]], witness_words: list[dict[str, Any]]) -> dict[str, int] | None:
        if not master_words or not witness_words:
            return None
        n, m = len(master_words), len(witness_words)
        scores = [[0.0] * (m + 1) for _ in range(n + 1)]
        trace = [[None] * (m + 1) for _ in range(n + 1)]
        best_score = 0.0
        best_cell = (0, 0)

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                diag = scores[i - 1][j - 1] + self._score(master_words[i - 1], witness_words[j - 1])
                up = scores[i - 1][j] - 1.8
                left = scores[i][j - 1] - 1.8
                best = max(0.0, diag, up, left)
                if best == 0.0:
                    trace[i][j] = None
                elif best == diag:
                    trace[i][j] = "diag"
                elif best == up:
                    trace[i][j] = "up"
                else:
                    trace[i][j] = "left"
                scores[i][j] = best
                if best > best_score:
                    best_score = best
                    best_cell = (i, j)

        if best_score <= 0:
            return None

        i, j = best_cell
        end_i, end_j = i, j
        while i > 0 and j > 0 and scores[i][j] > 0:
            op = trace[i][j]
            if op == "diag":
                i -= 1
                j -= 1
            elif op == "up":
                i -= 1
            elif op == "left":
                j -= 1
            else:
                break
        return {
            "master_start": i,
            "master_end": end_i,
            "witness_start": j,
            "witness_end": end_j,
        }

    def _global_alignment(
        self,
        left_seq: list[dict[str, Any]],
        right_seq: list[dict[str, Any]],
    ) -> tuple[list[tuple[int | None, int | None]], set[int]]:
        n, m = len(left_seq), len(right_seq)
        scores = [[0.0] * (m + 1) for _ in range(n + 1)]
        trace = [[None] * (m + 1) for _ in range(n + 1)]
        gap = -1.8

        for i in range(1, n + 1):
            scores[i][0] = scores[i - 1][0] + gap
            trace[i][0] = "up"
        for j in range(1, m + 1):
            scores[0][j] = scores[0][j - 1] + gap
            trace[0][j] = "left"

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                diag = scores[i - 1][j - 1] + self._score(left_seq[i - 1], right_seq[j - 1])
                up = scores[i - 1][j] + gap
                left = scores[i][j - 1] + gap
                transpose = float("-inf")
                if i > 1 and j > 1:
                    transpose = (
                        scores[i - 2][j - 2]
                        + self._score(left_seq[i - 2], right_seq[j - 1])
                        + self._score(left_seq[i - 1], right_seq[j - 2])
                        - 0.2
                    )
                best = max(diag, up, left, transpose)
                scores[i][j] = best
                if best == transpose:
                    trace[i][j] = "transpose"
                elif best == diag:
                    trace[i][j] = "diag"
                elif best == up:
                    trace[i][j] = "up"
                else:
                    trace[i][j] = "left"

        pairs: list[tuple[int | None, int | None]] = []
        transposed_left: set[int] = set()
        i, j = n, m
        while i > 0 or j > 0:
            op = trace[i][j]
            if op == "diag":
                pairs.append((i - 1, j - 1))
                i -= 1
                j -= 1
            elif op == "up":
                pairs.append((i - 1, None))
                i -= 1
            elif op == "left":
                pairs.append((None, j - 1))
                j -= 1
            elif op == "transpose":
                pairs.append((i - 1, j - 2))
                pairs.append((i - 2, j - 1))
                transposed_left.update({i - 1, i - 2})
                i -= 2
                j -= 2
            else:
                if i > 0:
                    pairs.append((i - 1, None))
                    i -= 1
                elif j > 0:
                    pairs.append((None, j - 1))
                    j -= 1
        pairs.reverse()
        return pairs, transposed_left

    def _integrate_witness(
        self,
        *,
        rows: list[dict[str, Any]],
        witness_doc_id: str,
        witness_words: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        left_seq = [self._representative_key(row) for row in rows]
        right_seq = [self._word_ref(word) for word in witness_words]
        pairs, transposed = self._global_alignment(left_seq, right_seq)
        new_rows: list[dict[str, Any]] = []

        for left_idx, right_idx in pairs:
            if left_idx is None:
                row = {
                    "row_id": new_id("row"),
                    "row_index": 0,
                    "cells": {witness_doc_id: [right_seq[right_idx]]},
                    "flags": {"transposed": False},
                    "manual": False,
                    "variant_type": SYNTACTIC,
                    "variant_source": "automatic",
                    "notes": "",
                }
                new_rows.append(row)
                continue

            row = copy.deepcopy(rows[left_idx])
            row["cells"].setdefault(witness_doc_id, [])
            if right_idx is not None:
                row["cells"][witness_doc_id] = [right_seq[right_idx]]
            if left_idx in transposed:
                row["flags"]["transposed"] = True
            new_rows.append(row)

        return new_rows

    def _pair_variant_type(self, anchor: dict[str, Any], item: dict[str, Any]) -> str:
        if not anchor or not item:
            return SYNTACTIC

        if self._same_surface(anchor, item):
            return MATCH
        same_graphic = anchor.get("graphic") == item.get("graphic") and anchor.get("graphic")
        same_broad = anchor.get("broad") == item.get("broad") and anchor.get("broad")
        same_phonetic = anchor.get("phonetic") == item.get("phonetic") and anchor.get("phonetic")
        same_lemma = self._same_lemma(anchor, item)
        same_lexeme = same_lemma or self._same_lexeme_family(anchor, item)
        graphic_ratio = similarity_ratio(anchor.get("graphic", ""), item.get("graphic", ""))
        broad_ratio = similarity_ratio(anchor.get("broad", ""), item.get("broad", ""))
        shared_agreement = self._shared_feature_agreement(anchor, item)
        abbreviation_like = self._abbreviation_like(anchor, item)

        if same_graphic or same_broad:
            return GRAPHICAL
        if same_lemma and abbreviation_like and (shared_agreement >= 0.5 or self._same_feature(anchor, item, "category")):
            return GRAPHICAL
        if same_lemma and same_phonetic and graphic_ratio >= 0.54:
            return PHONETIC
        if same_lemma and self._likely_morphological(anchor, item):
            return MORPHOLOGICAL
        if same_lemma:
            if abbreviation_like or graphic_ratio >= 0.78:
                return GRAPHICAL
            if same_phonetic:
                return PHONETIC
            return MORPHOLOGICAL
        if same_lexeme and (self._likely_morphological(anchor, item) or (shared_agreement >= 0.8 and graphic_ratio < 0.68)):
            return MORPHOLOGICAL
        if same_lexeme and same_phonetic:
            return PHONETIC
        if same_lexeme and (graphic_ratio >= 0.72 or broad_ratio >= 0.82):
            return GRAPHICAL
        if same_phonetic and broad_ratio >= 0.45:
            return PHONETIC
        if graphic_ratio >= 0.92:
            return GRAPHICAL
        return LEXICAL

    def _choose_anchor(self, readings: list[dict[str, Any]]) -> dict[str, Any]:
        penalties = {
            MATCH: -0.2,
            GRAPHICAL: 0.0,
            PHONETIC: 1.2,
            MORPHOLOGICAL: 2.6,
            LEXICAL: 4.3,
            SYNTACTIC: 5.0,
        }
        best = readings[0]
        best_score = float("inf")
        best_lemma_support = -1
        for candidate in readings:
            score = 0.0
            for other in readings:
                if other is candidate:
                    continue
                score += penalties[self._pair_variant_type(candidate, other)]
            lemma_support = sum(1 for other in readings if self._same_lemma(candidate, other))
            if score < best_score or (score == best_score and lemma_support > best_lemma_support):
                best = candidate
                best_score = score
                best_lemma_support = lemma_support
        return best

    def _build_variant_detail(
        self,
        *,
        anchor: dict[str, Any] | None,
        relation_counts: Counter[str],
        has_omission: bool,
        transposed: bool,
    ) -> str:
        bits: list[str] = []
        if transposed:
            bits.append("есть перестановка соседних слов")
        elif has_omission:
            bits.append("есть пропуски или вставки")

        if anchor:
            anchor_text = anchor.get("text") or anchor.get("lemma") or ""
            if anchor_text:
                bits.append(f"опорное чтение: {anchor_text}")

        relation_labels = {
            GRAPHICAL: "графич.",
            PHONETIC: "фонетич.",
            MORPHOLOGICAL: "морфол.",
            SYNTACTIC: "синтаксич.",
            LEXICAL: "лексич.",
        }
        summary = [f"{relation_labels[key]} {relation_counts[key]}" for key in VARIANT_TYPES if relation_counts.get(key)]
        if summary:
            bits.append("в строке: " + ", ".join(summary))
        return "; ".join(bits)

    def _analyze_row(self, row: dict[str, Any]) -> dict[str, Any]:
        populated = {doc_id: cell[0] for doc_id, cell in row["cells"].items() if cell}
        if len(populated) < 2:
            return {
                "variant_type": SYNTACTIC,
                "variant_auto_type": SYNTACTIC,
                "variant_detail": "недостаточно чтений для сопоставления",
                "relation_counts": {SYNTACTIC: 1},
                "anchor_text": None,
                "state_label": "Недостаточно чтений",
            }

        transposed = bool(row["flags"].get("transposed"))
        has_omission = any(not cell for cell in row["cells"].values())
        surface_values = {self._surface_form(item) for item in populated.values()}
        if len(surface_values) == 1 and not transposed and not has_omission:
            return {
                "variant_type": MATCH,
                "variant_auto_type": MATCH,
                "variant_detail": "Во всех выбранных списках чтение совпадает.",
                "relation_counts": {},
                "anchor_text": next(iter(populated.values())).get("text") or None,
                "state_label": "Совпадение",
            }
        anchor = self._choose_anchor(list(populated.values()))
        relation_counts: Counter[str] = Counter()
        for item in populated.values():
            if item is anchor:
                continue
            pair_type = self._pair_variant_type(anchor, item)
            if pair_type == MATCH:
                continue
            relation_counts[pair_type] += 1

        if transposed:
            relation_counts[SYNTACTIC] += 1
        elif has_omission:
            relation_counts[SYNTACTIC] += 1

        priority = [SYNTACTIC, LEXICAL, MORPHOLOGICAL, PHONETIC, GRAPHICAL]
        primary = GRAPHICAL
        for variant_type in priority:
            if relation_counts.get(variant_type):
                primary = variant_type
                break

        if not relation_counts:
            return {
                "variant_type": MATCH,
                "variant_auto_type": MATCH,
                "variant_detail": "Во всех выбранных списках чтение совпадает.",
                "relation_counts": {},
                "anchor_text": anchor.get("text") or None,
                "state_label": "Совпадение",
            }

        return {
            "variant_type": primary,
            "variant_auto_type": primary,
            "variant_detail": self._build_variant_detail(
                anchor=anchor,
                relation_counts=relation_counts,
                has_omission=has_omission,
                transposed=transposed,
            ),
            "relation_counts": dict(relation_counts),
            "anchor_text": anchor.get("text") or None,
            "state_label": "Разночтение",
        }

    def _finalize_rows(self, rows: list[dict[str, Any]]) -> None:
        for index, row in enumerate(rows, start=1):
            row["row_index"] = index
            for cell in row["cells"].values():
                cell.sort(key=lambda item: item.get("token_id") or "")
            analysis = self._analyze_row(row)
            row["variant_auto_type"] = analysis["variant_auto_type"]
            row["variant_detail"] = analysis["variant_detail"]
            row["relation_counts"] = analysis["relation_counts"]
            row["anchor_text"] = analysis["anchor_text"]
            row["state_label"] = analysis["state_label"]
            if row.get("variant_source") != "manual":
                row["variant_type"] = analysis["variant_type"]
                row["variant_source"] = "automatic"
