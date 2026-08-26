from datetime import date

from database import (
    get_connection,
    init_db,
)

from contract_delivery_processor import (
    process_company_delivery,
)


def get_delivery_company_ids(conn):
    rows = conn.execute(
        """
        SELECT DISTINCT company_id
        FROM contract_delivery_profiles
        WHERE company_id IS NOT NULL
          AND is_active = 1
        ORDER BY company_id
        """
    ).fetchall()

    return [
        int(row["company_id"])
        for row in rows
    ]


def run_contract_deliveries(
    *,
    as_of_date=None,
    dry_run=True,
    max_send_per_company=None,
):
    if as_of_date is None:
        as_of_date = date.today()

    init_db()

    totals = {
        "companies": 0,
        "events": 0,
        "sent": 0,
        "simulated": 0,
        "errors": 0,
    }

    with get_connection() as conn:
        company_ids = get_delivery_company_ids(
            conn
        )

        print(
            "DATE EVALUATION :",
            as_of_date.isoformat(),
        )

        print(
            "MODE :",
            "DRY-RUN"
            if dry_run
            else "ENVOI REEL",
        )

        print(
            "SOCIETES A TRAITER :",
            len(company_ids),
        )

        print()

        for company_id in company_ids:
            totals["companies"] += 1

            print(
                "----------------------------------------"
            )

            print(
                "SOCIETE :",
                company_id,
            )

            try:
                results = (
                    process_company_delivery(
                        conn,
                        company_id=company_id,
                        as_of_date=as_of_date,
                        dry_run=dry_run,
                        max_send=max_send_per_company,
                    )
                )

            except Exception as exc:
                totals["errors"] += 1

                print(
                    "ERREUR SOCIETE :",
                    str(exc),
                )

                continue

            print(
                "EVENEMENTS TRAITES :",
                len(results),
            )

            totals["events"] += len(
                results
            )

            for result in results:
                status = str(
                    result.get("status")
                    or ""
                )

                if status == "sent":
                    totals["sent"] += 1

                elif status == "simulated":
                    totals["simulated"] += 1

                elif status == "error":
                    totals["errors"] += 1

                print(
                    result.get(
                        "profile_key"
                    ),
                    "|",
                    result.get(
                        "event_key"
                    ),
                    "|",
                    result.get(
                        "recipient_email"
                    ),
                    "|",
                    status,
                )

                if result.get(
                    "error_message"
                ):
                    print(
                        "ERREUR :",
                        result[
                            "error_message"
                        ],
                    )

        print()
        print(
            "========================================"
        )

        print(
            "BILAN DIFFUSION CONTRATS"
        )

        print(
            "========================================"
        )

        print(
            "SOCIETES :",
            totals["companies"],
        )

        print(
            "EVENEMENTS :",
            totals["events"],
        )

        print(
            "SIMULES :",
            totals["simulated"],
        )

        print(
            "ENVOYES :",
            totals["sent"],
        )

        print(
            "ERREURS :",
            totals["errors"],
        )

        print()

        if dry_run:
            print(
                "AUCUN MAIL REEL ENVOYE"
            )

        return totals


if __name__ == "__main__":
    run_contract_deliveries(
        dry_run=True,
    )