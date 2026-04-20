from __future__ import annotations

from pathlib import Path

from corpus_app import AlignmentEngine, RepositoryStorage, export_alignment_to_tei
from corpus_app.config import BASE_DIR


SOURCE_FILES = [
    "EO_117-119_2.xml",
    "EArkh_72-73_2.xml",
    "ETip_119-120_2.xml",
    "EPant_140-141_2.xml",
    "EPog_120-122_2.xml",
]


def main() -> None:
    storage = RepositoryStorage()
    engine = AlignmentEngine(storage)

    imported = []
    for file_name in SOURCE_FILES:
        path = BASE_DIR / file_name
        if not path.exists():
            raise FileNotFoundError(path)
        imported.append(storage.import_document_file(path))

    assert len(storage.list_documents()) >= 5, "Не все XML были импортированы."

    docs_by_name = {item["display_name"]: item for item in storage.list_documents()}
    master = docs_by_name["EPog_120-122_2"]
    witnesses = []
    for key in ["EArkh_72-73_2", "ETip_119-120_2", "EO_117-119_2", "EPant_140-141_2"]:
        doc = docs_by_name[key]
        start = doc["sheet_labels"][0] if doc["sheet_labels"] else None
        end = doc["sheet_labels"][-1] if doc["sheet_labels"] else None
        witnesses.append(
            {
                "document_id": doc["doc_id"],
                "sheet_start": start,
                "sheet_end": end,
                "sort_order": len(witnesses) + 1,
            }
        )

    state = engine.build_alignment(
        name="Самопроверка: Притча о блудном сыне",
        master_doc_id=master["doc_id"],
        master_sheet_start="120",
        master_sheet_end="122",
        witnesses=witnesses,
    )
    storage.save_alignment(state)
    assert len(state["rows"]) > 100, "Выравнивание получилось подозрительно коротким."

    state = engine.insert_empty_row(state, row_index=10)
    state = engine.move_cell(state, row_index=11, document_id=witnesses[0]["document_id"], delta=-1)
    state = engine.set_variant_type(state, row_index=10, variant_type="синтаксическое")
    storage.save_alignment(state)

    reloaded = storage.load_alignment(state["alignment_id"])
    assert reloaded["rows"][10]["variant_type"] == "синтаксическое", "Ручная правка не сохранилась."

    tei_text = export_alignment_to_tei(storage=storage, alignment_state=reloaded)
    export_path = storage.save_export(reloaded["alignment_id"], tei_text)
    assert Path(export_path).exists(), "Экспортированный TEI не создан."
    assert "<listApp>" in tei_text and "<rdg" in tei_text, "Экспорт TEI не содержит выравнивания."

    docs_after = storage.list_documents()
    assert len(docs_after) >= 5, "После сохранения документы пропали из хранилища."

    print("SELF_CHECK_OK")
    print(f"documents={len(docs_after)}")
    print(f"rows={len(reloaded['rows'])}")
    print(f"export={export_path}")


if __name__ == "__main__":
    main()

