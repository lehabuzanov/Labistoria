from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.dom import minidom

from .alignment import GRAPHICAL, LEXICAL, MORPHOLOGICAL, PHONETIC, SYNTACTIC


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("", TEI_NS)


def export_alignment_to_tei(*, storage, alignment_state: dict) -> str:
    root = ET.Element(f"{{{TEI_NS}}}TEI")
    tei_header = ET.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    file_desc = ET.SubElement(tei_header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = ET.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    title = ET.SubElement(title_stmt, f"{{{TEI_NS}}}title")
    title.text = alignment_state["name"]
    publication_stmt = ET.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    ET.SubElement(publication_stmt, f"{{{TEI_NS}}}p").text = "Экспорт параллельного корпуса из Streamlit-приложения."
    source_desc = ET.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    list_wit = ET.SubElement(source_desc, f"{{{TEI_NS}}}listWit")

    doc_order = [alignment_state["master_doc_id"]] + [item["document_id"] for item in alignment_state.get("witnesses", [])]
    for doc_id in doc_order:
        doc = storage.get_document(doc_id)
        witness = ET.SubElement(list_wit, f"{{{TEI_NS}}}witness")
        witness.set(f"{{{XML_NS}}}id", f"wit-{doc_id}")
        ET.SubElement(witness, f"{{{TEI_NS}}}abbr").text = doc["display_name"]
        ET.SubElement(witness, f"{{{TEI_NS}}}title").text = doc["title"]
        ET.SubElement(witness, f"{{{TEI_NS}}}idno", {"type": "internal"}).text = doc_id

    encoding_desc = ET.SubElement(tei_header, f"{{{TEI_NS}}}encodingDesc")
    class_decl = ET.SubElement(encoding_desc, f"{{{TEI_NS}}}classDecl")
    taxonomy = ET.SubElement(class_decl, f"{{{TEI_NS}}}taxonomy")
    for variant in [GRAPHICAL, PHONETIC, MORPHOLOGICAL, SYNTACTIC, LEXICAL]:
        category = ET.SubElement(taxonomy, f"{{{TEI_NS}}}category")
        category.set(f"{{{XML_NS}}}id", variant_slug(variant))
        ET.SubElement(category, f"{{{TEI_NS}}}catDesc").text = variant

    text = ET.SubElement(root, f"{{{TEI_NS}}}text")
    body = ET.SubElement(text, f"{{{TEI_NS}}}body")
    div = ET.SubElement(body, f"{{{TEI_NS}}}div", {"type": "parallel-alignment"})
    div.set(f"{{{XML_NS}}}id", alignment_state["alignment_id"])
    ET.SubElement(div, f"{{{TEI_NS}}}head").text = alignment_state["name"]

    list_app = ET.SubElement(div, f"{{{TEI_NS}}}listApp")
    for row in alignment_state["rows"]:
        app = ET.SubElement(list_app, f"{{{TEI_NS}}}app")
        app.set(f"{{{XML_NS}}}id", row["row_id"])
        app.set("ana", f"#{variant_slug(row['variant_type'])}")
        app.set("type", row["variant_type"])
        if row.get("notes"):
            app.set("n", row["notes"])
        for doc_id in doc_order:
            cell = row["cells"].get(doc_id, [])
            if not cell:
                continue
            rdg = ET.SubElement(app, f"{{{TEI_NS}}}rdg")
            rdg.set("wit", f"#wit-{doc_id}")
            rdg.set("corresp", " ".join(f"storage://documents/{doc_id}#token/{item['token_id']}" for item in cell))
            rdg.set("source", f"storage://documents/{doc_id}")
            rdg.text = " ".join(item["text"] for item in cell)
            first = cell[0]
            if first.get("sheet"):
                rdg.set("subtype", f"sheet:{first['sheet']}")
            if first.get("page"):
                rdg.set("resp", f"page:{first['page']}")
            if first.get("line") is not None:
                rdg.set("loc", f"line:{first['line']}")

    rough = ET.tostring(root, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def variant_slug(value: str) -> str:
    mapping = {
        GRAPHICAL: "graphical",
        PHONETIC: "phonetic",
        MORPHOLOGICAL: "morphological",
        SYNTACTIC: "syntactic",
        LEXICAL: "lexical",
    }
    return mapping.get(value, "variant")

