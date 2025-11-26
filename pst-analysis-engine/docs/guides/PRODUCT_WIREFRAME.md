# VeriCase Analysis - Product Wireframe

## What VeriCase Does

VeriCase is a dispute intelligence platform that helps legal teams and construction professionals manage evidence, analyze correspondence, and build cases from email archives (PST files).

---

## User Journey

### 1. First Time Setup

**Screen: Welcome / Profile Selection**
- User lands on a clean welcome screen
- Three options:
  - **"Set up a Project"** - For construction/development projects
  - **"Set up a Case"** - For legal disputes
  - **"Add Users / Team"** - (Future feature)

**User Action:** Clicks one of the options

---

### 2. Project Setup Flow

**Screen 1: Project Identification**
- Form fields:
  - Project Name* (required)
  - Project Code* (required, must be unique)
  - Start Date (date picker)
  - Completion Date (date picker)
- Navigation: "Continue" button

**Screen 2: Stakeholders & Keywords**
- **Stakeholders Section:**
  - Table with columns: Role | Name/Organisation | Actions
  - Dropdown for Role: Main Contractor, Council, Employers Agent, Project Manager, Client, Building Control, Subcontractor, Custom
  - "Add Stakeholder" button
  - Each row has "Remove" button
  
- **Keywords Section:**
  - Table with columns: Keyword | Variations | Actions
  - "Add Keyword" button
  - Variations field for alternative spellings/terms
  
- **Contract Type:**
  - Dropdown: JCT, NEC, FIDIC, PPC, Custom
  - If Custom selected, text input appears

- **Templates:**
  - "Load Template" button with options:
    - Residential Project (pre-fills common stakeholders/keywords)
    - Infrastructure Project (pre-fills different set)

**Screen 3: Review & Confirm**
- Summary view showing:
  - Project Name, Code, Dates
  - Contract Type
  - List of Stakeholders
  - List of Keywords
- "Create Project" button (final submission)
- "Back" button to edit

**Result:** User is redirected to Dashboard

---

### 3. Case Setup Flow

**Screen 1: Case Identification**
- Form fields:
  - Case Name* (required)
  - Case ID (optional custom ID)
  - Resolution Route (dropdown: Litigation, Adjudication, Arbitration, Mediation, Negotiation)
  - Claimant (text)
  - Defendant (text)
  - Case Status (dropdown)
  - Client (text)

**Screen 2: Legal Team**
- Table: Role | Name | Actions
- Roles: Solicitor, Barrister, Expert Witness, Client, Other
- "Add Team Member" button

**Screen 3: Heads of Claim & Keywords**
- **Heads of Claim Table:**
  - Columns: Claim Head | Status | Actions | Actions
  - "Add Head of Claim" button
  
- **Keywords Table:**
  - Same as Project setup
  - "Add Keyword" button

**Screen 4: Deadlines**
- Table: Task | Description | Deadline Date | Actions
- "Add Deadline" button
- Calendar picker for dates

**Screen 5: Review & Confirm**
- Summary of all case information
- "Create Case" button

**Result:** User is redirected to Dashboard

---

### 4. Dashboard

**Layout:**
- Top bar with VeriCase logo and navigation
- Welcome message: "Welcome to [Project/Case Name]"
- "New Profile" button (returns to wizard)

**Main Content:**

**Quick Actions Section:**
- Card: "Upload Evidence"
  - Icon: Cloud upload
  - Description: "Import PST files, emails, documents, and other evidence sources"
  - Click opens upload modal

- Card: "View Correspondence"
  - Icon: Envelope
  - Description: "Browse emails, attachments, and evidence"
  - Click navigates to correspondence page

**Statistics Widgets:**
- Evidence Summary:
  - Total emails indexed
  - Total attachments extracted
  - Last processed date

- Programme Analysis (if applicable):
  - Baseline vs Actual comparison
  - Critical path items
  - Delay events

- Deadlines (for cases):
  - Upcoming deadlines
  - Overdue items
  - Completed tasks

**Recent Activity:**
- List of recently processed files
- Recent email threads
- Recent attachments

---

### 5. Upload Evidence

**Modal Dialog:**
- Title: "Upload Evidence"
- Large drag-and-drop area:
  - Cloud upload icon
  - Text: "Drag and drop PST files here or click to browse"
  - File input (hidden)
  
**During Upload:**
- Progress bar showing percentage
- Status text: "Uploading... X%"
- Cancel button

**After Upload:**
- Success message with checkmark
- "Processing..." status
- Message: "Your PST file is being processed. You can view the emails in the correspondence section once processing is complete."
- "View Correspondence" button

**Supported Files:**
- .pst (up to 50GB)
- .eml, .msg
- .pdf, .docx, .xlsx, .csv

---

### 6. Correspondence View

**Layout:**
- Top bar with case/project name
- Filter panel on left
- Main email grid (AG-Grid)
- Email detail panel on right (when email selected)

**Email Grid Columns:**
- Date
- From
- To
- Subject
- Attachments (icon + count)
- Keywords (tags)
- Stakeholders (tags)
- Folder (PST folder path)
- Thread indicator

**Filtering:**
- Date range picker
- Keyword filter (multi-select)
- Stakeholder filter (multi-select)
- Folder filter
- Has attachments toggle
- Search box (searches subject, from, to)

**Email Detail Panel (Right Side):**
When user clicks an email row:
- **Email Header:**
  - Subject (large, bold)
  - From, To, CC (formatted)
  - Date/Time
  - Message-ID
  - Thread ID
  
- **Attachments List:**
  - Each attachment shows:
    - Filename
    - File size
    - File type icon
    - Download button
    - Preview button (if supported)
  
- **Metadata:**
  - PST source file
  - Folder path
  - Keywords (clickable tags)
  - Stakeholders (clickable tags)
  
- **Thread View:**
  - Shows related emails in conversation
  - Expandable thread tree
  - Click to jump to email in thread

**Actions:**
- "Link to Programme Activity" button (if programmes uploaded)
- "Download All Attachments" button
- "Export Email" button

---

### 7. Attachment Preview

**Modal Dialog:**
- Shows attachment preview
- For PDFs: Embedded PDF viewer
- For images: Image viewer
- For documents: Download option
- File metadata:
  - Original filename
  - Size
  - Extracted date
  - Source email
  - Hash (for deduplication)

---

### 8. Programme Analysis (Placeholder)

**Widget on Dashboard:**
- Shows baseline vs actual comparison
- Critical path visualization
- Delay events list
- Links to correspondence

**Full Programme View:**
- Upload programme files (Asta XML, PDF)
- Compare baseline vs as-built
- Identify delays
- Link delays to correspondence

---

## Key User Interactions

### Searching & Filtering
- User types in search box → Grid filters in real-time
- User selects keyword → Shows only emails with that keyword
- User selects date range → Shows emails in that period
- User clicks folder → Shows emails from that PST folder

### Email Threading
- Emails with same thread ID are visually grouped
- User clicks thread indicator → Expands to show all emails in thread
- User can navigate between emails in same thread

### Keyword/Stakeholder Tagging
- Tags appear as colored badges on emails
- User clicks tag → Filters to show all emails with that tag
- Tags are automatically applied based on wizard configuration
- User can see which keywords/stakeholders matched

### Attachment Management
- User clicks attachment icon → Shows list of attachments
- User clicks download → File downloads
- User clicks preview → Opens preview modal
- Duplicate attachments (same hash) are marked

---

## Data Flow

### PST Processing Flow:
1. User uploads PST file
2. System saves file to uploads folder
3. Background process starts:
   - Opens PST file using pypff
   - Iterates through folders and messages
   - Extracts email metadata (no body)
   - Extracts attachments to evidence folder
   - Calculates SHA-256 hash for each attachment
   - Checks for duplicates
   - Matches keywords and stakeholders
   - Builds email threads
   - Stores metadata in database
4. User sees processing status update
5. When complete, emails appear in correspondence view

### Email Threading Logic:
- System uses Message-ID, In-Reply-To, References headers
- Groups emails into conversation threads
- Assigns thread_id to related emails
- Displays threads in chronological order

### Keyword Matching:
- System checks email subject, from, to, cc fields
- Checks attachment filenames
- Matches against configured keywords and variations
- Applies tags automatically

### Stakeholder Matching:
- System checks email addresses against stakeholder list
- Matches names and organizations
- Applies tags automatically

---

## Visual Design Elements

### Color Scheme:
- Primary: Purple/Blue (#667eea)
- Success: Green (#48bb78)
- Warning: Orange
- Error: Red
- Background: Light gray (#f7fafc)
- Cards: White with shadow

### Icons:
- Font Awesome icons throughout
- Cloud upload for file operations
- Envelope for emails
- Paperclip for attachments
- Calendar for dates
- Users for stakeholders
- Tags for keywords

### Typography:
- Headers: Bold, larger font
- Body: Standard readable font
- Labels: Medium weight
- Helper text: Smaller, gray

---

## User Experience Principles

1. **Forensic Integrity**
   - PST files never modified
   - Email bodies stay in PST
   - Only metadata and attachments extracted
   - Original file paths preserved

2. **Progressive Disclosure**
   - Wizard breaks complex setup into steps
   - Dashboard shows summary, details on demand
   - Filters can be expanded/collapsed

3. **Immediate Feedback**
   - Progress bars for uploads
   - Status updates for processing
   - Success/error messages
   - Loading indicators

4. **Efficiency**
   - Templates for quick setup
   - Bulk operations where possible
   - Keyboard shortcuts (future)
   - Auto-save drafts

5. **Clarity**
   - Clear labels and instructions
   - Helpful error messages
   - Visual indicators (icons, colors)
   - Consistent navigation

---

## Screen States

### Empty State:
- Dashboard shows: "Upload evidence to get started"
- Correspondence shows: "No emails yet. Upload a PST file to begin."
- Friendly, encouraging messaging

### Loading State:
- Spinner or progress indicator
- "Processing..." or "Loading..." text
- Disabled actions during processing

### Error State:
- Clear error message
- Suggested actions
- Option to retry
- Contact/support information

### Success State:
- Confirmation message
- Next action suggested
- Visual confirmation (checkmark, animation)

---

*This wireframe describes the actual product experience and user interactions, not technical implementation details.*

