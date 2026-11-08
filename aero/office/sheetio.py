"""Lectura y escritura de hojas de cálculo para el editor.

* XLSX/XLSM: openpyxl conserva fórmulas, formatos de celda, anchos, celdas combinadas, validaciones y
  (en XLSM) las macros sin ejecutarlas. Los gráficos e imágenes que ya tenga el archivo NO los conserva
  openpyxl: se detecta y se avisa antes de guardar (se propone una copia).
* XLS, XLSB y ODS: se leen los valores con calamine (rápido); al guardar se crea un XLSX (las fórmulas del
  original no se recuperan) o un ODS solo con valores. Se avisa.
* CSV/TSV: valores (con detección del separador y de los números con coma decimal).
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook, load_workbook

READ_EXT = {".xlsx", ".xlsm", ".xls", ".xlsb", ".ods", ".csv", ".tsv"}
WRITE_FORMATS = {"xlsx": "Excel (XLSX)", "csv": "CSV (hoja actual)", "ods": "OpenDocument (ODS, solo valores)"}


@dataclass
class LoadedBook:
    wb: Workbook
    cached: Workbook | None = None      # valores calculados guardados por la aplicación de origen
    unsupported: list[str] = field(default_factory=list)
    source: str = "xlsx"


def _number(text: str):
    t = text.strip()
    if not t:
        return None
    if t.startswith("="):
        return t
    for cand in (t, t.replace(".", "").replace(",", ".") if "," in t else t):
        try:
            v = float(cand)
            return int(v) if v.is_integer() and "." not in cand and "e" not in cand.lower() else v
        except ValueError:
            continue
    return text


def load(path: str) -> LoadedBook:
    ext = Path(path).suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        wb = load_workbook(path, keep_vba=ext == ".xlsm")
        try:
            cached = load_workbook(path, data_only=True, read_only=False)
        except Exception:  # noqa: BLE001
            cached = None
        return LoadedBook(wb, cached, _scan_xlsx(path), "xlsx")
    if ext in (".csv", ".tsv"):
        raw = Path(path).read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
            delim = dialect.delimiter
        except csv.Error:
            delim = "\t" if ext == ".tsv" else ","
        wb = Workbook()
        ws = wb.active
        ws.title = Path(path).stem[:31] or "Hoja1"
        for row in csv.reader(io.StringIO(text), delimiter=delim):
            ws.append([_number(c) for c in row])
        return LoadedBook(wb, None, [], "csv")
    # XLS, XLSB, ODS: valores con calamine
    from python_calamine import CalamineWorkbook

    cw = CalamineWorkbook.from_path(path)
    wb = Workbook()
    wb.remove(wb.active)
    for name in cw.sheet_names:
        ws = wb.create_sheet(name[:31])
        for row in cw.get_sheet_by_name(name).to_python(skip_empty_area=False):
            ws.append([None if v == "" else v for v in row])
    if not wb.sheetnames:
        wb.create_sheet("Hoja1")
    return LoadedBook(wb, None, [f"{ext.upper().lstrip('.')}: se abren los valores; las fórmulas y el formato del "
                                 "original no se recuperan"], ext.lstrip("."))


def _scan_xlsx(path: str) -> list[str]:
    found = []
    try:
        names = zipfile.ZipFile(path).namelist()
    except zipfile.BadZipFile:
        return found
    if any(n.startswith("xl/charts/") for n in names):
        found.append("gráficos existentes")
    if any(n.startswith("xl/media/") for n in names):
        found.append("imágenes")
    if any(n.startswith("xl/pivotTables/") for n in names):
        found.append("tablas dinámicas")
    if any(n.startswith("xl/slicers/") for n in names):
        found.append("segmentaciones")
    return found


def save(book: LoadedBook, path: str, sheet: str | None = None, evaluator=None) -> None:
    ext = Path(path).suffix.lower()
    wb = book.wb
    if ext in (".xlsx", ".xlsm"):
        wb.save(path)
        return
    ws = wb[sheet] if sheet else wb.active

    def val(r, c):
        v = ws.cell(r, c).value
        if evaluator is not None and isinstance(v, str) and v.startswith("="):
            v = evaluator.value(ws.title, r, c)
        return v

    rows = [[val(r, c) for c in range(1, ws.max_column + 1)] for r in range(1, ws.max_row + 1)]
    if ext in (".csv", ".tsv"):
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter="\t" if ext == ".tsv" else ";")
            for row in rows:
                w.writerow(["" if v is None else (str(v).replace(".", ",") if isinstance(v, float) else v)
                            for v in row])
        return
    if ext == ".ods":
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.table import Table, TableCell, TableRow
        from odf.text import P

        od = OpenDocumentSpreadsheet()
        for name in wb.sheetnames:
            sws = wb[name]
            t = Table(name=name)
            for r in range(1, sws.max_row + 1):
                tr = TableRow()
                for c in range(1, sws.max_column + 1):
                    v = sws.cell(r, c).value
                    if evaluator is not None and isinstance(v, str) and v.startswith("="):
                        v = evaluator.value(name, r, c)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        tc = TableCell(valuetype="float", value=v)
                    else:
                        tc = TableCell(valuetype="string")
                    if v is not None:
                        tc.addElement(P(text=str(v)))
                    tr.addElement(tc)
                t.addElement(tr)
            od.spreadsheet.addElement(t)
        od.save(path)
        return
    raise ValueError(f"No se puede guardar en formato {ext.upper()}.")
