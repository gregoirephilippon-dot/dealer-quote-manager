from email.message import EmailMessage
from email.policy import SMTP


def build_delivery_email(
    *,
    from_address,
    to_address,
    subject,
    body_text,
    ics_content,
    event_key,
):
    if not from_address:
        raise ValueError(
            "Adresse expéditeur manquante"
        )

    if not to_address:
        raise ValueError(
            "Adresse destinataire manquante"
        )

    if not subject:
        raise ValueError(
            "Sujet manquant"
        )

    if not ics_content:
        raise ValueError(
            "Contenu ICS manquant"
        )

    message = EmailMessage(
        policy=SMTP
    )

    message["From"] = from_address
    message["To"] = to_address
    message["Subject"] = subject

    message.set_content(
        body_text or "",
        subtype="plain",
        charset="utf-8",
    )

    safe_event_key = (
        str(event_key or "event")
        .replace(":", "-")
        .replace("/", "-")
        .replace("\\", "-")
    )

    filename = (
        f"{safe_event_key}.ics"
    )

    message.add_attachment(
        ics_content.encode("utf-8"),
        maintype="text",
        subtype="calendar",
        filename=filename,
        params={
            "method": "PUBLISH",
            "charset": "utf-8",
        },
    )

    return message
