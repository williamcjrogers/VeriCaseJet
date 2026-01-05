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
    date_epoch: Option<i64>,
    received: Vec<String>,

    body_text: Option<String>,
    body_html: Option<String>,
    // Lightweight derived fields to ease downstream loading.
    sender_email: Option<String>,
    sender_name: Option<String>,
}

#[derive(Serialize)]
struct AttachmentRecord {
    id: String,
    email_message_id: String,
    pst_file_id: String,
    project_id: Option<String>,
    case_id: Option<String>,
    filename: String,
    content_type: Option<String>,
    file_size_bytes: usize,
    s3_bucket: String,
    s3_key: String,
    attachment_hash: String,
    is_inline: bool,
    content_id: Option<String>,
    source_path: String,
}

#[derive(Serialize)]
struct Manifest {
    pst_file_id: String,
    source_bucket: String,
    source_key: String,
    output_bucket: String,
    output_prefix: String,
    emails_total: usize,
    attachments_total: usize,
    duration_s: f64,
    ndjson_gz_key: String,
    csv_gz_key: String,
    attachments_ndjson_gz_key: String,
    attachments_csv_gz_key: String,
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
            return mail.get_body().ok().map(|s| s.to_string());
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

fn best_html_part(mail: &ParsedMail) -> Option<String> {
    if mail.subparts.is_empty() {
        let ctype = mail.ctype.mimetype.to_ascii_lowercase();
        if ctype.starts_with("text/html") || ctype == "text/html" {
            return mail.get_body().ok().map(|s| s.to_string());
        }
        return None;
    }
    for part in &mail.subparts {
        if let Some(html) = best_html_part(part) {
            if !html.is_empty() {
                return Some(html);
            }
        }
    }
    None
}

fn stable_uuid(seed: &str) -> Uuid {
    // Deterministic UUID derived from SHA-256(seed). This supports idempotent reruns.
    let mut hasher = Sha256::new();
    hasher.update(seed.as_bytes());
    let digest = hasher.finalize();
    let mut bytes = [0u8; 16];
    bytes.copy_from_slice(&digest[..16]);
    // RFC4122 variant + "v5-like" version marker (0101) to keep UUIDs well-formed.
    bytes[6] = (bytes[6] & 0x0F) | 0x50;
    bytes[8] = (bytes[8] & 0x3F) | 0x80;
    Uuid::from_bytes(bytes)
}

fn sha256_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

fn sanitize_filename(value: &str, fallback: &str) -> String {
    let mut name = value.trim().to_string();
    if name.is_empty() {
        name = fallback.to_string();
    }
    // Prevent path traversal and control chars.
    name = name
        .replace('\\', "_")
        .replace('/', "_")
        .replace('\0', "")
        .replace('\r', "")
        .replace('\n', "");
    // Keep it bounded; S3 keys support long names but UIs/DBs often don't.
    if name.len() > 200 {
        name.truncate(200);
    }
    name
}

fn parse_filename_from_headers(mail: &ParsedMail) -> Option<String> {
    // Prefer Content-Disposition filename
    if let Some(cd) = header_first(mail, "Content-Disposition") {
        if let Some(fname) = parse_param(&cd, "filename") {
            return Some(fname);
        }
    }
    // Fallback: Content-Type name
    if let Some(ct) = header_first(mail, "Content-Type") {
        if let Some(name) = parse_param(&ct, "name") {
            return Some(name);
        }
    }
    None
}

fn parse_param(header_value: &str, key: &str) -> Option<String> {
    let key_l = key.to_ascii_lowercase();
    for part in header_value.split(';').skip(1) {
        let p = part.trim();
        if p.is_empty() {
            continue;
        }
        let mut iter = p.splitn(2, '=');
        let k = iter.next()?.trim().to_ascii_lowercase();
        let v = iter.next()?.trim();
        if k != key_l {
            continue;
        }
        let unquoted = v
            .trim_matches('"')
            .trim_matches('\'')
            .trim()
            .to_string();
        if unquoted.is_empty() {
            return None;
        }
        return Some(unquoted);
    }
    None
}

fn looks_like_mbox(buf: &[u8]) -> bool {
    buf.starts_with(b"From ") || buf.windows(6).any(|w| w == b"\nFrom ")
}

fn split_mbox(buf: &[u8]) -> Vec<Vec<u8>> {
    // Split an mbox file into individual RFC822 message bytes (without the "From " envelope line).
    // This is a best-effort parser and is intentionally simple.
    let mut starts: Vec<usize> = Vec::new();
    if buf.starts_with(b"From ") {
        starts.push(0);
    }
    for i in 0..buf.len().saturating_sub(6) {
        if buf[i] == b'\n' && buf[i + 1..].starts_with(b"From ") {
            starts.push(i + 1);
        }
    }
    if starts.is_empty() {
        return vec![buf.to_vec()];
    }
    starts.sort_unstable();
    starts.dedup();
    let mut out: Vec<Vec<u8>> = Vec::new();
    for (idx, start) in starts.iter().enumerate() {
        let end = starts.get(idx + 1).copied().unwrap_or(buf.len());
        if end <= *start {
            continue;
        }
        let seg = &buf[*start..end];
        // Drop the first "From " line
        if let Some(pos) = seg.iter().position(|b| *b == b'\n') {
            let msg = &seg[pos + 1..];
            if !msg.is_empty() {
                out.push(msg.to_vec());
            }
        }
    }
    out
}

fn parse_sender(from_header: &str) -> (Option<String>, Option<String>) {
    // Best-effort: "Name <email@domain>" or "email@domain"
    let text = from_header.trim();
    if text.is_empty() {
        return (None, None);
    }
    if let Some(start) = text.find('<') {
        if let Some(end) = text.find('>') {
            let email = text[start + 1..end].trim();
            let name = text[..start].trim().trim_matches('"').trim_matches('\'');
            let email_opt = if email.is_empty() { None } else { Some(email.to_string()) };
            let name_opt = if name.is_empty() { None } else { Some(name.to_string()) };
            return (email_opt, name_opt);
        }
    }
    if text.contains('@') {
        return (Some(text.to_string()), None);
    }
    (None, Some(text.to_string()))
}

fn is_attachment_part(part: &ParsedMail) -> bool {
    if !part.subparts.is_empty() {
        return false;
    }
    let ctype = part.ctype.mimetype.to_ascii_lowercase();
    if ctype.starts_with("text/plain") || ctype.starts_with("text/html") {
        return false;
    }
    // Treat non-text leaf parts with either a disposition or filename as attachment-like.
    let cd = header_first(part, "Content-Disposition").unwrap_or_default().to_ascii_lowercase();
    let has_filename = parse_filename_from_headers(part).is_some();
    if cd.starts_with("attachment") {
        return true;
    }
    if cd.starts_with("inline") && has_filename {
        return true;
    }
    // No explicit disposition, but has a name/filename and isn't text => likely an attachment.
    has_filename
}

fn collect_attachment_parts<'a>(mail: &'a ParsedMail, out: &mut Vec<&'a ParsedMail>) {
    if mail.subparts.is_empty() {
        if is_attachment_part(mail) {
            out.push(mail);
        }
        return;
    }
    for part in &mail.subparts {
        collect_attachment_parts(part, out);
    }
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
    let attachments_ndjson_path = out_dir.join("attachments.ndjson.gz");
    let attachments_csv_path = out_dir.join("attachments.csv.gz");
    let manifest_path = out_dir.join("manifest.json");

    let mut ndjson = GzEncoder::new(File::create(&ndjson_path)?, Compression::default());
    let mut csv = GzEncoder::new(File::create(&csv_path)?, Compression::default());
    let mut att_ndjson =
        GzEncoder::new(File::create(&attachments_ndjson_path)?, Compression::default());
    let mut att_csv = GzEncoder::new(File::create(&attachments_csv_path)?, Compression::default());

    // CSV header: keep this stable; loader COPY uses this ordering.
    writeln!(
        csv,
        "id,pst_file_id,project_id,case_id,message_id,in_reply_to,references_header,subject,from_header,to_header,cc_header,bcc_header,date_header,date_epoch,sender_email,sender_name,body_text,body_html,source_path"
    )?;

    let mut emails_total = 0usize;
    let mut attachments_total = 0usize;

    writeln!(
        att_csv,
        "id,email_message_id,pst_file_id,project_id,case_id,filename,content_type,file_size_bytes,s3_bucket,s3_key,attachment_hash,is_inline,content_id,source_path"
    )?;

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

        // Most RFC822 messages start with headers like "From:" or include an mbox envelope line.
        // If this looks like mbox, split into individual messages.
        let messages: Vec<Vec<u8>> = if looks_like_mbox(&buf) {
            split_mbox(&buf)
        } else {
            // Skip obvious non-mail files early.
            if !buf.starts_with(b"From:")
                && !buf.starts_with(b"Return-Path:")
                && !buf.starts_with(b"Received:")
                && !buf.starts_with(b"Date:")
                && !buf.starts_with(b"Subject:")
            {
                continue;
            }
            vec![buf]
        };

        let rel_source = path
            .strip_prefix(&extract_dir)
            .ok()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| path.display().to_string());

        for (msg_idx, msg_bytes) in messages.into_iter().enumerate() {
            // Best-effort parse; skip malformed items instead of failing the whole PST.
            let mail = match mailparse::parse_mail(&msg_bytes) {
                Ok(m) => m,
                Err(_) => continue,
            };

            let message_id = header_first(&mail, "Message-ID");
            let in_reply_to = header_first(&mail, "In-Reply-To");
            let references = header_first(&mail, "References");
            let subject = header_first(&mail, "Subject");
            let from_header = header_first(&mail, "From");
            let to_header = header_first(&mail, "To");
            let cc_header = header_first(&mail, "Cc");
            let bcc_header = header_first(&mail, "Bcc");
            let date_header = header_first(&mail, "Date");
            let date_epoch = date_header
                .as_deref()
                .and_then(|d| mailparse::dateparse(d).ok());

            let (sender_email, sender_name) = from_header
                .as_deref()
                .map(parse_sender)
                .unwrap_or((None, None));

            // Deterministic email ID
            let seed = format!(
                "pst:{}|src:{}|mid:{}|idx:{}",
                args.pst_file_id,
                rel_source,
                message_id.clone().unwrap_or_default(),
                msg_idx
            );
            let id = stable_uuid(&seed).to_string();

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
                source_path: rel_source.clone(),
                message_id,
                in_reply_to,
                references,
                subject,
                from: from_header.clone(),
                to: to_header.clone(),
                cc: cc_header.clone(),
                bcc: bcc_header.clone(),
                date: date_header.clone(),
                date_epoch,
                received: header_all(&mail, "Received"),
                body_text: best_text_part(&mail),
                body_html: best_html_part(&mail),
                sender_email,
                sender_name,
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
                "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
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
                csv_escape(
                    &record
                        .date_epoch
                        .map(|v| v.to_string())
                        .unwrap_or_default()
                ),
                csv_escape(record.sender_email.as_deref().unwrap_or("")),
                csv_escape(record.sender_name.as_deref().unwrap_or("")),
                csv_escape(record.body_text.as_deref().unwrap_or("")),
                csv_escape(record.body_html.as_deref().unwrap_or("")),
                csv_escape(&record.source_path),
            )?;

            // Attachments: extract MIME leaf parts and upload to S3 under OUTPUT_PREFIX/attachments/
            let mut parts: Vec<&ParsedMail> = Vec::new();
            collect_attachment_parts(&mail, &mut parts);
            for (part_idx, part) in parts.into_iter().enumerate() {
                let content = match part.get_body_raw() {
                    Ok(v) => v,
                    Err(_) => continue,
                };
                if content.is_empty() {
                    continue;
                }
                let attachment_hash = sha256_bytes(&content);
                let filename_raw = parse_filename_from_headers(part).unwrap_or_else(|| {
                    format!("attachment-{:03}.bin", part_idx)
                });
                let filename = sanitize_filename(&filename_raw, "attachment.bin");

                let cd = header_first(part, "Content-Disposition")
                    .unwrap_or_default()
                    .to_ascii_lowercase();
                let is_inline = cd.starts_with("inline")
                    || header_first(part, "Content-ID").is_some();
                let content_id = header_first(part, "Content-ID");
                let content_type = Some(part.ctype.mimetype.clone()).filter(|v| !v.is_empty());

                // Deterministic attachment ID.
                let att_seed = format!(
                    "pst:{}|email:{}|hash:{}|name:{}|idx:{}",
                    args.pst_file_id, id, attachment_hash, filename, part_idx
                );
                let attachment_id = stable_uuid(&att_seed).to_string();

                let safe_name = sanitize_filename(&filename, "attachment.bin");
                let prefix = args.output_prefix.trim_start_matches('/').to_string();
                let att_key = format!("{prefix}attachments/{}/{}__{}", id, attachment_id, safe_name);

                // Write attachment to local disk (keeps S3 upload path-based + avoids holding
                // multiple ByteStreams).
                let att_dir = out_dir.join("attachments").join(&id);
                fs::create_dir_all(&att_dir).ok();
                let att_path = att_dir.join(format!("{}__{}", attachment_id, safe_name));
                File::create(&att_path)?.write_all(&content)?;
                upload_file(&s3, &args.output_bucket, &att_key, &att_path).await?;

                let att_record = AttachmentRecord {
                    id: attachment_id.clone(),
                    email_message_id: id.clone(),
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
                    filename: filename.clone(),
                    content_type,
                    file_size_bytes: content.len(),
                    s3_bucket: args.output_bucket.clone(),
                    s3_key: att_key.clone(),
                    attachment_hash: attachment_hash.clone(),
                    is_inline,
                    content_id,
                    source_path: rel_source.clone(),
                };

                let att_json = serde_json::to_string(&att_record)?;
                writeln!(att_ndjson, "{att_json}")?;

                writeln!(
                    att_csv,
                    "{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
                    csv_escape(&att_record.id),
                    csv_escape(&att_record.email_message_id),
                    csv_escape(&att_record.pst_file_id),
                    csv_escape(att_record.project_id.as_deref().unwrap_or("")),
                    csv_escape(att_record.case_id.as_deref().unwrap_or("")),
                    csv_escape(&att_record.filename),
                    csv_escape(att_record.content_type.as_deref().unwrap_or("")),
                    csv_escape(&att_record.file_size_bytes.to_string()),
                    csv_escape(&att_record.s3_bucket),
                    csv_escape(&att_record.s3_key),
                    csv_escape(&att_record.attachment_hash),
                    csv_escape(if att_record.is_inline { "true" } else { "false" }),
                    csv_escape(att_record.content_id.as_deref().unwrap_or("")),
                    csv_escape(&att_record.source_path),
                )?;

                attachments_total += 1;
            }

            emails_total += 1;
        }
    }

    ndjson.finish()?;
    csv.finish()?;
    att_ndjson.finish()?;
    att_csv.finish()?;

    let mut sha = std::collections::BTreeMap::new();
    sha.insert(
        "emails.ndjson.gz".to_string(),
        sha256_file(&ndjson_path)?,
    );
    sha.insert("emails.csv.gz".to_string(), sha256_file(&csv_path)?);
    sha.insert(
        "attachments.ndjson.gz".to_string(),
        sha256_file(&attachments_ndjson_path)?,
    );
    sha.insert(
        "attachments.csv.gz".to_string(),
        sha256_file(&attachments_csv_path)?,
    );

    let prefix = args.output_prefix.trim_start_matches('/').to_string();
    let ndjson_key = format!("{prefix}emails.ndjson.gz");
    let csv_key = format!("{prefix}emails.csv.gz");
    let attachments_ndjson_key = format!("{prefix}attachments.ndjson.gz");
    let attachments_csv_key = format!("{prefix}attachments.csv.gz");
    let manifest_key = format!("{prefix}manifest.json");

    let manifest = Manifest {
        pst_file_id: args.pst_file_id.clone(),
        source_bucket: args.source_bucket.clone(),
        source_key: args.source_key.clone(),
        output_bucket: args.output_bucket.clone(),
        output_prefix: prefix.clone(),
        emails_total,
        attachments_total,
        duration_s: started.elapsed().as_secs_f64(),
        ndjson_gz_key: ndjson_key.clone(),
        csv_gz_key: csv_key.clone(),
        attachments_ndjson_gz_key: attachments_ndjson_key.clone(),
        attachments_csv_gz_key: attachments_csv_key.clone(),
        manifest_key: manifest_key.clone(),
        sha256: sha,
        version: env!("CARGO_PKG_VERSION").to_string(),
    };
    let manifest_json = serde_json::to_vec_pretty(&manifest)?;
    File::create(&manifest_path)?.write_all(&manifest_json)?;

    upload_file(&s3, &args.output_bucket, &ndjson_key, &ndjson_path).await?;
    upload_file(&s3, &args.output_bucket, &csv_key, &csv_path).await?;
    upload_file(
        &s3,
        &args.output_bucket,
        &attachments_ndjson_key,
        &attachments_ndjson_path,
    )
    .await?;
    upload_file(
        &s3,
        &args.output_bucket,
        &attachments_csv_key,
        &attachments_csv_path,
    )
    .await?;
    upload_file(&s3, &args.output_bucket, &manifest_key, &manifest_path).await?;

    println!(
        "OK pst_file_id={} emails_total={} attachments_total={} duration_s={:.2}",
        args.pst_file_id,
        emails_total,
        attachments_total,
        started.elapsed().as_secs_f64()
    );

    Ok(())
}
