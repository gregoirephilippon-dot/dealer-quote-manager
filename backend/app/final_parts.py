import math


IMPORTED_OIL_PART_NUMBERS = {
    "24567220",
    "24567221",
    "24567222",
    "54419768",
}

IMPORTED_COOLANT_PART_NUMBERS = {
    "22567233",
    "22567259",
    "22567215",
    "24712786",
    "24712788",
    "24712790",
    "24712783",
    "22567261",
    "22567217",
}

CONCENTRATED_COOLANT_PART_NUMBERS = {
    "22567215",
    "22567217",
}


def _value(row, key, default=None):
    try:
        if key in row.keys():
            return row[key]
    except Exception:
        pass

    if isinstance(row, dict):
        return row.get(key, default)

    return default


def _float(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return float(default)


def _normalized(value):
    return " ".join(
        str(value or "")
        .casefold()
        .replace("’", "'")
        .strip()
        .rstrip(".")
        .split()
    )


def _line_to_dict(line):
    try:
        return {key: line[key] for key in line.keys()}
    except Exception:
        return dict(line)


def _is_group_marker(description):
    description = str(description or "").strip()
    return (
        len(description) == 1
        and description.upper() in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    )


def _is_oil_notice(description):
    normalized = _normalized(description)

    return normalized == (
        "engine oil and oil filters, "
        "note the oil specification in the service protocol "
        "in product center"
    )


def _is_imported_oil(line):
    description = _normalized(_value(line, "description", ""))
    part_number = str(
        _value(line, "part_number", "") or ""
    ).strip()

    return (
        description == "engine oil"
        or part_number in IMPORTED_OIL_PART_NUMBERS
    )


def _is_imported_coolant(line):
    description = _normalized(_value(line, "description", ""))
    part_number = str(
        _value(line, "part_number", "") or ""
    ).strip()

    return (
        description == "volvo coolant ready mixed"
        or part_number in IMPORTED_COOLANT_PART_NUMBERS
    )


def _billable_per_service(
    quantity_per_service,
    packaging_liters,
    packaging_mode,
):
    quantity_per_service = _float(quantity_per_service)
    packaging_liters = _float(packaging_liters)
    packaging_mode = str(
        packaging_mode or "consumed"
    ).strip().lower()

    result = quantity_per_service

    if (
        packaging_mode == "package"
        and packaging_liters > 0
        and quantity_per_service > 0
    ):
        result = (
            math.ceil(
                quantity_per_service / packaging_liters
            )
            * packaging_liters
        )

    return result


def _synthetic_fluid_line(
    description,
    part_number,
    quantity,
    unit_price,
):
    quantity = _float(quantity)
    unit_price = _float(unit_price)

    return {
        "id": None,
        "quote_id": None,
        "component": "Fluide",
        "description": description,
        "part_number": str(part_number or "").strip(),
        "quantity": quantity,
        "unit_price": unit_price,
        "total_price": quantity * unit_price,
        "labour_time": 0,
        "source_sheet": "Dealer Quote Manager",
        "discount_code": None,
        "dealer_net_total": 0,
        "customer_price_total": 0,
        "_final_generated": True,
    }


def build_final_parts(quote, lines):
    """
    Retourne les elements reellement retenus apres calcul.

    Les quote_lines originales ne sont jamais modifiees.

    - lignes a quantite nulle : masquees
    - reperes A/B/C... : masques
    - notice technique huile : masquee
    - pieces ordinaires : conservees
    - huile/coolant importes : conserves s'ils ne sont pas remplaces
    - huile/coolant remplaces : anciennes lignes masquees et
      valeurs finales du logiciel ajoutees
    """

    replace_oil = bool(
        _value(quote, "replace_imported_oil", 0)
    )

    replace_coolant = bool(
        _value(quote, "replace_imported_coolant", 0)
    )

    final_lines = []

    for source_line in lines:
        quantity = _float(
            _value(source_line, "quantity", 0)
        )

        if quantity <= 0:
            continue

        description = str(
            _value(source_line, "description", "") or ""
        ).strip()

        if _is_group_marker(description):
            continue

        if _is_oil_notice(description):
            continue

        if replace_oil and _is_imported_oil(source_line):
            continue

        if replace_coolant and _is_imported_coolant(source_line):
            continue

        final_lines.append(
            _line_to_dict(source_line)
        )

    # --------------------------------------------------------
    # HUILE FINALE
    # --------------------------------------------------------

    if replace_oil:
        service_count = _float(
            _value(quote, "oil_service_count", 0)
        )

        quantity_per_service = _float(
            _value(quote, "oil_quantity_per_service", 0)
        )

        packaging_liters = _float(
            _value(quote, "oil_packaging_liters", 0)
        )

        packaging_mode = _value(
            quote,
            "oil_packaging_mode",
            "consumed",
        )

        billable_per_service = _billable_per_service(
            quantity_per_service,
            packaging_liters,
            packaging_mode,
        )

        final_quantity = (
            service_count * billable_per_service
        )

        if final_quantity > 0:
            final_lines.append(
                _synthetic_fluid_line(
                    description="Engine oil",
                    part_number=_value(
                        quote,
                        "oil_catalog_part_no",
                        "",
                    ),
                    quantity=final_quantity,
                    unit_price=_value(
                        quote,
                        "oil_price_per_liter",
                        0,
                    ),
                )
            )

    # --------------------------------------------------------
    # LIQUIDE DE REFROIDISSEMENT FINAL
    # --------------------------------------------------------

    if replace_coolant:
        part_number = str(
            _value(
                quote,
                "coolant_catalog_part_no",
                "",
            )
            or ""
        ).strip()

        service_count = _float(
            _value(quote, "coolant_service_count", 0)
        )

        quantity_per_service = _float(
            _value(
                quote,
                "coolant_quantity_per_service",
                0,
            )
        )

        concentrate_percent = _float(
            _value(
                quote,
                "coolant_concentrate_percent",
                100,
            )
        )

        if concentrate_percent <= 0:
            concentrate_percent = 100

        if concentrate_percent > 100:
            concentrate_percent = 100

        volume_factor = (
            concentrate_percent / 100
            if part_number
            in CONCENTRATED_COOLANT_PART_NUMBERS
            else 1
        )

        required_per_service = (
            quantity_per_service * volume_factor
        )

        packaging_liters = _float(
            _value(
                quote,
                "coolant_packaging_liters",
                0,
            )
        )

        packaging_mode = _value(
            quote,
            "coolant_packaging_mode",
            "consumed",
        )

        billable_per_service = _billable_per_service(
            required_per_service,
            packaging_liters,
            packaging_mode,
        )

        final_quantity = (
            service_count * billable_per_service
        )

        if final_quantity > 0:
            final_lines.append(
                _synthetic_fluid_line(
                    description="Volvo coolant ready mixed",
                    part_number=part_number,
                    quantity=final_quantity,
                    unit_price=_value(
                        quote,
                        "coolant_price_per_liter",
                        0,
                    ),
                )
            )

    return final_lines
