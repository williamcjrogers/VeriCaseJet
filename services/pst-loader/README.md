# `pst-loader` (bulk loader)

Loads extractor output (`emails.csv.gz`) into Postgres/Aurora using `COPY`.

This is intended to run as a separate Step Functions stage (Batch job).

## Environment Variables
- `DATABASE_URL` (required) – SQLAlchemy or psycopg2 URL
- `PST_FILE_ID` (required)
- `OUTPUT_BUCKET` (required)
- `OUTPUT_PREFIX` (required) – must include trailing `/`

## What it does (skeleton)
1. Downloads `emails.csv.gz` from `s3://$OUTPUT_BUCKET/$OUTPUT_PREFIX/emails.csv.gz`
2. `COPY`s into a staging table `pst_v2_emails_raw`

Later stages can transform/upsert into `email_messages` (and attachments tables) deterministically.

