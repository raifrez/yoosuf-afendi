"""Stream selected columns from XLSX using only the Python standard library.

The supplied exports contain labels in row 1, a blank row, and variable names
in row 2 or 3. Discover the variable header rather than treating labels as data.
"""

from collections import deque
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
from xml.parsers import expat
import zipfile


NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def sheet_paths(archive):
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {r.attrib["Id"]: r.attrib["Target"] for r in relationships}
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    for sheet in workbook.find(NS + "sheets"):
        target = targets[sheet.attrib[REL]]
        path = target.lstrip("/") if target.startswith("/") else str(PurePosixPath("xl") / target)
        yield sheet.attrib["name"], path


def rows(path, columns=None, header_key=None, sheet=None):
    """Yield row dictionaries; columns=None includes every column in the header.

    header_key identifies the variable-name row (e.g. unit__id or uqhh__id).
    Without it the first nonempty row is the header, useful for dictionaries.
    """
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            with archive.open("xl/sharedStrings.xml") as source:
                for _, element in ET.iterparse(source, events=("end",)):
                    if element.tag == NS + "si":
                        strings.append("".join(t.text or "" for t in element.iter(NS + "t")))
                        element.clear()
        candidates = list(sheet_paths(archive))
        selected = next(((name, name_path) for name, name_path in candidates if sheet is None or name == sheet), None)
        if selected is None:
            raise ValueError(f"Worksheet {sheet!r} not found in {path}")
        queue = deque()
        state = {"header": None, "row": {}, "column": None, "type": None,
                 "capture": False, "text": [], "row_number": 0}
        wanted = set(columns) if columns is not None else None

        def start(tag, attrs):
            tag = tag.rsplit(":", 1)[-1]
            if tag == "row":
                state["row"] = {}
                state["row_number"] = int(attrs.get("r", 0))
            elif tag == "c":
                ref = attrs.get("r", "")
                column = ref.rstrip("0123456789")
                state["column"] = column
                state["type"] = attrs.get("t")
                state["text"] = []
            elif tag in ("v", "t"):
                header = state["header"]
                state["capture"] = header is None or state["column"] in header

        def text(value):
            if state["capture"]:
                state["text"].append(value)

        def end(tag):
            tag = tag.rsplit(":", 1)[-1]
            if tag in ("v", "t"):
                state["capture"] = False
            elif tag == "c":
                value = "".join(state["text"])
                if value and state["type"] == "s":
                    value = strings[int(value)]
                if value:
                    state["row"][state["column"]] = value
            elif tag == "row":
                values = state["row"]
                if state["header"] is None:
                    if values and (header_key is None or header_key in values.values()):
                        if wanted is not None and not wanted.issubset(values.values()):
                            raise ValueError(f"{path}: missing columns {sorted(wanted - set(values.values()))}")
                        state["header"] = {c: v for c, v in values.items() if wanted is None or v in wanted}
                    elif state["row_number"] > 20:
                        raise ValueError(f"Variable header {header_key!r} not found in first 20 rows of {path}")
                elif values:
                    queue.append({key: values.get(col, "") for col, key in state["header"].items()})

        parser = expat.ParserCreate()
        parser.StartElementHandler = start
        parser.EndElementHandler = end
        parser.CharacterDataHandler = text
        with archive.open(selected[1]) as source:
            while True:
                chunk = source.read(262144)
                parser.Parse(chunk, not chunk)
                while queue:
                    yield queue.popleft()
                if not chunk:
                    break
        if state["header"] is None:
            raise ValueError(f"No header found in {path}")
