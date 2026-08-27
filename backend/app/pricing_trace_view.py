import json


def _money(value, currency):
    try:
        value = float(value or 0)
    except Exception:
        value = 0
    return f"{value:,.2f} {currency}".replace(",", " ")


def _percent(value):
    if value is None:
        return "-"
    try:
        return f"{float(value):.2f} %"
    except Exception:
        return "-"


def get_pricing_result_html(quote):
    currency = quote["currency"] or "EUR"

    try:
        raw_trace = quote["pricing_trace_json"]
    except Exception:
        raw_trace = None

    if not raw_trace:
        return """
        <div class="card">
            <h3>Resultat apres recalcul du contrat</h3>
            <p class="muted">
                Aucun detail de calcul enregistre.
                Utiliser Enregistrer donnees contrat + recalculer.
            </p>
        </div>
        """

    try:
        trace = json.loads(raw_trace)
    except Exception:
        return """
        <div class="card warning">
            <h3>Resultat apres recalcul du contrat</h3>
            <p>Trace de calcul illisible.</p>
        </div>
        """

    parts = trace.get("parts", {})
    labour = trace.get("labour", {})
    services = trace.get("services", {})
    fluids = trace.get("fluids", {})
    fees = trace.get("fees", {})
    result = trace.get("result", {})
    indexation = trace.get("indexation", [])

    dealer_parts = float(parts.get("dealer_total") or 0)
    customer_parts = float(parts.get("customer_total_before_indexation") or 0)

    parts_margin_amount = customer_parts - dealer_parts
    parts_margin_percent = (
        parts_margin_amount / dealer_parts * 100
        if dealer_parts > 0
        else None
    )

    part_rows = ""

    for line in parts.get("lines", []):
        part_rows += f"""
        <tr>
            <td>{line.get('part_number') or '-'}</td>
            <td>{line.get('description') or '-'}</td>
            <td>{float(line.get('quantity') or 0):.2f}</td>
            <td>{_money(line.get('imported_unit_price'), currency)}</td>
            <td>{_money(line.get('catalog_unit_price'), currency)}</td>
            <td>{line.get('discount_code') or '-'}</td>
            <td>{_percent(line.get('dealer_discount_percent'))}</td>
            <td>{_money(line.get('dealer_net_total'), currency)}</td>
            <td>{_percent(line.get('customer_discount_percent'))}</td>
            <td>{_money(line.get('customer_price_total'), currency)}</td>
            <td>{_money(line.get('margin_amount'), currency)}</td>
            <td>{_percent(line.get('margin_percent'))}</td>
        </tr>
        """

    service_rows = ""

    for service in services.get("lines", []):
        reason = service.get("exclusion_reason") or "-"

        service_rows += f"""
        <tr>
            <td>{service.get('service_id') or '-'}</td>
            <td>{service.get('service_name') or '-'}</td>
            <td>{_money(service.get('calculated_price'), currency)}</td>
            <td><strong>{_money(service.get('amount_added_to_total'), currency)}</strong></td>
            <td>{reason}</td>
        </tr>
        """

    index_rows = ""

    for row in indexation:
        index_rows += f"""
        <tr>
            <td>Annee {row.get('year')}</td>
            <td>{_percent(row.get('parts_rate'))}</td>
            <td>{float(row.get('parts_factor') or 1):.4f}</td>
            <td>{_percent(row.get('labour_rate'))}</td>
            <td>{float(row.get('labour_factor') or 1):.4f}</td>
        </tr>
        """

    return f"""
    <div class="card">
        <h3>Resultat apres recalcul du contrat</h3>

        <div class="grid">
            <div><strong>Total client</strong><br>{_money(result.get('selling_total'), currency)}</div>
            <div><strong>Prix mensuel</strong><br>{_money(result.get('selling_monthly'), currency)} / mois</div>
            <div><strong>Cout importe / heure</strong><br>{_money(result.get('cost_per_hour'), currency)} / h</div>
            <div><strong>Prix client / heure</strong><br>{_money(result.get('selling_per_hour'), currency)} / h</div>
            <div><strong>Duree calculee</strong><br>{result.get('contract_years') or 0} an(s)</div>
            <div><strong>Lignes pieces avec DC</strong><br>{parts.get('dc_lines_used') or 0}</div>
        </div>

        <hr>

        <div class="grid">
            <div><strong>Pieces achat dealer</strong><br>{_money(parts.get('dealer_total'), currency)}</div>
            <div><strong>Pieces vente client avant indexation</strong><br>{_money(parts.get('customer_total_before_indexation'), currency)}</div>
            <div><strong>Pieces apres indexation</strong><br>{_money(parts.get('indexed_customer_total'), currency)}</div>
            <div><strong>Marge pieces avant indexation</strong><br>{_money(parts_margin_amount, currency)} ({_percent(parts_margin_percent)})</div>
            <div><strong>Main-d'oeuvre importee</strong><br>{_money(labour.get('imported_total'), currency)}</div>
            <div>
                <strong>Traçabilité MO</strong><br>
                Source Volvo :
                {_money(labour.get('source_rate'), currency)} / h
                × {float(labour.get('source_hours') or 0):.2f} h
                = {_money(labour.get('source_total'), currency)}
                <br>
                DQM :
                {_money(labour.get('active_rate'), currency)} / h
                × {float(labour.get('source_hours') or 0):.2f} h
                = {_money(labour.get('active_total'), currency)}
                <br>
                Écart :
                {_money(labour.get('delta'), currency)}
            </div>
            <div><strong>Main-d'oeuvre apres marge</strong><br>{_money(labour.get('customer_total_before_indexation'), currency)} ({_percent(labour.get('margin_percent'))})</div>
            <div><strong>Main-d'oeuvre apres indexation</strong><br>{_money(labour.get('indexed_customer_total'), currency)}</div>
            <div><strong>Services additionnels ajoutes</strong><br>{_money(services.get('total_added'), currency)}</div>
            <div><strong>Huile + coolant</strong><br>{_money(fluids.get('total'), currency)}</div>
            <div><strong>Logistique</strong><br>{_money(fees.get('logistics_amount'), currency)} ({_percent(fees.get('logistics_percent'))})</div>
            <div><strong>Administration</strong><br>{_money(fees.get('admin_amount'), currency)} ({_percent(fees.get('admin_percent'))})</div>
        </div>

        <details style="margin-top:20px;">
            <summary class="button secondary" style="cursor:pointer; display:inline-block;">
                Voir le detail du calcul
            </summary>

            <h4 style="margin-top:20px;">Detail pieces</h4>

            <div style="overflow-x:auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Reference</th>
                            <th>Description</th>
                            <th>Qte</th>
                            <th>Prix importe</th>
                            <th>Prix catalogue</th>
                            <th>DC</th>
                            <th>Remise dealer</th>
                            <th>Achat dealer</th>
                            <th>Remise client</th>
                            <th>Vente client</th>
                            <th>Marge</th>
                            <th>Marge %</th>
                        </tr>
                    </thead>
                    <tbody>
                        {part_rows or '<tr><td colspan="12">Aucune ligne piece.</td></tr>'}
                    </tbody>
                </table>
            </div>

            <h4>Services inclus</h4>

            <div style="overflow-x:auto;">
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Service</th>
                            <th>Montant calcule</th>
                            <th>Ajoute au total</th>
                            <th>Controle anti-doublon</th>
                        </tr>
                    </thead>
                    <tbody>
                        {service_rows or '<tr><td colspan="5">Aucun service.</td></tr>'}
                    </tbody>
                </table>
            </div>

            <h4>Indexation appliquee</h4>

            <div style="overflow-x:auto;">
                <table>
                    <thead>
                        <tr>
                            <th>Annee</th>
                            <th>Pieces</th>
                            <th>Coef. pieces cumule</th>
                            <th>Main-d'oeuvre</th>
                            <th>Coef. MO cumule</th>
                        </tr>
                    </thead>
                    <tbody>
                        {index_rows or '<tr><td colspan="5">Aucune indexation.</td></tr>'}
                    </tbody>
                </table>
            </div>

            <p>
                Base client non indexee :
                <strong>{_money(fees.get('non_indexed_base'), currency)}</strong>
            </p>
        </details>
    </div>
    """
