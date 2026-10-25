#!/usr/bin/env python3
"""Transfer selected authored Notes paragraphs into an original PPTX package.

All selected slides must already have Notes parts in both decks. Every other ZIP
entry is copied from the original unchanged, preserving slides and animations.
Requires lxml (available in the Codex presentation runtime).
"""

from __future__ import annotations

import argparse
import posixpath
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/package/2006/relationships}"
NS = {"p": P[1:-1]}
NOTES_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"


def slide_count(archive: ZipFile) -> int:
    return sum(
        name.startswith("ppt/slides/slide")
        and name.endswith(".xml")
        and name[len("ppt/slides/slide") : -len(".xml")].isdigit()
        for name in archive.namelist()
    )


def note_part(archive: ZipFile, slide: int) -> str:
    rels = f"ppt/slides/_rels/slide{slide}.xml.rels"
    if rels not in archive.namelist():
        raise ValueError(f"slide {slide} has no relationships part")
    root = etree.fromstring(archive.read(rels))
    matches = [r.get("Target", "") for r in root.findall(R + "Relationship")
               if r.get("Type") == NOTES_TYPE]
    if len(matches) != 1:
        raise ValueError(f"slide {slide} must have exactly one existing Notes part")
    target = matches[0]
    part = (target.lstrip("/") if target.startswith("/")
            else posixpath.normpath(posixpath.join("ppt/slides", target)))
    if part not in archive.namelist():
        raise ValueError(f"Notes part missing for slide {slide}: {part}")
    return part


def body_paragraphs(data: bytes):
    root = etree.fromstring(data)
    bodies = []
    for shape in root.xpath(".//p:sp", namespaces=NS):
        placeholder = shape.xpath("./p:nvSpPr/p:nvPr/p:ph", namespaces=NS)
        if placeholder and placeholder[0].get("type") == "body":
            bodies.append(shape.find(P + "txBody"))
    if len(bodies) != 1 or bodies[0] is None:
        raise ValueError("expected one Notes body placeholder")
    return root, bodies[0], bodies[0].findall(A + "p")


def transfer(source: Path, authored: Path, output: Path, slides: list[int]) -> None:
    if source.resolve() == output.resolve() or authored.resolve() == output.resolve():
        raise ValueError("output must be a new file")
    if not slides or len(slides) != len(set(slides)):
        raise ValueError("provide unique slide numbers")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(source) as original, ZipFile(authored) as edited:
        count = slide_count(original)
        if count != slide_count(edited):
            raise ValueError("source and authored decks have different slide counts")
        if any(not 1 <= slide <= count for slide in slides):
            raise ValueError(f"slide numbers must be between 1 and {count}")
        patches: dict[str, bytes] = {}
        for slide in slides:
            original_part = note_part(original, slide)
            authored_part = note_part(edited, slide)
            tree, body, old_paragraphs = body_paragraphs(original.read(original_part))
            _, _, new_paragraphs = body_paragraphs(edited.read(authored_part))
            for paragraph in old_paragraphs:
                body.remove(paragraph)
            for paragraph in new_paragraphs:
                body.append(deepcopy(paragraph))
            patches[original_part] = etree.tostring(
                tree, xml_declaration=True, encoding="UTF-8", standalone=True
            )
        with ZipFile(output, "w") as result:
            for info in original.infolist():
                result.writestr(info, patches.get(info.filename, original.read(info.filename)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="original user PPTX")
    parser.add_argument("--authored", type=Path, required=True, help="PPTX with revised Notes")
    parser.add_argument("--output", type=Path, required=True, help="new PPTX path")
    parser.add_argument("--slides", type=int, nargs="+", required=True, help="1-based slide numbers")
    args = parser.parse_args()
    transfer(args.source, args.authored, args.output, args.slides)
    print(args.output)


if __name__ == "__main__":
    main()
