# Inventory Native CSV Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add native CSV downloads for order and product-code inventory views without changing existing XLSX contracts.

**Architecture:** Reuse the existing inventory query services and filters. Add small CSV serialization helpers beside the existing export methods, expose explicit `.csv` routes with the existing permission/audit decorators, and add frontend download URLs without changing the current XLSX action.

**Tech Stack:** Flask, Python `csv`/`io`, Vue composables, pytest, openpyxl for existing XLSX regression tests.

## Global Constraints

- Only the order list and product-code list receive CSV endpoints.
- Existing XLSX endpoints and response contracts remain unchanged.
- CSV is UTF-8 with BOM and uses standards-compliant quoting.
- Product codes remain text and preserve leading zeroes.
- All exports require `inventory:export` and retain audit logging.
- No database migration, attachment migration, production write, commit, push, or deployment in this task.

### Task 1: Add shared CSV serialization and product-group export

**Files:**
- Modify: `modules/services/inventory_product_query_service.py`
- Modify: `modules/services/inventory_service.py`
- Test: `tests/test_inventory_product_query.py`

- [ ] Write tests for UTF-8 BOM, headers, all filtered rows, product code text, formula-prefix protection, and unchanged inventory facts.
- [ ] Run the focused tests and verify they fail because CSV methods do not exist.
- [ ] Add `export_groups_csv(**filters)` and `export_inventory_csv(**filters)` using `io.StringIO(newline='')`, `csv.writer`, and UTF-8-BOM bytes.
- [ ] Reuse the existing paginated query loops and row mappings used by XLSX exports.
- [ ] Run the focused tests and verify they pass.

### Task 2: Expose protected CSV routes and frontend URLs

**Files:**
- Modify: `modules/routes/inventory.py`
- Modify: `frontend/src/lib/api/inventory.js`
- Modify: `frontend/src/composables/useInventory.js`
- Test: `tests/test_inventory_product_query.py`
- Test: `frontend/tests/unit/inventory-view-behavior.spec.js`

- [ ] Add `.csv` routes using `check_auth`, `check_permission('inventory:export')`, existing audit events, and `send_file` with `text/csv; charset=utf-8`.
- [ ] Add explicit CSV URL builders that preserve current filter, sort, and selected-id query parameters.
- [ ] Add a CSV action beside the existing XLSX action without changing the XLSX URL.
- [ ] Verify unauthorized users receive 403 and authorized users receive `.csv` downloads.

### Task 3: Full regression and acceptance

**Files:**
- Modify: `frontend/tests/e2e/inventory-filter-workbench.spec.js`
- Test: `tests/test_export_contracts.py`

- [ ] Add browser/API acceptance for both view downloads, filter inheritance, and file names.
- [ ] Run focused backend tests, inventory frontend tests, full frontend unit tests, build, API facade and import-cycle checks.
- [ ] Run `git diff --check` and review only intended files.
- [ ] Stop before commit, push, PR, or deployment; report results and any production-login limitation.
