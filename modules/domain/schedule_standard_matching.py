"""Exact product/route/process standard matching over caller-supplied facts."""


class ScheduleStandardMatchingPolicy:
    OUTPUT_FIELDS = (
        "id", "version", "setup_minutes", "standard_minutes_per_unit", "difficulty_factor",
        "route_id", "route_version_id", "process_id", "process_version_id", "product_id", "product_code",
    )

    @staticmethod
    def select(candidates, *, route_id, route_version_id, process_id,
               process_version_id, product_id, product_code, as_of_date):
        effective_date = (as_of_date or "").strip() or None
        eligible = [
            row for row in candidates
            if row.get("process_id") == process_id
            and row.get("status", "active") == "active"
            and float(row.get("standard_minutes_per_unit") or 0) > 0
            and (not effective_date or not row.get("effective_from") or row["effective_from"] <= effective_date)
            and (not effective_date or not row.get("effective_to") or row["effective_to"] >= effective_date)
        ]
        scopes = []
        if route_version_id and process_version_id:
            scopes.append(("route_version", lambda row:
                row.get("route_version_id") == route_version_id
                and row.get("process_version_id") == process_version_id))
        if route_id:
            scopes.append(("route", lambda row:
                row.get("route_id") == route_id
                and (row.get("route_version_id") is None or row.get("route_version_id") == route_version_id)))
        scopes.append(("process", lambda row:
            row.get("route_id") is None and row.get("route_version_id") is None
            and (row.get("process_version_id") is None or row.get("process_version_id") == process_version_id)))

        def product_match(row):
            if product_id is not None:
                return row.get("product_id") == product_id
            return bool(product_code) and row.get("product_id") is None and row.get("product_code") == product_code

        def generic_match(row):
            return (row.get("product_id") or 0) == 0 and (row.get("product_code") or "") == ""

        # Product identity has precedence over route specificity.
        for kind, identity in (("product", product_match), ("generic", generic_match)):
            for scope, relation in scopes:
                matches = [row for row in eligible if identity(row) and relation(row)]
                if matches:
                    selected = max(matches, key=lambda row: (int(row.get("version") or 0), int(row["id"])))
                    return {**{field: selected.get(field) for field in ScheduleStandardMatchingPolicy.OUTPUT_FIELDS},
                            "match_scope": f"{scope}:{kind}"}
        return None
