from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import streamlit as st

from corpus_app import AlignmentEngine, RepositoryStorage, export_alignment_to_tei
from corpus_app.alignment import VARIANT_TYPES
from corpus_app.config import ASSETS_DIR, BASE_DIR


REPOSITORY_URL = "https://github.com/lehabuzanov/Labistoria"
RAW_BASE_URL = "https://raw.githubusercontent.com/lehabuzanov/Labistoria/main/assets/fonts"
MANUSCRIPT_SAMPLE = "чл҃къ ꙗже ѣсть ꙗко ҃ ҇ ⷭ ⷮ ⷬ ⷯ ꙯ ⸱ №"
UI_SAMPLE = "Параллельный корпус списков"


st.set_page_config(
    page_title="Параллельный корпус списков",
    page_icon="📜",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_storage() -> RepositoryStorage:
    return RepositoryStorage()


def build_font_face(name: str, file_name: str, *, weight: int = 400) -> str:
    font_path = ASSETS_DIR / "fonts" / file_name
    if not font_path.exists():
        return ""
    font_url = f"{RAW_BASE_URL}/{file_name}"
    return f"""
    @font-face {{
      font-family: "{name}";
      src: url("{font_url}") format("truetype");
      font-weight: {weight};
      font-style: normal;
      font-display: swap;
    }}
    """


def inject_styles() -> None:
    css_path = ASSETS_DIR / "styles.css"
    font_css = "\n".join(
        [
            build_font_face("LabMonomakh", "Monomakh-Regular.ttf"),
            build_font_face("LabNotoSerif", "NotoSerif-Regular.ttf"),
            build_font_face("LabOldStandard", "OldStandard-Regular.ttf"),
            build_font_face("LabOranienbaum", "Oranienbaum-Regular.ttf"),
        ]
    )
    st.markdown(f"<style>{font_css}\n{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def card(title: str, body: str, subtitle: str | None = None) -> None:
    subtitle_html = f'<div class="metric-subtitle">{html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="metric-card">
          <div class="metric-title">{html.escape(title)}</div>
          <div class="metric-value">{html.escape(body)}</div>
          {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def load_document_name_map(storage: RepositoryStorage) -> dict[str, dict]:
    docs = storage.list_documents()
    return {doc["doc_id"]: doc for doc in docs}


def sheet_range_text(doc: dict) -> str:
    labels = doc["sheet_labels"]
    if not labels:
        return "Листовая разметка отсутствует"
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]}–{labels[-1]}"


def render_repo_callout() -> None:
    st.sidebar.markdown(
        f"""
        <div class="sidebar-callout">
          <div class="sidebar-callout-title">Репозиторий проекта</div>
          <a class="repo-link" href="{REPOSITORY_URL}" target="_blank">{REPOSITORY_URL}</a>
          <div class="small-note">Здесь хранится актуальная версия Streamlit-приложения и исходные TEI-файлы.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_guide() -> None:
    st.sidebar.markdown(
        """
        <div class="sidebar-callout">
          <div class="sidebar-callout-title">Краткая инструкция</div>
          <ol class="guide-list">
            <li>Импортируйте XML-TEI из папки проекта или загрузите новые.</li>
            <li>Выберите главный список и листы, затем задайте диапазоны остальных.</li>
            <li>Просмотрите автоматическое выравнивание и вручную поправьте спорные места.</li>
            <li>Экспортируйте параллельный корпус в отдельный XML-TEI.</li>
          </ol>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_font_panel() -> None:
    st.sidebar.markdown(
        f"""
        <div class="sidebar-callout">
          <div class="sidebar-callout-title">Шрифтовая проверка</div>
          <div class="small-note">Рукописный слой</div>
          <div class="manuscript-preview manuscript">{html.escape(MANUSCRIPT_SAMPLE)}</div>
          <div class="small-note" style="margin-top:0.55rem;">Интерфейсный слой</div>
          <div class="ui-preview">{html.escape(UI_SAMPLE)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_document_cards(storage: RepositoryStorage) -> None:
    documents = storage.list_documents()
    if not documents:
        st.info("Пока нет ни одного импортированного документа.")
        return

    cards: list[str] = []
    for doc in documents:
        warnings = ""
        if doc["warnings"]:
            warnings = '<div class="catalog-warning">' + "<br>".join(html.escape(item) for item in doc["warnings"]) + "</div>"
        cards.append(
            f"""
            <article class="catalog-card">
              <div class="catalog-topline">{html.escape(doc["display_name"])}</div>
              <h3>{html.escape(doc["title"])}</h3>
              <div class="catalog-meta">
                <span>Листы: {html.escape(sheet_range_text(doc))}</span>
                <span>Слов: {doc["word_count"]}</span>
                <span>Кодировка: {html.escape(doc["actual_encoding"])}</span>
              </div>
              {warnings}
            </article>
            """
        )
    st.markdown('<div class="catalog-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def render_library_tab(storage: RepositoryStorage) -> None:
    st.subheader("Импорт XML-TEI")
    st.markdown(
        """
        <div class="small-note">
          Файлы сохраняются в `storage/uploads`, разобранные токены — в `storage/parsed`,
          метаданные и сессии выравнивания — в `storage/corpus.db`, экспорт — в `storage/exports`.
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.05, 1.05])
    with left:
        if st.button("Импортировать XML из папки проекта", use_container_width=True):
            imported = 0
            skipped = 0
            before_docs = {item["doc_id"] for item in storage.list_documents()}
            for xml_path in storage.scan_project_xml_files(BASE_DIR):
                document = storage.import_document_file(xml_path)
                if document["doc_id"] in before_docs:
                    skipped += 1
                else:
                    imported += 1
                    before_docs.add(document["doc_id"])
            st.success(f"Импорт завершён: новых файлов {imported}, уже известных {skipped}.")

    with right:
        uploads = st.file_uploader(
            "Загрузить новые списки",
            type=["xml"],
            accept_multiple_files=True,
            help="Приложение автоматически определяет фактическую кодировку и сохраняет файл для следующих сеансов.",
        )
        if uploads:
            imported = 0
            for upload in uploads:
                storage.import_document_bytes(
                    file_name=upload.name,
                    source_bytes=upload.getvalue(),
                    display_name=upload.name,
                )
                imported += 1
            st.success(f"Загружено файлов: {imported}.")

    st.markdown("### Каталог списков")
    render_document_cards(storage)


def choose_sheet_range(meta: dict, prefix: str) -> tuple[str | None, str | None]:
    labels = meta["sheet_labels"]
    if not labels:
        return None, None
    left, right = st.columns(2)
    with left:
        start = st.selectbox("От листа", labels, key=f"{prefix}_start")
    with right:
        end = st.selectbox("До листа", labels, index=len(labels) - 1, key=f"{prefix}_end")
    return start, end


def create_alignment_form(storage: RepositoryStorage, engine: AlignmentEngine) -> str | None:
    documents = storage.list_documents()
    if len(documents) < 2:
        st.info("Для выравнивания нужны как минимум два загруженных списка.")
        return None

    doc_map = {doc["display_name"]: doc for doc in documents}
    doc_names = list(doc_map.keys())

    with st.form("create_alignment_form"):
        st.subheader("Новое автоматическое выравнивание")
        alignment_name = st.text_input("Название корпуса / сессии", value="Притча о блудном сыне")
        master_name = st.selectbox("Главный список", doc_names)
        master_doc = doc_map[master_name]
        st.markdown('<div class="inner-banner">Диапазон листов главного списка</div>', unsafe_allow_html=True)
        master_start, master_end = choose_sheet_range(master_doc, "master")
        st.markdown('<div class="inner-banner">Подключаемые списки</div>', unsafe_allow_html=True)
        witness_names = st.multiselect(
            "Выберите списки для выравнивания",
            [name for name in doc_names if name != master_name],
            default=[name for name in doc_names if name != master_name],
        )

        witness_configs: list[dict] = []
        for idx, witness_name in enumerate(witness_names, start=1):
            witness_doc = doc_map[witness_name]
            st.markdown(f"**{idx}. {witness_name}**")
            start, end = choose_sheet_range(witness_doc, f"wit_{witness_doc['doc_id']}")
            witness_configs.append(
                {
                    "document_id": witness_doc["doc_id"],
                    "sheet_start": start,
                    "sheet_end": end,
                    "sort_order": idx,
                }
            )

        submitted = st.form_submit_button("Выполнить автоматическое выравнивание", use_container_width=True)
        if submitted and witness_configs:
            state = engine.build_alignment(
                name=alignment_name,
                master_doc_id=master_doc["doc_id"],
                master_sheet_start=master_start,
                master_sheet_end=master_end,
                witnesses=witness_configs,
            )
            storage.save_alignment(state)
            st.success("Выравнивание выполнено и сохранено.")
            return state["alignment_id"]
        if submitted and not witness_configs:
            st.warning("Нужно выбрать хотя бы один список-свидетель.")
    return None


def cell_text(cell: list[dict]) -> str:
    return " ".join(item["text"] for item in cell) if cell else "—"


def cell_title(cell: list[dict]) -> str:
    if not cell:
        return "Пустое соответствие"
    parts = []
    for item in cell:
        bits = [
            f"token={item.get('token_id', '')}",
            f"sheet={item.get('sheet', '')}",
            f"page={item.get('page', '')}",
            f"line={item.get('line', '')}",
        ]
        if item.get("lemma"):
            bits.append(f"lemma={item['lemma']}")
        parts.append("; ".join(bits))
    return " | ".join(parts)


def variant_slug(variant_type: str) -> str:
    return {
        "графическое": "graphical",
        "фонетическое": "phonetic",
        "морфологическое": "morphological",
        "синтаксическое": "syntactic",
        "лексическое": "lexical",
    }.get(variant_type, "default")


def filtered_rows(state: dict, variant_filter: list[str], row_span: tuple[int, int]) -> list[dict]:
    output = []
    for row in state["rows"]:
        if row["variant_type"] not in variant_filter:
            continue
        if not (row_span[0] <= row["row_index"] <= row_span[1]):
            continue
        output.append(row)
    return output


def render_alignment_table(rows: list[dict], doc_map: dict[str, dict], visible_docs: list[str], *, table_id: str) -> None:
    header_cells = ['<th class="index-col">№</th>', '<th class="type-col">Тип</th>']
    header_cells.extend(f"<th>{html.escape(doc_map[doc_id]['display_name'])}</th>" for doc_id in visible_docs)

    body_rows: list[str] = []
    for row in rows:
        variant_class = variant_slug(row["variant_type"])
        cells = [
            f'<td class="index-col">{row["row_index"]}</td>',
            f'<td class="type-col"><span class="type-badge type-{variant_class}">{html.escape(row["variant_type"])}</span></td>',
        ]
        for doc_id in visible_docs:
            value = cell_text(row["cells"].get(doc_id, []))
            title = cell_title(row["cells"].get(doc_id, []))
            cells.append(
                f'<td class="manuscript-cell manuscript" title="{html.escape(title)}">{html.escape(value)}</td>'
            )
        row_attrs = ' data-transposed="true"' if row["flags"].get("transposed") else ""
        body_rows.append(f'<tr class="variant-row variant-{variant_class}"{row_attrs}>{"".join(cells)}</tr>')

    table_html = f"""
    <div class="alignment-grid-shell" id="{html.escape(table_id)}">
      <table class="alignment-grid">
        <thead><tr>{''.join(header_cells)}</tr></thead>
        <tbody>{''.join(body_rows)}</tbody>
      </table>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)


def stats_dataframe(state: dict) -> pd.DataFrame:
    counts = {variant: 0 for variant in VARIANT_TYPES}
    for row in state["rows"]:
        counts[row["variant_type"]] = counts.get(row["variant_type"], 0) + 1
    return pd.DataFrame([{"Тип": key, "Строк": value} for key, value in counts.items()])


def render_stats_cards(state: dict) -> None:
    counts = {variant: 0 for variant in VARIANT_TYPES}
    for row in state["rows"]:
        counts[row["variant_type"]] = counts.get(row["variant_type"], 0) + 1
    cols = st.columns(len(VARIANT_TYPES))
    for col, variant in zip(cols, VARIANT_TYPES):
        with col:
            card(variant, str(counts[variant]))


def render_row_context(state: dict, doc_map: dict[str, dict], focus_row: int, visible_docs: list[str]) -> None:
    start = max(1, focus_row - 3)
    end = min(len(state["rows"]), focus_row + 3)
    rows = filtered_rows(state, VARIANT_TYPES, (start, end))
    render_alignment_table(rows, doc_map, visible_docs, table_id="context-grid")


def move_document_order(state: dict, document_id: str, delta: int) -> dict:
    order = state.get("visible_document_order", [])
    if document_id not in order:
        return state
    index = order.index(document_id)
    target = index + delta
    if target < 0 or target >= len(order):
        return state
    order[index], order[target] = order[target], order[index]
    state["visible_document_order"] = order
    return state


def render_quick_instruction() -> None:
    st.markdown(
        f"""
        <div class="quick-guide">
          <div class="quick-guide-title">Быстрый старт</div>
          <div class="quick-guide-grid">
            <div><strong>1.</strong> Импортируйте XML-TEI из репозитория или загрузите новые списки.</div>
            <div><strong>2.</strong> Выберите главный список и соответствующие листы остальных рукописей.</div>
            <div><strong>3.</strong> Проверьте авто-выравнивание, исправьте спорные строки вручную.</div>
            <div><strong>4.</strong> Сохраните рабочую сессию и экспортируйте параллельный TEI.</div>
          </div>
          <div class="quick-guide-repo">Репозиторий: <a href="{REPOSITORY_URL}" target="_blank">{REPOSITORY_URL}</a></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_alignment_tab(storage: RepositoryStorage, engine: AlignmentEngine) -> None:
    new_alignment_id = create_alignment_form(storage, engine)
    alignments = storage.list_alignments()
    if not alignments:
        st.info("Сохранённых выравниваний пока нет.")
        return

    alignment_options = {item["name"] + f" ({item['alignment_id']})": item["alignment_id"] for item in alignments}
    default_label = next((label for label, value in alignment_options.items() if value == new_alignment_id), next(iter(alignment_options)))
    selected_label = st.selectbox(
        "Открыть сохранённое выравнивание",
        list(alignment_options),
        index=list(alignment_options).index(default_label),
    )
    state = storage.load_alignment(alignment_options[selected_label])
    doc_map = load_document_name_map(storage)

    st.subheader("Рабочая сессия")
    top_left, top_mid, top_right = st.columns(3)
    with top_left:
        card("Название", state["name"], "Сессия хранится в SQLite и доступна после перезапуска")
    with top_mid:
        card("Строк выравнивания", str(len(state["rows"])), "Каждая строка — единица сравнения")
    with top_right:
        card("Главный список", doc_map[state["master_doc_id"]]["display_name"], "Опорный текст для авто-выравнивания")

    st.markdown("### Порядок следования списков")
    doc_choice = st.selectbox(
        "Переставить список",
        state["visible_document_order"],
        format_func=lambda doc_id: doc_map[doc_id]["display_name"],
    )
    c1, c2, c3 = st.columns([1, 1, 4])
    with c1:
        if st.button("Выше", use_container_width=True):
            state = move_document_order(state, doc_choice, -1)
            storage.save_alignment(state)
    with c2:
        if st.button("Ниже", use_container_width=True):
            state = move_document_order(state, doc_choice, 1)
            storage.save_alignment(state)
    with c3:
        order_text = " → ".join(doc_map[doc_id]["display_name"] for doc_id in state["visible_document_order"])
        st.caption("Текущий порядок: " + order_text)

    st.markdown("### Фильтры просмотра")
    visible_docs = st.multiselect(
        "Показывать списки",
        options=state["visible_document_order"],
        default=state["visible_document_order"],
        format_func=lambda doc_id: doc_map[doc_id]["display_name"],
    )
    if not visible_docs:
        visible_docs = state["visible_document_order"]
    variant_filter = st.multiselect("Показывать типы разночтений", VARIANT_TYPES, default=VARIANT_TYPES)
    row_span = st.slider("Диапазон строк", 1, max(1, len(state["rows"])), (1, min(120, len(state["rows"]))))
    rows = filtered_rows(state, variant_filter, row_span)
    render_alignment_table(rows, doc_map, visible_docs, table_id="main-grid")

    st.markdown("### Статистика разночтений")
    render_stats_cards(state)

    st.markdown("### Ручная коррекция")
    focus_row = st.number_input(
        "Строка для редактирования",
        min_value=1,
        max_value=max(1, len(state["rows"])),
        value=min(row_span[0], len(state["rows"])),
        step=1,
    )
    render_row_context(state, doc_map, focus_row, visible_docs)

    editable_docs = state["visible_document_order"]
    selected_doc = st.selectbox(
        "Какой список правим",
        editable_docs,
        format_func=lambda doc_id: doc_map[doc_id]["display_name"],
    )
    b1, b2, b3, b4, b5 = st.columns(5)
    with b1:
        if st.button("Сдвинуть вверх", use_container_width=True):
            state = engine.move_cell(state, row_index=focus_row - 1, document_id=selected_doc, delta=-1)
            storage.save_alignment(state)
    with b2:
        if st.button("Сдвинуть вниз", use_container_width=True):
            state = engine.move_cell(state, row_index=focus_row - 1, document_id=selected_doc, delta=1)
            storage.save_alignment(state)
    with b3:
        if st.button("Вставить пустую выше", use_container_width=True):
            state = engine.insert_empty_row(state, row_index=focus_row - 1)
            storage.save_alignment(state)
    with b4:
        if st.button("Вставить пустую ниже", use_container_width=True):
            state = engine.insert_empty_row(state, row_index=focus_row)
            storage.save_alignment(state)
    with b5:
        if st.button("Склеить с нижней", use_container_width=True):
            state = engine.merge_down(state, row_index=focus_row - 1, document_id=selected_doc)
            storage.save_alignment(state)

    c1, c2, c3 = st.columns([2, 1.5, 1.5])
    with c1:
        manual_type = st.selectbox(
            "Исправить тип разночтения",
            VARIANT_TYPES,
            index=VARIANT_TYPES.index(state["rows"][focus_row - 1]["variant_type"]),
        )
    with c2:
        if st.button("Сохранить тип", use_container_width=True):
            state = engine.set_variant_type(state, row_index=focus_row - 1, variant_type=manual_type)
            storage.save_alignment(state)
    with c3:
        if st.button("Удалить пустую строку", use_container_width=True):
            state = engine.delete_row_if_empty(state, row_index=focus_row - 1)
            storage.save_alignment(state)

    if st.button("Пересчитать автоматические типы заново", use_container_width=True):
        state = engine.reclassify(state)
        storage.save_alignment(state)
        st.success("Автоматическая классификация обновлена.")

    st.markdown("### Экспорт XML-TEI")
    if st.button("Сформировать XML-TEI для параллельного корпуса", use_container_width=True):
        tei_text = export_alignment_to_tei(storage=storage, alignment_state=state)
        export_path = storage.save_export(state["alignment_id"], tei_text)
        state["export_path"] = export_path
        storage.save_alignment(state)
        st.success(f"Экспорт сохранён: {export_path}")

    if state.get("export_path"):
        export_text = Path(state["export_path"]).read_text(encoding="utf-8")
        st.download_button(
            "Скачать XML-TEI",
            data=export_text,
            file_name=Path(state["export_path"]).name,
            mime="application/xml",
            use_container_width=True,
        )


def render_help_tab() -> None:
    st.subheader("Как устроено приложение")
    st.markdown(
        """
        <div class="help-card">
          <h3>Краткая инструкция</h3>
          <ol class="guide-list">
            <li>Импортируйте XML-TEI из корня проекта или добавьте новые файлы через загрузчик.</li>
            <li>Создайте сессию выравнивания: выберите главный список, затем листы главного и остальных списков.</li>
            <li>Просмотрите авто-результат, фильтруйте разночтения и вручную поправляйте ошибочные строки.</li>
            <li>Все изменения сохраняются автоматически, поэтому к работе можно вернуться в следующий сеанс.</li>
            <li>Экспорт создаёт отдельный TEI-файл параллельного корпуса и не изменяет исходные рукописные XML.</li>
          </ol>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="help-card">
          <h3>Где что хранится</h3>
          <ul class="plain-list">
            <li><code>storage/uploads</code> — исходные XML-TEI.</li>
            <li><code>storage/parsed</code> — разобранные токены и метаданные для повторного открытия.</li>
            <li><code>storage/corpus.db</code> — документы, выравнивания, ручные правки и ссылки на экспорт.</li>
            <li><code>storage/exports</code> — выгруженные XML-TEI параллельного корпуса.</li>
          </ul>
          <p><strong>Репозиторий проекта:</strong> <a href="{REPOSITORY_URL}" target="_blank">{REPOSITORY_URL}</a></p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    inject_styles()
    storage = get_storage()
    engine = AlignmentEngine(storage)

    render_repo_callout()
    render_sidebar_guide()
    render_font_panel()

    st.markdown(
        f"""
        <section class="hero-shell">
          <div class="hero-kicker">Академическая демонстрация параллельного корпуса</div>
          <h1>Параллельный корпус списков «Притча о блудном сыне»</h1>
          <p>
            Приложение загружает XML-TEI, извлекает слова и атрибуты, автоматически выравнивает списки,
            показывает разночтения, сохраняет ручные правки и экспортирует результат в TEI-представление корпуса.
          </p>
          <div class="hero-links">
            <a href="{REPOSITORY_URL}" target="_blank">Открыть репозиторий</a>
            <span>Постоянное хранилище: <code>storage/</code></span>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    render_quick_instruction()

    docs = storage.list_documents()
    col1, col2, col3 = st.columns(3)
    with col1:
        card("Импортировано списков", str(len(docs)), "Доступны сразу после повторного запуска")
    with col2:
        card("Сохранено выравниваний", str(len(storage.list_alignments())), "Сессии не теряются между сеансами")
    with col3:
        word_total = sum(doc["word_count"] for doc in docs)
        card("Слов в хранилище", str(word_total), "Импортированные TEI-токены")

    tab1, tab2, tab3 = st.tabs(["Библиотека", "Выравнивание", "Справка"])
    with tab1:
        render_library_tab(storage)
    with tab2:
        render_alignment_tab(storage, engine)
    with tab3:
        render_help_tab()


if __name__ == "__main__":
    main()
