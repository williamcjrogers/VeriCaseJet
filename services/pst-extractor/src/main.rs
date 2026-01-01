use anyhow::{anyhow, Context, Result};
use aws_sdk_s3::primitives::ByteStream;
use clap::Parser;
use flate2::write::GzEncoder;
use flate2::Compression;
use mailparse::ParsedMail;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;
use uuid::Uuid;
use walkdir::WalkDir;

#[derive(Parser, Debug)]
#[command(author, version, about)]
struct Args {
    #[arg(long, env = "PST_FILE_ID")]
    pst_file_id: String,

    #[arg(long, env = "PROJECT_ID", default_value = "")]
    project_id: String,

    #[arg(long, env = "CASE_ID", default_value = "")]
    case_id: String,

    #[arg(long, env = "SOURCE_BUCKET")]
    source_bucket: String,

    #[arg(long, env = "SOURCE_KEY")]
    source_key: String,

    #[arg(long, env = "OUTPUT_BUCKET")]
    output_bucket: String,

    #[arg(long, env = "OUTPUT_PREFIX")]
    output_prefix: String,

    #[arg(long, env = "WORK_DIR", default_value = "/scratch")]
    work_dir: String,

    #[arg(long, env = "READPST_PATH", default_value = "readpst")]
    readpst_path: String,
}

#[derive(Serialize)]
struct EmailRecord {
    id: String,
    pst_file_id: String,
    project_id: Option<String>,
    case_id: Option<String>,
    source_path: String,

    message_id: Option<String>,
    in_reply_to: Option<String>,
    references: Option<String>,
    subject: Option<String>,
    from: Option<String>,
    to: Option<String>,
    cc: Option<String>,
    bcc: Option<String>,
    date: Option<String>,
    received: Vec<String>,

    body_text: Option<String>,
}

#[derive(Serialize)]
struct Manifest {
    pst_file_id: String,
    source_bucket: String,
    source_key: String,
    output_bucket: String,
    output_prefix: String,
    emails_total: usize,
    duration_s: f64,
    ndjson_gz_key: String,
    csv_gz_key: String,
    manifest_key: String,
    sha256: std::collections::BTreeMap<String, String>,
    version: String,
}

fn header_first(mail: &ParsedMail, name: &str) -> Option<String> {
    mail.headers
        .get_first_value(name)
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

fn header_all(mail: &ParsedMail, name: &str) -> Vec<String> {
    mail.headers
        .get_all_values(name)
        .into_iter()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
        .collect()
}

fn best_text_part(mail: &ParsedMail) -> Option<String> {
    // Prefer text/plain leaf parts.
    if mail.subparts.is_empty() {
        let ctype = mail.ctype.mimetype.to_ascii_lowercase();
        if ctype.starts_with("text/plain") || ctype == "text/plain" {
            return mail.get_body().ok().map(|s| s.trim().to_string());
        }
        return None;
    }
    for part in &mail.subparts {
        if let Some(text) = best_text_part(part) {
            if !text.is_empty() {
                return Some(text);
            }
        }
    }
    None
}

fn sha256_file(path: &Path) -> Result<String> {
    let mut file = File::open(path).with_context(|| format!("open {}", path.display()))?;
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 1024 * 1024];
    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

async fn upload_file(s3: &aws_sdk_s3::Client, bucket: &str, key: &str, path: &Path) -> Result<()> {
    let body = ByteStream::from_path(path.to_path_buf())
        .await
        .with_context(|| format!("read {}", path.display()))?;
    s3.put_object()
        .bucket(bucket)
        .key(key)
        .body(body)
        .send()
        .await
        .with_context(|| format!("upload s3://{}/{}", bucket, key))?;
    Ok(())
}

async fn download_file(s3: &aws_sdk_s3::Client, bucket: &str, key: &str, path: &Path) -> Result<()> {
    let obj = s3
        .get_object()
        .bucket(bucket)
        .key(key)
        .send()
        .await
        .with_context(|| format!("download s3://{}/{}", bucket, key))?;
    let mut reader = obj.body.into_async_read();
    let mut file = tokio::fs::File::create(path)
        .await
        .with_context(|| format!("create {}", path.display()))?;
    tokio::io::copy(&mut reader, &mut file)
        .await
        .with_context(|| format!("write {}", path.display()))?;
    Ok(())
}

fn run_readpst(readpst_path: &str, pst_path: &Path, out_dir: &Path) -> Result<()> {
    let status = Command::new(readpst_path)
        .args([
            "-o",
            out_dir
                .to_str()
                .ok_or_else(|| anyhow!("invalid out_dir"))?,
            pst_path
                .to_str()
                .ok_or_else(|| anyhow!("invalid pst_path"))?,
        ])
        .status()
        .with_context(|| format!("spawn {}", readpst_path))?;
    if !status.success() {
        return Err(anyhow!("readpst failed with status {}", status));
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let started = Instant::now();

    let cfg = aws_config::load_from_env().await;
    let s3 = aws_sdk_s3::Client::new(&cfg);

    let work_root = PathBuf::from(&args.work_dir).join(&args.pst_file_id);
    let extract_dir = work_root.join("extract");
    let out_dir = work_root.join("out");
    fs::create_dir_all(&extract_dir).context("create extract dir")?;
    fs::create_dir_all(&out_dir).context("create out dir")?;

    let pst_path = work_root.join("input.pst");
    download_file(&s3, &args.source_bucket, &args.source_key, &pst_path).await?;

    run_readpst(&args.readpst_path, &pst_path, &extract_dir)?;

    let ndjson_path = out_dir.join("emails.ndjson.gz");
    let csv_path = out_dir.join("emails.csv.gz");
    let manifest_path = out_dir.join("manifest.json");

    let mut ndjson = GzEncoder::new(File::create(&ndjson_path)?, Compression::default());
    let mut csv = GzEncoder::new(File::create(&csv_path)?, Compression::default());

    // CSV header: keep this stable; loader COPY uses this ordering.
    writeln!(
        csv,
        "id,pst_file_id,project_id,case_id,message_id,in_reply_to,references_header,subject,from,to,cc,bcc,date,body_text,source_path"
    )?;

    let mut emails_total = 0usize;

    for entry in WalkDir::new(&extract_dir).into_iter().filter_map(|e| e.ok()) {
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path();
        // Heuristic: `readpst` outputs lots of small metadata files; only parse files that look like mail.
        let mut buf = Vec::new();
        File::open(path)?.read_to_end(&mut buf)?;
        if buf.len() < 10 {
            continue;
        }
        // Most RFC822 messages start with a header like "From:".
        if !buf.starts_with(b"From:") && !buf.starts_with(b"Return-Path:") {
            continue;
        }

        let mail = mailparse::parse_mail(&buf)?;
        let id = Uuid::new_v4().to_string();
        let record = EmailRecord {
            id: id.clone(),
            pst_file_id: args.pst_file_id.clone(),
            project_id: if args.project_id.is_empty() {
                None
            } else {
                Some(args.project_id.clone())
            },
            case_id: if args.case_id.is_empty() {
                None
            } else {
                Some(args.case_id.clone())
            },
            source_path: path.display().to_string(),
            message_id: header_first(&mail, "Message-ID"),
            in_reply_to: header_first(&mail, "In-Reply-To"),
            references: header_first(&mail, "References"),
            subject: header_first(&mail, "Subject"),
            from: header_first(&mail, "From"),
            to: header_first(&mail, "To"),
            cc: header_first(&mail, "Cc"),
            bcc: header_first(&mail, "Bcc"),
            date: header_first(&mail, "Date"),
            received: header_all(&mail, "Received"),
            body_text: best_text_part(&mail),
        };

        let json_line = serde_json::to_string(&record)?;
        writeln!(ndjson, "{json_line}")?;

        // CSV row – escape quotes by doubling them (RFC4180).
        fn csv_escape(value: &str) -> String {
            let needs_quotes = value.contains(',') || value.contains('"') || value.contains('\n');
            if !needs_quotes {
                return value.to_string();
            }
            format!("\"{}\"", value.replace('"', "\"\""))
        }

        writeln!(
            csv,
            "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
            csv_escape(&id),
            csv_escape(&args.pst_file_id),
            csv_escape(&args.project_id),
            csv_escape(&args.case_id),
            csv_escape(record.message_id.as_deref().unwrap_or("")),
            csv_escape(record.in_reply_to.as_deref().unwrap_or("")),
            csv_escape(record.references.as_deref().unwrap_or("")),
            csv_escape(record.subject.as_deref().unwrap_or("")),
            csv_escape(record.from.as_deref().unwrap_or("")),
            csv_escape(record.to.as_deref().unwrap_or("")),
            csv_escape(record.cc.as_deref().unwrap_or("")),
            csv_escape(record.bcc.as_deref().unwrap_or("")),
            csv_escape(record.date.as_deref().unwrap_or("")),
            csv_escape(record.body_text.as_deref().unwrap_or("")),
            csv_escape(&record.source_path),
        )?;

        emails_total += 1;
    }

    ndjson.finish()?;
    csv.finish()?;

    let mut sha = std::collections::BTreeMap::new();
    sha.insert(
        "emails.ndjson.gz".to_string(),
        sha256_file(&ndjson_path)?,
    );
    sha.insert("emails.csv.gz".to_string(), sha256_file(&csv_path)?);

    let prefix = args.output_prefix.trim_start_matches('/').to_string();
    let ndjson_key = format!("{prefix}emails.ndjson.gz");
    let csv_key = format!("{prefix}emails.csv.gz");
    let manifest_key = format!("{prefix}manifest.json");

    let manifest = Manifest {
        pst_file_id: args.pst_file_id.clone(),
        source_bucket: args.source_bucket.clone(),
        source_key: args.source_key.clone(),
        output_bucket: args.output_bucket.clone(),
        output_prefix: prefix.clone(),
        emails_total,
        duration_s: started.elapsed().as_secs_f64(),
        ndjson_gz_key: ndjson_key.clone(),
        csv_gz_key: csv_key.clone(),
        manifest_key: manifest_key.clone(),
        sha256: sha,
        version: env!("CARGO_PKG_VERSION").to_string(),
    };
    let manifest_json = serde_json::to_vec_pretty(&manifest)?;
    File::create(&manifest_path)?.write_all(&manifest_json)?;

    upload_file(&s3, &args.output_bucket, &ndjson_key, &ndjson_path).await?;
    upload_file(&s3, &args.output_bucket, &csv_key, &csv_path).await?;
    upload_file(&s3, &args.output_bucket, &manifest_key, &manifest_path).await?;

    println!(
        "OK pst_file_id={} emails_total={} duration_s={:.2}",
        args.pst_file_id,
        emails_total,
        started.elapsed().as_secs_f64()
    );

    Ok(())
}
