# VeriCase Architecture: Forensically Sound Evidence Management

## Core Philosophy

**"The PST is the evidence. The attachments are the work product."**

VeriCase solves the £13 billion evidence crisis by maintaining forensic integrity while making dispute-critical documents instantly accessible.

## The VeriCase Approach

### Traditional (Broken) Approach:
1. Extract all emails from PST
2. Store millions of emails in database
3. Lose connection to original evidence
4. Compromise chain of custody
5. Duplicate 1-3 million emails needlessly

### VeriCase (Forensically Sound) Approach:
1. **PST Stays Intact** - Original remains immutable forensic evidence
2. **Extract Attachments Only** - Contracts, drawings, invoices, reports, expert reports
3. **Create Metadata Index** - Lightweight pointers to PST location
4. **Tag & Search Documents** - Keywords and stakeholders on attachments
5. **Preserve Chain of Custody** - Everything traceable to PST source

## Evidence Flow

```
PST File (Untouched)
    ↓
[VeriCase Processing]
    ↓
    ├─→ email_index table (metadata: subject, from, to, date, PST location)
    └─→ attachments/ directory (extracted PDFs, DOCXs, DWGs, etc.)
            ↓
         attachments table (searchable document index with keywords/stakeholders)
```

## Database Architecture

### email_index Table
**Purpose:** Lightweight searchable index of emails WITHOUT extracting content

**Contains:**
- PST file path (forensic source)
- PST message ID (exact location)
- Subject line
- From/To/CC addresses
- Date sent
- Keywords matched
- Stakeholders identified
- Attachment count

**Does NOT Contain:**
- Email body (stays in PST)
- Email attachments (extracted separately)

### attachments Table (THE MAIN EVIDENCE TABLE)
**Purpose:** Extracted physical documents that are the real dispute evidence

**Contains:**
- Physical file path (extracted document)
- Original filename
- Source PST file
- Parent email metadata
- Keywords matched
- Stakeholders identified
- File type, size, date
- Forensic chain back to PST

**This is what users search and work with.**

## Evidence Extraction Process

```python
def ingest_pst_file(pst_path, profile_id):
    """
    1. Read PST file (but don't extract emails)
    2. For each email:
       a. Create metadata index entry (email_index table)
       b. Extract attachments to file system
       c. Tag attachments with keywords/stakeholders
       d. Index attachments (attachments table)
    3. PST file moves to evidence/ directory unchanged
    """
```

## Key Capabilities

### 1. Forensic Integrity
- Original PST never modified
- Chain of custody preserved
- Tribunal-ready evidence
- Audit trail of all extractions

### 2. Intelligent Document Indexing
- Attachments auto-tagged with project keywords
- Stakeholder identification
- Construction-specific understanding (variations, delays, RFIs, etc.)
- Contract-aware tagging (JCT, NEC, FIDIC)

### 3. Efficient Storage
- Don't duplicate 1-3 million emails
- Focus on dispute-critical documents
- Attachments average 5-10% of PST size
- Massive cost savings

### 4. Dispute-Ready Organization
- Contracts, correspondence, drawings, reports
- Invoices, payment applications
- Expert reports, site records
- Variations, RFIs, delay notices
- **All instantly searchable and filterable**

## User Workflow

### Setup (wizard.html)
1. Create Project or Case
2. Define keywords (Delay, Variation, Section 278, etc.)
3. List stakeholders (Main Contractor, EA, Client, etc.)

### Upload (pst-upload.html)
1. Drag-drop PST file
2. Automatic background processing begins
3. PST stored in evidence/ directory

### Processing (pst_ingestion_engine.py)
1. Read PST without extracting
2. For each email with attachments:
   - Extract attachment to file system
   - Create email metadata index
   - Tag with keywords/stakeholders
   - Build searchable document index

### Search & Work
1. Search attachments by keyword, stakeholder, date
2. View contracts, invoices, drawings, reports
3. Click to see parent email context (opens PST)
4. Build bundles for tribunal submissions

## The £13 Billion Problem Solved

### Before VeriCase:
- Evidence scattered across systems
- Staff turnover = lost knowledge
- Millions of emails to review manually
- Documents buried in forgotten PSTs
- Days to find critical evidence

### With VeriCase:
- PST uploaded once, attachments extracted automatically
- Keywords defined upfront tag everything
- Critical documents surfaced immediately
- Knowledge persists beyond staff changes
- Hours (not days) to build winning case

## Competitive Advantages

### vs. Relativity / Legacy eDiscovery
- **Purpose-built for construction disputes**, not generic litigation
- **Forensically sound** attachment extraction vs. full email duplication
- **3x efficiency** through cloud-native architecture
- **Construction intelligence** built-in (contract types, industry terms)

### vs. Aconex / Document Management
- **Dispute-first design**, not project management adapted
- **Automatic evidence reconstruction**, not manual filing
- **Sector-aware tagging**, not generic metadata
- **Unified workspace** for all stakeholders

## Technical Benefits

### For Legal Teams:
- Fast evidence discovery
- Reliable chain of custody
- Tribunal-ready presentation
- Lower technology costs

### For Construction Teams:
- Knowledge persists beyond staff changes
- Project history always accessible
- Evidence ready when disputes arise
- No ongoing filing burden

### For Experts:
- Complete evidence set
- Traceable to original source
- Efficient analysis workflow
- Professional presentation

## The VeriCase Difference

**Traditional systems manage documents.**
**VeriCase reconstructs truth from fragmented evidence.**

By keeping PST files intact while extracting and intelligently indexing attachments, VeriCase solves the fundamental evidence crisis: making millions of historical records instantly accessible while maintaining forensic integrity.

The result? Legal teams win more disputes. Construction firms protect their positions. Experts deliver better analysis. All while spending less on technology.

**"Make time your ally, not your enemy."**

