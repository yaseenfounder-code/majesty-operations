# Majesty OS Demo

A standalone, local manufacturing and warehouse demo. **No live TikTok, Shopify, Odoo, ShipStation, carrier, camera, accounting, or production inventory connection exists.** All sample identities and shipments are fictional. The shipping PDF is visibly void and has no postage.

## Run on a Mac mini (Python 3.11+)

From this `majesty-os-demo` directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app majesty:create_app seed
flask --app majesty:create_app run --host 127.0.0.1 --port 5000
```

Open `http://127.0.0.1:5000` in the browser **on the same machine**. On Windows, activate `.venv\Scripts\activate` instead. The SQLite database is `instance/majesty.db`, ignored by Git. Initialization creates tables; `seed` only populates an empty database and is safe to repeat. No credentials or external service are needed. Live processes must be started again after restarting your computer or cloud task.

Run tests:

```sh
python -m pytest -q
```

Tests use isolated temporary databases, not the running demo database. To start a separate fresh demo without deleting the existing database, set `DATABASE_URL=sqlite:////absolute/path/to/new-demo.db` when seeding and running. Never point this demo at a live database.

## Demonstrate the full loop

1. Use the **ADMIN** demo role in the sidebar. Open **Raw Materials** to see oils (mL), shared packaging (each), labels, lots, suppliers, and location quantities.
2. Open **BOMs**, select **Vanaco 30 mL**, target **500**, and calculate. Initially the maximum is **180**, limited by back labels. Oil shortage is **2,700 mL**, and back label shortage is **320**. The calculator subtracts materials allocated to active production. Select any product to inspect its eight BOM lines. The editor can change component quantities, and shared templates merge common lines without deleting fragrance-specific lines. Editing is blocked while that product has an open production order; cancel or finish it first.
3. Open **Manufacturing**. Use the seeded **MO1**, 20 Vanaco units, or create a small new order. Creation does not consume stock. Click **Allocate materials**, **Confirm pulled** for every component, and **Start production**. Complete 5 units to demonstrate partial production, then the remaining 15. The resulting consumption is 180 mL oil, 420 mL base, and 20 of each packaging component. Finished stock appears in **RESERVE-R03**. Canceling an unfinished remainder releases its material allocation; completed output remains intact.
4. Open **Audit Log** to inspect `PRODUCTION_CONSUMPTION` and `PRODUCTION_OUTPUT`. Open **Replenishment** and refill Vanaco's pick face to its target of 40. This moves stock from reserve to **PICK-A-12** without changing total stock.
5. Open **Mapping Review**. Approve **Vanaco 30ML → Vanaco 30 mL** for TikTok order **TT10001**. The exact Rouge SKU already resolved automatically. The unrelated **Laytown 50 mL** example deliberately has **NO STRONG SUGGESTION**; reject it or leave it pending. Catalog selection supports browsing every product and text filtering. Approved source/item mappings apply to future identical marketplace keys.
6. Open **Orders**, find **TT10001**, and **Reserve inventory**. Physical quantities remain unchanged; available pick inventory decreases. Insufficient forward-pick stock creates an exception and a waiting status; replenish and retry. Reservations are all-or-nothing across order lines.
7. Switch to **FEEDER**. Select **TOTE-001**, then **Get next order**. It takes the oldest eligible reserved order. Try `WRONG` to see a red warning and an exception. Enter `MJS-FR-0362-VA-30`, quantity 2, and `MJS-FR-0002-RO-50`, quantity 1. A barcode scanner acting as a keyboard can enter the displayed `DEMO-…` barcodes instead. Complete pick. Goods physically move into the tote location; reservations are released as items are picked.
8. Switch to **PACKER**. Start the tote's packing session. **CAMERA: RECORDING** is explicitly a simulation: a session record is created, no actual recording takes place. Verify the same two product quantities. Generate the void demo PDF label, then **Complete order & release tote**. Packing cannot complete with missing products or without a label.
9. Switch to **ADMIN**. The order is **SHIPPED**, the tote is **AVAILABLE**, and the packing session has completion timestamps and a simulated video reference. Inspect `RESERVATION`, `PICK`, `PACK`, and `SHIP` transactions and the completed session. Shipping removes stock once; moving stock into tote/packing locations does not.
10. In **Orders**, import a new fake TikTok order with marketplace key `tt-vanaco-30`. It now resolves using the saved mapping. Use a unique order number each time.

## Architecture

- **Flask + Jinja + vanilla JavaScript:** server-rendered screens, mobile/tablet responsive CSS, warehouse-sized actions, form validation, local demo role switching, CSRF protection.
- **SQLAlchemy relational models:** products/components, BOMs/templates/lines, locations, balances, append-only application inventory transactions, production/material consumption, customer orders/lines, mappings/reviews, reservations, totes/assignments, pick/pack events, shipments, camera sessions, users, audit and exception events.
- **`majesty/services.py`:** shared inventory and workflow rules. Stock movements update balances and ledger together inside a database transaction. Reservations are separate records with ledger events. Quantity fields use decimal arithmetic; fractional raw materials are supported. Components are measured in native units; no barcode per mL is required.
- **`majesty/db.py`:** SQLite foreign keys and serialized write transactions (`BEGIN IMMEDIATE`) prevent two workers from simultaneously claiming stock/totes. Rejected requests roll back all preceding mutations and record an exception in a separate transaction. SQLAlchemy keeps schema/application code portable; see PostgreSQL caveat below.
- **`majesty/adapters.py`:** marketplace, shipping, camera and AI verification contracts, functional demo marketplace/shipping implementations. Real provider implementations are intentionally absent. Packing sessions store expected order links, pack events, station, operator, timestamps, simulated recording reference and an unrun AI outcome. No facial recognition.
- **`majesty/seed.py`:** ten fragrance SKUs in 30/50/100 mL variants, shared components, three templates, sample production/orders, mapping edge cases, locations, four users, eight reusable totes. Initial inventory itself is entered as receipt transactions.
- **`tests/test_workflow.py`:** buildability/shortages, production allocation/consumption/output/partial cancellation, stock conservation, reservation availability/rollback, mapping persistence, wrong scan/overpick, tote exclusivity, packing guards, ledger/session/shipment results, seed idempotence, page rendering, CSRF/role controls, and a complete HTTP production-to-shipment flow.

The database schema is defined in `majesty/models.py`. Products and raw materials share one item identity and stock ledger while being separated by item kind. This prevents disconnected manufacturing and warehouse quantities.

## Demo boundaries and next steps

This is a functional local MVP, not production-ready warehouse software. Role switching is deliberately unauthenticated and the default role is admin; keep it on loopback. There is no real recording, AI inference, carrier service, external API update, or enterprise authentication. No real PII is seeded.

Production uses BOM-derived actual consumption for the entered completed quantity; per-component variance, scrap tracking, material-bin scan verification, lot-level traceability across multiple batches, purchase orders, and accounting are future work. Lot metadata is stored on components in this demo, not a full multi-lot stock subledger. Units are native quantities; L/mL and kg/grams are not implicitly converted. Forward-pick stock must be replenished before reservation. There is no automatic replenishment scheduler. Rejected mapping orders remain exceptions for human handling.

Core relational models are PostgreSQL-compatible, but switching to PostgreSQL requires adding its driver, schema migrations, and replacing SQLite's global write serialization with tested row locks/serializable transactions and retry handling before concurrent use. `create_all` is for first-time demo initialization, not schema migration. No PostgreSQL readiness claim is made.

Before any production adoption: add authenticated users and authorization review, Alembic migrations, backups/restore tests, provider idempotency and webhooks, row-level concurrency tests for the chosen database, immutable audit retention, operational monitoring, and approved real integration adapters. All real connections must be a separate explicitly authorized project.
