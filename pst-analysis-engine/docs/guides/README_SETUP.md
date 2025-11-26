# VeriCase Quick Start Guide

## What's Been Implemented

### 1. Enhanced Wizard ✅
- **Templates**: Quick-load construction and infrastructure project templates
- **CSV Import**: Bulk import stakeholders from CSV files
- **Smart Defaults**: Intelligent suggestions based on contract type and resolution route
- **Dashboard Redirect**: Wizard now sends users to dispute intelligence dashboard

### 2. Dispute Intelligence Dashboard ✅
- **Command Center**: Central hub for case/project management
- **Evidence Status**: Real-time tracking of uploaded and processed evidence
- **Quick Actions**: Upload evidence, view correspondence, manage stakeholders
- **Activity Feed**: Track all recent actions and changes
- **Tailored Views**: Different widgets for Projects vs Cases
- **Heads of Claim Pipeline**: Visual tracking of claim development (Cases)
- **Deadline Management**: Alerts for upcoming deadlines (Cases)

### 3. PST Ingestion Pipeline ✅
**VeriCase's Forensically Sound Approach:**
- **PST Files Remain Intact**: Original PST files stay as immutable forensic evidence
- **Attachment Extraction**: ONLY attachments (the actual evidence) are extracted to file system
- **Metadata Indexing**: Create searchable index pointing back to PST without duplicating email content
- **Intelligent Tagging**: Attachments automatically tagged with keywords and stakeholders
- **Document Focus**: Contracts, invoices, drawings, reports become searchable documents
- **Chain of Custody**: Always traceable back to original PST location

**Why This Approach?**
- Maintains forensic integrity of original evidence
- Attachments are the real dispute-critical documents
- Saves massive storage (don't duplicate 1-3 million emails)
- PST remains available for tribunal presentation
- Focus on actionable evidence, not email clutter

## Installation & Setup

### 1. Install Python Dependencies
```bash
cd pst-analysis-engine
pip install -r requirements.txt
pip install -r requirements-api.txt
```

### 2. Initialize Database
The database will be created automatically on first run with the schema in `src/database/schema.sql`

### 3. Start the API Server
**Windows:**
```bash
START_SERVER.bat
```

**Mac/Linux:**
```bash
python src/api_server.py
```

The server will start on **http://localhost:8010**

### 4. Access the Application
Open your browser to:
- **Wizard**: `http://localhost:8010/../wizard.html`
- **Dashboard**: Created automatically after wizard completion

## User Workflow

### For New Projects/Cases:

1. **Setup** (`wizard.html`)
   - Choose Project or Case
   - Fill in identification details
   - Add stakeholders (or use templates/CSV import)
   - Define keywords for evidence tagging
   - Review and create

2. **Dashboard** (`ui/dashboard.html`)
   - View project/case overview
   - See quick stats and alerts
   - Access quick actions

3. **Upload Evidence** (`ui/pst-upload.html`)
   - Drag and drop PST files
   - Upload emails and documents
   - Processing starts automatically

4. **View Correspondence** 
   - Access processed emails
   - Search by keywords
   - Filter by stakeholders
   - View attachments

## Technical Architecture

### Frontend
- `wizard.html` + `wizard-logic.js` - Enhanced setup wizard
- `ui/dashboard.html` - Dispute intelligence dashboard
- `ui/pst-upload.html` - Evidence upload interface

### Backend API (`src/api_server.py`)
- `/api/projects` - Create/retrieve projects
- `/api/cases` - Create/retrieve cases
- `/api/evidence/upload` - Upload PST and other files
- `/api/evidence/status/{job_id}` - Check processing status
- `/api/correspondence/{profile_id}` - Get correspondence data

### PST Ingestion Engine (`src/ingestion/pst_ingestion_engine.py`)
**Forensically Sound Evidence Extraction:**
1. **PST Remains Intact** - Original file never modified
2. **Extract Attachments Only** - Contracts, drawings, invoices, reports saved to `evidence/{profile_id}/attachments/`
3. **Create Email Index** - Lightweight metadata (subject, from, to, date) pointing to PST location
4. **Tag Attachments** - Auto-tag with keywords/stakeholders from wizard config
5. **Build Search Index** - Attachments become searchable documents
6. **Preserve Chain of Custody** - Every attachment traceable to PST source

**Result:** Users search and work with attachments (the real evidence), while PST remains as authoritative forensic source.

### Database (SQLite)
- **projects** - Project metadata
- **cases** - Case metadata  
- **stakeholders** - Project/case parties
- **keywords** - Search terms and variations
- **heads_of_claim** - Claim tracking (cases)
- **deadlines** - Deadline management (cases)
- **email_index** - Metadata index pointing to PST (NO email bodies)
- **attachments** - THE MAIN EVIDENCE TABLE (extracted documents)
- **evidence_sources** - Track uploaded PST files
- **processing_jobs** - Background job status

**Critical Architecture Note:**
- `email_index` = lightweight pointers to PST emails (subject, from, to, date, PST location)
- `attachments` = extracted physical files (contracts, invoices, reports, drawings)
- PST files stay intact in `evidence/` directory as immutable forensic sources

## Port Configuration

The system runs on **port 8010** as specified.

## Next Steps

The foundation is complete! Priority additions:
1. Actual correspondence view/grid
2. Enhanced search and filtering
3. Timeline visualization
4. Document bundling for submissions
5. Team collaboration features

## File Structure
```
pst-analysis-engine/
├── wizard.html                      # Enhanced setup wizard
├── wizard-logic.js                  # Wizard logic with templates
├── ui/
│   ├── dashboard.html              # Dispute intelligence dashboard
│   └── pst-upload.html             # Evidence upload interface
├── src/
│   ├── api_server.py               # Flask API on port 8010
│   ├── ingestion/
│   │   └── pst_ingestion_engine.py # PST processing engine
│   ├── database/
│   │   └── schema.sql              # Database schema
│   └── [existing modules]
└── START_SERVER.bat                # Quick start script
```

