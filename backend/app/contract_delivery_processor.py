from datetime import date

from contract_delivery_engine import (
    evaluate_pending_delivery_events,
    prepare_delivery_message,
    prepare_delivery_ics,
)

from contract_delivery_mail import (
    build_delivery_email,
)


DEFAULT_FROM_ADDRESS = (
    "contrats@dealer-quote-manager.local"
)


def process_company_delivery(
    conn,
    company_id,
    as_of_date=None,
    dry_run=True,
    from_address=None,
):
    """
    Prépare les diffusions d'une société.

    dry_run=True :
        - aucun email n'est envoyé ;
        - prépare message + ICS + email MIME ;
        - écrit ou actualise un log 'simulated'.

    dry_run=False :
        - volontairement interdit tant que SMTP
          n'est pas configuré et validé.
    """

    if not dry_run:
        raise RuntimeError(
            "Envoi réel désactivé : SMTP non configuré"
        )

    if as_of_date is None:
        as_of_date = date.today()

    if from_address is None:
        from_address = DEFAULT_FROM_ADDRESS

    events = evaluate_pending_delivery_events(
        conn,
        company_id,
        as_of_date=as_of_date,
    )

    results = []

    for event in events:
        message = prepare_delivery_message(
            conn,
            event,
        )

        if not message:
            continue

        subject = str(
            message.get("subject") or ""
        )

        body_text = str(
            message.get("body_text") or ""
        )

        ics_content = prepare_delivery_ics(
            conn,
            event,
        )

        if not ics_content:
            raise RuntimeError(
                "ICS non généré pour "
                f"{event.get('event_key')}"
            )

        email_message = build_delivery_email(
            from_address=from_address,
            to_address=event[
                "recipient_email"
            ],
            subject=subject,
            body_text=body_text,
            ics_content=ics_content,
            event_key=event[
                "event_key"
            ],
        )

        event_revision = int(
            event.get("event_revision") or 0
        )

        conn.execute(
            """
            INSERT INTO contract_delivery_log (
                company_id,
                profile_id,
                recipient_id,
                rule_id,
                event_key,
                event_uid,
                event_revision,
                subject,
                status,
                sent_at,
                error_message
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                'simulated',
                NULL,
                NULL
            )
            ON CONFLICT(
                recipient_id,
                rule_id,
                event_key,
                event_revision
            )
            DO UPDATE SET
                company_id = excluded.company_id,
                profile_id = excluded.profile_id,
                event_uid = excluded.event_uid,
                subject = excluded.subject,
                status = 'simulated',
                sent_at = NULL,
                error_message = NULL
            """,
            (
                int(event["company_id"]),
                int(event["profile_id"]),
                int(event["recipient_id"]),
                int(event["rule_id"]),
                str(event["event_key"]),
                str(event["event_uid"]),
                event_revision,
                subject,
            ),
        )

        results.append(
            {
                "company_id":
                    int(event["company_id"]),

                "profile_id":
                    int(event["profile_id"]),

                "profile_key":
                    event["profile_key"],

                "recipient_id":
                    int(event["recipient_id"]),

                "recipient_name":
                    event.get("recipient_name"),

                "recipient_email":
                    event["recipient_email"],

                "rule_id":
                    int(event["rule_id"]),

                "event_key":
                    event["event_key"],

                "event_uid":
                    event["event_uid"],

                "event_revision":
                    event_revision,

                "subject":
                    subject,

                "body_text":
                    body_text,

                "ics_content":
                    ics_content,

                "ics_generated":
                    True,

                "email_message":
                    email_message,

                "email_bytes":
                    email_message.as_bytes(),

                "status":
                    "simulated",
            }
        )

    conn.commit()

    return results