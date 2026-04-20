from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont

from corpus_app import AlignmentEngine, RepositoryStorage, export_alignment_to_tei
from corpus_app.config import BASE_DIR
from streamlit_app import MANUSCRIPT_SAMPLE, REPOSITORY_URL, UI_SAMPLE, build_font_face


SOURCE_FILES = [
    "EO_117-119_2.xml",
    "EArkh_72-73_2.xml",
    "ETip_119-120_2.xml",
    "EPant_140-141_2.xml",
    "EPog_120-122_2.xml",
]

FONT_FILES = {
    "manuscript": BASE_DIR / "assets" / "fonts" / "Monomakh-Regular.ttf",
    "manuscript_fallback": BASE_DIR / "assets" / "fonts" / "NotoSerif-Regular.ttf",
    "ui_primary": BASE_DIR / "assets" / "fonts" / "OldStandard-Regular.ttf",
    "ui_heading": BASE_DIR / "assets" / "fonts" / "Oranienbaum-Regular.ttf",
}


def font_cmap(font_path: Path) -> dict[int, str]:
    font = TTFont(font_path)
    return font.getBestCmap()


def assert_font_has_chars(font_path: Path, sample_text: str) -> None:
    cmap = font_cmap(font_path)
    required = {ord(ch) for ch in sample_text if not ch.isspace()}
    missing = [chr(code) for code in sorted(required) if code not in cmap]
    assert not missing, f"Шрифт {font_path.name} не покрывает символы: {' '.join(missing)}"


def assert_font_stack_has_chars(font_paths: list[Path], sample_text: str) -> None:
    combined: dict[int, str] = {}
    for font_path in font_paths:
        combined.update(font_cmap(font_path))
    required = {ord(ch) for ch in sample_text if not ch.isspace()}
    missing = [chr(code) for code in sorted(required) if code not in combined]
    assert not missing, f"Шрифтовый стек не покрывает символы: {' '.join(missing)}"


def assert_font_embedding() -> None:
    manuscript_css = build_font_face("LabMonomakh", "Monomakh-Regular.ttf")
    fallback_css = build_font_face("LabNotoSerif", "NotoSerif-Regular.ttf")
    ui_css = build_font_face("LabOldStandard", "OldStandard-Regular.ttf")
    heading_css = build_font_face("LabOranienbaum", "Oranienbaum-Regular.ttf")
    assert 'raw.githubusercontent.com/lehabuzanov/Labistoria/main/assets/fonts/Monomakh-Regular.ttf' in manuscript_css, "Monomakh не подключается в CSS."
    assert 'raw.githubusercontent.com/lehabuzanov/Labistoria/main/assets/fonts/NotoSerif-Regular.ttf' in fallback_css, "Noto Serif не подключается в CSS."
    assert 'raw.githubusercontent.com/lehabuzanov/Labistoria/main/assets/fonts/OldStandard-Regular.ttf' in ui_css, "Old Standard не подключается в CSS."
    assert 'raw.githubusercontent.com/lehabuzanov/Labistoria/main/assets/fonts/Oranienbaum-Regular.ttf' in heading_css, "Oranienbaum не подключается в CSS."


def main() -> None:
    for font_path in FONT_FILES.values():
        assert font_path.exists(), f"Отсутствует файл шрифта: {font_path}"
    assert_font_stack_has_chars(
        [FONT_FILES["manuscript"], FONT_FILES["manuscript_fallback"]],
        MANUSCRIPT_SAMPLE,
    )
    assert_font_has_chars(FONT_FILES["ui_primary"], UI_SAMPLE)
    assert_font_has_chars(FONT_FILES["ui_heading"], UI_SAMPLE)
    assert_font_embedding()
    assert REPOSITORY_URL.startswith("https://github.com/"), "Ссылка на репозиторий не настроена."

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
    print("FONT_CHECK_OK")
    print(f"documents={len(docs_after)}")
    print(f"rows={len(reloaded['rows'])}")
    print(f"export={export_path}")


if __name__ == "__main__":
    main()
