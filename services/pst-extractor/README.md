# `pst-extractor` (compiled PST extractor)

This is the **PST Pipeline V2** extractor stage: a compiled worker designed to run on **EC2**
(via AWS Batch / ECS on EC2) with local scratch (NVMe/EBS).

It:
1. Downloads a PST from S3 to local disk
2. Runs `readpst` (compiled) to export messages to EML files
3. Parses exported EML files and emits:
   - `emails.ndjson.gz` (audit/reprocess)
   - `emails.csv.gz` (DB bulk-load)
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

