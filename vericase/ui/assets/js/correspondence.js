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
  console.log(
    "[Correspondence] Grid ready, refreshing with project:",
    projectId,
  );
  gridApi.refreshServerSide({ purge: true });
})();
let columnApi;
let allEmails = [];
let currentViewMode = "all";
let currentAttachment;
let showFullContent = true; // Default to showing full content
let hideExcludedEmails = true; // Default to hiding excluded emails
let lastIncludeHiddenState = false;

// Function to download attachment using a signed URL
window.downloadAttachment = async function (
  evidenceId,
  attachmentId,
  fileName,
) {
  const documentId = looksLikeUuid(attachmentId)
    ? attachmentId
    : evidenceId;
  try {
    const response = await fetch(
      `${API_BASE}/api/evidence/items/${evidenceId}/attachments/${attachmentId}/url`,
    );
    if (!response.ok) throw new Error("Failed to get download URL");

    const data = await response.json();
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

  // Derive a documentId from legacy args (most data passes document_id as attachmentId)
  const documentId = looksLikeUuid(attachmentId)
    ? attachmentId
    : evidenceId;

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

  // Close modal on Escape key
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      closeAttachmentPreview();
      closeProgrammeModal();
    }
  });

  try {
    // Load both the file URL and OCR text in parallel
    const [fileData, ocrData] = await Promise.all([
      getSignedUrlForDocument(documentId),
      fetch(
        `${API_BASE}/api/correspondence/attachments/${documentId}/ocr-text`,
      )
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    ]);

    const { url, content_type } = fileData;
    const lowerName = (fileName || "").toLowerCase();
    const isImage =
      /\.(png|jpg|jpeg|gif|webp|bmp|svg)$/.test(lowerName) ||
      (content_type || "").startsWith("image/");
    const isPdf =
      /\.pdf$/.test(lowerName) || content_type === "application/pdf";

    // Build preview HTML with OCR panel
    let previewHTML =
      '<div style="display: flex; height: 100%; gap: 20px;">';

    // Left panel: Document preview (2/3 width)
    previewHTML +=
      '<div style="flex: 2; display: flex; flex-direction: column; min-width: 0;">';

    if (isImage) {
      previewHTML += `
                        <div style="flex: 1; display: flex; align-items: center; justify-content: center; background: #f3f4f6; border-radius: 8px; overflow: hidden;">
                            <img src="${url}" loading="lazy" style="max-width: 100%; max-height: 100%; object-fit: contain;"/>
                        </div>`;
    } else if (isPdf) {
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #f9fafb; border-radius: 8px; padding: 40px;">
                            <div style="font-size: 4rem; margin-bottom: 20px;">📄</div>
                            <h3 style="color: #1f2937; margin-bottom: 10px; text-align: center;">${fileName || "Document"}</h3>
                            <p style="color: #6b7280; margin-bottom: 20px; text-align: center;">PDF viewer opens in new tab</p>
                            <button onclick="window.open('${url}', '_blank')"
                                    style="background: #3b82f6; color: white; border: none; padding: 12px 24px; 
                                           border-radius: 6px; cursor: pointer; font-weight: 500; box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);">
                                <i class="fas fa-external-link-alt"></i> Open PDF
                            </button>
                        </div>`;
    } else {
      previewHTML += `
                        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #f9fafb; border-radius: 8px; padding: 40px;">
                            <div style="font-size: 3rem; margin-bottom: 20px;">📎</div>
                            <p style="color: #6b7280; margin-bottom: 20px; text-align: center;">Preview not available for this file type</p>
                            <button onclick="window.open('${url}', '_blank')" 
                                    style="background: #10b981; color: white; border: none; padding: 12px 24px;
                                           border-radius: 6px; cursor: pointer; font-weight: 500;">
                                <i class="fas fa-download"></i> Download File
                            </button>
                        </div>`;
    }

    previewHTML += "</div>";

    // Right panel: OCR Text (1/3 width, if available)
    if (
      ocrData &&
      (ocrData.extracted_text || ocrData.ocr_status === "processing")
    ) {
      previewHTML +=
        '<div style="flex: 1; display: flex; flex-direction: column; border-left: 2px solid #e5e7eb; padding-left: 20px; min-width: 0;">';
      previewHTML +=
        '<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; gap: 10px;">';
      previewHTML +=
        '<h4 style="margin: 0; color: #1f2937; font-size: 0.95rem; flex: 1;"><i class="fas fa-scroll" style="color: #17B5A3;"></i> OCR Extracted Text</h4>';

      if (ocrData.extracted_text) {
        previewHTML += `
                            <button onclick="copyOCRText()" title="Copy text to clipboard"
                                    style="background: #10b981; color: white; border: none; padding: 6px 12px;
                                           border-radius: 6px; cursor: pointer; font-size: 0.813rem; font-weight: 500; white-space: nowrap;">
                                <i class="fas fa-copy"></i> Copy
                            </button>`;
      }
      previewHTML += "</div>";

      if (ocrData.ocr_status === "processing") {
        previewHTML += `
                            <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #fef3c7; border-radius: 8px; padding: 20px;">
                                <div class="spinner" style="width: 32px; height: 32px; border-width: 3px;"></div>
                                <p style="margin-top: 16px; color: #92400e; font-weight: 500; text-align: center;">Processing OCR...</p>
                                <p style="margin-top: 8px; color: #78350f; font-size: 0.875rem; text-align: center;">Text extraction in progress.<br>Refresh preview in a moment.</p>
                            </div>`;
      } else if (ocrData.extracted_text) {
        // Highlight keywords in OCR text
        let highlightedText = ocrData.extracted_text;

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

// Function to close attachment preview
window.closeAttachmentPreview = function () {
  const modal = document.getElementById("attachmentPreviewModal");
  modal.style.display = "none";
  modal.setAttribute("aria-hidden", "true");
  currentAttachment = null;
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
        const token =
          localStorage.getItem("token") ||
          localStorage.getItem("jwt") ||
          "";
        let apiUrl = `${API_BASE}/api/correspondence/emails/server-side`;

        // Add project/case filter
        const queryParams = new URLSearchParams();
        if (projectId) queryParams.append("project_id", projectId);
        if (caseId) queryParams.append("case_id", caseId);
        // When showing excluded emails, request hidden/spam/other-project rows from server
        if (!hideExcludedEmails) queryParams.append("include_hidden", "true");
        if (queryParams.toString())
          apiUrl += "?" + queryParams.toString();

        const response = await fetch(apiUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
