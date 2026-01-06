# `pst-extractor` (compiled PST extractor)

This is the **PST Pipeline V2** extractor stage: a compiled worker designed to run on **EC2**
(via AWS Batch / ECS on EC2) with local scratch (NVMe/EBS).

It:
1. Downloads a PST from S3 to local disk
2. Runs `readpst` (compiled) to export messages to EML files
3. Parses exported EML files and emits:
   - `emails.ndjson.gz` (audit/reprocess)
   - `emails.csv.gz` (DB bulk-load)
   - `attachments.ndjson.gz` (audit/reprocess)
   - `attachments.csv.gz` (DB bulk-load)
   - raw attachment objects under `OUTPUT_PREFIX/attachments/`
   - `manifest.json`
4. Uploads outputs to S3 under `OUTPUT_PREFIX`

## Environment Variables (from Step Functions)
- `PST_FILE_ID` (required)
- `PROJECT_ID` (optional)
- `CASE_ID` (optional)
- `SOURCE_BUCKET` (required)
- `SOURCE_KEY` (required)
- `OUTPUT_BUCKET` (required)
- `OUTPUT_PREFIX` (required)

## Local run
Requires AWS credentials in the environment (or instance role in AWS):
```bash
docker build -t pst-extractor .
docker run --rm \
  -e PST_FILE_ID=... \
  -e PROJECT_ID=... \
  -e SOURCE_BUCKET=vericase-docs \
  -e SOURCE_KEY=.../file.pst \
  -e OUTPUT_BUCKET=vericase-docs \
  -e OUTPUT_PREFIX=pst-v2/.../ \
  pst-extractor
```

## Run tests

### Recommended on Windows (Docker)

Running `cargo test` natively on Windows can fail if your Rust toolchain is the GNU target
(`x86_64-pc-windows-gnu`) and you don't have `dlltool.exe` available.

This repo's simplest, most repeatable path is to run the tests in a Linux Rust container:

```bash
# from services/pst-extractor/
docker run --rm -v "$PWD:/src" -w /src rust:1.88-bookworm cargo test
```

### Native (if you already have Rust set up)

```bash
cd services/pst-extractor
cargo test
```

