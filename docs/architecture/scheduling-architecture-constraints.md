# Scheduling architecture constraints

The repository enforces these boundaries through `npm run check:architecture` and
the regular Python test suite:

- Route modules may call services, but may not import database or repository modules.
  Re-export and relative import forms are expanded before the check.
- Domain policy modules may not import Flask, routes, services, database helpers, or
  repositories.
- `schedule_capacity_allocation.py` is a pure policy module: it may not import or call
  database, repository, service, or framework APIs.
- Scheduling services must read and write through repositories. The only SQL-shaped
  calls allowed in these services are explicit transaction-control statements needed
  to preserve existing transaction and `SAVEPOINT` behavior.
- Frontend features call the public `frontend/src/lib/api.js` facade. Only that facade
  may import the implementation modules under `frontend/src/lib/api/`; direct network
  transports and low-level client exports are forbidden outside the API implementation.
- Backend and frontend import graphs are checked for cycles.
- `schedule_capacity_service.py` has a decision-complexity budget of 413, measured at
  the Task 7 baseline (`0efb204`). This is a non-growth ratchet: refactors may reduce
  the score, but new branching, loops, or conditional rules must be implemented in a
  domain policy or allocator and delegated to by the service.

To run all architecture gates:

```sh
npm run check:architecture
```

The frontend build continues to run its API-facade and import-cycle gates as well.
