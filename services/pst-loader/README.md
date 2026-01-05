# `pst-loader` (bulk loader)

Loads extractor output (`emails.csv.gz`, `attachments.csv.gz`) into Postgres/Aurora using `COPY`,
then **upserts** into core tables (`email_messages`, `email_attachments`, `evidence_items`).

This is intended to run as a separate Step Functions stage (Batch job).

## Environment Variables
- `DATABASE_URL` (required) – SQLAlchemy or psycopg2 URL
- `PST_FILE_ID` (required)
- `OUTPUT_BUCKET` (required)
- `OUTPUT_PREFIX` (required) – must include trailing `/`

## What it does (skeleton)
1. Downloads `emails.csv.gz` (required) and `attachments.csv.gz` (optional but recommended)\n+2. `COPY`s into staging tables (`pst_v2_emails_raw`, `pst_v2_attachments_raw`)\n+3. Upserts into:\n+   - `email_messages` (for correspondence UI)\n+   - `email_attachments` (for attachment tracking)\n+   - `evidence_items` (so attachments appear in the Evidence Repository + inline preview/download works)\n+\n+This makes the pipeline **end-to-end visible** in the UI without requiring follow-on manual sync steps.

