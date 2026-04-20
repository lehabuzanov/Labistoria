from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from .utils import new_id, normalize_surface, now_iso, ordered_unique, phonetic_key, similarity_ratio


GRAPHICAL = "графическое"
PHONETIC = "фонетическое"
MORPHOLOGICAL = "морфологическое"
SYNTACTIC = "синтаксическое"
LEXICAL = "лексическое"
VARIANT_TYPES = [GRAPHICAL, PHONETIC, MORPHOLOGICAL, SYNTACTIC, LEXICAL]


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
        return {
            "token_id": word["token_id"],
            "text": word["text"],
            "lemma": word.get("lemma"),
            "features": word.get("features", {}),
            "sheet": word.get("sheet"),
            "page": word.get("page"),
            "line": word.get("line"),
            "normalized": word.get("normalized") or normalize_surface(word["text"]),
            "phonetic": word.get("phonetic") or phonetic_key(word["text"]),
        }

    def _representative_key(self, row: dict[str, Any]) -> dict[str, Any]:
        for cell in row["cells"].values():
            if cell:
                return cell[0]
        return {"token_id": None, "text": "", "lemma": None, "features": {}, "normalized": "", "phonetic": ""}

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

    def _classify_row(self, row: dict[str, Any]) -> str:
        cells = [cell for cell in row["cells"].values() if cell]
        if len(cells) < 2:
            return SYNTACTIC
        primary = [cell[0] for cell in cells]
        if row["flags"].get("transposed"):
            return SYNTACTIC

        normalized = {item.get("normalized") for item in primary if item.get("normalized")}
        phonetic = {item.get("phonetic") for item in primary if item.get("phonetic")}
        lemmas = {item.get("lemma") for item in primary if item.get("lemma")}
        features = {jsonable(item.get("features", {})) for item in primary}

        if len(normalized) == 1:
            return GRAPHICAL
        if len(lemmas) == 1 and len(features) > 1:
            return MORPHOLOGICAL
        if len(phonetic) == 1:
            return PHONETIC
        if len(lemmas) == 1:
            return GRAPHICAL
        return LEXICAL

    def _finalize_rows(self, rows: list[dict[str, Any]]) -> None:
        for index, row in enumerate(rows, start=1):
            row["row_index"] = index
            for cell in row["cells"].values():
                cell.sort(key=lambda item: item.get("token_id") or "")
            if row.get("variant_source") != "manual":
                row["variant_type"] = self._classify_row(row)
                row["variant_source"] = "automatic"


def jsonable(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)

