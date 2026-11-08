"""Hojas de cálculo: fórmulas conservadas y recalculadas, formato, ordenar, filtrar, hojas, gráficos y formatos."""

import time

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill


def _book(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Ventas"
    ws.append(["Mes", "Unidades", "Precio", "Total"])
    for i, (m, u, p) in enumerate([("Marzo", 30, 2.5), ("Enero", 10, 3.0), ("Febrero", 20, 2.0)], start=2):
        ws.append([m, u, p, f"=B{i}*C{i}"])
    ws["D5"] = "=SUM(D2:D4)"
    ws["A1"].font = Font(bold=True)
    ws["A1"].fill = PatternFill("solid", fgColor="FFFFF2A8")
    ws["D2"].number_format = "#,##0.00 €"
    other = wb.create_sheet("Resumen")
    other["A1"] = "=Ventas!D5*2"
    wb.save(str(path))


def _wait(qapp, cond, t=10):
    end = time.monotonic() + t
    while time.monotonic() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)


def test_formulas_evaluate_and_survive_save(qapp, tmp_path, controller):
    src = tmp_path / "ventas.xlsx"
    _book(src)
    ed = controller.open_sheet_editor(str(src))
    m = ed.model
    assert m.data(m.index(4, 3)) == "145", "SUM de los totales calculados (75 + 30 + 40)"
    assert m.data(m.index(1, 3)) == "75,00 €", "formato numérico de moneda"
    assert m.data(m.index(0, 0), 0x0006).bold(), "negrita leída (FontRole)"
    # Editar un valor recalcula las fórmulas dependientes, también en otra hoja
    m.setData(m.index(1, 1), "40")
    assert m.data(m.index(4, 3)) == "170"
    assert ed.ev.value("Resumen", 1, 1) == 340
    ed.view.setCurrentIndex(m.index(5, 1))
    ed.formula.setText("=PROMEDIO(B2:B4)")
    ed.commit_formula()
    assert m.data(m.index(5, 1)).startswith("23,333"), "fórmula escrita en la barra con nombre en español"
    out = tmp_path / "ventas_editado.xlsx"
    ed.save_to(str(out))
    wb = load_workbook(str(out))
    ws = wb["Ventas"]
    assert ws["D5"].value == "=SUM(D2:D4)" and ws["D2"].value == "=B2*C2", "las fórmulas se guardan tal cual"
    assert ws["B2"].value == 40 and ws["B6"].value == "=PROMEDIO(B2:B4)"
    assert ws["A1"].font.b and ws["A1"].fill.fgColor.rgb.endswith("FFF2A8"), "el formato se conserva"
    assert wb["Resumen"]["A1"].value == "=Ventas!D5*2"
    ed.dirty = False
    ed.close()


def test_sort_filter_sheets_chart_and_undo(qapp, tmp_path, controller):
    src = tmp_path / "ventas.xlsx"
    _book(src)
    ed = controller.open_sheet_editor(str(src))
    m = ed.model
    ed.view.setCurrentIndex(m.index(0, 0))
    ed.sort_column(False)
    assert [m.data(m.index(r, 0)) for r in (1, 2, 3)] == ["Enero", "Febrero", "Marzo"]
    ed.undo()
    assert m.data(m.index(1, 0)) == "Marzo", "deshacer el orden"
    ed.filter.setText("ene")
    hidden = [ed.view.isRowHidden(r) for r in (1, 2, 3)]
    assert hidden == [True, False, True]
    ed.filter.clear()
    # Formato: negrita y relleno sobre la selección
    ed.view.selectionModel().select(m.index(1, 1), ed.view.selectionModel().SelectionFlag.ClearAndSelect)
    ed.toggle_font("b")
    assert ed.model.ws["B2"].font.b
    ed.add_sheet()
    assert len(ed.book.wb.sheetnames) == 3
    # Gráfico de barras con A1:B4
    sel = ed.view.selectionModel()
    sel.clearSelection()
    for r in range(4):
        for c in range(2):
            sel.select(m.index(r, c), sel.SelectionFlag.Select)
    ed.tabs.setCurrentIndex(0)
    for r in range(4):
        for c in range(2):
            sel.select(m.index(r, c), sel.SelectionFlag.Select)
    ed.insert_chart("Barras", preview=False)
    out = tmp_path / "con_grafico.xlsx"
    ed.save_to(str(out))
    ws = load_workbook(str(out))["Ventas"]
    import zipfile

    assert any(n.startswith("xl/charts/") for n in zipfile.ZipFile(out).namelist()), "gráfico guardado en el XLSX"
    assert ws["B2"].font.b
    ed.dirty = False
    ed.close()


def test_csv_ods_xls_formats(qapp, tmp_path, controller):
    from aero.office import sheetio
    from aero.office.formula import Evaluator

    csv_path = tmp_path / "datos.csv"
    csv_path.write_text("Nombre;Importe\nAna;1.234,5\nLuis;20\n", encoding="utf-8")
    book = sheetio.load(str(csv_path))
    ws = book.wb.active
    assert ws["B2"].value == 1234.5 and ws["B3"].value == 20, "números con coma decimal"
    src = tmp_path / "ventas.xlsx"
    _book(src)
    book = sheetio.load(str(src))
    ev = Evaluator(book.wb, book.cached)
    sheetio.save(book, str(tmp_path / "v.csv"), "Ventas", ev)
    lines = (tmp_path / "v.csv").read_text(encoding="utf-8-sig").splitlines()
    assert lines[-1].endswith(";145") or lines[-1].endswith(";145,0"), lines[-1]
    sheetio.save(book, str(tmp_path / "v.ods"), None, ev)
    back = sheetio.load(str(tmp_path / "v.ods"))
    assert back.wb["Ventas"]["D5"].value == 145 and back.unsupported, "ODS: valores y aviso"
