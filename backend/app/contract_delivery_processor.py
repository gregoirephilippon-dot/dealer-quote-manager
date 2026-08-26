import os
import smtplib
import ssl
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
    "dealerquotemanager@gmail.com"
)


def _smtp_settings():
    return {
        "host": os.environ.get(
            "DQM_SMTP_HOST",
            "",
        ),
        "port": int(
            os.environ.get(
                "DQM_SMTP_PORT",
                "587",
            )
        ),
        "user": os.environ.get(
            "DQM_SMTP_USER",
            "",
        ),
        "password": os.environ.get(
            "DQM_SMTP_PASSWORD",
            "",
        ),
    }


def _send_email_smtp(
    email_message,
):
    settings = _smtp_settings()

    if not settings["host"]:
        raise RuntimeError(
            "DQM_SMTP_HOST manquant"
        )

    if not settings["user"]:
        raise RuntimeError(
            "DQM_SMTP_USER manquant"
        )

    if not settings["password"]:
        raise RuntimeError(
            "DQM_SMTP_PASSWORD manquant"
        )

    context = ssl.create_default_context()

    with smtplib.SMTP(
        settings["host"],
        settings["port"],
        timeout=30,
    ) as smtp:
        smtp.ehlo()

        smtp.starttls(
            context=context
        )

        smtp.ehlo()

        smtp.login(
            settings["user"],
            settings["password"],
        )

        refused = smtp.send_message(
            email_message,
            from_addr=settings["user"],
            to_addrs=[
                str(
                    email_message["To"]
                )
            ],
        )

    if refused:
        raise RuntimeError(
            f"Destinataire refusé : {refused}"
        )


def process_company_delivery(
    conn,
    company_id,
    as_of_date=None,
    dry_run=True,
    from_address=None,
    max_send=None,
):
    """
    Prépare ou envoie les diffusions d'une société.

    dry_run=True :
        aucun SMTP ;
        prépare message + ICS + MIME ;
        journalise en 'simulated'.

    dry_run=False :
        envoie réellement par SMTP ;
        'sent' uniquement après succès ;
        'error' en cas d'échec.

    max_send :
        limite le nombre de TENTATIVES réelles.
        max_send=1 garantit qu'un seul mail
        maximum peut être tenté.
    """

    if as_of_date is None:
        as_of_date = date.today()

    settings = _smtp_settings()

    if from_address is None:
        from_address = (
            settings["user"]
            or DEFAULT_FROM_ADDRESS
        )

    events = evaluate_pending_delivery_events(
        conn,
        company_id,
        as_of_date=as_of_date,
    )

    results = []

    attempt_count = 0

    for event in events:
        if (
            not dry_run
            and max_send is not None
            and attempt_count >= max_send
        ):
            break

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
            event.get(
                "event_revision"
            )
            or 0
        )

        event_date = (
            str(event.get("event_date"))
            if event.get("event_date")
            else None
        )

        status = "simulated"
        error_message = None
        sent_ok = False

        if not dry_run:
            attempt_count += 1

            try:
                _send_email_smtp(
                    email_message
                )

                status = "sent"
                sent_ok = True

            except Exception as exc:
                status = "error"
                error_message = str(exc)

        if not dry_run:
            if sent_ok:
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
                        ?,
                        CURRENT_TIMESTAMP,
                        NULL
                    )
                    ON CONFLICT(
                        recipient_id,
                        rule_id,
                        event_key,
                        event_revision
                    )
                    DO UPDATE SET
                        company_id =
                            excluded.company_id,
                        profile_id =
                            excluded.profile_id,
                        event_uid =
                            excluded.event_uid,
                        subject =
                            excluded.subject,
                        status =
                            excluded.status,
                        sent_at =
                            CURRENT_TIMESTAMP,
                        error_message =
                            NULL
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
                        status,
                    ),
                )
    
            else:
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
                        ?,
                        NULL,
                        ?
                    )
                    ON CONFLICT(
                        recipient_id,
                        rule_id,
                        event_key,
                        event_revision
                    )
                    DO UPDATE SET
                        company_id =
                            excluded.company_id,
                        profile_id =
                            excluded.profile_id,
                        event_uid =
                            excluded.event_uid,
                        subject =
                            excluded.subject,
                        status =
                            excluded.status,
                        sent_at =
                            NULL,
                        error_message =
                            excluded.error_message
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
                        status,
                        error_message,
                    ),
                )
    
            conn.execute(
                """
                UPDATE contract_delivery_log
                SET event_date = ?
                WHERE company_id = ?
                  AND recipient_id = ?
                  AND rule_id = ?
                  AND event_key = ?
                  AND event_revision = ?
                """,
                (
                    event_date,
                    int(event["company_id"]),
                    int(event["recipient_id"]),
                    int(event["rule_id"]),
                    str(event["event_key"]),
                    event_revision,
                ),
            )
    
        results.append(
            {
                "company_id":
                    int(event["company_id"]),

                "profile_key":
                    event["profile_key"],

                "recipient_email":
                    event["recipient_email"],

                "event_key":
                    event["event_key"],

                "event_uid":
                    event["event_uid"],

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
                    status,

                "error_message":
                    error_message,
            }
        )

        if not dry_run:
            conn.commit()

    return results