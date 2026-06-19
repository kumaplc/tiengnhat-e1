"""
Control IronCAD scene parts from Python through COM.

Examples:
  python ironcad_part_controller.py purchase LIST.csv --rgb 255,0,0
  python ironcad_part_controller.py selected
  python ironcad_part_controller.py 11 --rgb 255,0,0
  python ironcad_part_controller.py paint 11 --rgb 255,0,0
  python ironcad_part_controller.py interactive
  python ironcad_part_controller.py color --name PART_001 --rgb 255,0,0
  python ironcad_part_controller.py hide --name PART_001
  python ironcad_part_controller.py show --id 12345
  python ironcad_part_controller.py members --name PART_001 --filter color

Run IronCAD first and open a Scene before using this script.
Install COM support once with:
  python -m pip install pywin32
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pythoncom
import win32com.client
import win32com.client.gencache


# IronCAD 27's Eye automation type library can generate broken pywin32
# child wrappers for Shapes/IShapesDisp. Force late binding so returned COM
# collections stay usable after someone has run makepy/EnsureDispatch.
win32com.client.gencache.GetClassForCLSID = lambda clsid: None


PROG_IDS = (
    "IronCAD.Application",
    "IRONCAD.Application",
    "IronCAD.Application.2025",
    "IRONCAD.Application.2025",
    "IronCAD.Application.27",
    "IronCAD.Application.27",
)

PART_TYPES = {
    1: "part/assembly",
}

COLOR_PROPERTIES = (
    "SurfaceColor",
    "Color",
    "RGBColor",
    "DiffuseColor",
    "FaceColor",
    "RenderColor",
)

COLOR_METHODS = (
    "SetColor",
    "SetRGBColor",
    "SetDiffuseColor",
    "SetFaceColor",
    "SetRenderColor",
    "SetPartColor",
    "SetSmartPaintColor",
)

VISIBILITY_PROPERTIES = (
    "Visible",
    "IsVisible",
    "Hidden",
    "IsHidden",
    "Suppressed",
    "IsSuppressed",
)

SHOW_METHODS = ("Show", "ShowPart", "ShowElement", "Unhide", "UnHide", "Unsuppress")
HIDE_METHODS = ("Hide", "HidePart", "HideElement", "Suppress")
DEFAULT_OK_STATUS = "O"
DEFAULT_OK_COLOR = (255, 0, 0)


@dataclass
class SceneItem:
    element: object
    depth: int
    name: str
    system_name: str
    element_id: str
    type_value: object


@dataclass
class PurchaseRow:
    code: str
    status: str
    line_number: int


class IronCadControllerError(RuntimeError):
    pass


def connect_ironcad():
    pythoncom.CoInitialize()
    errors: list[str] = []

    for prog_id in PROG_IDS:
        try:
            return win32com.client.GetActiveObject(prog_id)
        except Exception as exc:
            errors.append(f"{prog_id}: {exc}")

    raise IronCadControllerError(
        "Khong ket noi duoc IronCAD dang chay. Hay mo IronCAD truoc.\n"
        + "\n".join(errors)
    )


def active_scene_doc(app):
    candidates = []
    for name in ("ActivePage", "ActiveScene", "ActiveDocument"):
        try:
            value = getattr(app, name)
        except Exception:
            continue
        if value is not None:
            candidates.append((name, value))

    for origin, candidate in candidates:
        if has_member(candidate, "GetTopElement"):
            return candidate

    for origin, candidate in candidates:
        if has_member(candidate, "Shape") or has_member(candidate, "SelectedItems"):
            return candidate

    details = ", ".join(origin for origin, _ in candidates) or "none"
    raise IronCadControllerError(
        "Khong tim thay Scene dang active. Hay mo/click vao cua so Scene trong IronCAD. "
        f"Candidates: {details}"
    )


def has_member(obj, name: str) -> bool:
    try:
        getattr(obj, name)
        return True
    except Exception:
        return False


def safe_get(obj, name: str, default=""):
    try:
        value = getattr(obj, name)
        return "" if value is None else value
    except Exception:
        return default


def safe_call(obj, name: str, *args):
    member = getattr(obj, name)
    return member(*args)


def iter_scene_items(scene_doc) -> Iterable[SceneItem]:
    # Chỉ sử dụng iter_page_items để lấy các part ở depth 3
    # Nếu scene có GetTopElement, vẫn dùng iter_element_children nhưng giới hạn depth
    if has_member(scene_doc, "GetTopElement"):
        # Giới hạn depth = 3 (chỉ lấy part)
        top = safe_call(scene_doc, "GetTopElement")
        yield from iter_element_children_limited(top, depth=0, max_depth=3)
    else:
        yield from iter_page_items(scene_doc)


# Hàm mới: đệ quy có giới hạn depth
def iter_element_children_limited(element, depth: int, max_depth: int) -> Iterable[SceneItem]:
    yield make_scene_item(element, depth)
    if depth >= max_depth:
        return
    children = get_children(element)
    for child in children:
        yield from iter_element_children_limited(child, depth + 1, max_depth)


# Prefix của node chính chứa part thật. Node khác (不要, アセンブリ...) bị bỏ qua.
MAIN_NODE_PREFIX = "M566-00"

def iter_page_items(page) -> Iterable[SceneItem]:
    """
    Quét có chọn lọc: chỉ đi vào node bắt đầu bằng MAIN_NODE_PREFIX.
    Dừng ở depth-3 (part level) - không đệ quy vào shape con của part.
    Cấu trúc:
      root.Shape (depth-0)
        └── M566-00 外観図 (depth-1)  ← chỉ quét đây
            └── M566-01 架台部 (depth-2, section)
                └── M566-01001 架台 (depth-3) ← DỪNG Ở ĐÂY
    """
    try:
        shape = page.Shape
        depth1 = shape.ChildShapes
        count1 = int(depth1.Count)
    except Exception:
        return

    # Tìm node chính (M566-00 外観図)
    main_node = None
    for i in range(1, count1 + 1):
        try:
            node = depth1.Item(i)
            name = str(node.Name) if hasattr(node, "Name") else ""
            if name.startswith(MAIN_NODE_PREFIX):
                main_node = node
                break
        except Exception:
            continue

    if main_node is None:
        # Fallback: nếu không tìm thấy node chính, quét depth-1 thôi
        for i in range(1, count1 + 1):
            try:
                node = depth1.Item(i)
                yield make_scene_item(node, depth=1)
            except Exception:
                continue
        return

    # Quét sections (depth-2)
    try:
        sections = main_node.ChildShapes
        count2 = int(sections.Count)
    except Exception:
        return

    for si in range(1, count2 + 1):
        try:
            section = sections.Item(si)
            yield make_scene_item(section, depth=2)
        except Exception:
            continue

        # Quét parts (depth-3) - CHỈ đọc Name, KHÔNG gọi ChildShapes
        try:
            parts = section.ChildShapes
            count3 = int(parts.Count)
        except Exception:
            continue

        for pi in range(1, count3 + 1):
            try:
                part = parts.Item(pi)
                yield make_scene_item(part, depth=3)
            except Exception:
                continue


def iter_tree_shape(tree_shape, depth: int) -> Iterable[SceneItem]:
    yield make_scene_item(tree_shape, depth)

    try:
        child_shapes = tree_shape.ChildShapes
        count = int(child_shapes.Count)
    except Exception:
        return

    for index in range(1, count + 1):
        try:
            yield from iter_tree_shape(child_shapes.Item(index), depth + 1)
        except Exception:
            continue


def iter_element_children(element, depth: int) -> Iterable[SceneItem]:
    yield make_scene_item(element, depth)

    children = get_children(element)
    for child in children:
        yield from iter_element_children(child, depth + 1)


def get_children(element) -> list[object]:
    try:
        child_array = element.GetChildrenZArray()
    except Exception:
        return []

    count = get_zarray_count(child_array)
    children = []
    for index in range(count):
        child = get_zarray_item(child_array, index)
        if child is not None:
            children.append(child)
    return children


def get_zarray_count(zarray) -> int:
    count_member = getattr(zarray, "Count", None)
    if count_member is None:
        return 0

    try:
        return int(count_member)
    except Exception:
        pass

    try:
        return int(count_member())
    except Exception:
        pass

    # pywin32 can expose COM out parameters as return values.
    try:
        result = count_member(0)
        if isinstance(result, tuple):
            return int(result[-1])
        return int(result)
    except Exception:
        return 0


def get_zarray_item(zarray, index: int):
    get_member = getattr(zarray, "Get", None)
    if get_member is None:
        return None

    for args in ((index,), (index, None), (index, 0)):
        try:
            result = get_member(*args)
            if isinstance(result, tuple):
                return first_com_object(result)
            return result
        except Exception:
            continue

    return None


def first_com_object(values: tuple):
    for value in values:
        if hasattr(value, "_oleobj_") or value is not None:
            return value
    return None


def make_scene_item(element, depth: int) -> SceneItem:
    name = str(safe_get(element, "Name"))
    system_name = str(safe_get(element, "SystemName"))
    element_id = str(safe_get(element, "Id"))
    if not element_id:
        element_id = system_name or name

    return SceneItem(
        element=element,
        depth=depth,
        name=name,
        system_name=system_name,
        element_id=element_id,
        type_value=safe_get(element, "Type"),
    )


def selected_items(scene_doc) -> list[SceneItem]:
    try:
        selection = scene_doc.GetSelectedItems()
    except Exception as exc:
        try:
            selection = scene_doc.SelectedItems
        except Exception:
            raise IronCadControllerError(f"Khong doc duoc selected items: {exc}") from exc

    try:
        count = int(selection.Count)
    except Exception:
        count = 0

    items: list[SceneItem] = []
    for index in range(1, count + 1):
        try:
            items.append(make_scene_item(selection.Item(index), 0))
        except Exception as exc:
            print(f"Bo qua selected item {index}: {exc}")
    return items


def find_targets(scene_doc, args) -> list[SceneItem]:
    if args.selected:
        targets = selected_items(scene_doc)
    else:
        targets = list(iter_scene_items(scene_doc))

    if args.id:
        targets = [item for item in targets if item.element_id == str(args.id)]

    if args.name:
        pattern = args.name.lower()
        targets = [
            item
            for item in targets
            if fnmatch.fnmatch(item.name.lower(), pattern)
            or fnmatch.fnmatch(item.system_name.lower(), pattern)
        ]

    if not targets:
        raise IronCadControllerError("Khong tim thay part/element phu hop.")

    return targets


def find_part_by_number(scene_doc, number: int) -> SceneItem:
    matches = find_part_by_number_with_descendants(scene_doc, number)
    return matches[0]


def find_part_by_number_with_descendants(scene_doc, number: int) -> list[SceneItem]:
    candidates = [
        str(number),
        f"Part{number}",
        f"PART_{number:03d}",
        f"PART_{number}",
    ]
    lowered = {candidate.lower() for candidate in candidates}

    items = list(iter_scene_items(scene_doc))
    for index, item in enumerate(items):
        names = {item.name.lower(), item.system_name.lower(), item.element_id.lower()}
        if names & lowered:
            result = [item]
            for child in items[index + 1 :]:
                if child.depth <= item.depth:
                    break
                if child.name.strip():
                    result.append(child)
            return result

    raise IronCadControllerError(
        "Khong tim thay part theo so "
        f"{number}. Da thu: {', '.join(candidates)}"
    )


def find_parts_by_code(scene_doc, code: str) -> list[SceneItem]:
    """
    Tìm tất cả item có tên bắt đầu bằng mã code (có thể có khoảng trắng và tên phía sau).
    """
    code_lower = code.lower()
    items = list(iter_scene_items(scene_doc))
    matches = []
    for item in items:
        name_lower = item.name.lower()
        if name_lower.startswith(code_lower + " ") or name_lower == code_lower:
            matches.append(item)
        elif code_lower in name_lower:
            matches.append(item)
    return matches


def part_number_from_code(code: str) -> int:
    code = code.split()[0].strip()
    match = re.search(r"(\d+)\s*$", code.strip())
    if not match:
        raise IronCadControllerError(f"Ma so khong co so part o cuoi: {code}")
    return int(match.group(1))


def parse_rgb(text: str) -> tuple[int, int, int]:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("RGB phai co dang R,G,B. Vi du: 255,0,0")

    try:
        rgb = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("RGB chi nhan so nguyen 0..255") from exc

    if any(value < 0 or value > 255 for value in rgb):
        raise argparse.ArgumentTypeError("RGB chi nhan gia tri 0..255")

    return rgb


def read_purchase_file(path: Path, code_column: str | None, status_column: str | None) -> list[PurchaseRow]:
    if not path.exists():
        raise IronCadControllerError(f"Khong tim thay file mua hang: {path}")

    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return read_purchase_xlsx(path, code_column, status_column)

    return read_purchase_text(path, code_column, status_column)


def read_purchase_text(path: Path, code_column: str | None, status_column: str | None) -> list[PurchaseRow]:
    text = path.read_text(encoding="utf-8-sig")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise IronCadControllerError(f"File mua hang rong: {path}")

    delimiter = detect_delimiter(lines[0])
    if delimiter:
        rows = list(csv.reader(lines, delimiter=delimiter))
    else:
        rows = [line.split() for line in lines]

    return purchase_rows_from_table(rows, code_column, status_column)


def detect_delimiter(header_line: str) -> str | None:
    for delimiter in (",", "\t", ";"):
        if delimiter in header_line:
            return delimiter
    return None


def read_purchase_xlsx(path: Path, code_column: str | None, status_column: str | None) -> list[PurchaseRow]:
    try:
        import openpyxl
    except ImportError as exc:
        raise IronCadControllerError(
            "Doc .xlsx can openpyxl. Cai bang: python -m pip install openpyxl"
        ) from exc

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = []
    for row in sheet.iter_rows(values_only=True):
        values = ["" if value is None else str(value).strip() for value in row]
        if any(values):
            rows.append(values)
    return purchase_rows_from_table(rows, code_column, status_column)


def is_header_row(row: list[str]) -> bool:
    text = " ".join(row).lower()
    header_keywords = (
        "図番", "型式", "入荷", "状況", "ma so", "maso", "ma", "code", "part",
        "tinh trang", "tinhtrang", "status", "mua hang", "muahang"
    )
    for kw in header_keywords:
        if kw in text:
            return True
    has_digit = any(re.search(r'\d', cell) for cell in row)
    return not has_digit


def purchase_rows_from_table(
    rows: list[list[str]], code_column: str | None, status_column: str | None
) -> list[PurchaseRow]:
    if not rows:
        return []

    code_index, status_index, data_start = detect_purchase_columns(rows, code_column, status_column)

    if data_start == 0 and len(rows) > 0 and is_header_row(rows[0]):
        data_start = 1

    result: list[PurchaseRow] = []
    for offset, row in enumerate(rows[data_start:], start=data_start + 1):
        if len(row) <= max(code_index, status_index):
            continue

        code = str(row[code_index]).strip()
        status = str(row[status_index]).strip().upper()
        if not code and not status:
            continue
        if not code:
            print(f"SKIP line {offset}: thieu ma so")
            continue

        result.append(PurchaseRow(code=code, status=status, line_number=offset))

    return result


def detect_purchase_columns(
    rows: list[list[str]], code_column: str | None, status_column: str | None
) -> tuple[int, int, int]:
    first_row = [str(value).strip() for value in rows[0]]
    normalized = [normalize_header(value) for value in first_row]

    if code_column or status_column:
        code_index = find_header_index(normalized, code_column or "ma so")
        status_index = find_header_index(normalized, status_column or "tinh trang")
        return code_index, status_index, 1

    code_candidates = (
        "ma so", "maso", "ma", "code", "part",
        "zu ban", "zubanhoshiki", "zuban",
        "図番/型式", "図番", "型式", "パーツ番号", "部品番号",
    )
    code_index = find_header_index_optional(normalized, code_candidates)
    if code_index is None:
        for i, h in enumerate(first_row):
            if h in ("図番/型式", "図番", "型式", "パーツ番号", "部品番号"):
                code_index = i
                break

    status_candidates = (
        "tinh trang", "tinhtrang", "tinh trang mua hang",
        "tinhtrang mua hang", "tinhtrangmuahang",
        "status", "mua hang", "muahang",
        "nyuka", "nyukajokyo",
        "入荷状況", "入荷", "状況", "購入状況", "発注状況",
    )
    status_index = find_header_index_optional(normalized, status_candidates)
    if status_index is None:
        for i, h in enumerate(first_row):
            if h in ("入荷状況", "入荷", "状況", "購入状況", "発注状況"):
                status_index = i
                break

    if code_index is not None and status_index is not None:
        return code_index, status_index, 1

    return 0, 1, 0


def normalize_header(value: str) -> str:
    text = value.strip().lower()
    replacements = {
        "ã": "a",
        "á": "a",
        "à": "a",
        "ả": "a",
        "ạ": "a",
        "ă": "a",
        "ắ": "a",
        "ằ": "a",
        "ẳ": "a",
        "ẵ": "a",
        "ặ": "a",
        "â": "a",
        "ấ": "a",
        "ầ": "a",
        "ẩ": "a",
        "ẫ": "a",
        "ậ": "a",
        "đ": "d",
        "é": "e",
        "è": "e",
        "ẻ": "e",
        "ẽ": "e",
        "ẹ": "e",
        "ê": "e",
        "ế": "e",
        "ề": "e",
        "ể": "e",
        "ễ": "e",
        "ệ": "e",
        "í": "i",
        "ì": "i",
        "ỉ": "i",
        "ĩ": "i",
        "ị": "i",
        "ó": "o",
        "ò": "o",
        "ỏ": "o",
        "õ": "o",
        "ọ": "o",
        "ô": "o",
        "ố": "o",
        "ồ": "o",
        "ổ": "o",
        "ỗ": "o",
        "ộ": "o",
        "ơ": "o",
        "ớ": "o",
        "ờ": "o",
        "ở": "o",
        "ỡ": "o",
        "ợ": "o",
        "ú": "u",
        "ù": "u",
        "ủ": "u",
        "ũ": "u",
        "ụ": "u",
        "ư": "u",
        "ứ": "u",
        "ừ": "u",
        "ử": "u",
        "ữ": "u",
        "ự": "u",
        "ý": "y",
        "ỳ": "y",
        "ỷ": "y",
        "ỹ": "y",
        "ỵ": "y",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return " ".join(text.split())


def find_header_index(headers: list[str], expected: str) -> int:
    expected_normalized = normalize_header(expected)
    for index, header in enumerate(headers):
        if header == expected_normalized:
            return index
    raise IronCadControllerError(f"Khong thay cot: {expected}")


def find_header_index_optional(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    normalized_candidates = {normalize_header(c) for c in candidates}
    for index, header in enumerate(headers):
        if header in normalized_candidates:
            return index
    return None


def apply_purchase_rows(
    scene_doc,
    rows: list[PurchaseRow],
    ok_status: str,
    rgb: tuple[int, int, int],
    ignore_status: bool = False,
) -> tuple[int, int, int]:
    painted = 0
    skipped = 0
    failed = 0

    ok_statuses = {ok_status.upper(), "○", "〇"}

    for row in rows:
        if not ignore_status and row.status not in ok_statuses:
            skipped += 1
            print(f"SKIP line {row.line_number}: {row.code} status={row.status}")
            continue

        try:
            targets = find_parts_by_code(scene_doc, row.code)
            if not targets:
                raise IronCadControllerError(f"Khong tim thay part cho ma: {row.code}")

            changed = 0
            for item in targets:
                try:
                    action = set_part_color(item.element, rgb)
                    changed += 1
                    print(f"OK line {row.line_number}: {row.code} -> {item.name} ({action})")
                except IronCadControllerError as exc:
                    print(f"SKIP shape line {row.line_number}: {row.code} {item.name} -> {exc}")
            if changed:
                painted += 1
            else:
                failed += 1
        except IronCadControllerError as exc:
            failed += 1
            print(f"ERROR line {row.line_number}: {row.code} -> {exc}")

    update_scene(scene_doc)
    return painted, skipped, failed


def create_purchase_template(path: Path) -> None:
    if path.exists():
        raise IronCadControllerError(f"File da ton tai, khong ghi de: {path}")

    rows = [
        ["ma so", "tinh trang mua hang"],
        ["M56-0011", "O"],
        ["M56-0012", "X"],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def parse_part_number(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("So part phai la so nguyen. Vi du: 11") from exc

    if value < 0:
        raise argparse.ArgumentTypeError("So part khong duoc am.")

    return value


def rgb_to_colorref(rgb: tuple[int, int, int]) -> int:
    red, green, blue = rgb
    return red | (green << 8) | (blue << 16)


def color_values(rgb: tuple[int, int, int]) -> tuple[object, ...]:
    colorref = rgb_to_colorref(rgb)
    red, green, blue = rgb
    return (
        colorref,
        (red, green, blue),
        [red, green, blue],
        f"{red},{green},{blue}",
    )


def set_part_color(element, rgb: tuple[int, int, int]) -> str:
    errors: list[str] = []
    shape = resolve_instance_shape(element)

    try:
        surface_finish = shape.Components(7).Item(1).SurfaceFinish
        surface_finish.SurfaceColor = rgb_to_colorref(rgb)
        try:
            surface_finish.SurfaceColorIntensity = 100.0
        except Exception:
            pass
        refresh_shape_graphics(shape)
        return f"{target_label(shape)}.Components(7).Item(1).SurfaceFinish.SurfaceColor"
    except Exception as exc:
        errors.append(f"SurfaceFinish.SurfaceColor: {short_error(exc)}")

    for target in candidate_color_targets(shape):
        for property_name in COLOR_PROPERTIES:
            for value in color_values(rgb):
                try:
                    setattr(target, property_name, value)
                    refresh_shape_graphics(shape)
                    return f"{target_label(target)}.{property_name} = {value}"
                except Exception as exc:
                    errors.append(f"{property_name}={value!r}: {short_error(exc)}")

        for method_name in COLOR_METHODS:
            for args in color_method_argument_sets(rgb):
                try:
                    safe_call(target, method_name, *args)
                    refresh_shape_graphics(shape)
                    return f"{target_label(target)}.{method_name}{args}"
                except Exception as exc:
                    errors.append(f"{method_name}{args}: {short_error(exc)}")

    raise IronCadControllerError(
        "Khong doi duoc mau cho element nay. Thu lenh members de xem ten API mau.\n"
        + "\n".join(errors[:20])
    )


def candidate_color_targets(element) -> list[object]:
    targets = [element]
    try:
        targets.append(element.Components(7).Item(1).SurfaceFinish)
    except Exception:
        pass

    for name in (
        "Style",
        "RenderStyle",
        "SmartPaint",
        "Appearance",
        "Display",
        "DisplayProperties",
        "Material",
    ):
        try:
            value = getattr(element, name)
            if value is not None:
                targets.append(value)
        except Exception:
            continue
    return targets


def resolve_instance_shape(element):
    if has_member(element, "Components"):
        return element

    for name in ("InstanceShape", "Shape"):
        try:
            value = getattr(element, name)
            if value is not None and has_member(value, "Components"):
                return value
        except Exception:
            continue

    return element


def refresh_shape_graphics(shape) -> None:
    for method_name in ("MarkGraphicsDirty", "MarkDirty"):
        try:
            method = getattr(shape, method_name)
            if callable(method):
                method()
        except Exception:
            continue

    try:
        page = getattr(shape, "Page")
    except Exception:
        page = None

    if page is not None:
        for method_name in ("Update", "UpdateDisplay"):
            try:
                method = getattr(page, method_name)
                if callable(method):
                    method()
            except Exception:
                continue


def color_method_argument_sets(rgb: tuple[int, int, int]) -> tuple[tuple[object, ...], ...]:
    red, green, blue = rgb
    colorref = rgb_to_colorref(rgb)
    return (
        (colorref,),
        (red, green, blue),
        ((red, green, blue),),
        ([red, green, blue],),
    )


def set_visibility(element, visible: bool) -> str:
    errors: list[str] = []
    shape = resolve_instance_shape(element)

    try:
        shape.Suppressed = not visible
        return f"{target_label(shape)}.Suppressed = {not visible}"
    except Exception as exc:
        errors.append(f"Suppressed={not visible!r}: {short_error(exc)}")

    try:
        element.DisplayFlag = visible
        return f"{target_label(element)}.DisplayFlag = {visible}"
    except Exception as exc:
        errors.append(f"DisplayFlag={visible!r}: {short_error(exc)}")

    for property_name in VISIBILITY_PROPERTIES:
        values = visibility_values(property_name, visible)
        for value in values:
            try:
                setattr(element, property_name, value)
                return f"{property_name} = {value}"
            except Exception as exc:
                errors.append(f"{property_name}={value!r}: {short_error(exc)}")

    method_names = SHOW_METHODS if visible else HIDE_METHODS
    for method_name in method_names:
        try:
            safe_call(element, method_name)
            return f"{method_name}()"
        except Exception as exc:
            errors.append(f"{method_name}(): {short_error(exc)}")

    raise IronCadControllerError(
        "Khong doi duoc an/hien cho element nay. Thu lenh members de xem ten API visibility.\n"
        + "\n".join(errors[:20])
    )


def visibility_values(property_name: str, visible: bool) -> tuple[object, ...]:
    lowered = property_name.lower()
    desired = not visible if "hidden" in lowered or "suppressed" in lowered else visible
    return (desired, int(desired))


def update_scene(scene_doc) -> None:
    for method_name in ("Update", "UpdateDisplay", "Refresh", "Regen"):
        try:
            method = getattr(scene_doc, method_name)
            if callable(method):
                method()
                return
        except Exception:
            continue


def print_items(items: Iterable[SceneItem]) -> None:
    print(f"{'ID':>8}  {'TYPE':>8}  {'NAME'}")
    print("-" * 72)
    for item in items:
        indent = "  " * max(item.depth, 0)
        type_text = str(item.type_value)
        print(f"{item.element_id:>8}  {type_text:>8}  {indent}{item.name}")


def print_members(item: SceneItem, filter_text: str | None) -> None:
    names = [name for name in dir(item.element) if not name.startswith("_")]
    if filter_text:
        filter_lower = filter_text.lower()
        names = [name for name in names if filter_lower in name.lower()]

    print(f"Members for {item.name} (ID {item.element_id}):")
    for name in sorted(names):
        print(name)


def short_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ")
    return text[:180]


def target_label(target) -> str:
    try:
        name = getattr(target, "Name")
        if name:
            return str(name)
    except Exception:
        pass
    return type(target).__name__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dieu khien part IronCAD: list, doi mau, an/hien."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="Liet ke scene tree hien tai.")
    subparsers.add_parser("selected", help="Liet ke cac item dang chon trong IronCAD.")

    purchase = subparsers.add_parser(
        "purchase",
        help="Doc file mua hang, status O thi doi mau, status X giu nguyen.",
    )
    purchase.add_argument("file", type=Path, help="File .txt/.csv/.tsv hoac .xlsx.")
    purchase.add_argument("--rgb", type=parse_rgb, default=DEFAULT_OK_COLOR, help="Mau cho status O.")
    purchase.add_argument("--ok-status", default=DEFAULT_OK_STATUS, help="Trang thai can doi mau. Mac dinh: O.")
    purchase.add_argument("--code-column", help="Ten cot ma so neu file co header khac.")
    purchase.add_argument("--status-column", help="Ten cot tinh trang neu file co header khac.")
    purchase.add_argument("--ignore-status", action="store_true", help="Bo qua kiem tra status, doi mau tat ca cac dong.")

    template = subparsers.add_parser("template", help="Tao file mau mua_hang_mau.csv.")
    template.add_argument("file", type=Path, nargs="?", default=Path("mua_hang_mau.csv"))

    paint = subparsers.add_parser("paint", help="Doi mau theo so part. Vi du: paint 11 --rgb 255,0,0")
    paint.add_argument("number", type=parse_part_number, help="So trong ten Part. Vi du 11 -> Part11.")
    paint.add_argument("--rgb", required=True, type=parse_rgb, help="Vi du: 255,0,0")

    interactive = subparsers.add_parser("interactive", help="Nhap so part va mau RGB lien tuc.")
    interactive.add_argument("--rgb", type=parse_rgb, help="Mau mac dinh. Vi du: 255,0,0")

    for command in ("hide", "show", "color", "members"):
        child = subparsers.add_parser(command)
        add_target_args(child)
        if command == "color":
            child.add_argument("--rgb", required=True, type=parse_rgb, help="Vi du: 255,0,0")
        if command == "members":
            child.add_argument("--filter", help="Loc member theo chuoi, vi du: color")

    return parser


def normalize_shortcut_args(argv: list[str]) -> list[str]:
    if argv and argv[0].isdigit():
        return ["paint", *argv]
    return argv


def add_target_args(parser: argparse.ArgumentParser) -> None:
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--name", help="Ten part/assembly. Chap nhan wildcard, vi du: BRACKET*")
    target_group.add_argument("--id", help="Element Id trong lenh list.")
    target_group.add_argument("--selected", action="store_true", help="Dung cac part dang chon.")


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize_shortcut_args(argv))

    if args.command == "template":
        create_purchase_template(args.file)
        print(f"Created: {args.file}")
        return 0

    app = connect_ironcad()
    scene_doc = active_scene_doc(app)

    if args.command == "list":
        print_items(iter_scene_items(scene_doc))
        return 0

    if args.command == "selected":
        print_items(selected_items(scene_doc))
        return 0

    if args.command == "purchase":
        rows = read_purchase_file(args.file, args.code_column, args.status_column)
        painted, skipped, failed = apply_purchase_rows(
            scene_doc, rows, args.ok_status, args.rgb, args.ignore_status
        )
        print(f"Done: painted={painted}, skipped={skipped}, failed={failed}")
        return 0

    if args.command == "paint":
        targets = find_part_by_number_with_descendants(scene_doc, args.number)
        for item in targets:
            try:
                action = set_part_color(item.element, args.rgb)
                print(f"OK: {item.name} (ID {item.element_id}) -> {action}")
            except IronCadControllerError as exc:
                print(f"SKIP: {item.name} (ID {item.element_id}) -> {exc}")
        update_scene(scene_doc)
        return 0

    if args.command == "interactive":
        run_interactive(scene_doc, args.rgb)
        return 0

    targets = find_targets(scene_doc, args)

    if args.command == "members":
        print_members(targets[0], args.filter)
        return 0

    for item in targets:
        if args.command == "hide":
            action = set_visibility(item.element, visible=False)
        elif args.command == "show":
            action = set_visibility(item.element, visible=True)
        elif args.command == "color":
            action = set_part_color(item.element, args.rgb)
        else:
            raise AssertionError(args.command)

        print(f"OK: {item.name} (ID {item.element_id}) -> {action}")

    update_scene(scene_doc)
    return 0


def run_interactive(scene_doc, default_rgb: tuple[int, int, int] | None) -> None:
    print("Nhap: <so_part> <R,G,B>")
    print("Vi du: 11 255,0,0")
    if default_rgb:
        print(f"Mau mac dinh: {format_rgb(default_rgb)}. Khi do chi can nhap so part, vi du: 11")
    print("Go q de thoat.")

    while True:
        text = input("> ").strip()
        if text.lower() in {"q", "quit", "exit"}:
            return
        if not text:
            continue

        parts = text.split()
        try:
            number = parse_part_number(parts[0])
            rgb = parse_rgb(parts[1]) if len(parts) > 1 else default_rgb
            if rgb is None:
                print("Hay nhap mau RGB, vi du: 11 255,0,0")
                continue

            targets = find_part_by_number_with_descendants(scene_doc, number)
            actions = []
            for item in targets:
                try:
                    actions.append(f"{item.name}: {set_part_color(item.element, rgb)}")
                except IronCadControllerError as exc:
                    actions.append(f"{item.name}: SKIP ({exc})")
            update_scene(scene_doc)
            print(f"OK: Part{number} -> {format_rgb(rgb)}")
            for action in actions:
                print(f"  {action}")
        except (argparse.ArgumentTypeError, IronCadControllerError) as exc:
            print(f"ERROR: {exc}")


def format_rgb(rgb: tuple[int, int, int]) -> str:
    return f"{rgb[0]},{rgb[1]},{rgb[2]}"


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except IronCadControllerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)