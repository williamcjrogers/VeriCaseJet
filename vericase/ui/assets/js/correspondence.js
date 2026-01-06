// Use centralized configuration
const API_BASE = window.VeriCaseConfig
  ? window.VeriCaseConfig.apiUrl
  : window.location.origin;
console.log("Correspondence using API URL:", API_BASE);

// Initialize VeriCaseApp - it will handle URL params and default project
let caseId = null;
let projectId = null;
const isAdmin = true; // Open access mode

// Promise-based grid ready mechanism (no polling)
let gridApi;
let resolveGridReady;
const gridReadyPromise = new Promise((resolve) => {
  resolveGridReady = resolve;
});

// Initialize state immediately
(async function initState() {
  await VeriCaseApp.init();
  caseId = VeriCaseApp.caseId;
  projectId = VeriCaseApp.projectId;
  window.caseId = caseId; // Make it globally available for other functions
  console.log(
    "VeriCaseApp initialized - projectId:",
    projectId,
    "caseId:",
    caseId,
  );

  // Update URL if needed (so bookmarks work)
  VeriCaseApp.updateUrl();

  // Wait for grid to be ready using promise (no polling)
  await gridReadyPromise;

  // Keywords and stakeholders are now preloaded in onGridReady callback
  // which also triggers a cell refresh after caches are populated.
  
  console.log(
    "[Correspondence] Grid ready with project:",
    projectId,
  );
})();
// NOTE: columnApi is deprecated in AG Grid v31+. All column methods are now on gridApi.
let allEmails = [];
let currentViewMode = "all";
let currentAttachment;
let showFullContent = true; // Default to showing full content
let hideExcludedEmails = true; // Default to hiding excluded emails
let lastIncludeHiddenState = false;
let attachmentPreviewKeyHandler = null;
let smartFilterFields = new Set();
let smartFilterLastText = "";
let emailBodyViewMode = "outlook"; // "outlook" (HTML as Outlook would show), "raw" (full text), or "cleaned" (display)
let currentEmailDetailData = null; // Store current detail data for toggle

// Server-side filter state (drives AG Grid SSRM endpoint query params)
let selectedStakeholderId = null;
let selectedDomain = null;  // Domain filter (extracted from emails)
let selectedKeywordId = null;
let stakeholdersCache = null;
let domainsCache = null;  // Cache for email domains
let keywordsCache = null;
let keywordIndex = null;
let emailAddressesCache = null;  // Cache for unique email addresses for filters

// Linking target caches
const linkTargetsCache = {
  matter: null,
  claim: null,
};

const GRID_VIEW_STORAGE_KEY = "vc_correspondence_grid_views";
const GRID_VIEW_ACTIVE_KEY = "vc_correspondence_grid_view_active";
const DEFAULT_HIDDEN_COLUMNS = new Set([
  "email_body_full",
  "thread_id",
  "has_attachments",
]);

// Grid performance: fixed row heights (avoid autoHeight measurement on large datasets)
const ROW_HEIGHT_COLLAPSED = 96;
const ROW_HEIGHT_EXPANDED = 360;

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Get Font Awesome icon class for a file based on extension
function getFileIconClass(filename) {
  const ext = (filename || "").toLowerCase().split(".").pop();
  const iconMap = {
    // Documents
    pdf: "fas fa-file-pdf",
    doc: "fas fa-file-word",
    docx: "fas fa-file-word",
    xls: "fas fa-file-excel",
    xlsx: "fas fa-file-excel",
    ppt: "fas fa-file-powerpoint",
    pptx: "fas fa-file-powerpoint",
    // Text
    txt: "fas fa-file-alt",
    csv: "fas fa-file-csv",
    json: "fas fa-file-code",
    xml: "fas fa-file-code",
    html: "fas fa-file-code",
    md: "fas fa-file-alt",
    // Images
    png: "fas fa-file-image",
    jpg: "fas fa-file-image",
    jpeg: "fas fa-file-image",
    gif: "fas fa-file-image",
    svg: "fas fa-file-image",
    webp: "fas fa-file-image",
    bmp: "fas fa-file-image",
    tiff: "fas fa-file-image",
    // Media
    mp3: "fas fa-file-audio",
    wav: "fas fa-file-audio",
    ogg: "fas fa-file-audio",
    mp4: "fas fa-file-video",
    avi: "fas fa-file-video",
    mov: "fas fa-file-video",
    webm: "fas fa-file-video",
    // Archives
    zip: "fas fa-file-archive",
    rar: "fas fa-file-archive",
    "7z": "fas fa-file-archive",
    tar: "fas fa-file-archive",
    gz: "fas fa-file-archive",
    // Email
    msg: "fas fa-envelope",
    eml: "fas fa-envelope",
    pst: "fas fa-envelope-open-text",
  };
  return iconMap[ext] || "fas fa-file";
}

// Store current Excel workbook for sheet switching
let currentExcelWorkbook = null;

// Render Excel file preview using SheetJS
async function renderExcelPreview(url, fileName) {
  const container = document.getElementById("officePreviewContainer");
  const tabsContainer = document.getElementById("excelSheetTabs");
  if (!container) return;

  try {
    // Fetch the file as array buffer
    const response = await fetch(url);
    if (!response.ok) throw new Error("Failed to fetch file");
    const arrayBuffer = await response.arrayBuffer();

    // Parse with SheetJS
    if (typeof XLSX === "undefined") {
      throw new Error("SheetJS library not loaded");
    }

    const workbook = XLSX.read(arrayBuffer, { type: "array" });
    currentExcelWorkbook = workbook;

    // Create sheet tabs if multiple sheets
    if (workbook.SheetNames.length > 1 && tabsContainer) {
      tabsContainer.innerHTML = workbook.SheetNames.map((name, idx) =>
        `<button onclick="switchExcelSheet('${name.replace(/'/g, "\\'")}', this)"
                style="padding: 4px 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 0.75rem; font-weight: 500;
                       ${idx === 0 ? 'background: white; color: #217346;' : 'background: rgba(255,255,255,0.2); color: white;'}"
                ${idx === 0 ? 'class="active-sheet"' : ''}>
          ${escapeHtml(name)}
        </button>`
      ).join("");
    }

    // Render first sheet
    renderExcelSheet(workbook.SheetNames[0]);

  } catch (error) {
    console.error("Excel preview error:", error);
    container.innerHTML = `
      <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #6b7280; padding: 40px;">
        <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: #ef4444; margin-bottom: 16px;"></i>
        <p style="margin: 0 0 8px 0; font-weight: 600; color: #374151;">Unable to preview spreadsheet</p>
        <p style="margin: 0; text-align: center; font-size: 0.875rem;">${escapeHtml(error.message)}</p>
      </div>`;
  }
}

// Render a specific Excel sheet
function renderExcelSheet(sheetName) {
  const container = document.getElementById("officePreviewContainer");
  if (!container || !currentExcelWorkbook) return;

  const worksheet = currentExcelWorkbook.Sheets[sheetName];
  if (!worksheet) return;

  // Convert to HTML table
  const html = XLSX.utils.sheet_to_html(worksheet, { editable: false });

  // Style the table for better presentation
  container.innerHTML = `
    <style>
      #officePreviewContainer table {
        border-collapse: collapse;
        width: 100%;
        font-size: 0.8125rem;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }
      #officePreviewContainer th,
      #officePreviewContainer td {
        border: 1px solid #e5e7eb;
        padding: 6px 10px;
        text-align: left;
        white-space: nowrap;
        max-width: 300px;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      #officePreviewContainer th {
        background: #f3f4f6;
        font-weight: 600;
        color: #374151;
        position: sticky;
        top: 0;
        z-index: 1;
      }
      #officePreviewContainer tr:nth-child(even) {
        background: #f9fafb;
      }
      #officePreviewContainer tr:hover {
        background: #e5f3ff;
      }
    </style>
    ${html}
  `;
}

// Switch between Excel sheets
window.switchExcelSheet = function(sheetName, btn) {
  renderExcelSheet(sheetName);

  // Update tab styling
  const tabsContainer = document.getElementById("excelSheetTabs");
  if (tabsContainer) {
    tabsContainer.querySelectorAll("button").forEach(b => {
      b.style.background = "rgba(255,255,255,0.2)";
      b.style.color = "white";
    });
    if (btn) {
      btn.style.background = "white";
      btn.style.color = "#217346";
    }
  }
};

// Render Word document preview using Mammoth.js
async function renderWordPreview(url, fileName) {
  const container = document.getElementById("officePreviewContainer");
  if (!container) return;

  try {
    // Fetch the file as array buffer
    const response = await fetch(url);
    if (!response.ok) throw new Error("Failed to fetch file");
    const arrayBuffer = await response.arrayBuffer();

    // Parse with Mammoth.js
    if (typeof mammoth === "undefined") {
      throw new Error("Mammoth.js library not loaded");
    }

    const result = await mammoth.convertToHtml({ arrayBuffer });

    // Style the Word content
    container.innerHTML = `
      <style>
        #officePreviewContainer .word-content {
          font-family: 'Cambria', 'Georgia', serif;
          font-size: 0.95rem;
          line-height: 1.8;
          color: #1f2937;
          max-width: 800px;
          margin: 0 auto;
        }
        #officePreviewContainer .word-content h1 {
          font-size: 1.75rem;
          font-weight: 700;
          margin: 1.5em 0 0.5em;
          color: #111827;
        }
        #officePreviewContainer .word-content h2 {
          font-size: 1.375rem;
          font-weight: 600;
          margin: 1.25em 0 0.5em;
          color: #1f2937;
        }
        #officePreviewContainer .word-content h3 {
          font-size: 1.125rem;
          font-weight: 600;
          margin: 1em 0 0.5em;
          color: #374151;
        }
        #officePreviewContainer .word-content p {
          margin: 0 0 1em;
        }
        #officePreviewContainer .word-content table {
          border-collapse: collapse;
          width: 100%;
          margin: 1em 0;
        }
        #officePreviewContainer .word-content th,
        #officePreviewContainer .word-content td {
          border: 1px solid #d1d5db;
          padding: 8px 12px;
          text-align: left;
        }
        #officePreviewContainer .word-content th {
          background: #f3f4f6;
          font-weight: 600;
        }
        #officePreviewContainer .word-content ul,
        #officePreviewContainer .word-content ol {
          margin: 0.5em 0 1em;
          padding-left: 2em;
        }
        #officePreviewContainer .word-content li {
          margin: 0.25em 0;
        }
        #officePreviewContainer .word-content img {
          max-width: 100%;
          height: auto;
          margin: 1em 0;
        }
        #officePreviewContainer .word-content a {
          color: #2563eb;
          text-decoration: underline;
        }
      </style>
      <div class="word-content">
        ${result.value}
      </div>
    `;

    // Log any conversion warnings
    if (result.messages && result.messages.length > 0) {
      console.warn("Mammoth conversion warnings:", result.messages);
    }

  } catch (error) {
    console.error("Word preview error:", error);
    container.innerHTML = `
      <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #6b7280; padding: 40px;">
        <i class="fas fa-exclamation-triangle" style="font-size: 3rem; color: #ef4444; margin-bottom: 16px;"></i>
        <p style="margin: 0 0 8px 0; font-weight: 600; color: #374151;">Unable to preview document</p>
        <p style="margin: 0; text-align: center; font-size: 0.875rem;">${escapeHtml(error.message)}</p>
      </div>`;
  }
}

function rebuildKeywordIndex() {
  const map = new Map();
  if (Array.isArray(keywordsCache)) {
    keywordsCache.forEach((k) => {
      if (k && k.id) map.set(String(k.id), k);
    });
  }
  keywordIndex = map;
}

function formatMatchedKeywords(value) {
  const ids = Array.isArray(value) ? value : [];
  if (!ids.length) return "";
  const labels = ids
    .map((id) => {
      const item = keywordIndex?.get(String(id));
      return item?.name || String(id);
    })
    .filter(Boolean);
  return labels.join(", ");
}

// Vibrant color palette for keywords - each keyword gets a unique color
const KEYWORD_COLORS = [
  { bg: '#DBEAFE', border: '#3B82F6', text: '#1E40AF' },  // Blue
  { bg: '#FEF3C7', border: '#F59E0B', text: '#92400E' },  // Amber
  { bg: '#D1FAE5', border: '#10B981', text: '#065F46' },  // Green
  { bg: '#FCE7F3', border: '#EC4899', text: '#9F1239' },  // Pink
  { bg: '#E0E7FF', border: '#6366F1', text: '#3730A3' },  // Indigo
  { bg: '#FED7AA', border: '#F97316', text: '#9A3412' },  // Orange
  { bg: '#E9D5FF', border: '#A855F7', text: '#6B21A8' },  // Purple
  { bg: '#CCFBF1', border: '#14B8A6', text: '#134E4A' },  // Teal
  { bg: '#FECACA', border: '#EF4444', text: '#991B1B' },  // Red
  { bg: '#BBF7D0', border: '#22C55E', text: '#166534' },  // Lime
];

function renderKeywordChips(value) {
  const ids = Array.isArray(value) ? value : [];
  if (!ids.length) return '<span style="color: var(--text-muted);">-</span>';

  const chips = ids
    .map((id, index) => {
      const item = keywordIndex?.get(String(id));
      const name = item?.name || String(id);
      const tooltip = item?.definition
        ? `${item.definition}`
        : item?.variations
          ? `${item.variations}`
          : "";
      const titleAttr = tooltip ? ` title="${escapeHtml(tooltip)}"` : "";
      
      // Assign color based on keyword ID hash for consistency, or use index as fallback
      const colorIndex = (typeof id === 'string' ? id.charCodeAt(0) : id) % KEYWORD_COLORS.length;
      const colors = KEYWORD_COLORS[colorIndex];
      
      return `<span${titleAttr} style="display:inline-flex; align-items:center; padding:4px 12px; border-radius:999px; border: 2px solid ${colors.border}; background: ${colors.bg}; color: ${colors.text}; font-size: 0.8125rem; font-weight: 600; line-height: 1.3; white-space: nowrap; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">${escapeHtml(name)}</span>`;
    })
    .join(" ");

  return `<div style="display:flex; flex-wrap:wrap; gap:8px; padding:2px 0;">${chips}</div>`;
}

const REPLY_SPLIT_REGEX =
  /^(?:\s*>?\s*On .+ wrote:|\s*>?\s*From:\s|\s*>?\s*Sent:\s|\s*>?\s*To:\s|\s*>?\s*Cc:\s|\s*>?\s*Subject:\s|\s*>?\s*Disclaimer From:\s|-----Original Message-----|----- Forwarded message -----|Begin forwarded message)/mi;
const BANNER_PATTERNS = [
  // EXACT match for common external email banners (highest priority)
  /^\s*EXTERNAL\s+EMAIL\s*:\s*Don'?t\s+click\s+links\s+or\s+open\s+attachments\s+unless\s+the\s+content\s+is\s+expected\s+and\s+known\s+to\s+be\s+safe\.?\s*$/gmi,
  /^\s*\[?\s*EXTERNAL\s*\]?\s*:?\s*Don'?t\s+click\s+links.*$/gmi,
  // Catch ANY line containing "EXTERNAL EMAIL" followed by warning text
  /^.*EXTERNAL\s+EMAIL\s*:.*(?:click|links?|attachments?|safe).*$/gmi,
  // Original patterns
  /^\s*\[?\s*caution[:\-]?\s*external email[\s\]]?.*$/gmi,
  /^\s*\[?\s*warning[:\-]?\s*external email[\s\]]?.*$/gmi,
  /^\s*\[?\s*external sender[\s\]]?.*$/gmi,
  /^\s*external email[:\-].*$/gmi,
  /^\s*external email\b.*$/gmi,
  /^\s*caution[:\s-]*external.*$/gmi,
  /^\s*this email originated outside.*$/gmi,
  /^\s*this email originated from outside.*$/gmi,
  /^\s*do not (?:click|open) (?:links?|attachments?).*$/gmi,
  /^\s*don'?t (?:click|open) (?:links?|attachments?).*$/gmi,
  /^.*expected\s+and\s+known\s+to\s+be\s+safe.*$/gmi,
  /^\s*attachments? and links? .* (?:unsafe|suspicious|dangerous).*$/gmi,
];
const FOOTER_MARKERS = [
  /^\s*disclaimer from:.*$/mi,
  /^\s*this email (and any attachments )?(is|are) confidential.*/mi,
  /^\s*this message (and any attachments )?(contains|may contain) (confidential|privileged).*/mi,
  /^\s*the information (contained|in) this (e-?mail|message).*confidential.*/mi,
  /^\s*this email is intended.*/mi,
  /^\s*this message is intended.*/mi,
  /^\s*if you have received this (e-?mail|message) in error.*/mi,
  /^\s*if you are not the intended recipient.*/mi,
  /^\s*please notify the sender.*/mi,
  /^\s*please delete.*(this email|this message).*/mi,
  /^\s*any views or opinions.*/mi,
  /^\s*views expressed.*/mi,
  /^\s*no liability.*/mi,
  /^\s*company policy.*/mi,
  /^\s*data protection.*/mi,
  /^\s*privacy notice.*/mi,
  /^\s*disclaimer[:\s].*/mi,
  /^\s*registered office.*/mi,
  /^\s*registered address.*/mi,
  /^\s*head office.*/mi,
  /^\s*office address.*/mi,
  /^\s*registered in (england|wales|scotland|ireland).*/mi,
  /^\s*vat (registration|reg\.?|number|no\.?).*/mi,
  /^\s*company (registration|reg\.? no|number).*/mi,
  /^\s*please consider the environment.*/mi,
  /^\s*think before you print.*/mi,
  /^\s*this email has been scanned for viruses.*/mi,
  /^\s*for information about how we process data.*privacy.*/mi,
  /^\s*click here to unsubscribe.*/mi,
];

function stripInlineCssNoise(text) {
  if (!text) return "";
  return String(text).replace(/^\s*[A-Za-z][A-Za-z0-9_-]*\s*\{[^}]*\}\s*$/gm, "");
}

function extractTopMessage(text) {
  if (!text) return "";
  const normalized = String(text).replace(/\r\n/g, "\n");
  const match = REPLY_SPLIT_REGEX.exec(normalized);
  if (!match || typeof match.index !== "number") return normalized.trim();
  const candidate = normalized.slice(0, match.index).trim();
  if (candidate.length >= 20 || normalized.trim().length <= 200) {
    return candidate;
  }
  return normalized.trim();
}

function stripFooterNoise(text) {
  if (!text) return "";
  let cleaned = String(text);

  BANNER_PATTERNS.forEach((pattern) => {
    cleaned = cleaned.replace(pattern, "");
  });

  let cutIndex = -1;
  FOOTER_MARKERS.forEach((pattern) => {
    const match = pattern.exec(cleaned);
    if (match && typeof match.index === "number") {
      if (cutIndex === -1 || match.index < cutIndex) {
        cutIndex = match.index;
      }
    }
  });
  if (cutIndex >= 0) {
    cleaned = cleaned.slice(0, cutIndex).trimEnd();
  }

  cleaned = cleaned.replace(/^\s*[-_]{2,}\s*$/gm, "");
  cleaned = cleaned.replace(/^\s*$/gm, "");
  cleaned = cleaned.replace(/\n{3,}/g, "\n\n");

  return cleaned.trim();
}

function normalizeBodyWhitespace(text) {
  if (!text) return "";
  let cleaned = String(text);
  cleaned = cleaned.replace(/[^\S\n]+/g, " ");
  cleaned = cleaned.replace(/\n{3,}/g, "\n\n");
  return cleaned.trim();
}

function cleanEmailBodyText(text) {
  if (!text) return "";
  const topMessage = extractTopMessage(text);
  const noCss = stripInlineCssNoise(topMessage);
  const noFooter = stripFooterNoise(noCss);
  return normalizeBodyWhitespace(noFooter);
}

/**
 * Strip CAUTION/EXTERNAL EMAIL banners for grid display only.
 * Evidence is preserved in the Email Details modal (getRawBodyText).
 */
function stripBannersForGrid(text) {
  if (!text) return "";
  let cleaned = String(text);
  BANNER_PATTERNS.forEach((pattern) => {
    cleaned = cleaned.replace(pattern, "");
  });
  // Clean up excess whitespace after banner removal
  cleaned = cleaned.replace(/^\s*$/gm, "");
  cleaned = cleaned.replace(/\n{3,}/g, "\n\n");
  return cleaned.trim();
}

function getBodyTextValue(data) {
  // Prefer server-computed display body when present.
  // This is derived using the latest backend cleaning pipeline (HTML->text, multi-language reply parsing).
  // Strip CAUTION banners for grid preview (evidence preserved in modal via getRawBodyText).
  if (data?.email_body) {
    return stripBannersForGrid(normalizeBodyWhitespace(String(data.email_body)));
  }

  const raw = data?.body_text_clean || data?.body_text || "";
  return cleanEmailBodyText(raw);
}

function getBodyPreviewText(data) {
  const clean = getBodyTextValue(data);
  if (clean) return clean;
  return "";
}

function formatEmailBodyText(text) {
  const value = String(text || "").replace(/\r\n/g, "\n").trim();
  if (!value) return "";
  const parts = value.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  if (!parts.length) {
    return escapeHtml(value).replace(/\n/g, "<br>");
  }
  return parts
    .map((p) => `<p>${escapeHtml(p).replace(/\n/g, "<br>")}</p>`)
    .join("");
}

/**
 * Format raw body text for forensic display - preserves EVERYTHING (no filtering, no trimming content).
 * Only escapes HTML for security and converts newlines to <br> for display.
 * Evidence preservation: all text is visible by scrolling.
 */
function formatRawBodyText(text) {
  if (!text || typeof text !== "string") return "";
  // Normalize line endings only (CRLF -> LF) but preserve all content
  const value = text.replace(/\r\n/g, "\n");
  // Escape HTML for security, convert newlines to <br>, preserve all whitespace and structure
  return escapeHtml(value).replace(/\n/g, "<br>");
}

/**
 * Safely convert HTML to plain text without executing scripts.
 * Creates a temporary DOM element, sets innerHTML (which escapes scripts),
 * then extracts textContent for plain text.
 */
function htmlToTextSafe(html) {
  if (!html || typeof html !== "string") return "";
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  return tmp.textContent || tmp.innerText || "";
}

/**
 * Format recipient array (list of strings) into display string.
 */
function formatRecipients(recipients) {
  if (!recipients) return "-";
  if (Array.isArray(recipients) && recipients.length > 0) {
    return recipients.join(", ");
  }
  if (typeof recipients === "string" && recipients.trim()) {
    return recipients;
  }
  return "-";
}

/**
 * Get raw forensic body (source-of-truth) from email data - UNALTERED.
 * Prefers body_text_full, falls back to body_text, then safe HTML->text conversion.
 * Evidence preservation: returns complete unaltered text (only trims leading/trailing whitespace for display).
 */
function getRawBodyText(data) {
  // Prefer body_text_full (raw forensic source)
  if (data?.body_text_full && typeof data.body_text_full === "string") {
    return data.body_text_full;
  }
  // Fall back to body_text (also raw)
  if (data?.body_text && typeof data.body_text === "string") {
    return data.body_text;
  }
  // Last resort: safe HTML->text conversion (never executes HTML)
  if (data?.body_html && typeof data.body_html === "string") {
    return htmlToTextSafe(data.body_html);
  }
  return "";
}

function formatFileSize(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let idx = 0;
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024;
    idx += 1;
  }
  const precision = size >= 10 || idx === 0 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[idx]}`;
}

/**
 * Parse an email address string to extract name and email parts.
 * Handles formats like:
 * - "John Doe <john@example.com>"
 * - "john@example.com"
 * - "'John Doe' <john@example.com>"
 * - "john@example.com (John Doe)"
 */
function parseEmailAddress(emailStr) {
  if (!emailStr) return null;
  const str = String(emailStr).trim();
  if (!str) return null;

  // Pattern: "Name <email@domain.com>" or "'Name' <email@domain.com>"
  const angleMatch = str.match(/^["']?([^"'<]+?)["']?\s*<([^>]+)>$/);
  if (angleMatch) {
    const name = angleMatch[1].trim();
    const email = angleMatch[2].trim();
    return { name: name || null, email };
  }

  // Pattern: "email@domain.com (Name)"
  const parenMatch = str.match(/^([^\s(]+@[^\s(]+)\s*\(([^)]+)\)$/);
  if (parenMatch) {
    const email = parenMatch[1].trim();
    const name = parenMatch[2].trim();
    return { name: name || null, email };
  }

  // Just an email address
  const emailOnly = str.match(/^[^\s@]+@[^\s@]+\.[^\s@]+$/);
  if (emailOnly) {
    return { name: null, email: str };
  }

  // Fallback: could be just a name or malformed
  if (str.includes("@")) {
    // Try to extract email from string
    const emailInStr = str.match(/([^\s<>"']+@[^\s<>"']+\.[^\s<>"',;]+)/);
    if (emailInStr) {
      const email = emailInStr[1];
      const name = str.replace(email, "").replace(/[<>"'(),;]/g, "").trim();
      return { name: name || null, email };
    }
  }

  // Treat as name/text only
  return { name: str, email: null };
}

/**
 * Split a string containing multiple email addresses.
 * Handles comma, semicolon, and newline separators.
 */
function splitEmailAddresses(value) {
  if (!value) return [];
  const str = String(value).trim();
  if (!str) return [];

  // Split by comma, semicolon, or newline - but be careful with quoted names containing commas
  const results = [];
  let current = "";
  let inQuotes = false;
  let inAngleBrackets = false;

  for (let i = 0; i < str.length; i++) {
    const char = str[i];
    
    if (char === '"' || char === "'") {
      inQuotes = !inQuotes;
      current += char;
    } else if (char === '<') {
      inAngleBrackets = true;
      current += char;
    } else if (char === '>') {
      inAngleBrackets = false;
      current += char;
    } else if (!inQuotes && !inAngleBrackets && (char === ',' || char === ';' || char === '\n')) {
      const trimmed = current.trim();
      if (trimmed) results.push(trimmed);
      current = "";
    } else {
      current += char;
    }
  }
  
  const final = current.trim();
  if (final) results.push(final);

  return results;
}

/**
 * Extract domain/company name from an email address.
 * e.g., "john@example.com" → "example.com"
 */
function extractDomainFromEmail(email) {
  if (!email || typeof email !== 'string') return null;
  const atIndex = email.lastIndexOf('@');
  if (atIndex === -1) return null;
  return email.substring(atIndex + 1).toLowerCase();
}

/**
 * Extract unique stakeholder domains from From, To, and Cc fields.
 * Returns an array of unique domain names.
 */
function extractStakeholders(emailFrom, emailTo, emailCc) {
  const domains = new Set();

  // Helper to process a field (which may contain multiple addresses)
  const processField = (value) => {
    if (!value) return;
    const addresses = splitEmailAddresses(value);
    for (const addr of addresses) {
      const parsed = parseEmailAddress(addr);
      if (parsed && parsed.email) {
        const domain = extractDomainFromEmail(parsed.email);
        if (domain) {
          domains.add(domain);
        }
      }
    }
  };

  processField(emailFrom);
  processField(emailTo);
  processField(emailCc);

  return Array.from(domains).sort();
}

/**
 * Format email address(es) for display in the grid.
 * Shows FULL name and email address clearly - no truncation.
 */
function formatEmailAddressCell(value) {
  if (!value) return '<span style="color: var(--text-muted);">-</span>';

  const addresses = splitEmailAddresses(value);
  if (!addresses.length) return '<span style="color: var(--text-muted);">-</span>';

  const parsed = addresses.map(parseEmailAddress).filter(Boolean);
  if (!parsed.length) return '<span style="color: var(--text-muted);">-</span>';

  // Format each address as: Name <email> or just email
  const formatOne = (p) => {
    if (p.name && p.email) {
      return `<div style="line-height: 1.5; margin-bottom: 4px;">
        <span style="font-weight: 600; color: var(--text-primary);">${escapeHtml(p.name)}</span>
        <span style="color: var(--text-muted); font-size: 0.85rem;"> &lt;${escapeHtml(p.email)}&gt;</span>
      </div>`;
    }
    if (p.email) {
      return `<div style="line-height: 1.5; margin-bottom: 4px; color: var(--text-primary);">${escapeHtml(p.email)}</div>`;
    }
    if (p.name) {
      return `<div style="line-height: 1.5; margin-bottom: 4px; font-weight: 600; color: var(--text-primary);">${escapeHtml(p.name)}</div>`;
    }
    return '';
  };

  // Show all addresses (up to 5, then show count)
  const maxToShow = 5;
  const toShow = parsed.slice(0, maxToShow);
  const remaining = parsed.length - maxToShow;

  let html = toShow.map(formatOne).join('');
  
  if (remaining > 0) {
    const moreNames = parsed.slice(maxToShow).map(p => p.name || p.email).join(', ');
    html += `<div style="color: var(--vc-teal); font-size: 0.8rem; font-weight: 600;" title="${escapeHtml(moreNames)}">+${remaining} more</div>`;
  }

  return `<div style="padding: 2px 0;">${html}</div>`;
}

// -----------------------------
// Helpers
// -----------------------------

function looksLikeUuid(value) {
  if (!value) return false;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    String(value).trim(),
  );
}

function getCsrfToken() {
  // Keep per-browser token stable to satisfy backend CSRF binding.
  const key = "vericase_csrf";
  let token = localStorage.getItem(key);
  if (token && /^[a-f0-9]{64}$/i.test(token)) return token;

  try {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    token = Array.from(bytes)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  } catch {
    // Fallback: less ideal, but keeps UI functional.
    token = Array.from({ length: 64 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
  }

  localStorage.setItem(key, token);
  return token;
}

function getAuthHeaders() {
  const token =
    localStorage.getItem("vericase_token") ||
    localStorage.getItem("token") ||
    localStorage.getItem("jwt") ||
    "";
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  // Safe to always include; backend only enforces on CSRF-protected endpoints.
  headers["X-CSRF-Token"] = getCsrfToken();
  return headers;
}

// -----------------------------
// Assistant (Quick/Deep)
// -----------------------------

function getAssistantEls() {
  return {
    query: document.getElementById("aiQuery"),
    response: document.getElementById("aiResponse"),
    progress: document.getElementById("researchProgress"),
    progressTitle: document.getElementById("progressTitle"),
    progressStatus: document.getElementById("progressStatus"),
    researchPlan: document.getElementById("researchPlan"),
    modelProgress: document.getElementById("modelProgress"),
    modelsStatus: document.getElementById("aiModelsStatus"),
    quickBtn: document.getElementById("quickSearchBtn"),
    deepBtn: document.getElementById("deepResearchBtn"),
  };
}

function getChatContext() {
  // Prefer app-state context (URL/localStorage aware), then local globals.
  const ctxCaseId =
    window.caseId ||
    (window.VeriCaseApp ? window.VeriCaseApp.caseId : null) ||
    caseId ||
    null;
  const ctxProjectId =
    (window.VeriCaseApp ? window.VeriCaseApp.projectId : null) ||
    projectId ||
    null;

  if (ctxCaseId) return { case_id: ctxCaseId, project_id: null };
  if (ctxProjectId) return { project_id: ctxProjectId, case_id: null };
  return { project_id: null, case_id: null };
}

function setAssistantBusy({ busy, mode, statusText }) {
  const els = getAssistantEls();

  if (els.quickBtn) els.quickBtn.disabled = !!busy;
  if (els.deepBtn) els.deepBtn.disabled = !!busy;

  if (els.modelsStatus) {
    els.modelsStatus.textContent = statusText || (busy ? "Working…" : "");
  }

  if (!els.progress) return;
  if (busy) {
    els.progress.style.display = "block";
    if (els.progressTitle) {
      els.progressTitle.textContent = mode === "deep" ? "Deep analysis…" : "Quick analysis…";
    }
    if (els.progressStatus) {
      els.progressStatus.textContent = "Reviewing relevant emails…";
    }
  } else {
    els.progress.style.display = "none";
  }
}

function sanitizeUrl(url) {
  try {
    const u = String(url || "").trim();
    if (!u) return null;
    if (/^(https?:\/\/|mailto:)/i.test(u)) return u;
    return null;
  } catch {
    return null;
  }
}

function renderInline(rawText) {
  let t = escapeHtml(rawText);

  // Inline code
  t = t.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Links: [text](url)
  t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, label, url) => {
    const safe = sanitizeUrl(url);
    if (!safe) return label;
    return `<a href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });

  // Bold - improved pattern to handle text like **Word:** correctly
  t = t.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // Italic
  t = t.replace(/(^|[^*])\*([^*]+?)\*(?!\*)/g, "$1<em>$2</em>");

  return t;
}

function renderMarkdown(markdown) {
  const src = String(markdown || "").replace(/\r\n/g, "\n");
  const lines = src.split("\n");

  const out = [];
  let inCodeBlock = false;
  let codeLang = "";
  let codeLines = [];
  let listType = null; // 'ul' | 'ol' | null
  let paragraphLines = [];

  function flushParagraph() {
    const text = paragraphLines.join(" ").trim();
    if (text) out.push(`<p>${renderInline(text)}</p>`);
    paragraphLines = [];
  }

  function closeList() {
    if (listType) {
      out.push(`</${listType}>`);
      listType = null;
    }
  }

  function openList(type) {
    if (listType !== type) {
      closeList();
      out.push(`<${type}>`);
      listType = type;
    }
  }

  for (const rawLine of lines) {
    const line = String(rawLine ?? "");
    const trimmed = line.trim();

    if (inCodeBlock) {
      if (trimmed.startsWith("```")) {
        const code = escapeHtml(codeLines.join("\n"));
        const langClass = codeLang ? ` language-${escapeHtml(codeLang)}` : "";
        out.push(`<pre><code class="${langClass.trim()}">${code}</code></pre>`);
        inCodeBlock = false;
        codeLang = "";
        codeLines = [];
      } else {
        codeLines.push(line);
      }
      continue;
    }

    if (trimmed.startsWith("```")) {
      flushParagraph();
      closeList();
      inCodeBlock = true;
      codeLang = trimmed.slice(3).trim();
      codeLines = [];
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      closeList();
      continue;
    }

    if (trimmed === "---" || trimmed === "***") {
      flushParagraph();
      closeList();
      out.push("<hr>");
      continue;
    }

    // Support h1-h6 headers (map h4-h6 to h4 for styling consistency)
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      closeList();
      const rawLevel = headingMatch[1].length;
      const level = Math.min(rawLevel, 4); // Cap at h4 for styling
      const text = headingMatch[2];
      out.push(`<h${level}>${renderInline(text)}</h${level}>`);
      continue;
    }

    const bqMatch = trimmed.match(/^>\s?(.*)$/);
    if (bqMatch) {
      flushParagraph();
      closeList();
      out.push(`<blockquote><p>${renderInline(bqMatch[1])}</p></blockquote>`);
      continue;
    }

    const olMatch = trimmed.match(/^(\d+)\.\s+(.+)$/);
    if (olMatch) {
      flushParagraph();
      openList("ol");
      out.push(`<li>${renderInline(olMatch[2])}</li>`);
      continue;
    }

    const ulMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (ulMatch) {
      flushParagraph();
      openList("ul");
      out.push(`<li>${renderInline(ulMatch[1])}</li>`);
      continue;
    }

    closeList();
    paragraphLines.push(trimmed);
  }

  if (inCodeBlock) {
    const code = escapeHtml(codeLines.join("\n"));
    const langClass = codeLang ? ` language-${escapeHtml(codeLang)}` : "";
    out.push(`<pre><code class="${langClass.trim()}">${code}</code></pre>`);
  }
  flushParagraph();
  closeList();

  return out.join("\n");
}

function renderChatResponse(payload) {
  const els = getAssistantEls();
  if (!els.response) return;

  const mode = payload?.mode || "";
  const models = Array.isArray(payload?.model_responses)
    ? payload.model_responses.map((m) => m?.model).filter(Boolean)
    : [];
  const uniqueModels = [...new Set(models.map((m) => String(m)))];
  const modelLabel = uniqueModels.length ? uniqueModels.join(", ") : "—";
  const secs =
    payload?.processing_time === null || payload?.processing_time === undefined
      ? null
      : Number(payload.processing_time);

  const answer = payload?.answer || "";
  const answerHtml = renderMarkdown(answer);

  const keyFindings = Array.isArray(payload?.key_findings)
    ? payload.key_findings.filter(Boolean).map((x) => String(x))
    : [];
  const sources = Array.isArray(payload?.sources) ? payload.sources : [];

  // Build professional header
  const headerHtml = `
    <div class="vc-assistant-header">
      <div class="vc-assistant-header-icon">
        <i class="fas fa-brain"></i>
      </div>
      <div class="vc-assistant-header-info">
        <div class="vc-assistant-header-title">Pattern Recognition & Connection Mapping</div>
        <div class="vc-assistant-header-meta">
          <span class="vc-assistant-badge vc-assistant-badge-${mode === 'deep' ? 'deep' : 'quick'}">${escapeHtml(mode === 'deep' ? 'Deep Analysis' : 'Quick Search')}</span>
          ${secs !== null && Number.isFinite(secs) ? `<span class="vc-assistant-timing"><i class="fas fa-clock"></i> ${secs.toFixed(1)}s</span>` : ""}
          <span class="vc-assistant-models"><i class="fas fa-microchip"></i> ${escapeHtml(modelLabel)}</span>
        </div>
      </div>
    </div>
  `;

  // Build key findings section with improved styling
  const keyFindingsHtml = keyFindings.length
    ? `
      <div class="vc-assistant-section vc-assistant-key-findings">
        <div class="vc-assistant-section-header">
          <i class="fas fa-lightbulb"></i>
          <span>Key Findings</span>
        </div>
        <ul class="vc-assistant-findings-list">
          ${keyFindings.map((k) => `<li>${renderInline(k)}</li>`).join("")}
        </ul>
      </div>
    `
    : "";

  // Build evidence sources with download links
  const sourcesHtml = sources.length
    ? `
      <div class="vc-assistant-section vc-assistant-evidence">
        <div class="vc-assistant-section-header">
          <i class="fas fa-file-alt"></i>
          <span>Referenced Evidence</span>
          <span class="vc-assistant-count">${sources.length}</span>
        </div>
        <div class="vc-assistant-sources">
          ${sources
            .slice(0, 15)
            .map((s, idx) => {
              const subj = s?.subject || "(No subject)";
              const sender = s?.sender || "";
              const date = s?.date ? new Date(s.date).toLocaleString() : "";
              const rel = s?.relevance || "";
              const emailId = s?.email_id || s?.id || "";
              const hasAttachment = s?.has_attachment || s?.attachment_count > 0;
              
              return `
                <div class="vc-assistant-source" ${emailId ? `data-email-id="${escapeHtml(emailId)}"` : ""}>
                  <div class="vc-assistant-source-icon">
                    <i class="fas fa-envelope"></i>
                  </div>
                  <div class="vc-assistant-source-content">
                    <div class="vc-assistant-source-title">${renderInline(subj)}</div>
                    <div class="vc-assistant-source-meta">
                      ${sender ? `<span><i class="fas fa-user"></i> ${escapeHtml(sender)}</span>` : ""}
                      ${date ? `<span><i class="fas fa-calendar"></i> ${escapeHtml(date)}</span>` : ""}
                    </div>
                    ${rel ? `<div class="vc-assistant-source-rel">${renderInline(rel)}</div>` : ""}
                  </div>
                  <div class="vc-assistant-source-actions">
                    ${emailId ? `<button class="vc-assistant-source-btn" onclick="viewEvidenceFromAssistant('${escapeHtml(emailId)}')" title="View in detail panel"><i class="fas fa-eye"></i></button>` : ""}
                    ${hasAttachment ? `<button class="vc-assistant-source-btn" onclick="downloadEvidenceFromAssistant('${escapeHtml(emailId)}')" title="Download attachments"><i class="fas fa-download"></i></button>` : ""}
                  </div>
                </div>
              `;
            })
            .join("")}
          ${sources.length > 15 ? `<div class="vc-assistant-source-more"><i class="fas fa-ellipsis-h"></i> +${sources.length - 15} more references</div>` : ""}
        </div>
      </div>
    `
    : "";

  els.response.innerHTML = `
    ${headerHtml}
    <div class="vc-assistant-body">
      <div class="vc-assistant-answer">${answerHtml}</div>
      ${keyFindingsHtml}
    </div>
    ${sourcesHtml}
  `;
  els.response.style.display = "block";

  if (els.modelsStatus) {
    els.modelsStatus.textContent = uniqueModels.length ? `Models: ${uniqueModels.join(", ")}` : "";
  }
}

// View evidence from assistant panel
function viewEvidenceFromAssistant(emailId) {
  if (!emailId) return;
  // Find and select the email in the grid if possible
  if (window.gridApi) {
    let found = false;
    window.gridApi.forEachNode((node) => {
      if (node.data && (node.data.id === emailId || node.data.email_id === emailId)) {
        node.setSelected(true, true);
        window.gridApi.ensureNodeVisible(node, 'middle');
        found = true;
      }
    });
    if (found) {
      if (window.VericaseUI?.Toast) window.VericaseUI.Toast.info("Email selected in grid");
      return;
    }
  }
  // Fallback: open in detail panel directly
  if (window.VericaseUI?.Toast) window.VericaseUI.Toast.info("Locating evidence...");
}

// Download attachments from evidence
async function downloadEvidenceFromAssistant(emailId) {
  if (!emailId) return;
  try {
    const response = await fetch(`${API_BASE}/api/evidence/${emailId}/attachments`, {
      headers: getAuthHeaders()
    });
    if (!response.ok) throw new Error("Failed to fetch attachments");
    const data = await response.json();
    if (!data.attachments || data.attachments.length === 0) {
      if (window.VericaseUI?.Toast) window.VericaseUI.Toast.info("No attachments available");
      return;
    }
    // Download each attachment
    for (const att of data.attachments) {
      const url = att.download_url || `${API_BASE}/api/evidence/${emailId}/attachments/${att.id}/download`;
      const a = document.createElement("a");
      a.href = url;
      a.download = att.filename || "attachment";
      a.target = "_blank";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
    if (window.VericaseUI?.Toast) window.VericaseUI.Toast.success(`Downloading ${data.attachments.length} attachment(s)`);
  } catch (err) {
    console.error("Download error:", err);
    if (window.VericaseUI?.Toast) window.VericaseUI.Toast.error("Failed to download attachments");
  }
}

function renderResearchPlan(plan) {
  const els = getAssistantEls();
  if (!els.researchPlan) return;

  if (!plan) {
    els.researchPlan.style.display = "none";
    els.researchPlan.innerHTML = "";
    return;
  }

  const steps = Array.isArray(plan.analysis_steps)
    ? plan.analysis_steps.filter(Boolean).map((s) => String(s))
    : [];
  const assigned = plan.models_assigned && typeof plan.models_assigned === "object" ? plan.models_assigned : {};
  const assignedRows = Object.entries(assigned)
    .map(([model, task]) => `<li><strong>${escapeHtml(model)}:</strong> ${renderInline(task)}</li>`)
    .join("");

  els.researchPlan.innerHTML = `
    <div style="font-weight:700; margin-bottom:0.4rem; color: var(--vericase-navy);">Plan</div>
    ${plan.objective ? `<p><strong>Objective:</strong> ${renderInline(plan.objective)}</p>` : ""}
    ${plan.estimated_time ? `<p><strong>Estimated:</strong> ${escapeHtml(plan.estimated_time)}</p>` : ""}
    ${steps.length ? `<p style="margin-top:0.75rem;"><strong>Steps</strong></p><ol>${steps.map((s) => `<li>${renderInline(s)}</li>`).join("")}</ol>` : ""}
    ${assignedRows ? `<p style="margin-top:0.75rem;"><strong>Models</strong></p><ul>${assignedRows}</ul>` : ""}
  `;
  els.researchPlan.style.display = "block";
}

async function runAssistantQuery(mode) {
  const els = getAssistantEls();
  const query = (els.query ? els.query.value : "").trim();
  if (!query) {
    if (window.VericaseUI?.Toast) window.VericaseUI.Toast.warning("Type a question first.");
    return;
  }

  const ctx = getChatContext();
  if (!ctx.case_id && !ctx.project_id) {
    if (window.VericaseUI?.Toast) {
      window.VericaseUI.Toast.error("No case/project selected. Open a case or project and try again.");
    }
    return;
  }

  if (els.response) {
    els.response.style.display = "none";
    els.response.innerHTML = "";
  }
  renderResearchPlan(null);

  setAssistantBusy({ busy: true, mode, statusText: mode === "deep" ? "Deep analysis…" : "Quick analysis…" });

  try {
    const resp = await fetch(`${API_BASE}/api/ai-chat/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        query,
        mode,
        project_id: ctx.project_id,
        case_id: ctx.case_id,
      }),
    });

    if (!resp.ok) {
      const detail = await resp.text();
      throw new Error(`Assistant request failed (${resp.status}): ${detail || resp.statusText}`);
    }

    const payload = await resp.json();
    if (payload?.plan) renderResearchPlan(payload.plan);
    renderChatResponse(payload);
  } catch (e) {
    console.error("Assistant query failed:", e);
    if (window.VericaseUI?.Toast) window.VericaseUI.Toast.error("Assistant request failed.");
    const els2 = getAssistantEls();
    if (els2.response) {
      els2.response.innerHTML = `<div class="vc-assistant-error"><strong>Could not complete the request.</strong><div style="margin-top:0.5rem; color: var(--text-muted);">${escapeHtml(e?.message || String(e))}</div></div>`;
      els2.response.style.display = "block";
    }
  } finally {
    setAssistantBusy({ busy: false });
  }
}

window.aiQuickSearch = function () {
  return runAssistantQuery("quick");
};

window.aiDeepResearch = function () {
  return runAssistantQuery("deep");
};

async function getEvidenceDownloadUrl(evidenceId) {
  const resp = await fetch(`${API_BASE}/api/evidence/items/${evidenceId}/download-url`, {
    headers: {
      ...getAuthHeaders(),
    },
  });
  if (!resp.ok) throw new Error("Failed to get download URL");
  const data = await resp.json();
  return {
    url: data.download_url,
    mime_type: data.mime_type,
    filename: data.filename,
  };
}

// Get full evidence data including preview URL (inline disposition for viewing)
async function getEvidenceFullData(evidenceId) {
  const resp = await fetch(`${API_BASE}/api/evidence/items/${evidenceId}/full`, {
    headers: {
      ...getAuthHeaders(),
    },
  });
  if (!resp.ok) throw new Error("Failed to get evidence data");
  return resp.json();
}

function showLoading(isLoading) {
  const el = document.getElementById("loadingOverlay");
  if (!el) return;
  el.style.display = isLoading ? "flex" : "none";
}

// Function to download attachment using a signed URL
window.downloadAttachment = async function (
  evidenceId,
  attachmentId,
  fileName,
) {
  try {
    // In the current API, attachments are served as evidence items.
    const documentId = looksLikeUuid(attachmentId) ? attachmentId : evidenceId;
    const data = await getEvidenceDownloadUrl(documentId);
    const link = document.createElement("a");
    link.href = data.url;
    link.download = fileName || "download";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } catch (e) {
    console.error("Download failed:", e);
    if (window.VericaseUI) {
      VericaseUI.Toast.error("Error downloading attachment. Please try again.");
    } else {
      alert("Download failed. Please try again.");
    }
  }
};

// Function to download current attachment from preview
window.downloadCurrentAttachment = function () {
  if (currentAttachment) {
    downloadAttachment(
      currentAttachment.evidenceId,
      currentAttachment.attachmentId,
      currentAttachment.fileName,
    );
  } else {
    if (window.VericaseUI) {
        VericaseUI.Toast.warning("No attachment selected for download.");
    } else {
        alert("No attachment selected for download.");
    }
  }
};

// Function to preview attachment (accepts legacy args but uses document signed URL)
window.previewAttachment = async function (
  evidenceId,
  attachmentId,
  fileName,
) {
  const modal = document.getElementById("attachmentPreviewModal");
  const previewContent = document.getElementById("previewContent");
  const previewTitle = document.getElementById("previewTitle");
  if (!modal || !previewContent || !previewTitle) {
    console.warn("Attachment preview modal is missing from DOM");
    return;
  }

  // In the current API, attachments are served as evidence items.
  const documentId = looksLikeUuid(attachmentId) ? attachmentId : evidenceId;

  // Store current info
  currentAttachment = {
    evidenceId: documentId,
    attachmentId: documentId,
    fileName,
  };

  // Show modal
  modal.style.display = "flex";
  modal.setAttribute("aria-hidden", "false");
  previewTitle.textContent = `Preview: ${fileName}`;
  previewContent.innerHTML =
    '<div style="text-align: center; padding: 50px;"><div class="spinner"></div><p style="margin-top: 20px; color: #6b7280;">Loading preview and OCR text...</p></div>';

  // Close modal on Escape key (avoid stacking handlers)
  if (attachmentPreviewKeyHandler) {
    document.removeEventListener("keydown", attachmentPreviewKeyHandler);
  }
  attachmentPreviewKeyHandler = function (e) {
    if (e.key === "Escape") {
      closeAttachmentPreview();
      closeProgrammeModal();
    }
  };
  document.addEventListener("keydown", attachmentPreviewKeyHandler);

  try {
    // Load both the full evidence data and OCR text in parallel
    const [fullData, ocrData] = await Promise.all([
      getEvidenceFullData(documentId),
      fetch(`${API_BASE}/api/evidence/items/${documentId}/text-content?max_length=50000`, {
        headers: {
          ...getAuthHeaders(),
        },
      })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    ]);

    // Use preview_url (inline disposition) for viewing, download_url for downloads
    const preview = fullData.preview || {};
    const previewUrl = preview.preview_url;
    const downloadUrl = fullData.download_url || preview.download_url;
    const previewType = preview.preview_type || "unsupported";
    const mimeType = preview.mime_type || "";

    // Fallback to filename detection if preview_type is unsupported
    const lowerName = (fileName || "").toLowerCase();
    const isImage = previewType === "image" || /\.(png|jpg|jpeg|gif|webp|bmp|svg|tiff?)$/i.test(lowerName);
    const isPdf = previewType === "pdf" || /\.pdf$/i.test(lowerName);
    const isText = previewType === "text" || /\.(txt|csv|json|xml|html|md|log|ini|cfg|yaml|yml)$/i.test(lowerName);
    const isOffice = previewType === "office";
    const isAudio = previewType === "audio" || mimeType.startsWith("audio/");
    const isVideo = previewType === "video" || mimeType.startsWith("video/");

    // Specific Office type detection
    const isExcel = /\.(xlsx?|xls|xlsm|xlsb|csv)$/i.test(lowerName) ||
                    mimeType.includes("spreadsheet") || mimeType.includes("excel");
    const isWord = /\.(docx?|doc|rtf)$/i.test(lowerName) ||
                   mimeType.includes("wordprocessing") || mimeType.includes("msword");
    const isPowerPoint = /\.(pptx?|ppt)$/i.test(lowerName) ||
                         mimeType.includes("presentation") || mimeType.includes("powerpoint");

    // Use preview URL for inline viewing, fallback to download URL
    const url = previewUrl || downloadUrl;

    // Build preview HTML with OCR panel
    let previewHTML =
      '<div style="display: flex; height: 100%; gap: 20px;">';

    // Left panel: Document preview (2/3 width)
    previewHTML +=
      '<div style="flex: 2; display: flex; flex-direction: column; min-width: 0;">';

    if (isImage) {
      previewHTML += `
                        <div style="flex: 1; display: flex; align-items: center; justify-content: center; background: #f3f4f6; border-radius: 8px; overflow: hidden;">
                            <img src="${url}" loading="lazy" style="max-width: 100%; max-height: 100%; object-fit: contain;" alt="${escapeHtml(fileName || 'Image')}"/>
                        </div>`;
    } else if (isPdf) {
      // Render PDF inline using object tag with iframe fallback
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; background: #111827; border-radius: 8px; overflow: hidden;">
                          <object
                            data="${url}#toolbar=1&navpanes=0"
                            type="application/pdf"
                            style="width: 100%; height: 100%; border: 0; background: white;"
                          >
                            <iframe
                              title="${escapeHtml(fileName || "PDF")}"
                              src="${url}#toolbar=1&navpanes=0"
                              style="width: 100%; height: 100%; border: 0; background: white;"
                              loading="lazy"
                            ></iframe>
                          </object>
                          <div style="display:flex; justify-content:flex-end; gap:10px; padding:10px 12px; background: #0b1220; border-top: 1px solid rgba(255,255,255,0.08);">
                            <button onclick="window.open('${url}', '_blank')"
                                    style="background: rgba(59, 130, 246, 0.92); color: white; border: none; padding: 10px 14px; border-radius: 6px; cursor: pointer; font-weight: 600;">
                              <i class="fas fa-external-link-alt"></i> Open in new tab
                            </button>
                          </div>
                        </div>`;
    } else if (isText && ocrData && ocrData.text) {
      // Show text content directly from OCR/extracted text
      const textContent = ocrData.text.length > 10000 ? ocrData.text.substring(0, 10000) + "\n..." : ocrData.text;
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; background: #0b1220; border-radius: 8px; overflow: hidden;">
                          <pre style="flex: 1; margin: 0; padding: 16px; color: #e5e7eb; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.85rem; line-height: 1.6; overflow: auto; white-space: pre-wrap; word-break: break-word;">${escapeHtml(textContent)}</pre>
                          <div style="display:flex; justify-content:flex-end; gap:10px; padding:10px 12px; background: #0a0f18; border-top: 1px solid rgba(255,255,255,0.08);">
                            <button onclick="window.open('${downloadUrl || url}', '_blank')"
                                    style="background: #10b981; color: white; border: none; padding: 10px 14px; border-radius: 6px; cursor: pointer; font-weight: 600;">
                              <i class="fas fa-download"></i> Download
                            </button>
                          </div>
                        </div>`;
    } else if (isExcel) {
      // Excel files - render using SheetJS
      const excelIcon = lowerName.endsWith('.csv') ? 'fa-file-csv' : 'fa-file-excel';
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; background: white; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb;">
                          <div style="padding: 12px 16px; background: linear-gradient(135deg, #217346 0%, #185c37 100%); display: flex; align-items: center; justify-content: space-between;">
                            <div style="display: flex; align-items: center; gap: 10px;">
                              <i class="fas ${excelIcon}" style="color: white; font-size: 1.25rem;"></i>
                              <span style="font-weight: 600; color: white;">${escapeHtml(fileName || 'Excel Spreadsheet')}</span>
                            </div>
                            <div id="excelSheetTabs" style="display: flex; gap: 4px;"></div>
                          </div>
                          <div id="officePreviewContainer" style="flex: 1; overflow: auto; background: white;">
                            <div style="display: flex; align-items: center; justify-content: center; height: 100%; color: #6b7280;">
                              <div class="spinner" style="margin-right: 12px;"></div> Loading spreadsheet...
                            </div>
                          </div>
                          <div style="display:flex; justify-content:flex-end; gap:10px; padding:10px 12px; background: #f3f4f6; border-top: 1px solid #e5e7eb;">
                            <button onclick="window.open('${downloadUrl || url}', '_blank')"
                                    style="background: #217346; color: white; border: none; padding: 10px 14px; border-radius: 6px; cursor: pointer; font-weight: 600;">
                              <i class="fas fa-download"></i> Download Original
                            </button>
                          </div>
                        </div>`;
      // Load and render Excel after DOM update
      setTimeout(() => renderExcelPreview(url, fileName), 50);
    } else if (isWord) {
      // Word documents - render using Mammoth.js
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; background: white; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb;">
                          <div style="padding: 12px 16px; background: linear-gradient(135deg, #2b579a 0%, #1e3f6f 100%); display: flex; align-items: center; gap: 10px;">
                            <i class="fas fa-file-word" style="color: white; font-size: 1.25rem;"></i>
                            <span style="font-weight: 600; color: white;">${escapeHtml(fileName || 'Word Document')}</span>
                          </div>
                          <div id="officePreviewContainer" style="flex: 1; overflow: auto; padding: 24px 32px; background: white;">
                            <div style="display: flex; align-items: center; justify-content: center; height: 100%; color: #6b7280;">
                              <div class="spinner" style="margin-right: 12px;"></div> Loading document...
                            </div>
                          </div>
                          <div style="display:flex; justify-content:flex-end; gap:10px; padding:10px 12px; background: #f3f4f6; border-top: 1px solid #e5e7eb;">
                            <button onclick="window.open('${downloadUrl || url}', '_blank')"
                                    style="background: #2b579a; color: white; border: none; padding: 10px 14px; border-radius: 6px; cursor: pointer; font-weight: 600;">
                              <i class="fas fa-download"></i> Download Original
                            </button>
                          </div>
                        </div>`;
      // Load and render Word doc after DOM update
      setTimeout(() => renderWordPreview(url, fileName), 50);
    } else if (isPowerPoint) {
      // PowerPoint - show extracted text/slides info
      const pptText = preview.preview_content || (ocrData && ocrData.text);
      const slideCount = preview.page_count;
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; background: white; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb;">
                          <div style="padding: 12px 16px; background: linear-gradient(135deg, #d24726 0%, #b7361a 100%); display: flex; align-items: center; gap: 10px;">
                            <i class="fas fa-file-powerpoint" style="color: white; font-size: 1.25rem;"></i>
                            <span style="font-weight: 600; color: white;">${escapeHtml(fileName || 'PowerPoint Presentation')}</span>
                            ${slideCount ? `<span style="background: rgba(255,255,255,0.2); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; color: white;">${slideCount} slides</span>` : ''}
                          </div>
                          <div id="officePreviewContainer" style="flex: 1; overflow: auto; padding: 24px; background: #f8f9fa;">
                            ${pptText ? `<pre style="margin: 0; white-space: pre-wrap; word-break: break-word; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 0.9rem; line-height: 1.7; color: #374151;">${escapeHtml(pptText)}</pre>` :
                              `<div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #6b7280;">
                                <i class="fas fa-file-powerpoint" style="font-size: 4rem; color: #d24726; margin-bottom: 16px;"></i>
                                <p style="margin: 0 0 8px 0; font-weight: 600; color: #374151;">PowerPoint Preview</p>
                                <p style="margin: 0; text-align: center;">Download to view the full presentation</p>
                              </div>`}
                          </div>
                          <div style="display:flex; justify-content:flex-end; gap:10px; padding:10px 12px; background: #f3f4f6; border-top: 1px solid #e5e7eb;">
                            <button onclick="window.open('${downloadUrl || url}', '_blank')"
                                    style="background: #d24726; color: white; border: none; padding: 10px 14px; border-radius: 6px; cursor: pointer; font-weight: 600;">
                              <i class="fas fa-download"></i> Download Original
                            </button>
                          </div>
                        </div>`;
    } else if (isOffice) {
      // Generic Office fallback
      const officeText = preview.preview_content || (ocrData && ocrData.text);
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; background: white; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb;">
                          <div style="padding: 12px 16px; background: #6b7280; display: flex; align-items: center; gap: 10px;">
                            <i class="fas fa-file-alt" style="color: white; font-size: 1.25rem;"></i>
                            <span style="font-weight: 600; color: white;">${escapeHtml(fileName || 'Office Document')}</span>
                          </div>
                          <div style="flex: 1; overflow: auto; padding: 24px; background: #f8f9fa;">
                            ${officeText ? `<pre style="margin: 0; white-space: pre-wrap; word-break: break-word; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 0.9rem; line-height: 1.7; color: #374151;">${escapeHtml(officeText)}</pre>` :
                              `<div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #6b7280;">
                                <i class="fas fa-file-alt" style="font-size: 4rem; color: #6b7280; margin-bottom: 16px;"></i>
                                <p style="margin: 0;">Download to view this document</p>
                              </div>`}
                          </div>
                          <div style="display:flex; justify-content:flex-end; gap:10px; padding:10px 12px; background: #f3f4f6; border-top: 1px solid #e5e7eb;">
                            <button onclick="window.open('${downloadUrl || url}', '_blank')"
                                    style="background: #6b7280; color: white; border: none; padding: 10px 14px; border-radius: 6px; cursor: pointer; font-weight: 600;">
                              <i class="fas fa-download"></i> Download Original
                            </button>
                          </div>
                        </div>`;
    } else if (isAudio) {
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #f9fafb; border-radius: 8px; padding: 40px;">
                            <i class="fas fa-music" style="font-size: 4rem; color: #8b5cf6; margin-bottom: 20px;"></i>
                            <p style="color: #374151; font-weight: 600; margin-bottom: 16px;">${escapeHtml(fileName || 'Audio File')}</p>
                            <audio controls style="width: 100%; max-width: 400px; margin-bottom: 16px;">
                              <source src="${url}" type="${mimeType || 'audio/mpeg'}">
                              Your browser does not support audio playback.
                            </audio>
                            <button onclick="window.open('${downloadUrl || url}', '_blank')"
                                    style="background: #8b5cf6; color: white; border: none; padding: 10px 20px;
                                           border-radius: 6px; cursor: pointer; font-weight: 500;">
                                <i class="fas fa-download"></i> Download
                            </button>
                        </div>`;
    } else if (isVideo) {
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; background: #111827; border-radius: 8px; overflow: hidden;">
                          <video controls style="width: 100%; height: 100%; background: #000;">
                            <source src="${url}" type="${mimeType || 'video/mp4'}">
                            Your browser does not support video playback.
                          </video>
                          <div style="display:flex; justify-content:flex-end; gap:10px; padding:10px 12px; background: #0b1220; border-top: 1px solid rgba(255,255,255,0.08);">
                            <button onclick="window.open('${downloadUrl || url}', '_blank')"
                                    style="background: #10b981; color: white; border: none; padding: 10px 14px; border-radius: 6px; cursor: pointer; font-weight: 600;">
                              <i class="fas fa-download"></i> Download
                            </button>
                          </div>
                        </div>`;
    } else {
      // Unsupported file type - show download option
      const fileIcon = getFileIconClass(fileName || "");
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #f9fafb; border-radius: 8px; padding: 40px;">
                            <i class="${fileIcon}" style="font-size: 4rem; color: #6b7280; margin-bottom: 20px;"></i>
                            <p style="color: #374151; font-weight: 600; margin-bottom: 8px;">${escapeHtml(fileName || 'File')}</p>
                            <p style="color: #6b7280; margin-bottom: 20px; text-align: center;">Preview not available for this file type</p>
                            <button onclick="window.open('${downloadUrl || url}', '_blank')"
                                    style="background: #10b981; color: white; border: none; padding: 12px 24px;
                                           border-radius: 6px; cursor: pointer; font-weight: 500;">
                                <i class="fas fa-download"></i> Download File
                            </button>
                        </div>`;
    }

    previewHTML += "</div>";

    // Right panel: Extracted text (1/3 width, if available)
    if (ocrData && (ocrData.text || ocrData.cached !== undefined)) {
      previewHTML +=
        '<div style="flex: 1; display: flex; flex-direction: column; border-left: 2px solid #e5e7eb; padding-left: 20px; min-width: 0;">';
      previewHTML +=
        '<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; gap: 10px;">';
      previewHTML +=
        '<h4 style="margin: 0; color: #1f2937; font-size: 0.95rem; flex: 1;"><i class="fas fa-scroll" style="color: #17B5A3;"></i> OCR Extracted Text</h4>';

      if (ocrData.text) {
        previewHTML += `
                            <button onclick="copyOCRText()" title="Copy text to clipboard"
                                    style="background: #10b981; color: white; border: none; padding: 6px 12px;
                                           border-radius: 6px; cursor: pointer; font-size: 0.813rem; font-weight: 500; white-space: nowrap;">
                                <i class="fas fa-copy"></i> Copy
                            </button>`;
      }
      previewHTML += "</div>";

      if (ocrData.text) {
        // Highlight keywords in OCR text
        let highlightedText = ocrData.text;

        // Get keywords from current case/project (if available)
        try {
          const entityId = resolveEntityId();
          if (entityId && entityId !== "null") {
            const keywordsResponse = await fetch(
              `${API_BASE}/api/unified/${entityId}/keywords`,
              {
                headers: {
                  Authorization: `Bearer ${localStorage.getItem("token") || localStorage.getItem("jwt") || ""}`,
                },
              },
            );
            if (keywordsResponse.ok) {
              const keywords = await keywordsResponse.json();
              keywords.forEach((k) => {
                const keyword = k.name || k.keyword_name;
                if (keyword && keyword.length > 2) {
                  // Only highlight keywords with 3+ chars
                  // Escape special regex characters
                  const escapedKeyword = keyword.replace(
                    /[.*+?^${}()|[\]\\]/g,
                    "\\$&",
                  );
                  const regex = new RegExp(
                    `(\\b${escapedKeyword}\\b)`,
                    "gi",
                  );
                  highlightedText = highlightedText.replace(
                    regex,
                    '<mark style="background: #fef08a; padding: 2px 4px; border-radius: 2px; font-weight: 600;">$1</mark>',
                  );
                }
              });
            }
          }
        } catch (e) {
          console.warn("Could not load keywords for highlighting:", e);
        }

        // Escape HTML but preserve our <mark> tags
        const textToDisplay = highlightedText
          .replace(/<mark/g, "__MARK_OPEN__")
          .replace(/<\/mark>/g, "__MARK_CLOSE__")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/__MARK_OPEN__/g, "<mark")
          .replace(/__MARK_CLOSE__/g, "</mark>");

        previewHTML += `
                            <div id="ocrTextContent" style="flex: 1; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; overflow-y: auto; font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif; font-size: 0.875rem; line-height: 1.7; color: #374151; white-space: pre-wrap; box-shadow: inset 0 2px 4px rgba(0,0,0,0.05);">
                                ${textToDisplay}
                            </div>
                            <div style="margin-top: 12px; padding: 10px 12px; background: #dcfce7; border-radius: 6px; border: 1px solid #86efac;">
                                <div style="display: flex; align-items: center; gap: 8px; font-size: 0.8125rem; color: #166534;">
                                    <i class="fas fa-check-circle"></i>
                                    <span><mark style="background: #fef08a; padding: 1px 4px; border-radius: 2px; font-weight: 600;">Keywords</mark> highlighted • Extracted by AWS Textract</span>
                                </div>
                            </div>`;
      }

      previewHTML += "</div>";
    }

    previewHTML += "</div>";
    previewContent.innerHTML = previewHTML;
  } catch (error) {
    console.error("Error loading preview:", error);
    previewContent.innerHTML = `
                    <div style="text-align: center; padding: 50px; color: #ef4444;">
                        <i class="fas fa-exclamation-triangle" style="font-size: 3rem; margin-bottom: 20px;"></i>
                        <p style="font-size: 1.125rem; font-weight: 600; margin-bottom: 10px;">Error loading preview</p>
                        <p style="color: #6b7280; margin-bottom: 20px;">${error.message}</p>
                        <button onclick="downloadCurrentAttachment()" 
                                style="background: #3b82f6; color: white; border: none; padding: 10px 24px;
                                       border-radius: 6px; cursor: pointer; font-weight: 500;">
                            <i class="fas fa-download"></i> Try Downloading Instead
                        </button>
                    </div>
                `;
    if (window.VericaseUI) {
        VericaseUI.Toast.error("Failed to load preview. Please try again.");
    }
  }
};

window.copyOCRText = async function () {
  const el = document.getElementById("ocrTextContent");
  if (!el) return;
  const text = el.innerText || "";
  try {
    await navigator.clipboard.writeText(text);
    if (window.VericaseUI) {
      VericaseUI.Toast.success("Copied to clipboard");
    }
  } catch (e) {
    console.warn("Clipboard copy failed:", e);
  }
};

window.previewAttachmentInline = async function (
  evidenceId,
  attachmentId,
  fileName,
  triggerEl,
) {
  const container = document.getElementById("attachmentPreviewInline");
  if (!container) {
    return previewAttachment(evidenceId, attachmentId, fileName);
  }

  if (triggerEl && triggerEl.classList) {
    document.querySelectorAll(".attachment-item.is-active").forEach((el) => {
      el.classList.remove("is-active");
    });
    triggerEl.classList.add("is-active");
  }

  const documentId = looksLikeUuid(attachmentId) ? attachmentId : evidenceId;
  if (!documentId) {
    container.innerHTML = `
      <div class="attachment-preview-body">
        <div class="attachment-preview-placeholder">
          <i class="fas fa-file"></i>
          <span>Preview unavailable for this attachment.</span>
        </div>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="attachment-preview-body">
      <div class="attachment-preview-placeholder">
        <div class="spinner"></div>
        <span>Loading preview...</span>
      </div>
    </div>
  `;

  let preview = null;
  let detail = {};
  let fallbackDownload = null;

  try {
    const resp = await fetch(`${API_BASE}/api/evidence/items/${documentId}/full`, {
      headers: {
        ...getAuthHeaders(),
      },
    });
    if (resp.ok) {
      const payload = await resp.json();
      preview = payload?.preview || null;
      detail = payload?.detail || {};
    }
  } catch (e) {
    console.warn("Inline preview fetch failed:", e);
  }

  if (!preview) {
    try {
      fallbackDownload = await getEvidenceDownloadUrl(documentId);
    } catch (e) {
      fallbackDownload = null;
    }
  }

  const displayName = fileName || detail.filename || "Attachment";
  const safeName = escapeHtml(displayName);
  const jsName = String(displayName).replace(/'/g, "\\'");

  let bodyHtml = "";

  if (preview) {
    switch (preview.preview_type) {
      case "image":
        bodyHtml = `<img src="${preview.preview_url}" alt="${safeName}">`;
        break;
      case "pdf":
        bodyHtml = `<iframe src="${preview.preview_url}#toolbar=0"></iframe>`;
        break;
      case "text":
      case "office": {
        const content = preview.preview_content || "No content available";
        const contentStr = typeof content === "string" ? content : JSON.stringify(content, null, 2);
        const truncated =
          contentStr.length > 2000 ? `${contentStr.substring(0, 2000)}\n...` : contentStr;
        bodyHtml = `<pre class="attachment-preview-text">${escapeHtml(truncated)}</pre>`;
        break;
      }
      default:
        bodyHtml = `
          <div class="attachment-preview-placeholder">
            <i class="fas fa-file"></i>
            <span>Preview not available</span>
          </div>
        `;
    }
  } else if (fallbackDownload?.url) {
    const mime = fallbackDownload.mime_type || "";
    if (mime.startsWith("image/")) {
      bodyHtml = `<img src="${fallbackDownload.url}" alt="${safeName}">`;
    } else if (mime === "application/pdf") {
      bodyHtml = `<iframe src="${fallbackDownload.url}#toolbar=0"></iframe>`;
    } else {
      bodyHtml = `
        <div class="attachment-preview-placeholder">
          <i class="fas fa-file"></i>
          <span>Preview not available</span>
        </div>
      `;
    }
  } else {
    bodyHtml = `
      <div class="attachment-preview-placeholder">
        <i class="fas fa-file"></i>
        <span>Preview not available</span>
      </div>
    `;
  }

  const openDisabled = documentId ? "" : "disabled";
  const downloadDisabled = documentId ? "" : "disabled";

  container.innerHTML = `
    <div class="attachment-preview-header">
      <div class="attachment-preview-title">${safeName}</div>
      <div class="attachment-preview-actions">
        <button class="btn btn-ghost" type="button" ${openDisabled}
          onclick="previewAttachment('${evidenceId}', '${attachmentId}', '${jsName}')">
          Open
        </button>
        <button class="btn" type="button" ${downloadDisabled}
          onclick="downloadAttachment('${evidenceId}', '${attachmentId}', '${jsName}')">
          Download
        </button>
      </div>
    </div>
    <div class="attachment-preview-body">
      ${bodyHtml}
    </div>
  `;
};

// Function to close attachment preview
window.closeAttachmentPreview = function () {
  const modal = document.getElementById("attachmentPreviewModal");
  if (modal) {
    modal.style.display = "none";
    modal.setAttribute("aria-hidden", "true");
  }
  currentAttachment = null;
  if (attachmentPreviewKeyHandler) {
    document.removeEventListener("keydown", attachmentPreviewKeyHandler);
    attachmentPreviewKeyHandler = null;
  }
};

// Programme Management
function openProgrammeModal() {
  const modal = document.getElementById("programmeModal");
  if (modal) {
    modal.style.display = "flex";
    modal.setAttribute("aria-hidden", "false");
    // Reset status
    const status = document.getElementById("programmeUploadStatus");
    if (status) status.innerHTML = "";
  }
}

function closeProgrammeModal() {
  const modal = document.getElementById("programmeModal");
  if (modal) {
    modal.style.display = "none";
    modal.setAttribute("aria-hidden", "true");
  }
}

async function uploadProgramme() {
  const fileInput = document.getElementById("programmeFileInput");
  const typeInput = document.getElementById("programmeTypeInput");
  const statusDiv = document.getElementById("programmeUploadStatus");

  if (!fileInput.files || fileInput.files.length === 0) {
    statusDiv.innerHTML =
      '<span style="color: red;">Please select a file.</span>';
    return;
  }

  const file = fileInput.files[0];
  const type = typeInput.value;
  const formData = new FormData();
  formData.append("file", file);
  formData.append("programme_type", type);
  // Assuming we have caseId or projectId from global state
  if (window.caseId) formData.append("case_id", window.caseId);
  if (window.projectId) formData.append("project_id", window.projectId);

  statusDiv.innerHTML = '<span style="color: blue;">Uploading...</span>';

  try {
    const response = await fetch(`${API_BASE}/api/programmes/upload`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) throw new Error("Upload failed");

    const result = await response.json();
    statusDiv.innerHTML = `<span style="color: green;">Success! Programme uploaded. ID: ${result.id}</span>`;

    // Refresh grid to show new data if any linking happened
    setTimeout(() => {
      closeProgrammeModal();
      if (gridApi) gridApi.refreshServerSide({ purge: true });
    }, 1500);
  } catch (error) {
    console.error("Upload error:", error);
    statusDiv.innerHTML = `<span style="color: red;">Error: ${error.message}</span>`;
    if (window.VericaseUI) {
      VericaseUI.Toast.error("Failed to upload programme. Please try again.");
    }
  }
};

// Server-Side Datasource for AG Grid - handles 100k+ emails efficiently
const createServerSideDatasource = () => {
  return {
    getRows: async (params) => {
      console.log(
        "[Grid] Server-side request:",
        params.request.startRow,
        "-",
        params.request.endRow,
      );
      showLoading(true);

      try {
        let apiUrl = `${API_BASE}/api/correspondence/emails/server-side`;

        // Add project/case filter + search
        const queryParams = new URLSearchParams();
        if (projectId) queryParams.append("project_id", projectId);
        if (caseId) queryParams.append("case_id", caseId);
        if (selectedDomain) queryParams.append("domain", selectedDomain);
        if (selectedKeywordId) queryParams.append("keyword_id", selectedKeywordId);
        const quickFilterEl = document.getElementById("quickFilter");
        const quickSearch = quickFilterEl ? quickFilterEl.value.trim() : "";
        if (quickSearch) queryParams.append("search", quickSearch);
        // When showing excluded emails, request hidden/spam/other-project rows from server
        if (!hideExcludedEmails) queryParams.append("include_hidden", "true");
        if (queryParams.toString())
          apiUrl += "?" + queryParams.toString();

        const response = await fetch(apiUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
          },
          body: JSON.stringify({
            startRow: params.request.startRow,
            endRow: params.request.endRow,
            sortModel: params.request.sortModel || [],
            filterModel: params.request.filterModel || {},
            groupKeys: params.request.groupKeys || [],
            rowGroupCols: params.request.rowGroupCols || [],
          }),
        });

        if (!response.ok) {
          throw new Error(`Server error: ${response.status}`);
        }

        const data = await response.json();
        console.log(
          "[Grid] Loaded",
          data.rows.length,
          "rows, lastRow:",
          data.lastRow,
          "stats:",
          data.stats,
        );

        // Update statistics on first load
        if (params.request.startRow === 0 && data.stats) {
          console.log("[Grid] Updating stats:", data.stats);
          document.getElementById("totalEmails").textContent = (
            data.stats.total || 0
          ).toLocaleString();

          const excludedEl = document.getElementById("excludedCount");
          if (excludedEl && data.stats.excludedCount !== undefined) {
            excludedEl.textContent =
              data.stats.excludedCount === null
                ? "-"
                : (data.stats.excludedCount || 0).toLocaleString();
          }

          document.getElementById("uniqueThreads").textContent = (
            data.stats.uniqueThreads || 0
          ).toLocaleString();
          document.getElementById("withAttachments").textContent = (
            data.stats.withAttachments || 0
          ).toLocaleString();
          document.getElementById("dateRange").textContent =
            data.stats.dateRange || "-";
        }

        params.success({
          rowData: data.rows,
          rowCount: data.lastRow,
        });
      } catch (error) {
        console.error("[Grid] Server-side error:", error);
        params.fail();
        if (window.VericaseUI) {
            VericaseUI.Toast.error("Failed to load emails. Please try again.");
        } else {
            alert("Failed to load emails. Please try again.");
        }
      } finally {
        showLoading(false);
      }
    },
  };
};

// -----------------------------
// Grid + UI wiring
// -----------------------------

async function openEmailDetailById(emailId, fallbackRow) {
  if (!emailId) return;
  try {
    const resp = await fetch(`${API_BASE}/api/correspondence/emails/${emailId}`, { headers: getAuthHeaders() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const detailData = await resp.json();
    renderEmailDetail(detailData);
  } catch (err) {
    console.error("Detail fetch failed:", err);
    if (fallbackRow) {
      renderEmailDetail(fallbackRow);
    }
  }
}

function toggleEmailBodyView() {
  // Cycle through: outlook -> raw -> cleaned -> outlook
  if (emailBodyViewMode === "outlook") {
    emailBodyViewMode = "raw";
  } else if (emailBodyViewMode === "raw") {
    emailBodyViewMode = "cleaned";
  } else {
    emailBodyViewMode = "outlook";
  }
  if (currentEmailDetailData) {
    renderEmailDetail(currentEmailDetailData);
  }
}

function renderEmailDetail(data) {
  const panel = document.getElementById("detailPanel");
  const content = document.getElementById("detailContent");
  if (!panel || !content) return;

  panel.classList.remove("hidden");

  // Store current data for toggle
  currentEmailDetailData = data;

  const emailId = data?.id || data?.email_id || data?.emailId || null;
  const subject = data?.subject || data?.email_subject || "(No subject)";
  const from = data?.email_from || data?.sender_email || "-";
  
  // Use recipients_to/recipients_cc arrays (forensic source), fallback to legacy email_to/email_cc
  const recipientsTo = data?.recipients_to || (data?.email_to ? [data.email_to] : []);
  const recipientsCc = data?.recipients_cc || (data?.email_cc ? [data.email_cc] : []);
  const to = formatRecipients(recipientsTo);
  const cc = formatRecipients(recipientsCc);
  
  const when = data?.email_date || data?.date_sent || null;
  const dateText = when
    ? new Date(when).toLocaleString("en-GB", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "-";
  const excluded = data?.meta?.exclusion?.excluded === true;
  const excludedLabel = data?.meta?.exclusion?.excluded_label || null;

  // Body: Outlook (HTML as rendered), Raw (forensic - FULL unaltered text), or Cleaned (display convenience)
  const rawBodyText = getRawBodyText(data);
  const cleanedBodyText = data?.body_text_clean || getBodyTextValue(data) || "";
  const bodyHtml = data?.body_html || ""; // Original HTML body from Outlook/email client
  
  // Determine view mode label and toggle button text for 3-way cycle
  let viewModeLabel, toggleLabel, bodyContent;
  if (emailBodyViewMode === "outlook") {
    viewModeLabel = "Outlook View";
    toggleLabel = "Show Raw";
    // Render HTML in a sandboxed iframe for security with Outlook-like styling
    if (bodyHtml) {
      // Build a complete HTML document with proper structure for Outlook-faithful rendering
      const outlookStyles = `
        <style>
          /* Reset and Outlook-like defaults */
          body {
            margin: 0;
            padding: 12px 16px;
            font-family: 'Segoe UI', Calibri, Arial, sans-serif;
            font-size: 11pt;
            line-height: 1.5;
            color: #1f1f1f;
            background: #ffffff;
            word-wrap: break-word;
            overflow-wrap: break-word;
          }
          /* Preserve formatting in pre/code */
          pre, code {
            white-space: pre-wrap;
            word-wrap: break-word;
          }
          /* Tables like Outlook */
          table {
            border-collapse: collapse;
          }
          td, th {
            padding: 2px 4px;
          }
          /* Images should fit */
          img {
            max-width: 100%;
            height: auto;
          }
          /* Links styling */
          a {
            color: #0563C1;
            text-decoration: underline;
          }
          /* Blockquotes for replied content */
          blockquote {
            margin: 0.5em 0 0.5em 1em;
            padding-left: 1em;
            border-left: 2px solid #ccc;
          }
        </style>
      `;
      
      // Build the complete HTML document
      const fullHtmlDoc = '<!DOCTYPE html><html><head><meta charset="UTF-8"><base target="_blank">' + outlookStyles + '</head><body>' + bodyHtml + '</body></html>';
      
      // Escape for srcdoc attribute
      const escapedDoc = fullHtmlDoc.replace(/"/g, '&quot;');
      
      bodyContent = `<iframe 
        sandbox="allow-same-origin allow-popups" 
        style="width:100%; min-height:400px; max-height:80vh; border:1px solid var(--border); border-radius:8px; background:#fff;"
        srcdoc="${escapedDoc}"
        onload="try { this.style.height = Math.min(this.contentWindow.document.body.scrollHeight + 32, window.innerHeight * 0.8) + 'px'; } catch(e) {}"
      ></iframe>`;
    } else {
      // Fallback to raw text if no HTML available
      bodyContent = formatRawBodyText(rawBodyText) || `<span style='color: var(--text-muted); font-style: italic;'>No HTML body available - showing raw text</span>`;
    }
  } else if (emailBodyViewMode === "raw") {
    viewModeLabel = "Raw (Full)";
    toggleLabel = "Show Cleaned";
    bodyContent = formatRawBodyText(rawBodyText);
  } else {
    // "cleaned" mode
    viewModeLabel = "Cleaned";
    toggleLabel = "Show Outlook";
    bodyContent = formatEmailBodyText(cleanedBodyText);
  }
  const safeBody = bodyContent;

  const attachments = Array.isArray(data?.attachments) ? data.attachments : [];
  const attHtml = attachments.length
    ? `<div class="attachment-list">${attachments
        .map((a) => {
          const evidenceId = a.evidenceId || a.id || "";
          const attachmentId = a.attachmentId || a.id || "";
          const fileName = a.fileName || a.filename || "attachment";
          const fileSize = formatFileSize(a.file_size || a.fileSize);
          return `
            <button
              type="button"
              class="attachment-item attachment-item-button"
              data-evidence-id="${escapeHtml(evidenceId)}"
              data-attachment-id="${escapeHtml(attachmentId)}"
              data-filename="${escapeHtml(fileName)}"
              onclick="previewAttachmentInline(this.dataset.evidenceId, this.dataset.attachmentId, this.dataset.filename, this)"
            >
              <div class="attachment-icon"><i class="fas fa-paperclip"></i></div>
              <div class="attachment-info">
                <div class="attachment-name">${escapeHtml(fileName)}</div>
                ${fileSize ? `<div class="attachment-size">${fileSize}</div>` : ""}
              </div>
              <div class="attachment-actions"><i class="fas fa-eye"></i></div>
            </button>
          `;
        })
        .join("")}</div>`
    : `<div class="attachment-empty">No attachments</div>`;

  const previewHtml = attachments.length
    ? `
        <div class="attachment-preview" id="attachmentPreviewInline">
          <div class="attachment-preview-body">
            <div class="attachment-preview-placeholder">
              <i class="fas fa-eye"></i>
              <span>Select an attachment to preview</span>
            </div>
          </div>
        </div>
      `
    : "";

  content.innerHTML = `
    <div style="display:flex; flex-direction:column; gap: 0.75rem;">
      <div>
        <div style="font-weight:700; font-size:1.05rem; color: var(--text-primary);">${subject}</div>
        ${excluded ? `<div style="margin-top:0.25rem; color: var(--warning); font-weight:600;">Excluded${excludedLabel ? ` • ${excludedLabel}` : ""}</div>` : ""}
      </div>
      <div style="font-size:0.875rem; color: var(--text-secondary); line-height:1.4;">
        <div><strong>From:</strong> ${escapeHtml(from)}</div>
        <div><strong>To:</strong> ${escapeHtml(to)}</div>
        <div><strong>CC:</strong> ${escapeHtml(cc)}</div>
        <div><strong>Date:</strong> ${escapeHtml(dateText)}</div>
      </div>
      <div style="border-top: 1px solid var(--border); padding-top: 0.75rem;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap: 0.75rem;">
          <div style="font-weight:600;">Linked to</div>
          ${
            looksLikeUuid(emailId)
              ? `<button class="btn btn-ghost" type="button" onclick="openLinkModalForEmail('${escapeHtml(emailId)}');"><i class="fas fa-link"></i> Link</button>`
              : ""
          }
        </div>
        <div id="emailLinksContainer" data-email-id="${escapeHtml(emailId || "")}" style="margin-top: 0.5rem;">
          <div style="color: var(--text-muted); font-size: 0.875rem;">Loading…</div>
        </div>
      </div>
      <div style="border-top: 1px solid var(--border); padding-top: 0.75rem;">
        <div style="display:flex; align-items:center; justify-content:space-between; gap: 0.75rem; margin-bottom: 0.5rem;">
          <div style="font-weight:600;">Body <span style="font-weight:400; color: var(--text-muted); font-size:0.875rem;">(${viewModeLabel})</span></div>
          <button class="btn btn-ghost" type="button" onclick="toggleEmailBodyView();" style="font-size:0.875rem;">
            ${toggleLabel}
          </button>
        </div>
        <div style="font-size:0.9rem; color: var(--text); line-height:1.6;">${safeBody || "<span style='color: var(--text-muted); font-style: italic;'>No body content available</span>"}</div>
      </div>
      <div style="border-top: 1px solid var(--border); padding-top: 0.75rem;">
        <div style="font-weight:600; margin-bottom: 0.5rem;">Attachments</div>
        ${attHtml}
        ${previewHtml}
      </div>
    </div>
  `;

  if (looksLikeUuid(emailId)) {
    void renderEmailLinks(emailId);
  } else {
    const linksEl = document.getElementById("emailLinksContainer");
    if (linksEl) {
      linksEl.innerHTML = `<div style="color: var(--text-muted); font-size: 0.875rem;">Not available</div>`;
    }
  }
}

async function renderEmailLinks(emailId) {
  const container = document.getElementById("emailLinksContainer");
  if (!container || !looksLikeUuid(emailId)) return;

  container.dataset.emailId = String(emailId);
  container.innerHTML = `<div style="color: var(--text-muted); font-size: 0.875rem;">Loading…</div>`;

  try {
    const params = new URLSearchParams();
    params.set("item_type", "correspondence");
    params.set("item_id", String(emailId));
    params.set("page_size", "100");

    const resp = await fetch(`${API_BASE}/api/claims/links?${params}`, {
      headers: { ...getAuthHeaders() },
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const links = Array.isArray(data?.items) ? data.items : [];

    // Detail panel may have moved to a different email while this was loading.
    if (container.dataset.emailId !== String(emailId)) return;

    if (!links.length) {
      container.innerHTML = `<div style="color: var(--text-muted); font-size: 0.875rem;">Not linked yet</div>`;
      return;
    }

    const itemsHtml = links
      .slice(0, 50)
      .map((l) => {
        const matter = l.contentious_matter_name || l.contentious_matter_id || "";
        const claim = l.head_of_claim_name || l.head_of_claim_id || "";
        const rows = [];
        if (matter) rows.push(`<span><i class="fas fa-briefcase"></i> ${escapeHtml(matter)}</span>`);
        if (claim) rows.push(`<span><i class="fas fa-gavel"></i> ${escapeHtml(claim)}</span>`);
        const subtitle = l.link_type ? escapeHtml(l.link_type) : "";
        return `
          <div style="padding: 0.5rem 0.75rem; border: 1px solid var(--border-default); border-radius: 10px; background: var(--bg-secondary);">
            <div style="font-weight:600; display:flex; flex-wrap: wrap; gap: 0.5rem;">${rows.join("<span style=\"color: var(--text-muted);\">•</span>")}</div>
            ${subtitle ? `<div style="font-size: 0.8125rem; color: var(--text-secondary); margin-top: 0.25rem;">${subtitle}</div>` : ""}
          </div>
        `;
      })
      .join("");

    const more = links.length > 50 ? `<div style="color: var(--text-muted); font-size: 0.8125rem;">+${links.length - 50} more</div>` : "";
    container.innerHTML = `<div style="display:flex; flex-direction:column; gap: 0.5rem;">${itemsHtml}${more}</div>`;
  } catch (e) {
    console.error(e);
    if (container.dataset.emailId !== String(emailId)) return;
    container.innerHTML = `<div style="color: var(--text-muted); font-size: 0.875rem;">Failed to load links</div>`;
  }
}

window.toggleDetailPanel = function () {
  const panel = document.getElementById("detailPanel");
  if (!panel) return;
  panel.classList.toggle("hidden");
};

window.onQuickFilterChanged = function () {
  if (gridApi) gridApi.refreshServerSide({ purge: true });
};

/**
 * Extract the search term from a smart filter query.
 * Handles quoted strings, common prefixes, and natural language patterns.
 */
function extractSmartFilterTerm(rawText) {
  const raw = String(rawText || "").trim();
  if (!raw) return "";

  // Extract quoted strings first (highest priority)
  const quoted = raw.match(/"([^"]+)"|'([^']+)'/);
  let term = quoted ? (quoted[1] || quoted[2] || "") : "";
  
  if (!term) {
    // Look for common patterns
    const patterns = [
      /\bcontain(?:s|ing)?\s+(.+?)(?:\s+in\s+|\s*$)/i,
      /\babout\s+(.+?)(?:\s+in\s+|\s*$)/i,
      /\bmentioning\s+(.+?)(?:\s+in\s+|\s*$)/i,
      /\bwith\s+(?:word|text|term)s?\s+(.+?)(?:\s+in\s+|\s*$)/i,
      /\bincluding\s+(.+?)(?:\s+in\s+|\s*$)/i,
      /\breferencing\s+(.+?)(?:\s+in\s+|\s*$)/i,
      /\brelated\s+to\s+(.+?)(?:\s+in\s+|\s*$)/i,
    ];
    
    for (const pattern of patterns) {
      const match = raw.match(pattern);
      if (match) {
        term = match[1];
        break;
      }
    }
  }
  
  if (!term) term = raw;

  // Clean up the term
  term = term.trim();
  term = term.replace(/^(filter|find|show|include|exclude|hide|remove)\b[:\s]*/i, "");
  term = term.replace(/\b(in|within|from)\s+(the\s+)?(subject|body|email|emails|from|to|cc)(\s+(and|or)\s+(the\s+)?(subject|body|from|to|cc))*.*$/i, "");
  term = term.replace(/\b(subject|body|emails?)\b/gi, "");
  term = term.replace(/^(that|which|where)\s+/i, "");
  term = term.replace(/\s+/g, " ");
  return term.trim();
}

/**
 * Parse a date expression from natural language.
 * Returns { from: Date|null, to: Date|null }
 */
function parseSmartFilterDate(rawText) {
  const lower = rawText.toLowerCase();
  const now = new Date();
  const result = { from: null, to: null };

  // "last N days/weeks/months/years"
  const lastPeriod = lower.match(/\blast\s+(\d+)\s+(day|week|month|year)s?\b/);
  if (lastPeriod) {
    const num = parseInt(lastPeriod[1], 10);
    const unit = lastPeriod[2];
    const from = new Date(now);
    if (unit === "day") from.setDate(from.getDate() - num);
    else if (unit === "week") from.setDate(from.getDate() - num * 7);
    else if (unit === "month") from.setMonth(from.getMonth() - num);
    else if (unit === "year") from.setFullYear(from.getFullYear() - num);
    result.from = from;
    return result;
  }

  // "this week/month/year"
  if (/\bthis\s+week\b/.test(lower)) {
    const from = new Date(now);
    from.setDate(from.getDate() - from.getDay());
    result.from = from;
    return result;
  }
  if (/\bthis\s+month\b/.test(lower)) {
    const from = new Date(now.getFullYear(), now.getMonth(), 1);
    result.from = from;
    return result;
  }
  if (/\bthis\s+year\b/.test(lower)) {
    const from = new Date(now.getFullYear(), 0, 1);
    result.from = from;
    return result;
  }

  // "before/after DATE" or "since DATE"
  const beforeMatch = lower.match(/\bbefore\s+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})/);
  const afterMatch = lower.match(/\b(?:after|since)\s+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})/);
  if (beforeMatch) {
    const d = new Date(beforeMatch[1]);
    if (!isNaN(d.getTime())) result.to = d;
  }
  if (afterMatch) {
    const d = new Date(afterMatch[1]);
    if (!isNaN(d.getTime())) result.from = d;
  }

  // "in 2024" or "from 2024"
  const yearMatch = lower.match(/\b(?:in|from|year)\s*(\d{4})\b/);
  if (yearMatch) {
    const year = parseInt(yearMatch[1], 10);
    result.from = new Date(year, 0, 1);
    result.to = new Date(year, 11, 31);
  }

  return result;
}

/**
 * Smart filter parser - handles natural language queries.
 * Supports:
 * - Text search with field targeting (subject, body, from, to, cc)
 * - Date filtering (last N days, this month, before/after dates)
 * - Attachment filtering (has/without attachments)
 * - Exclusion status filtering
 * - Negation (not, without, exclude)
 * - Combined queries with AND/OR
 */
function parseSmartFilter(rawText) {
  const raw = String(rawText || "").trim();
  if (!raw) return { error: "Type a smart filter query. Examples:\n• 'Smith' in subject\n• from John last 30 days\n• with attachments\n• exclude 'newsletter' in subject" };

  const lower = raw.toLowerCase();
  const filterModel = {};

  // Check for negation patterns
  const isNegated = /^(not|without|exclude|excluding|hide|remove|doesn't|dont|don't|does not|no)\b/.test(lower) ||
                    /\b(not|without)\s+(containing|mentioning|including)\b/.test(lower);

  // Identify target fields
  const targets = {
    subject: /\b(subject|subj)\b/.test(lower),
    body: /\b(body|content|message|text)\b/.test(lower),
    from: /\bfrom\b(?!\s+\d{4})|\bsender\b|\bsent\s+by\b/.test(lower),
    to: /\b(to|recipient)s?\b/.test(lower) && !/\brelated\s+to\b/.test(lower),
    cc: /\bcc\b|\bcopied\b/.test(lower),
  };

  // Attachment handling
  const wantsAttachments = /\b(has|with|having)\s+attachments?\b/.test(lower);
  const wantsNoAttachments = /\b(no|without|missing|lacks?)\s+attachments?\b/.test(lower) ||
                              /\battachments?\s+(missing|none)\b/.test(lower);

  if (wantsAttachments || wantsNoAttachments) {
    filterModel.has_attachments = {
      filterType: "boolean",
      type: "equals",
      filter: wantsNoAttachments ? false : true,
    };
  }

  // Excluded emails handling
  const wantsExcluded = /\b(show|include)\s+excluded\b/.test(lower) ||
                        /\bexcluded\s+(emails?|only)\b/.test(lower);
  const hideExcluded = /\b(hide|remove)\s+excluded\b/.test(lower);

  if (wantsExcluded) {
    filterModel.excluded = { filterType: "boolean", type: "equals", filter: true };
  } else if (hideExcluded) {
    filterModel.excluded = { filterType: "boolean", type: "equals", filter: false };
  }

  // Date handling
  const dateFilters = parseSmartFilterDate(raw);
  if (dateFilters.from || dateFilters.to) {
    const dateFilter = { filterType: "date", type: "inRange" };
    if (dateFilters.from) dateFilter.dateFrom = dateFilters.from.toISOString().split("T")[0];
    if (dateFilters.to) dateFilter.dateTo = dateFilters.to.toISOString().split("T")[0];
    
    // If only one date, use different filter type
    if (dateFilters.from && !dateFilters.to) {
      dateFilter.type = "greaterThan";
    } else if (!dateFilters.from && dateFilters.to) {
      dateFilter.type = "lessThan";
    }
    
    filterModel.email_date = dateFilter;
  }

  // Extract the search term
  const term = extractSmartFilterTerm(raw);

  // If we have a search term, apply to fields
  if (term && term.length >= 2) {
    const fields = [];
    if (targets.subject) fields.push("email_subject");
    if (targets.body) fields.push("body_text_clean");
    if (targets.from) fields.push("email_from");
    if (targets.to) fields.push("email_to");
    if (targets.cc) fields.push("email_cc");

    // Default to subject + body if no specific fields mentioned
    if (!fields.length) {
      fields.push("email_subject", "body_text_clean");
    }

    const type = isNegated ? "notContains" : "contains";
    fields.forEach((field) => {
      filterModel[field] = { filterType: "text", type, filter: term };
    });
  }

  // If no filters could be extracted, provide helpful error
  if (!Object.keys(filterModel).length) {
    return {
      error: "Couldn't understand that query. Try:\n• 'Smith' in subject\n• from John Doe\n• emails last 7 days\n• with attachments\n• exclude 'newsletter'"
    };
  }

  return { filterModel };
}

window.applySmartFilter = function () {
  if (!gridApi || !gridApi.getFilterModel || !gridApi.setFilterModel) {
    toastError("Grid not ready yet.");
    return;
  }

  const input = document.getElementById("smartFilterInput");
  const raw = input ? input.value.trim() : "";
  const parsed = parseSmartFilter(raw);
  if (parsed.error) {
    toastError(parsed.error);
    return;
  }

  const model = gridApi.getFilterModel() || {};
  smartFilterFields.forEach((field) => {
    delete model[field];
  });
  smartFilterFields = new Set(Object.keys(parsed.filterModel));
  Object.assign(model, parsed.filterModel);

  gridApi.setFilterModel(model);
  smartFilterLastText = raw;
  gridApi.refreshServerSide({ purge: true });
  toastSuccess("Smart filter applied.");
};

window.clearSmartFilter = function () {
  if (!gridApi || !gridApi.getFilterModel || !gridApi.setFilterModel) {
    return;
  }
  const model = gridApi.getFilterModel() || {};
  smartFilterFields.forEach((field) => {
    delete model[field];
  });
  smartFilterFields = new Set();
  smartFilterLastText = "";

  const input = document.getElementById("smartFilterInput");
  if (input) input.value = "";

  gridApi.setFilterModel(model);
  gridApi.refreshServerSide({ purge: true });
  toastInfo("Smart filter cleared.");
};

window.setViewMode = function (mode) {
  currentViewMode = mode || "all";
  // For now, only the "all" view is implemented.
  const buttons = document.querySelectorAll(".view-toggle-group .btn");
  buttons.forEach((b) => b.classList.toggle("active", b.dataset.view === currentViewMode));
  if (currentViewMode !== "all") {
    if (window.VericaseUI) {
      VericaseUI.Toast.info("That view mode isn’t wired up yet.");
    }
  }
  if (gridApi) gridApi.refreshServerSide({ purge: true });
};

window.toggleFilterDropdown = function () {
  const menu = document.getElementById("filterDropdownMenu");
  const wrapper = document.getElementById("filterDropdown");
  if (menu) menu.classList.toggle("show");
  if (wrapper) wrapper.classList.toggle("open");
};

window.toggleMoreActionsDropdown = function () {
  const menu = document.getElementById("moreActionsMenu");
  const wrapper = document.getElementById("moreActionsDropdown");
  if (menu) {
    updateViewsDropdown();
    menu.classList.toggle("show");
  }
  if (wrapper) wrapper.classList.toggle("open");
};

window.closeAllDropdowns = function () {
  const menus = document.querySelectorAll(".dropdown-menu");
  menus.forEach((m) => m.classList.remove("show"));
  const wrappers = document.querySelectorAll(".toolbar-dropdown");
  wrappers.forEach((w) => w.classList.remove("open"));
};

function toastInfo(msg) {
  if (window.VericaseUI?.Toast) return window.VericaseUI.Toast.info(msg);
  console.log(msg);
}
function toastSuccess(msg) {
  if (window.VericaseUI?.Toast) return window.VericaseUI.Toast.success(msg);
  console.log(msg);
}
function toastError(msg) {
  if (window.VericaseUI?.Toast) return window.VericaseUI.Toast.error(msg);
  console.error(msg);
}

async function confirmDialog(message, options) {
  if (window.VericaseUI?.Confirm?.show) {
    return await window.VericaseUI.Confirm.show(message, options || {});
  }
  return window.confirm(message);
}

function showModal({ title, bodyHtml, footerHtml, widthPx }) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop visible";
  backdrop.style.zIndex = "9999";

  const modal = document.createElement("div");
  modal.className = "modal";
  if (widthPx) modal.style.maxWidth = `${widthPx}px`;

  modal.innerHTML = `
    <div class="modal-header">
      <div class="modal-title">${escapeHtml(title || "")}</div>
      <button class="btn btn-ghost" data-close="1" title="Close">✕</button>
    </div>
    <div class="modal-body">${bodyHtml || ""}</div>
    ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ""}
  `;

  backdrop.appendChild(modal);
  document.body.appendChild(backdrop);

  const close = () => {
    backdrop.classList.remove("visible");
    setTimeout(() => backdrop.remove(), 200);
    document.removeEventListener("keydown", onKey);
  };

  const onKey = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  };
  document.addEventListener("keydown", onKey);

  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) close();
  });
  modal.querySelectorAll("[data-close='1']").forEach((b) => b.addEventListener("click", close));

  return { backdrop, modal, close };
}

async function ensureStakeholdersLoaded() {
  if (Array.isArray(stakeholdersCache)) return stakeholdersCache;
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (caseId) params.set("case_id", caseId);
  const url = `${API_BASE}/api/correspondence/stakeholders${params.toString() ? `?${params}` : ""}`;
  const resp = await fetch(url, { headers: { ...getAuthHeaders() } });
  if (!resp.ok) throw new Error(`Failed to load stakeholders (${resp.status})`);
  const data = await resp.json();
  stakeholdersCache = Array.isArray(data?.items) ? data.items : [];
  return stakeholdersCache;
}

async function ensureDomainsLoaded() {
  if (Array.isArray(domainsCache)) return domainsCache;
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (caseId) params.set("case_id", caseId);
  const url = `${API_BASE}/api/correspondence/domains${params.toString() ? `?${params}` : ""}`;
  const resp = await fetch(url, { headers: { ...getAuthHeaders() } });
  if (!resp.ok) throw new Error(`Failed to load domains (${resp.status})`);
  const data = await resp.json();
  domainsCache = Array.isArray(data?.domains) ? data.domains : [];
  return domainsCache;
}

async function ensureKeywordsLoaded() {
  if (Array.isArray(keywordsCache)) return keywordsCache;
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (caseId) params.set("case_id", caseId);
  const url = `${API_BASE}/api/correspondence/keywords${params.toString() ? `?${params}` : ""}`;
  const resp = await fetch(url, { headers: { ...getAuthHeaders() } });
  if (!resp.ok) throw new Error(`Failed to load keywords (${resp.status})`);
  const data = await resp.json();
  keywordsCache = Array.isArray(data?.items) ? data.items : [];
  rebuildKeywordIndex();
  return keywordsCache;
}

async function ensureEmailAddressesLoaded() {
  if (emailAddressesCache) return emailAddressesCache;
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (caseId) params.set("case_id", caseId);
  const url = `${API_BASE}/api/correspondence/email-addresses${params.toString() ? `?${params}` : ""}`;
  try {
    const resp = await fetch(url, { headers: { ...getAuthHeaders() } });
    if (!resp.ok) {
      console.warn(`Failed to load email addresses (${resp.status}), using empty list`);
      emailAddressesCache = { from: [], to: [], cc: [] };
      return emailAddressesCache;
    }
    const data = await resp.json();
    emailAddressesCache = {
      from: Array.isArray(data?.from) ? data.from : [],
      to: Array.isArray(data?.to) ? data.to : [],
      cc: Array.isArray(data?.cc) ? data.cc : []
    };
  } catch (e) {
    console.warn("Could not load email addresses for filters:", e);
    emailAddressesCache = { from: [], to: [], cc: [] };
  }
  return emailAddressesCache;
}

function getSelectedEmailRows() {
  const rows = gridApi?.getSelectedRows ? gridApi.getSelectedRows() : [];
  return Array.isArray(rows) ? rows : [];
}

function getSelectedEmailIds() {
  return getSelectedEmailRows()
    .map((r) => r?.id)
    .filter((id) => looksLikeUuid(id));
}

function setStakeholderFilter(id) {
  selectedStakeholderId = id || null;
  gridApi?.refreshServerSide?.({ purge: true });
}

function setDomainFilter(domain) {
  selectedDomain = domain || null;
  gridApi?.refreshServerSide?.({ purge: true });
}

function setKeywordFilter(id) {
  selectedKeywordId = id || null;
  gridApi?.refreshServerSide?.({ purge: true });
}

window.showStakeholderFilter = async function () {
  try {
    const domains = await ensureDomainsLoaded();
    const current = selectedDomain;

    const { modal, close } = showModal({
      title: "Filter by domain",
      widthPx: 720,
      bodyHtml: `
        <input id="vcDomainSearch" class="input" style="width:100%; margin-bottom: 12px;" placeholder="Search domains..." />
        <div id="vcDomainList" style="max-height: 55vh; overflow:auto; border: 1px solid var(--border-default); border-radius: var(--radius-lg);"></div>
      `,
      footerHtml: `
        <button class="btn btn-ghost" id="vcDomainClear">Clear</button>
        <button class="btn btn-vericase" id="vcDomainClose">Done</button>
      `,
    });

    const listEl = modal.querySelector("#vcDomainList");
    const searchEl = modal.querySelector("#vcDomainSearch");

    const render = () => {
      const q = (searchEl.value || "").toLowerCase().trim();
      const filtered = !q
        ? domains
        : domains.filter((d) => d.toLowerCase().includes(q));

      listEl.innerHTML = filtered
        .slice(0, 500)
        .map((d) => {
          const active = d === current;
          return `
            <button class="dropdown-item" data-domain="${escapeHtml(d)}" style="display:block; width:100%; text-align:left; border-bottom: 1px solid var(--border-default); padding: 12px 16px; ${active ? "background: rgba(59,130,246,0.08);" : ""}">
              <div style="font-weight:600;">${escapeHtml(d)}</div>
            </button>
          `;
        })
        .join("");

      if (filtered.length === 0) {
        listEl.innerHTML = `<div style="padding: 24px; text-align: center; color: var(--text-secondary);">No domains found</div>`;
      }

      listEl.querySelectorAll("button[data-domain]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const domain = btn.getAttribute("data-domain");
          setDomainFilter(domain);
          toastSuccess(`Filtering by ${domain}`);
          close();
        });
      });
    };

    render();
    searchEl.addEventListener("input", render);
    modal.querySelector("#vcDomainClear").addEventListener("click", () => {
      setDomainFilter(null);
      toastSuccess("Domain filter cleared");
      close();
    });
    modal.querySelector("#vcDomainClose").addEventListener("click", close);
    setTimeout(() => searchEl.focus(), 0);
  } catch (e) {
    console.error(e);
    toastError("Could not load domains");
  }
};

window.showKeywordFilter = async function () {
  try {
    const items = await ensureKeywordsLoaded();
    const current = selectedKeywordId;

    const { modal, close } = showModal({
      title: "Filter by keyword",
      widthPx: 720,
      bodyHtml: `
        <input id="vcKeywordSearch" class="input" style="width:100%; margin-bottom: 12px;" placeholder="Search keywords..." />
        <div id="vcKeywordList" style="max-height: 55vh; overflow:auto; border: 1px solid var(--border-default); border-radius: var(--radius-lg);"></div>
      `,
      footerHtml: `
        <button class="btn btn-ghost" id="vcKeywordClear">Clear</button>
        <button class="btn btn-vericase" id="vcKeywordClose">Done</button>
      `,
    });

    const listEl = modal.querySelector("#vcKeywordList");
    const searchEl = modal.querySelector("#vcKeywordSearch");

    const render = () => {
      const q = (searchEl.value || "").toLowerCase().trim();
      const filtered = !q
        ? items
        : items.filter((k) => {
            const hay = `${k.name || ""} ${k.definition || ""} ${k.variations || ""}`.toLowerCase();
            return hay.includes(q);
          });

      listEl.innerHTML = filtered
        .slice(0, 1000)
        .map((k) => {
          const active = String(k.id) === String(current);
          const title = escapeHtml(k.name || "(Unnamed)");
          const defn = k.definition ? escapeHtml(k.definition) : "";
          const meta = k.variations ? escapeHtml(k.variations) : "";
          return `
            <button class="dropdown-item" data-id="${escapeHtml(k.id)}" style="display:block; width:100%; text-align:left; border-bottom: 1px solid var(--border-default); ${active ? "background: rgba(59,130,246,0.08);" : ""}">
              <div style="font-weight:600;">${title}</div>
              ${defn ? `<div style="font-size: 0.8125rem; color: var(--text-secondary);">${defn}</div>` : ""}
              ${meta ? `<div style="font-size: 0.8125rem; color: var(--text-secondary);">${meta}</div>` : ""}
            </button>
          `;
        })
        .join("");

      listEl.querySelectorAll("button[data-id]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.getAttribute("data-id");
          setKeywordFilter(id);
          toastSuccess("Keyword filter applied");
          close();
        });
      });
    };

    render();
    searchEl.addEventListener("input", render);
    modal.querySelector("#vcKeywordClear").addEventListener("click", () => {
      setKeywordFilter(null);
      toastSuccess("Keyword filter cleared");
      close();
    });
    modal.querySelector("#vcKeywordClose").addEventListener("click", close);
    setTimeout(() => searchEl.focus(), 0);
  } catch (e) {
    console.error(e);
    toastError("Could not load keywords");
  }
};

function loadGridViews() {
  try {
    const raw = localStorage.getItem(GRID_VIEW_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    console.warn("Failed to load grid views:", e);
    return [];
  }
}

function saveGridViews(views) {
  try {
    localStorage.setItem(GRID_VIEW_STORAGE_KEY, JSON.stringify(views));
  } catch (e) {
    console.warn("Failed to persist grid views:", e);
  }
}

function sanitizeColumnState(state) {
  if (!Array.isArray(state)) return [];
  return state.map((col) => {
    const colId = col.colId || col.columnId || col.field || "";
    return {
      ...col,
      pinned: null,
      hide: DEFAULT_HIDDEN_COLUMNS.has(colId) ? true : col.hide,
    };
  });
}

function getCurrentGridState() {
  return {
    columnState: gridApi?.getColumnState ? sanitizeColumnState(gridApi.getColumnState()) : [],
    sortModel: gridApi?.getColumnState ? gridApi.getColumnState().filter(c => c.sort).map(c => ({ colId: c.colId, sort: c.sort, sortIndex: c.sortIndex })) : null,
    filterModel: gridApi?.getFilterModel ? gridApi.getFilterModel() : null,
  };
}

function setActiveGridView(name) {
  if (name) {
    localStorage.setItem(GRID_VIEW_ACTIVE_KEY, name);
  } else {
    localStorage.removeItem(GRID_VIEW_ACTIVE_KEY);
  }
}

function applyGridView(view, options) {
  if (!view || !gridApi) return;
  const opts = { toast: true, refresh: true, ...(options || {}) };
  const state = view.state || {};

  if (Array.isArray(state.columnState) && state.columnState.length) {
    const sanitized = sanitizeColumnState(state.columnState);
    gridApi.applyColumnState({ state: sanitized, applyOrder: true });
  }
  // Apply sort via column state (setSortModel is deprecated in v31+)
  if (Array.isArray(state.sortModel) && state.sortModel.length) {
    gridApi.applyColumnState({
      state: state.sortModel.map(s => ({ colId: s.colId, sort: s.sort, sortIndex: s.sortIndex })),
      defaultState: { sort: null },
    });
  }
  if (gridApi.setFilterModel) {
    gridApi.setFilterModel(state.filterModel || null);
  }

  setActiveGridView(view.name);
  if (opts.refresh) gridApi.refreshServerSide({ purge: true });
  if (opts.toast && window.VericaseUI?.Toast) {
    window.VericaseUI.Toast.success(`View applied: ${view.name}`);
  }
  updateViewsDropdown();
}

function updateViewsDropdown() {
  const listEl = document.getElementById("viewsDropdownList");
  if (!listEl) return;
  const views = loadGridViews();
  const active = localStorage.getItem(GRID_VIEW_ACTIVE_KEY) || "";
  if (!views.length) {
    listEl.innerHTML = `<div class="dropdown-item" style="opacity:0.6;">No saved views</div>`;
    return;
  }
  listEl.innerHTML = views
    .map((v) => {
      const label = escapeHtml(v.name || "Untitled");
      const isActive = active && String(active).toLowerCase() === String(v.name).toLowerCase();
      return `
        <button class="dropdown-item" data-view="${escapeHtml(v.name)}" style="${isActive ? "background: rgba(59,130,246,0.08);" : ""}">
          <i class="fas fa-layer-group" style="margin-right:8px;"></i> ${label}
        </button>
      `;
    })
    .join("");

  listEl.querySelectorAll("button[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const name = btn.getAttribute("data-view");
      const view = loadGridViews().find((v) => String(v.name) === String(name));
      if (view) applyGridView(view, { toast: true });
      closeAllDropdowns();
    });
  });
}

window.openManageViews = function () {
  const views = loadGridViews();
  const { modal, close } = showModal({
    title: "Manage views",
    widthPx: 640,
    bodyHtml: `
      <div id="vcViewsList" style="display:flex; flex-direction:column; gap: 0.5rem;"></div>
    `,
    footerHtml: `<button class="btn btn-vericase" id="vcViewsDone">Done</button>`,
  });

  const listEl = modal.querySelector("#vcViewsList");
  const render = () => {
    const items = loadGridViews();
    const active = localStorage.getItem(GRID_VIEW_ACTIVE_KEY) || "";
    if (!items.length) {
      listEl.innerHTML = `<div style="color: var(--text-secondary);">No saved views yet.</div>`;
      return;
    }
    listEl.innerHTML = items
      .map((v) => {
        const label = escapeHtml(v.name || "Untitled");
        const isActive = active && String(active).toLowerCase() === String(v.name).toLowerCase();
        return `
          <div style="display:flex; align-items:center; justify-content:space-between; gap: 12px; padding: 10px 12px; border: 1px solid var(--border-default); border-radius: var(--radius-lg); ${isActive ? "background: rgba(59,130,246,0.08);" : ""}">
            <div>
              <div style="font-weight:600;">${label}</div>
              <div style="font-size:0.8rem; color: var(--text-secondary);">Saved layout</div>
            </div>
            <div style="display:flex; gap: 8px;">
              <button class="btn btn-ghost" data-action="apply" data-name="${escapeHtml(v.name)}">Apply</button>
              <button class="btn btn-ghost" data-action="rename" data-name="${escapeHtml(v.name)}">Rename</button>
              <button class="btn btn-ghost" data-action="delete" data-name="${escapeHtml(v.name)}">Delete</button>
            </div>
          </div>
        `;
      })
      .join("");

    listEl.querySelectorAll("button[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.getAttribute("data-action");
        const name = btn.getAttribute("data-name");
        if (!name) return;
        if (action === "apply") {
          const view = loadGridViews().find((v) => String(v.name) === String(name));
          if (view) applyGridView(view, { toast: true });
          close();
          return;
        }
        if (action === "rename") {
          const next = window.prompt("Rename view", name || "");
          if (!next || !next.trim()) return;
          const trimmed = next.trim();
          const items = loadGridViews();
          const idx = items.findIndex((v) => String(v.name) === String(name));
          if (idx >= 0) {
            items[idx].name = trimmed;
            saveGridViews(items);
            if (String(active).toLowerCase() === String(name).toLowerCase()) {
              setActiveGridView(trimmed);
            }
            updateViewsDropdown();
            render();
          }
          return;
        }
        if (action === "delete") {
          const ok = window.confirm(`Delete view "${name}"?`);
          if (!ok) return;
          const items = loadGridViews().filter((v) => String(v.name) !== String(name));
          saveGridViews(items);
          if (String(active).toLowerCase() === String(name).toLowerCase()) {
            setActiveGridView(null);
          }
          updateViewsDropdown();
          render();
        }
      });
    });
  };

  render();
  modal.querySelector("#vcViewsDone").addEventListener("click", close);
};

window.saveGridConfiguration = function () {
  if (!gridApi) return;
  try {
    const name = window.prompt("Name this view", "");
    if (!name || !name.trim()) return;
    const trimmed = name.trim();
    const views = loadGridViews();
    const state = getCurrentGridState();
    const existingIndex = views.findIndex(
      (v) => String(v.name).toLowerCase() === trimmed.toLowerCase(),
    );
    const nextView = {
      name: trimmed,
      state,
      updatedAt: new Date().toISOString(),
    };
    if (existingIndex >= 0) {
      views[existingIndex] = nextView;
    } else {
      views.push(nextView);
    }
    saveGridViews(views);
    setActiveGridView(trimmed);
    updateViewsDropdown();
    if (window.VericaseUI?.Toast) window.VericaseUI.Toast.success("View saved");
  } catch (e) {
    console.warn("Failed to save grid configuration:", e);
  }
};

window.resetGridConfiguration = function () {
  try {
    setActiveGridView(null);
    localStorage.removeItem("vc_correspondence_grid_state");
    if (gridApi?.resetColumnState) gridApi.resetColumnState();
    if (gridApi?.getColumns) {
      const showState = gridApi.getColumns().map((col) => {
        const colId = col.getColId();
        return {
          colId,
          hide: DEFAULT_HIDDEN_COLUMNS.has(colId),
          pinned: null,
        };
      });
      gridApi.applyColumnState({ state: showState, applyOrder: false });
    }
    // Use applyColumnState for sorting (setSortModel is deprecated)
    gridApi?.applyColumnState?.({
      state: [{ colId: "email_date", sort: "desc" }],  // Newest first
      defaultState: { sort: null },
    });
    gridApi?.refreshServerSide?.({ purge: true });
    updateViewsDropdown();
    if (window.VericaseUI) VericaseUI.Toast.success("Layout reset");
  } catch (e) {
    console.warn("Failed to reset grid configuration:", e);
  }
};

// -----------------------------
// Global UI actions (header / toolbar / panels)
// -----------------------------

window.toggleCommandPalette = function () {
  openCommandPalette();
};

window.refreshData = function () {
  try {
    if (gridApi) {
      gridApi.deselectAll?.();
      gridApi.refreshServerSide({ purge: true });
      if (window.VericaseUI?.Toast) window.VericaseUI.Toast.success("Refreshed");
    }
  } catch (e) {
    console.warn("Refresh failed:", e);
  }
};

window.openVeriCaseAnalysis = function () {
  const params = new URLSearchParams();
  if (projectId) params.set("projectId", projectId);
  if (!projectId && caseId) params.set("caseId", caseId);
  const url = params.toString()
    ? `vericase-analysis.html?${params.toString()}`
    : "vericase-analysis.html";
  window.location.href = url;
};

window.exportToExcel = function () {
  try {
    if (gridApi?.exportDataAsExcel) {
      gridApi.exportDataAsExcel({ fileName: "correspondence.xlsx" });
      return;
    }
    if (window.VericaseUI?.Toast) {
      window.VericaseUI.Toast.info("Excel export is not available in this build.");
    }
  } catch (e) {
    console.warn("Excel export failed:", e);
    if (window.VericaseUI?.Toast) window.VericaseUI.Toast.error("Export failed");
  }
};

window.printEmails = function () {
  try {
    window.print();
  } catch {
    // ignore
  }
};

window.toggleAIChat = function () {
  const container = document.getElementById("aiChatContainer");
  const floatingBtn = document.getElementById("aiFloatingToggleBtn");
  const closeBtn = document.getElementById("aiChatToggleBtn");
  if (!container) return;

  const isVisible = container.classList.toggle("ai-visible");
  
  // Toggle floating button visibility
  if (floatingBtn) {
    floatingBtn.classList.toggle("hidden", isVisible);
  }
  
  // Update close button aria attribute
  if (closeBtn) {
    closeBtn.setAttribute("aria-expanded", String(isVisible));
  }
};

function setContextPanelCollapsed(collapsed) {
  const panel = document.getElementById("contextPanel");
  const icon = document.getElementById("contextToggleIcon");
  if (!panel) return;
  panel.classList.toggle("collapsed", Boolean(collapsed));
  if (icon) icon.className = collapsed ? "fas fa-chevron-left" : "fas fa-chevron-right";

  // After transition completes, resize the grid to fill available space
  setTimeout(() => {
    if (gridApi) {
      gridApi.sizeColumnsToFit();
    }
  }, 320); // Slightly longer than the 0.3s CSS transition
}

window.toggleContextPanel = function () {
  const panel = document.getElementById("contextPanel");
  if (!panel) return;
  setContextPanelCollapsed(!panel.classList.contains("collapsed"));
};

window.toggleContextSection = function (sectionId) {
  const body = document.getElementById(`${sectionId}Body`);
  if (!body) return;
  body.classList.toggle("collapsed");
};

window.onLinkTypeChange = function () {
  void loadLinkTargetsForSelectedType();
};

window.openLinkModalForSelected = function () {
  const ids = getSelectedEmailIds();
  if (!ids.length) {
    toastInfo("Select one or more emails first");
    return;
  }
  openLinkModal(ids);
};

window.openLinkModalForEmail = function (emailId) {
  if (!looksLikeUuid(emailId)) {
    toastError("Invalid email id");
    return;
  }
  openLinkModal([emailId]);
};

async function ensureLinkTargetsLoaded(type) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (caseId) params.set("case_id", caseId);

  if (type === "matter") {
    if (!Array.isArray(linkTargetsCache.matter)) {
      const resp = await fetch(`${API_BASE}/api/claims/matters?${params}`, {
        headers: { ...getAuthHeaders() },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      linkTargetsCache.matter = Array.isArray(data?.items) ? data.items : [];
    }
    return linkTargetsCache.matter;
  }

  if (type === "claim") {
    if (!Array.isArray(linkTargetsCache.claim)) {
      const resp = await fetch(`${API_BASE}/api/claims/heads-of-claim?${params}`, {
        headers: { ...getAuthHeaders() },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      linkTargetsCache.claim = Array.isArray(data?.items) ? data.items : [];
    }
    return linkTargetsCache.claim;
  }

  return [];
}

async function linkEmailsToTarget(ids, type, targetId) {
  const bodyBase = {
    item_type: "correspondence",
    link_type: "supporting",
  };

  const payloads = ids
    .map((id) => {
      if (type === "matter") {
        return { ...bodyBase, item_id: id, contentious_matter_id: targetId };
      }
      if (type === "claim") {
        return { ...bodyBase, item_id: id, head_of_claim_id: targetId };
      }
      return null;
    })
    .filter(Boolean);

  const results = await Promise.all(
    payloads.map(async (p) => {
      const resp = await fetch(`${API_BASE}/api/claims/links`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
        },
        body: JSON.stringify(p),
      });

      if (resp.status === 409) return { ok: true, duplicate: true };
      if (!resp.ok) {
        const t = await resp.text();
        return { ok: false, error: t || `HTTP ${resp.status}` };
      }
      return { ok: true };
    }),
  );

  const okCount = results.filter((r) => r.ok).length;
  const dupCount = results.filter((r) => r.duplicate).length;
  const failCount = results.filter((r) => !r.ok).length;
  if (failCount) {
    toastError(`Linked ${okCount - dupCount}/${ids.length}. ${failCount} failed.`);
  } else if (dupCount) {
    toastSuccess(`Linked ${ids.length - dupCount}/${ids.length} (skipped ${dupCount} existing link(s))`);
  } else {
    toastSuccess(`Linked ${ids.length} email(s)`);
  }

  gridApi?.refreshServerSide?.({ purge: false });
  if (ids.length === 1) {
    void renderEmailLinks(ids[0]);
  }
}

function openLinkModal(emailIds) {
  if (!Array.isArray(emailIds) || !emailIds.length) return;

  let selectedType = "matter";
  let targets = [];
  let selectedTargetId = "";
  let selectedTargetName = "";

  const { modal, close } = showModal({
    title: `Link ${emailIds.length} email${emailIds.length === 1 ? "" : "s"}`,
    widthPx: 860,
    bodyHtml: `
      <div style="display:flex; flex-direction:column; gap: 0.75rem;">
        <div style="font-size:0.875rem; color: var(--text-secondary);">
          Choose a <strong>Contentious Matter</strong> or <strong>Head of Claim</strong>, then link the selected email${emailIds.length === 1 ? "" : "s"}.
        </div>
        <div style="display:flex; gap: 8px; flex-wrap: wrap;">
          <button class="btn btn-ghost active" type="button" id="vcLinkTypeMatter" title="Contentious Matter">
            <i class="fas fa-briefcase"></i> Matter
          </button>
          <button class="btn btn-ghost" type="button" id="vcLinkTypeClaim" title="Head of Claim">
            <i class="fas fa-gavel"></i> Head of Claim
          </button>
          <a class="btn btn-ghost" href="contentious-matters.html" style="margin-left:auto; text-decoration:none;" title="Manage matters and claims">
            <i class="fas fa-list"></i> Manage
          </a>
        </div>
        <input id="vcLinkSearch" class="input" style="width:100%;" placeholder="Search..." />
        <div id="vcLinkTargets" style="max-height: 52vh; overflow:auto; border: 1px solid var(--border-default); border-radius: var(--radius-lg);">
          <div style="padding: 12px; color: var(--text-muted);">Loading…</div>
        </div>
        <div id="vcLinkSelectedSummary" style="font-size:0.8125rem; color: var(--text-secondary);">
          No target selected
        </div>
      </div>
    `,
    footerHtml: `
      <button class="btn btn-ghost" id="vcLinkCancel">Cancel</button>
      <button class="btn btn-vericase" id="vcLinkConfirm" disabled><i class="fas fa-link"></i> Link</button>
    `,
  });

  const btnMatter = modal.querySelector("#vcLinkTypeMatter");
  const btnClaim = modal.querySelector("#vcLinkTypeClaim");
  const searchEl = modal.querySelector("#vcLinkSearch");
  const listEl = modal.querySelector("#vcLinkTargets");
  const summaryEl = modal.querySelector("#vcLinkSelectedSummary");
  const confirmBtn = modal.querySelector("#vcLinkConfirm");
  const cancelBtn = modal.querySelector("#vcLinkCancel");

  const setTypeButtons = () => {
    btnMatter?.classList.toggle("active", selectedType === "matter");
    btnClaim?.classList.toggle("active", selectedType === "claim");
  };

  const setSelected = (id, name) => {
    selectedTargetId = id || "";
    selectedTargetName = name || "";
    if (summaryEl) {
      summaryEl.textContent = selectedTargetId
        ? `Selected: ${selectedTargetName || selectedTargetId}`
        : "No target selected";
    }
    if (confirmBtn) confirmBtn.disabled = !selectedTargetId;
  };

  const renderTargets = () => {
    const q = (searchEl?.value || "").toLowerCase().trim();
    const items = !q
      ? targets
      : targets.filter((t) => `${t.name || ""} ${t.description || ""}`.toLowerCase().includes(q));

    listEl.innerHTML = items
      .slice(0, 500)
      .map((t) => {
        const id = escapeHtml(t.id);
        const name = escapeHtml(t.name || t.id);
        const desc = t.description ? escapeHtml(t.description) : "";
        const active = String(t.id) === String(selectedTargetId);
        return `
          <button class="dropdown-item" type="button" data-id="${id}" data-name="${name}" style="display:block; width:100%; text-align:left; border-bottom: 1px solid var(--border-default); ${active ? "background: rgba(59,130,246,0.08);" : ""}">
            <div style="font-weight:600;">${name}</div>
            ${desc ? `<div style="font-size: 0.8125rem; color: var(--text-secondary);">${desc}</div>` : ""}
          </button>
        `;
      })
      .join("");

    listEl.querySelectorAll("button[data-id]").forEach((b) => {
      b.addEventListener("click", () => {
        const id = b.getAttribute("data-id") || "";
        const name = b.getAttribute("data-name") || "";
        setSelected(id, name);
        renderTargets();
      });
    });

    if (!items.length) {
      listEl.innerHTML = `<div style="padding: 12px; color: var(--text-muted);">No matches</div>`;
    }
  };

  const loadTargets = async () => {
    setTypeButtons();
    setSelected("", "");
    listEl.innerHTML = `<div style="padding: 12px; color: var(--text-muted);">Loading…</div>`;
    try {
      targets = await ensureLinkTargetsLoaded(selectedType);
      renderTargets();
    } catch (e) {
      console.error(e);
      listEl.innerHTML = `<div style="padding: 12px; color: var(--text-muted);">Failed to load targets</div>`;
      toastError("Failed to load link targets");
    }
  };

  btnMatter?.addEventListener("click", () => {
    selectedType = "matter";
    void loadTargets();
  });
  btnClaim?.addEventListener("click", () => {
    selectedType = "claim";
    void loadTargets();
  });
  searchEl?.addEventListener("input", renderTargets);

  cancelBtn?.addEventListener("click", close);
  confirmBtn?.addEventListener("click", async () => {
    if (!selectedTargetId) return;
    const typeLabel = selectedType === "matter" ? "Contentious Matter" : "Head of Claim";
    const ok = await confirmDialog(
      `Link ${emailIds.length} email(s) to "${selectedTargetName || selectedTargetId}" (${typeLabel})?`,
      { title: "Link emails", confirmText: "Link", cancelText: "Cancel" },
    );
    if (!ok) return;
    try {
      await linkEmailsToTarget(emailIds, selectedType, selectedTargetId);
      close();
    } catch (e) {
      console.error(e);
      toastError("Linking failed");
    }
  });

  void loadTargets();
  setTimeout(() => searchEl?.focus(), 0);
}

window.linkSelectedEmails = async function () {
  const ids = getSelectedEmailIds();
  if (!ids.length) {
    toastInfo("Select one or more emails first");
    return;
  }

  const linkTypeEl = document.getElementById("linkTypeSelect");
  const targetEl = document.getElementById("linkTargetSelect");
  const type = linkTypeEl ? linkTypeEl.value : "";
  const targetId = targetEl ? targetEl.value : "";

  if (!type) {
    toastInfo("Choose a link type first");
    return;
  }
  if (!targetId) {
    toastInfo("Choose a link target first");
    return;
  }

  const ok = await confirmDialog(`Link ${ids.length} email(s) to the selected ${type}?`, {
    title: "Link emails",
    confirmText: "Link",
    cancelText: "Cancel",
  });
  if (!ok) return;

  try {
    await linkEmailsToTarget(ids, type, targetId);
  } catch (e) {
    console.error(e);
    toastError("Linking failed");
  }
};

window.markAsExcluded = async function () {
  const ids = getSelectedEmailIds();
  if (!ids.length) {
    toastInfo("Select one or more emails first");
    return;
  }

  const ok = await confirmDialog(`Mark ${ids.length} email(s) as excluded?`, {
    title: "Exclude emails",
    confirmText: "Exclude",
    cancelText: "Cancel",
    type: "danger",
  });
  if (!ok) return;

  const reason = window.prompt("Reason (optional)", "");

  try {
    const resp = await fetch(`${API_BASE}/api/correspondence/emails/bulk/exclude`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        email_ids: ids,
        case_id: caseId || null,
        project_id: projectId || null,
        excluded: true,
        reason: (reason || "").trim() || null,
      }),
    });

    if (!resp.ok) {
      const t = await resp.text();
      throw new Error(t || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    toastSuccess(`Excluded ${data?.updated ?? ids.length} email(s)`);
    gridApi?.refreshServerSide?.({ purge: true });
  } catch (e) {
    console.error(e);
    toastError("Failed to exclude emails");
  }
};

// Toggle body cell expansion
window.toggleBodyCell = async function (rowId) {
  if (!gridApi) return;
  const rowNode = gridApi.getRowNode(rowId);
  if (!rowNode || !rowNode.data) return;

  // Toggle expansion state
  const willExpand = !rowNode.data._bodyExpanded;
  rowNode.data._bodyExpanded = willExpand;

  // Use fixed heights to avoid expensive DOM measurement from autoHeight.
  rowNode.setRowHeight(willExpand ? ROW_HEIGHT_EXPANDED : ROW_HEIGHT_COLLAPSED);

  // Force cell refresh and row height recalculation
  gridApi.refreshCells({
    rowNodes: [rowNode],
    force: true,
    suppressFlash: true
  });
  gridApi.onRowHeightChanged();

  // Lazy-load full body on expand (keeps initial grid payload small + fast).
  if (willExpand && rowNode.data?.id && !rowNode.data._bodyFullLoaded && !rowNode.data._bodyLoading) {
    rowNode.data._bodyLoading = true;
    rowNode.data._bodyLoadError = null;
    gridApi.refreshCells({ rowNodes: [rowNode], force: true, suppressFlash: true });
    try {
      const resp = await fetch(`${API_BASE}/api/correspondence/emails/${rowNode.data.id}`, { headers: getAuthHeaders() });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const detail = await resp.json();
      const full = detail?.body_text_clean || detail?.body_text || "";
      if (full) {
        // Store in email_body so existing render helpers pick it up (and keep normalized rendering).
        rowNode.data.email_body = normalizeBodyWhitespace(String(full));
      }
      rowNode.data._bodyFullLoaded = true;
    } catch (e) {
      rowNode.data._bodyLoadError = e?.message || String(e);
    } finally {
      rowNode.data._bodyLoading = false;
      gridApi.refreshCells({ rowNodes: [rowNode], force: true, suppressFlash: true });
    }
  }
};

// Expand all email body cells in the grid
window.expandAllBodies = function () {
  if (!gridApi) return;
  const rowNodes = [];
  gridApi.forEachNode((node) => {
    if (node.data && !node.data._bodyExpanded) {
      node.data._bodyExpanded = true;
      node.setRowHeight(ROW_HEIGHT_EXPANDED);
      rowNodes.push(node);
    }
  });
  if (rowNodes.length) {
    gridApi.refreshCells({ rowNodes, force: true, suppressFlash: true });
    gridApi.onRowHeightChanged();
  }
};

// Collapse all email body cells in the grid
window.collapseAllBodies = function () {
  if (!gridApi) return;
  const rowNodes = [];
  gridApi.forEachNode((node) => {
    if (node.data && node.data._bodyExpanded) {
      node.data._bodyExpanded = false;
      node.setRowHeight(ROW_HEIGHT_COLLAPSED);
      rowNodes.push(node);
    }
  });
  if (rowNodes.length) {
    gridApi.refreshCells({ rowNodes, force: true, suppressFlash: true });
    gridApi.onRowHeightChanged();
  }
};

// Context panel placeholders to prevent dead controls
window.showSimilarEmails = function () {
  void showSimilarEmailsModal();
};
window.suggestExclusion = function () {
  const selected = getSelectedEmailRows();
  if (!selected.length) {
    toastInfo("Select emails first");
    return;
  }
  const subjects = selected.slice(0, 10).map((r) => r.email_subject || r.subject).filter(Boolean);
  const q = `Suggest whether these emails should be excluded from correspondence review, and why.\n\nSubjects:\n- ${subjects.join("\n- ")}`;
  const aiInput = document.getElementById("aiQuery");
  if (aiInput) aiInput.value = q;
  // Ensure assistant panel visible
  const container = document.getElementById("aiChatContainer");
  if (container && !container.classList.contains("ai-visible")) {
    window.toggleAIChat?.();
  }
  window.aiQuickSearch?.();
};
window.analyzeSelection = function () {
  const selected = getSelectedEmailRows();
  if (!selected.length) {
    toastInfo("Select emails first");
    return;
  }
  const subjects = selected.slice(0, 12).map((r) => r.email_subject || r.subject).filter(Boolean);
  const q = `Analyze the selected emails for themes, timeline signals, and potential relevance to claims/matters.\n\nSubjects:\n- ${subjects.join("\n- ")}`;
  const aiInput = document.getElementById("aiQuery");
  if (aiInput) aiInput.value = q;
  const container = document.getElementById("aiChatContainer");
  if (container && !container.classList.contains("ai-visible")) {
    window.toggleAIChat?.();
  }
  window.aiQuickSearch?.();
};
window.bulkSetCategory = function () {
  void bulkSetCategoryAction();
};
window.bulkAddKeywords = function () {
  void bulkAddKeywordsAction();
};
window.bulkExportSelected = function () {
  void bulkExportSelectedAction();
};

async function showSimilarEmailsModal() {
  const ids = getSelectedEmailIds();
  if (!ids.length) {
    toastInfo("Select an email first");
    return;
  }
  const emailId = ids[0];

  try {
    const params = new URLSearchParams();
    params.set("size", "50");
    if (!hideExcludedEmails) params.set("include_hidden", "true");
    const resp = await fetch(`${API_BASE}/api/correspondence/emails/${emailId}/similar?${params}`, {
      headers: { ...getAuthHeaders() },
    });
    if (!resp.ok) {
      const t = await resp.text();
      throw new Error(t || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    const items = Array.isArray(data?.items) ? data.items : [];

    const { modal, close } = showModal({
      title: `Similar emails (${items.length})`,
      widthPx: 900,
      bodyHtml: `
        <div style="color: var(--text-secondary); margin-bottom: 10px;">Based on email content (OpenSearch MLT). Click an item to open details.</div>
        <div id="vcSimilarList" style="max-height: 65vh; overflow:auto; border: 1px solid var(--border-default); border-radius: var(--radius-lg);"></div>
      `,
      footerHtml: `<button class="btn btn-vericase" id="vcSimilarClose">Close</button>`,
    });

    const listEl = modal.querySelector("#vcSimilarList");
    listEl.innerHTML = items
      .map((it) => {
        const subj = escapeHtml(it.subject || "(No subject)");
        const from = escapeHtml(it.sender_name || it.sender_email || "-");
        const date = it.date_sent ? escapeHtml(new Date(it.date_sent).toLocaleString()) : "-";
        const score = Number(it.score || 0).toFixed(2);
        return `
          <button class="dropdown-item" data-id="${escapeHtml(it.id)}" style="display:block; width:100%; text-align:left; border-bottom: 1px solid var(--border-default);">
            <div style="display:flex; justify-content: space-between; gap: 8px;">
              <div style="font-weight:600;">${subj}</div>
              <div style="font-size:0.8125rem; color: var(--text-secondary);">score ${score}</div>
            </div>
            <div style="font-size:0.8125rem; color: var(--text-secondary);">${from}${from && date ? " • " : ""}${date}</div>
          </button>
        `;
      })
      .join("");

    listEl.querySelectorAll("button[data-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        try {
          const resp2 = await fetch(`${API_BASE}/api/correspondence/emails/${id}`, { headers: { ...getAuthHeaders() } });
          if (!resp2.ok) throw new Error(`HTTP ${resp2.status}`);
          const detail = await resp2.json();
          renderEmailDetail(detail);
          close();
        } catch (e) {
          console.error(e);
          toastError("Failed to load email detail");
        }
      });
    });

    modal.querySelector("#vcSimilarClose").addEventListener("click", close);
  } catch (e) {
    console.error(e);
    toastError("Similar email search failed");
  }
}

async function bulkSetCategoryAction() {
  const ids = getSelectedEmailIds();
  if (!ids.length) {
    toastInfo("Select one or more emails first");
    return;
  }
  const category = window.prompt("Category name", "");
  if (!category || !category.trim()) return;

  try {
    const resp = await fetch(`${API_BASE}/api/correspondence/emails/bulk/set-category`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        email_ids: ids,
        case_id: caseId || null,
        project_id: projectId || null,
        category: category.trim(),
      }),
    });
    if (!resp.ok) {
      const t = await resp.text();
      throw new Error(t || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    toastSuccess(`Updated ${data?.updated ?? ids.length} email(s)`);
    gridApi?.refreshServerSide?.({ purge: false });
  } catch (e) {
    console.error(e);
    toastError("Bulk category update failed");
  }
}

async function bulkAddKeywordsAction() {
  const ids = getSelectedEmailIds();
  if (!ids.length) {
    toastInfo("Select one or more emails first");
    return;
  }

  let items;
  try {
    items = await ensureKeywordsLoaded();
  } catch (e) {
    console.error(e);
    toastError("Could not load keywords");
    return;
  }

  const { modal, close } = showModal({
    title: `Add keywords (${ids.length} selected)`,
    widthPx: 900,
    bodyHtml: `
      <input id="vcKwSearch" class="input" style="width:100%; margin-bottom: 12px;" placeholder="Search keywords..." />
      <div id="vcKwList" style="max-height: 60vh; overflow:auto; border: 1px solid var(--border-default); border-radius: var(--radius-lg);"></div>
    `,
    footerHtml: `
      <button class="btn btn-ghost" id="vcKwCancel">Cancel</button>
      <button class="btn btn-vericase" id="vcKwAdd">Add selected</button>
    `,
  });

  const listEl = modal.querySelector("#vcKwList");
  const searchEl = modal.querySelector("#vcKwSearch");
  const selected = new Set();

  const render = () => {
    const q = (searchEl.value || "").toLowerCase().trim();
    const filtered = !q
      ? items
      : items.filter((k) => `${k.name || ""} ${k.definition || ""} ${k.variations || ""}`.toLowerCase().includes(q));

    listEl.innerHTML = filtered
      .slice(0, 1500)
      .map((k) => {
        const checked = selected.has(String(k.id));
        const title = escapeHtml(k.name || "(Unnamed)");
        const defn = k.definition ? escapeHtml(k.definition) : "";
        const meta = k.variations ? escapeHtml(k.variations) : "";
        return `
          <label style="display:block; padding: 10px 12px; border-bottom: 1px solid var(--border-default); cursor:pointer;">
            <div style="display:flex; gap: 10px; align-items:flex-start;">
              <input type="checkbox" data-id="${escapeHtml(k.id)}" ${checked ? "checked" : ""} />
              <div>
                <div style="font-weight:600;">${title}</div>
                ${defn ? `<div style="font-size:0.8125rem; color: var(--text-secondary);">${defn}</div>` : ""}
                ${meta ? `<div style="font-size:0.8125rem; color: var(--text-secondary);">${meta}</div>` : ""}
              </div>
            </div>
          </label>
        `;
      })
      .join("");

    listEl.querySelectorAll("input[type='checkbox'][data-id]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = cb.getAttribute("data-id");
        if (!id) return;
        if (cb.checked) selected.add(String(id));
        else selected.delete(String(id));
      });
    });
  };

  render();
  searchEl.addEventListener("input", render);
  setTimeout(() => searchEl.focus(), 0);

  modal.querySelector("#vcKwCancel").addEventListener("click", close);
  modal.querySelector("#vcKwAdd").addEventListener("click", async () => {
    const keywordIds = Array.from(selected);
    if (!keywordIds.length) {
      toastInfo("Select one or more keywords");
      return;
    }
    try {
      const resp = await fetch(`${API_BASE}/api/correspondence/emails/bulk/add-keywords`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
        },
        body: JSON.stringify({
          email_ids: ids,
          case_id: caseId || null,
          project_id: projectId || null,
          keyword_ids: keywordIds,
        }),
      });
      if (!resp.ok) {
        const t = await resp.text();
        throw new Error(t || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      toastSuccess(`Updated ${data?.updated ?? ids.length} email(s)`);
      gridApi?.refreshServerSide?.({ purge: false });
      close();
    } catch (e) {
      console.error(e);
      toastError("Bulk keyword update failed");
    }
  });
}

async function bulkExportSelectedAction() {
  const ids = getSelectedEmailIds();
  if (!ids.length) {
    toastInfo("Select one or more emails first");
    return;
  }
  const includeBody = await confirmDialog("Include body text in export? (May be large)", {
    title: "Export",
    confirmText: "Include body",
    cancelText: "No body",
  });

  try {
    const resp = await fetch(`${API_BASE}/api/correspondence/emails/export`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        email_ids: ids,
        case_id: caseId || null,
        project_id: projectId || null,
        include_body: !!includeBody,
      }),
    });
    if (!resp.ok) {
      const t = await resp.text();
      throw new Error(t || `HTTP ${resp.status}`);
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "emails_export.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toastSuccess("Export started");
  } catch (e) {
    console.error(e);
    toastError("Export failed");
  }
}

async function loadLinkTargetsForSelectedType() {
  const linkTypeEl = document.getElementById("linkTypeSelect");
  const targetEl = document.getElementById("linkTargetSelect");
  const btnEl = document.getElementById("linkSelectedBtn");
  if (!linkTypeEl || !targetEl || !btnEl) return;

  const type = linkTypeEl.value;
  if (!type) {
    targetEl.style.display = "none";
    targetEl.innerHTML = `<option value="">Select target...</option>`;
    btnEl.disabled = true;
    return;
  }

  targetEl.style.display = "block";
  btnEl.disabled = true;
  targetEl.innerHTML = `<option value="">Loading...</option>`;

  try {
    const params = new URLSearchParams();
    if (projectId) params.set("project_id", projectId);
    if (caseId) params.set("case_id", caseId);

    if (type === "matter") {
      if (!Array.isArray(linkTargetsCache.matter)) {
        const resp = await fetch(`${API_BASE}/api/claims/matters?${params}`, { headers: { ...getAuthHeaders() } });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        linkTargetsCache.matter = Array.isArray(data?.items) ? data.items : [];
      }
      const items = linkTargetsCache.matter;
      targetEl.innerHTML = `<option value="">Select target...</option>` + items.map((m) => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`).join("");
    } else if (type === "claim") {
      if (!Array.isArray(linkTargetsCache.claim)) {
        const resp = await fetch(`${API_BASE}/api/claims/heads-of-claim?${params}`, { headers: { ...getAuthHeaders() } });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        linkTargetsCache.claim = Array.isArray(data?.items) ? data.items : [];
      }
      const items = linkTargetsCache.claim;
      targetEl.innerHTML = `<option value="">Select target...</option>` + items.map((c) => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name || c.id)}</option>`).join("");
    } else {
      targetEl.innerHTML = `<option value="">Select target...</option>`;
    }

    // Enable button only when selection + target present.
    updateLinkControls();
    targetEl.onchange = () => updateLinkControls();
  } catch (e) {
    console.error(e);
    targetEl.innerHTML = `<option value="">(Failed to load targets)</option>`;
    toastError("Failed to load link targets");
  }
}

function updateLinkControls() {
  const selectedCount = getSelectedEmailIds().length;

  const toolbarBtn = document.getElementById("linkToolbarBtn");
  const toolbarLabel = document.getElementById("linkToolbarLabel");
  if (toolbarBtn) toolbarBtn.disabled = selectedCount === 0;
  if (toolbarLabel) toolbarLabel.textContent = selectedCount ? `Link (${selectedCount})` : "Link";

  const btnEl = document.getElementById("linkSelectedBtn");
  const linkTypeEl = document.getElementById("linkTypeSelect");
  const targetEl = document.getElementById("linkTargetSelect");
  if (!btnEl || !linkTypeEl || !targetEl) return;
  const hasSelection = selectedCount > 0;
  const hasType = !!linkTypeEl.value;
  const hasTarget = !!targetEl.value;
  btnEl.disabled = !(hasSelection && hasType && hasTarget);
}

let commandPaletteModal = null;

function openCommandPalette() {
  if (commandPaletteModal) {
    commandPaletteModal.close();
    commandPaletteModal = null;
    return;
  }

  const commands = [
    { name: "Refresh data", run: () => window.refreshData?.() },
    { name: "VeriCase Analysis", run: () => window.openVeriCaseAnalysis?.() },
    { name: "Focus search", run: () => document.getElementById("quickFilter")?.focus() },
    { name: "Filter by stakeholder", run: () => window.showStakeholderFilter?.() },
    { name: "Filter by keyword", run: () => window.showKeywordFilter?.() },
    { name: "Show similar emails", run: () => window.showSimilarEmails?.() },
    { name: "Link selected emails", run: () => window.openLinkModalForSelected?.() },
    { name: "Export selected emails", run: () => window.bulkExportSelected?.() },
  ];

  commandPaletteModal = showModal({
    title: "Command palette",
    widthPx: 820,
    bodyHtml: `
      <input id="vcCmdSearch" class="input" style="width:100%; margin-bottom: 12px;" placeholder="Type a command..." />
      <div id="vcCmdList" style="border: 1px solid var(--border-default); border-radius: var(--radius-lg);"></div>
      <div style="margin-top: 10px; font-size: 0.8125rem; color: var(--text-secondary);">Tip: press Enter to run the first command.</div>
    `,
    footerHtml: `<button class="btn btn-vericase" id="vcCmdClose">Close</button>`,
  });

  const { modal, close } = commandPaletteModal;
  const input = modal.querySelector("#vcCmdSearch");
  const list = modal.querySelector("#vcCmdList");

  const render = () => {
    const q = (input.value || "").toLowerCase().trim();
    const filtered = !q ? commands : commands.filter((c) => c.name.toLowerCase().includes(q));
    list.innerHTML = filtered
      .slice(0, 30)
      .map((c, idx) => `
        <button class="dropdown-item" data-idx="${idx}" style="display:block; width:100%; text-align:left; border-bottom: 1px solid var(--border-default);">
          ${escapeHtml(c.name)}
        </button>
      `)
      .join("");
    list.querySelectorAll("button[data-idx]").forEach((b) => {
      b.addEventListener("click", () => {
        const i = Number(b.getAttribute("data-idx"));
        const cmd = filtered[i];
        if (!cmd) return;
        close();
        commandPaletteModal = null;
        cmd.run();
      });
    });
  };

  input.addEventListener("input", render);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const q = (input.value || "").toLowerCase().trim();
      const filtered = !q ? commands : commands.filter((c) => c.name.toLowerCase().includes(q));
      const cmd = filtered[0];
      if (!cmd) return;
      close();
      commandPaletteModal = null;
      cmd.run();
    }
  });

  modal.querySelector("#vcCmdClose").addEventListener("click", () => {
    close();
    commandPaletteModal = null;
  });

  render();
  setTimeout(() => input.focus(), 0);
}

window.openTableSettings = function () {
  if (!gridApi) return;
  try {
    // Show the side bar and focus the Columns panel.
    gridApi.setSideBarVisible?.(true);
    gridApi.openToolPanel?.("columns");
    if (window.VericaseUI?.Toast) {
      window.VericaseUI.Toast.info("Use Columns/Filters on the right to configure the table.");
    }
  } catch (e) {
    console.warn("Failed to open table settings:", e);
  }
};

function initGrid() {
  const currentUser = JSON.parse(localStorage.getItem("user") || "{}");
  const userIsAdmin =
    String(currentUser.role || "").toUpperCase() === "ADMIN";
  // Force collapse panels immediately
  setContextPanelCollapsed(true);
  const sidebarBtn = document.querySelector('[ref="eSideBarButton"]');
  if (sidebarBtn) sidebarBtn.click();

  // NOTE: Stakeholders cache is now pre-loaded in initState() before grid refresh.
  // This ensures the cache is populated when cells first render.

  const gridDiv = document.getElementById("emailGrid");
  if (!gridDiv || !window.agGrid) {
    console.error("AG Grid not available or grid element missing");
    return;
  }

  // Set AG Grid Enterprise license key (must happen before grid creation)
  try {
    const agKey = window.VeriCaseConfig
      ? window.VeriCaseConfig.agGridLicenseKey
      : window.VERICASE_AG_GRID_LICENSE_KEY;
    if (agKey && agGrid.LicenseManager) {
      agGrid.LicenseManager.setLicenseKey(agKey);
    }
  } catch (e) {
    console.warn("AG Grid license key init failed:", e);
  }

  const columnDefs = [
    {
      headerName: "Date",
      field: "email_date",
      sortable: true,
      filter: "agDateColumnFilter",
      width: 180,
      minWidth: 100,
      sort: "desc",  // Newest first
      sortIndex: 0,
      headerTooltip: "Sent date/time",
      cellRenderer: (p) => {
        if (!p.value) return "<span style='color: var(--text-muted);'>-</span>";
        const d = new Date(p.value);
        if (Number.isNaN(d.getTime())) return "<span style='color: var(--text-muted);'>-</span>";
        const day = String(d.getDate()).padStart(2, "0");
        const month = String(d.getMonth() + 1).padStart(2, "0");
        const year = d.getFullYear();
        const hours = String(d.getHours()).padStart(2, "0");
        const minutes = String(d.getMinutes()).padStart(2, "0");
        return `<div style="line-height: 1.4;">${day}/${month}/${year}<br/><span style="color: var(--text-secondary);">${hours}:${minutes}</span></div>`;
      },
    },
    {
      headerName: "From",
      field: "email_from",
      sortable: true,
      filter: "agSetColumnFilter",
      filterParams: {
        values: async (params) => {
          const addresses = await ensureEmailAddressesLoaded();
          return addresses.from || [];
        },
        refreshValuesOnOpen: true,
        buttons: ['reset', 'apply'],
        closeOnApply: true,
      },
      minWidth: 220,
      flex: 1,
      headerTooltip: "Sender - Click filter icon to see all senders",
      cellRenderer: (p) => formatEmailAddressCell(p.value),
    },
    {
      headerName: "To",
      field: "email_to",
      sortable: true,
      filter: "agSetColumnFilter",
      filterParams: {
        values: async (params) => {
          const addresses = await ensureEmailAddressesLoaded();
          return addresses.to || [];
        },
        refreshValuesOnOpen: true,
        buttons: ['reset', 'apply'],
        closeOnApply: true,
      },
      minWidth: 220,
      flex: 1,
      headerTooltip: "Primary recipients - Click filter icon to see all recipients",
      cellRenderer: (p) => formatEmailAddressCell(p.value),
    },
    {
      headerName: "Cc",
      field: "email_cc",
      sortable: true,
      filter: "agSetColumnFilter",
      filterParams: {
        values: async (params) => {
          const addresses = await ensureEmailAddressesLoaded();
          return addresses.cc || [];
        },
        refreshValuesOnOpen: true,
        buttons: ['reset', 'apply'],
        closeOnApply: true,
      },
      minWidth: 200,
      flex: 1,
      headerTooltip: "CC recipients - Click filter icon to see all CC recipients",
      cellRenderer: (p) => formatEmailAddressCell(p.value),
    },
    {
      headerName: "Stakeholders",
      field: "_stakeholders",
      sortable: true,
      filter: "agSetColumnFilter",
      width: 180,
      headerTooltip: "Unique domains/companies from From, To, and Cc",
      valueGetter: (p) => {
        if (!p.data) return [];
        return extractStakeholders(p.data.email_from, p.data.email_to, p.data.email_cc);
      },
      cellRenderer: (p) => {
        const stakeholders = p.value;
        if (!stakeholders || !Array.isArray(stakeholders) || stakeholders.length === 0) {
          return '<span style="color: var(--text-muted);">—</span>';
        }
        const display = stakeholders.slice(0, 2).join(", ");
        const extra = stakeholders.length > 2 ? ` +${stakeholders.length - 2}` : "";
        return `<span style="color: var(--vericase-teal); font-size: 0.75rem;">${display}${extra}</span>`;
      },
    },
    {
      headerName: "Subject",
      field: "email_subject",
      sortable: true,
      filter: "agTextColumnFilter",
      minWidth: 320,
      flex: 2,
      headerTooltip: "Email subject (Excluded badge indicates an exclusion tag)",
      cellRenderer: (p) => {
        const subj = escapeHtml(p.value || "(No subject)");
        const label = escapeHtml(p.data?.meta?.exclusion?.excluded_label || "");
        const excluded = p.data?.meta?.exclusion?.excluded === true;
        const linkCount = Number(p.data?.linked_to_count || 0);
        const emailId = p.data?.id ? escapeHtml(p.data.id) : "";

        const chips = [];
        if (excluded) {
          chips.push(
            `<span style="margin-left:8px; padding:2px 8px; border-radius:999px; font-size:0.75rem; background:#FEF3C7; color:#92400E;">${label || "Excluded"}</span>`,
          );
        }
        if (emailId) {
          chips.push(
            `<button type="button" onclick="openLinkModalForEmail('${emailId}'); event.stopPropagation();" title="Link to Contentious Matter / Head of Claim" style="margin-left:8px; padding:2px 8px; border-radius:999px; font-size:0.75rem; line-height:1; border: 1px solid var(--border-default); background: rgba(var(--vericase-teal-rgb), 0.08); color: var(--vc-teal); cursor: pointer;"><i class="fas fa-link"></i>${linkCount > 0 ? ` ${linkCount}` : ""}</button>`,
          );
        }

        return `${subj}${chips.join("")}`;
      },
    },
    {
      headerName: "Keywords",
      field: "matched_keywords",
      minWidth: 220,
      flex: 1,
      filter: "agSetColumnFilter",
      filterParams: {
        // Load keyword values from API (optimized for 100k+ rows)
        values: async (params) => {
          const keywords = await ensureKeywordsLoaded();
          return keywords.map(k => k.name || k.keyword || k.id).filter(Boolean);
        },
        refreshValuesOnOpen: true,
        buttons: ['reset', 'apply'],
        closeOnApply: true,
      },
      headerTooltip: "Matched keywords (auto-tagged + manually added)",
      valueGetter: (p) => formatMatchedKeywords(p.data?.matched_keywords),
      cellRenderer: (p) => renderKeywordChips(p.data?.matched_keywords),
    },
    ...(userIsAdmin
      ? [
          {
            headerName: "PST File",
            field: "pst_filename",
            sortable: true,
            // Use text filter for PST files (server-side compatible, no client-side value extraction)
            filter: "agTextColumnFilter",
            filterParams: {
              buttons: ['reset', 'apply'],
              closeOnApply: true,
            },
            minWidth: 220,
            flex: 1,
            headerTooltip: "Source PST file (admin only)",
            valueFormatter: (p) => p.value || "-",
          },
        ]
      : []),
    {
      headerName: "Body",
      field: "body_text_clean",
      minWidth: 300,
      flex: 2,
      filter: "agTextColumnFilter",
      headerTooltip: "Email body (click expand icon for larger view)",
      wrapText: false,
      cellClass: "body-cell",
      cellRenderer: (p) => {
        const bodyText = getBodyPreviewText(p.data) || "";
        if (!bodyText) {
          return '<span style="color: var(--text-muted);">-</span>';
        }

        const rowId = p.node.id;
        const isExpanded = p.node.data?._bodyExpanded || false;
        const icon = isExpanded ? "fa-compress-alt" : "fa-expand-alt";
        const isLoading = p.node.data?._bodyLoading === true;
        const loadErr = p.node.data?._bodyLoadError;

        // Format body for display - use full HTML formatting in both states
        const bodyHtml = formatEmailBodyText(getBodyTextValue(p.data));
        
        // Collapsed: smaller max-height with scroll, Expanded: larger max-height with scroll
        const maxHeight = isExpanded ? "300px" : "60px";
        const title = isExpanded ? "Collapse" : "Expand";

        return `
          <div style="display: flex; align-items: start; gap: 8px; width: 100%;">
            <button
              onclick="toggleBodyCell('${rowId}'); event.stopPropagation();"
              style="flex-shrink: 0; padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-secondary); cursor: pointer; font-size: 0.75rem;"
              title="${title}"
            >
              <i class="fas ${icon}"></i>
            </button>
            <div class="email-html-content" style="flex: 1; word-break: break-word; line-height: 1.5; max-height: ${maxHeight}; overflow: auto; padding-right: 4px;">
              ${isLoading ? `<div style="font-size:0.85rem; color: var(--text-muted); margin-bottom: 6px;"><i class="fas fa-spinner fa-spin"></i> Loading full body…</div>` : ""}
              ${loadErr ? `<div style="font-size:0.85rem; color: #b91c1c; margin-bottom: 6px;">Failed to load full body (${escapeHtml(String(loadErr))}). Showing preview.</div>` : ""}
              ${bodyHtml || '<span style="color: var(--text-muted); font-style: italic;">No body content</span>'}
            </div>
          </div>
        `;
      },
    },
    {
      headerName: "Thread Body",
      field: "email_body_full",
      minWidth: 400,
      flex: 3,
      filter: "agTextColumnFilter",
      headerTooltip: "Full email thread body (legacy)",
      wrapText: false,
      cellClass: 'body-cell',
      cellRenderer: (p) => {
        const body = p.data?.email_body || p.data?.body_text_clean || p.data?.body_text || "";
        if (!body) return '<span style="color: var(--text-muted);">—</span>';
        
        const rowId = p.node.id;
        const isExpanded = p.node.data?._bodyExpanded || false;
        const icon = isExpanded ? 'fa-compress-alt' : 'fa-expand-alt';
        
        // No truncation - show full content with scrolling
        const maxHeight = isExpanded ? "300px" : "60px";
        const title = isExpanded ? 'Collapse' : 'Expand';
        
        return `
          <div style="display: flex; align-items: start; gap: 8px; width: 100%;">
            <button 
              onclick="toggleBodyCell('${rowId}'); event.stopPropagation();" 
              style="flex-shrink: 0; padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-secondary); cursor: pointer; font-size: 0.75rem;"
              title="${title}"
            >
              <i class="fas ${icon}"></i>
            </button>
            <div style="flex: 1; white-space: pre-wrap; word-break: break-word; line-height: 1.5; max-height: ${maxHeight}; overflow: auto;">
              ${escapeHtml(body)}
            </div>
          </div>
        `;
      },
      hide: true,
      suppressColumnsToolPanel: true,
      suppressFiltersToolPanel: true,
    },
    {
      headerName: "Thread",
      field: "thread_id",
      minWidth: 140,
      flex: 1,
      filter: "agTextColumnFilter",
      headerTooltip: "Conversation/thread identifier",
      hide: true,
      suppressColumnsToolPanel: true,
      suppressFiltersToolPanel: true,
    },
    {
      headerName: "Notes",
      field: "notes",
      minWidth: 220,
      flex: 1,
      filter: "agTextColumnFilter",
      headerTooltip: "Internal notes (per email)",
    },
    {
      headerName: "Stakeholders",
      field: "matched_stakeholders",
      minWidth: 200,
      flex: 1,
      sortable: false,
      filter: false,
      headerTooltip: "Matched stakeholders from this email",
      wrapText: false,
      cellRenderer: (p) => {
        const stakeholderIds = Array.isArray(p.data?.matched_stakeholders) ? p.data.matched_stakeholders : [];
        if (!stakeholderIds.length) return '<span style="color: var(--text-muted);">-</span>';
        
        // Look up stakeholder names from cache
        const names = stakeholderIds.map((id) => {
          if (Array.isArray(stakeholdersCache)) {
            const found = stakeholdersCache.find((s) => s.id === id);
            if (found) return found.name || found.role || id;
          }
          return id; // Fallback to ID if not in cache
        });

        // Show stakeholders as colored pills
        const colors = [
          { bg: '#fef3c7', text: '#92400e' }, // Warm yellow
          { bg: '#dbeafe', text: '#1e40af' }, // Soft blue
          { bg: '#dcfce7', text: '#166534' }, // Mint green
          { bg: '#fce7f3', text: '#9d174d' }, // Soft pink
          { bg: '#f3e8ff', text: '#6b21a8' }, // Lavender
          { bg: '#e0f2fe', text: '#0369a1' }, // Sky blue
        ];
        
        return `<div style="display: flex; flex-wrap: wrap; gap: 6px; padding: 4px 0;">
          ${names.map((name, i) => {
            const color = colors[i % colors.length];
            return `<span style="display: inline-flex; align-items: center; padding: 5px 12px; border-radius: 16px; background: ${color.bg}; color: ${color.text}; font-size: 0.8rem; font-weight: 500;">${escapeHtml(name)}</span>`;
          }).join('')}
        </div>`;
      },
    },
    {
      headerName: "Has Attachments",
      field: "has_attachments",
      width: 140,
      sortable: true,
      filter: "agBooleanColumnFilter",
      headerTooltip: "Whether this email has attachments",
      valueFormatter: (p) => (p.value ? "Yes" : ""),
      hide: true,
      suppressColumnsToolPanel: true,
      suppressFiltersToolPanel: true,
    },
    {
      headerName: "Links",
      field: "linked_to_count",
      width: 110,
      sortable: true,
      filter: "agNumberColumnFilter",
      headerTooltip: "Linked Matters / Heads of Claim",
      valueGetter: (p) => Number(p.data?.linked_to_count || 0),
      cellRenderer: (p) => {
        const emailId = p.data?.id ? escapeHtml(p.data.id) : "";
        if (!emailId) return '<span style="color: var(--text-muted);">-</span>';
        const count = Number(p.value || 0);
        const suffix = count > 0 ? ` ${count}` : "";
        return `
          <button
            type="button"
            onclick="openLinkModalForEmail('${emailId}'); event.stopPropagation();"
            title="Link to Matter / Head of Claim"
            style="padding:2px 8px; border-radius:999px; font-size:0.75rem; line-height:1; border: 1px solid var(--border-default); background: rgba(var(--vericase-teal-rgb), 0.08); color: var(--vc-teal); cursor:pointer;"
          ><i class="fas fa-link"></i>${suffix}</button>
        `;
      },
    },
    {
      headerName: "Attachments",
      field: "attachment_count",
      minWidth: 260,
      flex: 1,
      sortable: false,
      filter: false,
      headerTooltip: "Attachment file names",
      wrapText: false,
      valueGetter: (p) => {
        const attachments = Array.isArray(p.data?.attachments) ? p.data.attachments : [];
        const names = attachments
          .map((a) => a?.fileName || a?.filename || a?.name)
          .filter(Boolean)
          .map((n) => String(n));
        return names.join(", ");
      },
      cellRenderer: (p) => {
        const attachments = Array.isArray(p.data?.attachments) ? p.data.attachments : [];
        if (!attachments.length) return '<span style="color: var(--text-muted);">-</span>';

        const items = attachments
          .map((a) => ({
            evidenceId: a?.evidenceId || a?.id || "",
            attachmentId: a?.attachmentId || a?.id || "",
            fileName: a?.fileName || a?.filename || a?.name || "attachment",
          }))
          .filter((a) => a.fileName);

        return `
          <div class="attachment-grid-list" style="max-height: 120px; overflow: auto; padding-right: 4px;">
            ${items
              .map((item) => {
                const safeName = escapeHtml(item.fileName);
                const jsName = String(item.fileName).replace(/'/g, "\\'");
                if (!item.evidenceId || !item.attachmentId) {
                  return `<span>${safeName}</span>`;
                }
                return `
                  <button
                    type="button"
                    class="attachment-grid-link"
                    onclick="previewAttachment('${item.evidenceId}', '${item.attachmentId}', '${jsName}'); event.stopPropagation();"
                    title="Preview ${safeName}"
                  >
                    ${safeName}
                  </button>
                `;
              })
              .join("")}
          </div>
        `;
      },
    },
    {
      headerName: "Programme Activity",
      field: "programme_activity",
      minWidth: 220,
      flex: 1,
      filter: "agTextColumnFilter",
      filterParams: { buttons: ['reset', 'apply'], closeOnApply: true },
      headerTooltip: "Mapped programme activity (as planned)",
      cellRenderer: (p) => p.value ? `<span style="color: var(--vericase-teal);">${escapeHtml(p.value)}</span>` : '<span style="color: var(--text-muted);">-</span>',
    },
    {
      headerName: "Planned Finish",
      field: "as_planned_finish_date",
      width: 160,
      sortable: true,
      filter: "agDateColumnFilter",
      filterParams: { buttons: ['reset', 'apply'], closeOnApply: true },
      headerTooltip: "As-planned finish date",
      valueFormatter: (p) => {
        if (!p.value) return "-";
        const d = new Date(p.value);
        if (Number.isNaN(d.getTime())) return "-";
        return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
      },
    },
    {
      headerName: "As-Built Activity",
      field: "as_built_activity",
      minWidth: 220,
      flex: 1,
      filter: "agTextColumnFilter",
      filterParams: { buttons: ['reset', 'apply'], closeOnApply: true },
      headerTooltip: "Mapped as-built programme activity",
      cellRenderer: (p) => p.value ? `<span style="color: var(--vericase-navy);">${escapeHtml(p.value)}</span>` : '<span style="color: var(--text-muted);">-</span>',
    },
    {
      headerName: "As-Built Finish",
      field: "as_built_finish_date",
      width: 160,
      sortable: true,
      filter: "agDateColumnFilter",
      filterParams: { buttons: ['reset', 'apply'], closeOnApply: true },
      headerTooltip: "As-built finish date",
      valueFormatter: (p) => {
        if (!p.value) return "-";
        const d = new Date(p.value);
        if (Number.isNaN(d.getTime())) return "-";
        return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
      },
    },
    {
      headerName: "Delay (days)",
      field: "delay_days",
      width: 130,
      sortable: true,
      filter: "agNumberColumnFilter",
      filterParams: { buttons: ['reset', 'apply'], closeOnApply: true },
      headerTooltip: "Delay days (if populated)",
      cellRenderer: (p) => {
        if (p.value === null || p.value === undefined) return '<span style="color: var(--text-muted);">-</span>';
        const days = Number(p.value);
        if (days > 0) return `<span style="color: #dc2626; font-weight: 500;">+${days}</span>`;
        if (days < 0) return `<span style="color: #16a34a; font-weight: 500;">${days}</span>`;
        return `<span style="color: var(--text-muted);">0</span>`;
      },
    },
    {
      headerName: "Critical Path",
      field: "is_critical_path",
      width: 140,
      sortable: true,
      filter: "agBooleanColumnFilter",
      headerTooltip: "Critical path flag (if populated)",
      cellRenderer: (p) => {
        if (p.value === true) return '<span style="display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 999px; background: #fee2e2; color: #991b1b; font-size: 0.75rem; font-weight: 500;"><i class="fas fa-exclamation-circle"></i> Critical</span>';
        return '<span style="color: var(--text-muted);">-</span>';
      },
    },
    {
      headerName: "Excluded",
      field: "excluded",
      width: 105,
      sortable: true,
      filter: "agBooleanColumnFilter",
      headerTooltip: "Whether this email is marked as excluded",
      valueGetter: (p) => p.data?.meta?.exclusion?.excluded === true,
      valueFormatter: (p) => (p.value ? "Yes" : ""),
    },
    {
      headerName: "Exclusion Label",
      field: "excluded_label",
      minWidth: 160,
      flex: 1,
      filter: "agTextColumnFilter",
      headerTooltip: "Exclusion tag/label",
      valueGetter: (p) => p.data?.meta?.exclusion?.excluded_label || "",
    },
  ];

  const gridOptions = {
    columnDefs,
    // AG Grid v35: Use legacy themes (CSS-based ag-theme-alpine) instead of new Theming API
    theme: "legacy",
    defaultColDef: {
      resizable: true,
      sortable: true,
      filter: true,
      floatingFilter: false,
      wrapHeaderText: true,
      autoHeaderHeight: true,
    },
    // v34.3+ Auto-size strategy: Fit columns to grid width on initial load
    // This replaces manual sizeColumnsToFit() and works better with SSRM
    autoSizeStrategy: {
      type: "fitGridWidth",
      defaultMinWidth: 80,
      defaultMaxWidth: 500,
    },
    rowModelType: "serverSide",
    // SSRM configuration for large datasets:
    // - cacheBlockSize: 100 rows per fetch (matches evidence grid)
    // - No maxBlocksInCache limit: allows smooth scrolling through large datasets
    //   without constant refetching. Previously limited to 10 blocks (~1000 rows)
    //   which caused visible loading on every scroll through 100k+ emails.
    cacheBlockSize: 100,
    // Debounce rapid scrolling to avoid excessive API calls
    blockLoadDebounceMillis: 100,
    // Improve initial scroll estimation for large datasets
    serverSideInitialRowCount: 1000,
    sideBar: {
      toolPanels: [
        {
          id: "columns",
          labelDefault: "Columns",
          labelKey: "columns",
          iconKey: "columns",
          toolPanel: "agColumnsToolPanel",
          toolPanelParams: {
            suppressRowGroups: true,
            suppressValues: true,
            suppressPivots: true,
            suppressPivotMode: true,
            suppressColumnFilter: false,
            suppressColumnSelectAll: false,
            suppressColumnExpandAll: false,
          },
        },
        {
          id: "filters",
          labelDefault: "Filters",
          labelKey: "filters",
          iconKey: "filter",
          toolPanel: "agFiltersToolPanel",
        },
      ],
    },
    // Required for Server-Side Row Model selection (keeps row identity stable across blocks).
    // The API returns a stable UUID string for each row in `id`.
    getRowId: (params) => params.data?.id,
    // Avoid expensive auto-height measurement; keep the grid responsive even at 100k+ rows.
    getRowHeight: (params) =>
      params?.data?._bodyExpanded ? ROW_HEIGHT_EXPANDED : ROW_HEIGHT_COLLAPSED,
    // v35 Row Selection API: Object-based configuration
    rowSelection: {
      mode: "multiRow",
      enableClickSelection: true,
      checkboxes: false,    // Disable checkbox column for cleaner email list UI
      headerCheckbox: false,
    },
    onGridReady: (params) => {
      gridApi = params.api;
      // NOTE: params.columnApi is deprecated in AG Grid v31+. Use params.api for column operations.

      // Close sidebar by default
      params.api.setSideBarVisible(false);

      // Restore active named view or fallback layout (best-effort)
      try {
        const activeName = localStorage.getItem(GRID_VIEW_ACTIVE_KEY);
        const views = loadGridViews();
        const activeView = activeName
          ? views.find((v) => String(v.name).toLowerCase() === String(activeName).toLowerCase())
          : null;
        if (activeView) {
          applyGridView(activeView, { toast: false, refresh: false });
        } else {
          const raw = localStorage.getItem("vc_correspondence_grid_state");
          if (raw && gridApi) {
            const state = JSON.parse(raw);
            if (state.columnState) {
              const sanitized = state.columnState.map((col) => ({
                ...col,
                hide: DEFAULT_HIDDEN_COLUMNS.has(col.colId) ? true : false,
                pinned: null,
              }));
              // Keep the default column order; only restore widths/visibility/etc.
              gridApi.applyColumnState({ state: sanitized, applyOrder: false });
            }
          }
        }
      } catch (e) {
        console.warn("Could not restore grid state:", e);
      }

      if (gridApi?.getColumns) {
        const showState = gridApi.getColumns().map((col) => {
          const colId = col.getColId();
          return {
            colId,
            hide: DEFAULT_HIDDEN_COLUMNS.has(colId),
            pinned: null,
          };
        });
        if (showState.length) {
          gridApi.applyColumnState({ state: showState, applyOrder: false });
        }
      }

      // Enforce default sort: newest first (using applyColumnState, setSortModel is deprecated)
      try {
        gridApi.applyColumnState?.({
          state: [{ colId: "email_date", sort: "desc" }],  // Newest first
          defaultState: { sort: null },
        });
      } catch {
        // ignore
      }

      gridApi.setGridOption("serverSideDatasource", createServerSideDatasource());
      updateViewsDropdown();
      
      // Preload keywords and stakeholders BEFORE resolving grid ready.
      // This ensures the caches are populated when SSRM renders the first cells.
      // Load in background (don't block grid initialization), but refresh after loaded.
      Promise.all([
        ensureKeywordsLoaded(),
        ensureStakeholdersLoaded()
      ]).then(() => {
        // Force a cell refresh so keyword/stakeholder chips show names instead of IDs
        if (gridApi) {
          gridApi.refreshCells({ force: true });
        }
      }).catch(e => {
        console.warn("[Correspondence] Could not preload keywords/stakeholders:", e);
      });
      
      resolveGridReady();
    },

    onFirstDataRendered: () => {
      // v35: autoSizeStrategy handles initial column sizing automatically
      // Fallback: also call sizeColumnsToFit() to ensure columns fill grid width
      try {
        if (gridApi) {
          gridApi.sizeColumnsToFit();
        }
      } catch (e) {
        console.warn("Could not size columns to fit:", e);
      }
      // Keep Quick Actions collapsed unless explicitly opened.
      setContextPanelCollapsed(true);
    },
    onSelectionChanged: () => {
      const selected = gridApi ? gridApi.getSelectedRows() : [];
      const countEl = document.getElementById("selectedCount");
      if (countEl) countEl.textContent = String(selected.length);

      const ctxCountEl = document.getElementById("contextSelectedCount");
      if (ctxCountEl) ctxCountEl.textContent = String(selected.length);

      const previewEl = document.getElementById("selectedEmailsPreview");
      if (previewEl) {
        if (!selected.length) {
          previewEl.innerHTML = `<div class="context-empty-state"><i class="fas fa-mouse-pointer"></i><p>Select emails for actions</p></div>`;
        } else {
          const items = selected.slice(0, 5).map((r) => {
            const subj = r.email_subject || "(No subject)";
            return `<div style="font-size:0.8125rem; padding:0.35rem 0; border-bottom:1px solid var(--border);">${subj}</div>`;
          }).join("");
          const more = selected.length > 5 ? `<div style="font-size:0.8rem; color: var(--text-muted); padding-top:0.5rem;">+${selected.length - 5} more</div>` : "";
          previewEl.innerHTML = `<div>${items}${more}</div>`;
        }
      }

      // Ensure quick-action controls stay enabled/disabled correctly.
      try {
        updateLinkControls();
      } catch {
        // ignore
      }
    },
    onRowDoubleClicked: (params) => {
      const row = params?.data;
      if (!row?.id) return;
      openEmailDetailById(row.id, row);
    },
  };

  gridApi = agGrid.createGrid(gridDiv, gridOptions);
}

// The script is injected after the components are loaded; initialise immediately.
initGrid();

// UX helpers (menus + shortcuts)
try {
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".toolbar-dropdown")) {
      window.closeAllDropdowns?.();
    }
  });
} catch {
  // ignore
}

try {
  if (window.VericaseUI?.Shortcuts?.register) {
    // Override the placeholder palette with the real one implemented here.
    window.VericaseUI.Shortcuts.register("ctrl+k", () => openCommandPalette());
  }
} catch {
  // ignore
}