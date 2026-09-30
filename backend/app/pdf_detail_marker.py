from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph


FONT_AWESOME_PATH = (
    Path(__file__).resolve().parent
    / "pdf_assets"
    / "fontawesome"
    / "fa-solid-900.ttf"
)

FONT_AWESOME_NAME = "FontAwesomeSolid"

pdfmetrics.registerFont(
    TTFont(
        FONT_AWESOME_NAME,
        str(FONT_AWESOME_PATH),
    )
)


FLUID_TOOL_DESCRIPTIONS = {
    "engine oil",
    "huile",
    "huile moteur",
    "coolant",
    "liquide de refroidissement",
    "volvo coolant ready mixed",
}


# Font Awesome Free Solid
ICON_SEARCH = "\uf002"       # magnifying-glass
ICON_TOOLS = "\uf7d9"        # screwdriver-wrench


ICON_STYLE = ParagraphStyle(
    "DetailMarkerIcon",
    fontName=FONT_AWESOME_NAME,
    fontSize=11,
    leading=11,
    textColor=colors.HexColor("#111111"),
    alignment=1,
    spaceBefore=0,
    spaceAfter=0,
)


def _value(row, key, default=None):
    try:
        if key in row.keys():
            return row[key]
    except Exception:
        pass

    if isinstance(row, dict):
        return row.get(key, default)

    return default


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalized(value):
    return " ".join(
        str(value or "")
        .casefold()
        .strip()
        .split()
    )


def detail_marker_kind(line):
    """
    Regle :
    - search : aucune reference ET aucun prix
    - tools  : reference OU prix
    - exception tools : huiles et coolant
    """

    description = _normalized(
        _value(line, "description", "")
    )

    if description in FLUID_TOOL_DESCRIPTIONS:
        return "tools"

    part_number = str(
        _value(line, "part_number", "") or ""
    ).strip()

    unit_price = _number(
        _value(line, "unit_price", 0)
    )

    total_price = _number(
        _value(line, "total_price", 0)
    )

    if (
        part_number
        or abs(unit_price) > 0
        or abs(total_price) > 0
    ):
        return "tools"

    return "search"


def detail_marker_drawing(line):
    """
    Retourne un vrai pictogramme Font Awesome.
    Le nom de fonction est conserve pour ne pas avoir
    a modifier les deux exports PDF.
    """

    if detail_marker_kind(line) == "tools":
        icon = ICON_TOOLS
    else:
        icon = ICON_SEARCH

    return Paragraph(
        icon,
        ICON_STYLE,
    )