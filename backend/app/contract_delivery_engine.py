from datetime import date, timedelta


def _safe_date(value):
    if not value:
        return None

    try:
        return date.fromisoformat(str(value))
    except Exception:
        return None


def evaluate_delivery_events(
    conn,
    company_id,
    as_of_date=None,
):
    """
    Évalue les règles de diffusion d'une société.

    Aucun mail n'est envoyé.
    Aucun log n'est écrit.

    Retourne uniquement les notifications candidates.
    """

    if as_of_date is None:
        as_of_date = date.today()

    if isinstance(as_of_date, str):
        as_of_date = date.fromisoformat(as_of_date)

    rules = conn.execute(
        """
        SELECT
            r.id AS rule_id,
            r.profile_id,
            r.rule_key,
            r.event_type,
            r.trigger_type,
            r.trigger_value,
            p.profile_key,
            p.profile_name
        FROM contract_delivery_rules r
        JOIN contract_delivery_profiles p
          ON p.id = r.profile_id
        WHERE p.company_id = ?
          AND p.is_active = 1
          AND r.is_active = 1
        ORDER BY p.id, r.id
        """,
        (company_id,),
    ).fetchall()

    results = []

    for rule in rules:
        rule_id = int(rule["rule_id"])
        profile_id = int(rule["profile_id"])

        profile_key = str(
            rule["profile_key"] or ""
        )

        event_type = str(
            rule["event_type"] or ""
        )

        trigger_type = str(
            rule["trigger_type"] or ""
        )

        trigger_value = float(
            rule["trigger_value"] or 0
        )

        recipients = conn.execute(
            """
            SELECT
                id,
                recipient_name,
                email,
                attach_ics
            FROM contract_delivery_recipients
            WHERE profile_id = ?
              AND is_active = 1
            ORDER BY id
            """,
            (profile_id,),
        ).fetchall()

        if not recipients:
            continue

        candidates = []

        # -------------------------------------------------
        # ATELIER / MAGASIN
        # Intervention selon heures restantes
        # -------------------------------------------------

        if (
            event_type == "intervention"
            and trigger_type == "hours_before"
        ):
            rows = conn.execute(
                """
                SELECT
                    i.id AS intervention_id,
                    i.intervention_type,
                    i.planned_engine_hours,
                    i.planned_date,
                    c.id AS contract_id,
                    c.contract_number,
                    c.customer_name,
                    c.product_designation,
                    c.product_name,
                    c.engine_serial_number,
                    c.current_engine_hours
                FROM contract_interventions i
                JOIN contracts c
                  ON c.id = i.contract_id
                WHERE c.company_id = ?
                  AND i.status = 'planned'
                  AND i.planned_engine_hours IS NOT NULL
                ORDER BY
                    i.planned_engine_hours,
                    i.id
                """,
                (company_id,),
            ).fetchall()

            for row in rows:
                current_hours = float(
                    row["current_engine_hours"] or 0
                )

                planned_hours = float(
                    row["planned_engine_hours"] or 0
                )

                remaining = (
                    planned_hours
                    - current_hours
                )

                if (
                    remaining >= 0
                    and remaining <= trigger_value
                ):
                    candidates.append(
                        {
                            "event_key":
                                f"intervention:{row['intervention_id']}",
                            "event_uid":
                                f"dqm:{company_id}:intervention:{row['intervention_id']}",
                            "contract_id":
                                int(row["contract_id"]),
                            "contract_number":
                                row["contract_number"],
                            "customer_name":
                                row["customer_name"],
                            "intervention_id":
                                int(row["intervention_id"]),
                            "intervention_type":
                                row["intervention_type"],
                            "planned_date":
                                row["planned_date"],
                            "planned_engine_hours":
                                planned_hours,
                            "reason":
                                f"{remaining:g} h restantes",
                        }
                    )

        # -------------------------------------------------
        # ATELIER / MAGASIN
        # Intervention selon jours restants
        # -------------------------------------------------

        elif (
            event_type == "intervention"
            and trigger_type == "days_before"
        ):
            rows = conn.execute(
                """
                SELECT
                    i.id AS intervention_id,
                    i.intervention_type,
                    i.planned_engine_hours,
                    i.planned_date,
                    c.id AS contract_id,
                    c.contract_number,
                    c.customer_name,
                    c.product_designation,
                    c.product_name,
                    c.engine_serial_number
                FROM contract_interventions i
                JOIN contracts c
                  ON c.id = i.contract_id
                WHERE c.company_id = ?
                  AND i.status = 'planned'
                  AND i.planned_date IS NOT NULL
                ORDER BY
                    i.planned_date,
                    i.id
                """,
                (company_id,),
            ).fetchall()

            for row in rows:
                planned_date = _safe_date(
                    row["planned_date"]
                )

                if not planned_date:
                    continue

                days_remaining = (
                    planned_date
                    - as_of_date
                ).days

                if (
                    days_remaining >= 0
                    and days_remaining <= trigger_value
                ):
                    candidates.append(
                        {
                            "event_key":
                                f"intervention:{row['intervention_id']}",
                            "event_uid":
                                f"dqm:{company_id}:intervention:{row['intervention_id']}",
                            "contract_id":
                                int(row["contract_id"]),
                            "contract_number":
                                row["contract_number"],
                            "customer_name":
                                row["customer_name"],
                            "intervention_id":
                                int(row["intervention_id"]),
                            "intervention_type":
                                row["intervention_type"],
                            "planned_date":
                                row["planned_date"],
                            "planned_engine_hours":
                                float(
                                    row["planned_engine_hours"] or 0
                                ),
                            "reason":
                                f"{days_remaining} jours restants",
                        }
                    )

        # -------------------------------------------------
        # FACTURATION
        # Toujours basée sur contract_billing_events
        # -------------------------------------------------

        elif (
            event_type == "billing"
            and trigger_type == "days_before"
        ):
            rows = conn.execute(
                """
                SELECT
                    b.id AS billing_event_id,
                    b.event_key AS billing_event_key,
                    b.billing_type,
                    b.due_date,
                    b.source_intervention_id,
                    c.id AS contract_id,
                    c.contract_number,
                    c.customer_name
                FROM contract_billing_events b
                JOIN contracts c
                  ON c.id = b.contract_id
                WHERE c.company_id = ?
                  AND b.status = 'planned'
                  AND b.due_date IS NOT NULL
                ORDER BY
                    b.due_date,
                    b.id
                """,
                (company_id,),
            ).fetchall()

            for row in rows:
                due_date = _safe_date(
                    row["due_date"]
                )

                if not due_date:
                    continue

                days_remaining = (
                    due_date
                    - as_of_date
                ).days

                if (
                    days_remaining >= 0
                    and days_remaining <= trigger_value
                ):
                    candidates.append(
                        {
                            "event_key":
                                f"billing:{row['billing_event_id']}",
                            "event_uid":
                                f"dqm:{company_id}:billing:{row['billing_event_id']}",
                            "contract_id":
                                int(row["contract_id"]),
                            "contract_number":
                                row["contract_number"],
                            "customer_name":
                                row["customer_name"],
                            "billing_event_id":
                                int(row["billing_event_id"]),
                            "billing_type":
                                row["billing_type"],
                            "due_date":
                                row["due_date"],
                            "source_intervention_id":
                                row["source_intervention_id"],
                            "reason":
                                f"{days_remaining} jours avant facturation",
                        }
                    )

        # -------------------------------------------------
        # COMMERCE
        # Fin / renouvellement
        # -------------------------------------------------

        elif (
            event_type == "contract_end"
            and trigger_type == "days_before"
        ):
            rows = conn.execute(
                """
                SELECT
                    id AS contract_id,
                    contract_number,
                    customer_name,
                    product_designation,
                    product_name,
                    engine_serial_number,
                    planned_end_date
                FROM contracts
                WHERE company_id = ?
                  AND planned_end_date IS NOT NULL
                ORDER BY planned_end_date, id
                """,
                (company_id,),
            ).fetchall()

            for row in rows:
                end_date = _safe_date(
                    row["planned_end_date"]
                )

                if not end_date:
                    continue

                days_remaining = (
                    end_date
                    - as_of_date
                ).days

                if (
                    days_remaining >= 0
                    and days_remaining <= trigger_value
                ):
                    candidates.append(
                        {
                            "event_key":
                                f"contract_end:{row['contract_id']}",
                            "event_uid":
                                f"dqm:{company_id}:contract_end:{row['contract_id']}",
                            "contract_id":
                                int(row["contract_id"]),
                            "contract_number":
                                row["contract_number"],
                            "customer_name":
                                row["customer_name"],
                            "planned_end_date":
                                row["planned_end_date"],
                            "reason":
                                f"{days_remaining} jours avant fin du contrat",
                        }
                    )

        # -------------------------------------------------
        # Un résultat par destinataire
        # -------------------------------------------------

        for candidate in candidates:
            for recipient in recipients:
                result = dict(candidate)

                result.update(
                    {
                        "company_id":
                            int(company_id),
                        "profile_id":
                            profile_id,
                        "profile_key":
                            profile_key,
                        "rule_id":
                            rule_id,
                        "rule_key":
                            rule["rule_key"],
                        "trigger_type":
                            trigger_type,
                        "trigger_value":
                            trigger_value,
                        "recipient_id":
                            int(recipient["id"]),
                        "recipient_name":
                            recipient["recipient_name"],
                        "recipient_email":
                            recipient["email"],
                        "attach_ics":
                            bool(
                                int(
                                    recipient["attach_ics"]
                                    or 0
                                )
                            ),
                    }
                )

                results.append(result)

    return results


def _delivery_event_date(event):
    profile_key = str(
        event.get("profile_key") or ""
    )

    if profile_key in (
        "atelier",
        "magasin",
    ):
        value = event.get(
            "planned_date"
        )

    elif profile_key == "facturation":
        value = event.get(
            "due_date"
        )

    elif profile_key == "commerce":
        value = event.get(
            "planned_end_date"
        )

    else:
        value = None

    if not value:
        return None

    return str(value)


def evaluate_pending_delivery_events(
    conn,
    company_id,
    as_of_date=None,
):
    candidates = evaluate_delivery_events(
        conn,
        company_id,
        as_of_date=as_of_date,
    )

    pending = []

    for event in candidates:
        event_date = _delivery_event_date(
            event
        )

        latest_sent = conn.execute(
            """
            SELECT
                event_revision,
                event_date
            FROM contract_delivery_log
            WHERE company_id = ?
              AND recipient_id = ?
              AND rule_id = ?
              AND event_key = ?
              AND status = 'sent'
            ORDER BY
                event_revision DESC,
                id DESC
            LIMIT 1
            """,
            (
                int(event["company_id"]),
                int(event["recipient_id"]),
                int(event["rule_id"]),
                str(event["event_key"]),
            ),
        ).fetchone()

        if latest_sent is None:
            event_revision = 0

        else:
            latest_revision = int(
                latest_sent["event_revision"]
                or 0
            )

            latest_date = (
                str(latest_sent["event_date"])
                if latest_sent["event_date"]
                else None
            )

            # Ancien envoi effectué avant l'ajout
            # de event_date :
            # on ne renvoie pas automatiquement.
            if latest_date is None:
                continue

            # Même date = événement déjà envoyé.
            if latest_date == event_date:
                continue

            # Date modifiée = nouvelle révision.
            event_revision = (
                latest_revision + 1
            )

        result = dict(event)

        result["event_revision"] = (
            event_revision
        )

        result["event_date"] = (
            event_date
        )

        pending.append(result)

    return pending


def prepare_delivery_message(
    conn,
    event,
):
    profile_key = str(
        event.get("profile_key") or ""
    )

    contract_number = str(
        event.get("contract_number") or "-"
    )

    customer_name = str(
        event.get("customer_name") or "-"
    )

    reason = str(
        event.get("reason") or ""
    )

    subject = ""
    lines = []

    # -----------------------------------------------------
    # ATELIER
    # -----------------------------------------------------

    if profile_key == "atelier":
        intervention_id = event.get(
            "intervention_id"
        )

        intervention = conn.execute(
            """
            SELECT
                i.intervention_type,
                i.planned_date,
                i.planned_engine_hours,
                c.product_designation,
                c.product_name,
                c.engine_serial_number
            FROM contract_interventions i
            JOIN contracts c
              ON c.id = i.contract_id
            WHERE i.id = ?
            """,
            (intervention_id,),
        ).fetchone()

        subject = (
            f"Intervention à préparer - "
            f"{contract_number}"
        )

        lines = [
            "INTERVENTION À PRÉPARER",
            "",
            f"Contrat : {contract_number}",
            f"Client : {customer_name}",
        ]

        if intervention:
            lines.extend(
                [
                    (
                        "Moteur : "
                        f"{intervention['product_designation'] or intervention['product_name'] or '-'}"
                    ),
                    (
                        "N° série : "
                        f"{intervention['engine_serial_number'] or '-'}"
                    ),
                    (
                        "Intervention : "
                        f"{intervention['intervention_type'] or '-'}"
                    ),
                    (
                        "Date prévue : "
                        f"{intervention['planned_date'] or '-'}"
                    ),
                    (
                        "Compteur prévu : "
                        f"{intervention['planned_engine_hours'] or 0:g} h"
                    ),
                ]
            )

        parts = conn.execute(
            """
            SELECT
                part_number,
                description,
                planned_quantity
            FROM contract_intervention_parts
            WHERE contract_intervention_id = ?
            ORDER BY part_number, id
            """,
            (intervention_id,),
        ).fetchall()

        lines.extend(
            [
                "",
                "PIÈCES PRÉVUES",
            ]
        )

        if parts:
            for part in parts:
                lines.append(
                    (
                        f"- {part['part_number'] or '-'} "
                        f"| {part['description'] or '-'} "
                        f"| Qté {part['planned_quantity'] or 0:g}"
                    )
                )
        else:
            lines.append(
                "- Aucune pièce planifiée"
            )

        lines.extend(
            [
                "",
                f"Déclenchement : {reason}",
            ]
        )

    # -----------------------------------------------------
    # MAGASIN
    # -----------------------------------------------------

    elif profile_key == "magasin":
        intervention_id = event.get(
            "intervention_id"
        )

        subject = (
            f"Pièces à prévoir - "
            f"{contract_number}"
        )

        lines = [
            "PIÈCES À PRÉVOIR",
            "",
            f"Contrat : {contract_number}",
            f"Client : {customer_name}",
            (
                "Date intervention : "
                f"{event.get('planned_date') or '-'}"
            ),
            "",
            "BESOINS PIÈCES",
        ]

        parts = conn.execute(
            """
            SELECT
                part_number,
                description,
                planned_quantity
            FROM contract_intervention_parts
            WHERE contract_intervention_id = ?
            ORDER BY part_number, id
            """,
            (intervention_id,),
        ).fetchall()

        if parts:
            for part in parts:
                lines.append(
                    (
                        f"- {part['part_number'] or '-'} "
                        f"| {part['description'] or '-'} "
                        f"| Qté {part['planned_quantity'] or 0:g}"
                    )
                )
        else:
            lines.append(
                "- Aucune pièce planifiée"
            )

        lines.extend(
            [
                "",
                f"Déclenchement : {reason}",
            ]
        )

    # -----------------------------------------------------
    # FACTURATION
    # -----------------------------------------------------

    elif profile_key == "facturation":
        due_date = str(
            event.get("due_date") or "-"
        )

        billing_type = str(
            event.get("billing_type") or "-"
        )

        billing_label = (
            "Mensuelle"
            if billing_type == "monthly"
            else "À l'intervention"
        )

        subject = (
            f"Échéance de facturation - "
            f"{contract_number}"
        )

        lines = [
            "ÉCHÉANCE DE FACTURATION",
            "",
            f"Contrat : {contract_number}",
            f"Client : {customer_name}",
            f"Date échéance : {due_date}",
            f"Mode : {billing_label}",
            "",
            f"Déclenchement : {reason}",
        ]

    # -----------------------------------------------------
    # COMMERCE
    # -----------------------------------------------------

    elif profile_key == "commerce":
        subject = (
            f"Fin de contrat à anticiper - "
            f"{contract_number}"
        )

        lines = [
            "FIN DE CONTRAT À ANTICIPER",
            "",
            f"Contrat : {contract_number}",
            f"Client : {customer_name}",
            (
                "Fin estimée : "
                f"{event.get('planned_end_date') or '-'}"
            ),
            "",
            f"Déclenchement : {reason}",
        ]

    else:
        subject = (
            f"Notification contrat - "
            f"{contract_number}"
        )

        lines = [
            f"Contrat : {contract_number}",
            f"Client : {customer_name}",
            f"Déclenchement : {reason}",
        ]

    return {
        "subject": subject,
        "body_text": "\n".join(lines),
    }


def _escape_ics_text(value):
    text = str(value or "")

    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def prepare_delivery_ics(
    conn,
    event,
):

    profile_key = str(
        event.get("profile_key") or ""
    )

    event_uid = str(
        event.get("event_uid") or ""
    )

    contract_number = str(
        event.get("contract_number") or "-"
    )

    customer_name = str(
        event.get("customer_name") or "-"
    )

    event_date = None
    summary = None
    description = None

    # -----------------------------------------------------
    # ATELIER / MAGASIN
    # -----------------------------------------------------

    if profile_key in (
        "atelier",
        "magasin",
    ):
        event_date = event.get(
            "planned_date"
        )

        summary = (
            f"Intervention {contract_number}"
        )

        description = (
            f"Contrat : {contract_number}\n"
            f"Client : {customer_name}\n"
            f"Intervention : "
            f"{event.get('intervention_type') or '-'}\n"
            f"Compteur prévu : "
            f"{event.get('planned_engine_hours') or 0:g} h"
        )

    # -----------------------------------------------------
    # FACTURATION
    # -----------------------------------------------------

    elif profile_key == "facturation":
        event_date = event.get(
            "due_date"
        )

        summary = (
            f"Facturation {contract_number}"
        )

        description = (
            f"Contrat : {contract_number}\n"
            f"Client : {customer_name}\n"
            f"Échéance de facturation"
        )

    # -----------------------------------------------------
    # COMMERCE
    # -----------------------------------------------------

    elif profile_key == "commerce":
        event_date = event.get(
            "planned_end_date"
        )

        summary = (
            f"Fin contrat {contract_number}"
        )

        description = (
            f"Contrat : {contract_number}\n"
            f"Client : {customer_name}\n"
            f"Fin estimée du contrat"
        )

    if not (
        event_uid
        and event_date
        and summary
    ):
        return None

    try:
        event_date_obj = date.fromisoformat(
            str(event_date)
        )
    except Exception:
        return None

    date_text = event_date_obj.strftime(
        "%Y%m%d"
    )

    end_date_text = (
        event_date_obj
        + timedelta(days=1)
    ).strftime(
        "%Y%m%d"
    )

    uid = (
        f"{event_uid}@dealer-quote-manager"
    )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Dealer Quote Manager//Contracts//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{_escape_ics_text(uid)}",
        f"SEQUENCE:{int(event.get('event_revision') or 0)}",
        f"DTSTART;VALUE=DATE:{date_text}",
        f"DTEND;VALUE=DATE:{end_date_text}",
        (
            "SUMMARY:"
            f"{_escape_ics_text(summary)}"
        ),
        (
            "DESCRIPTION:"
            f"{_escape_ics_text(description)}"
        ),
        "STATUS:CONFIRMED",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    return "\r\n".join(lines) + "\r\n"
