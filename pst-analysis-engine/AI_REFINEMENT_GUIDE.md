# VeriCase AI Refinement Wizard - User Guide

## Overview
The AI Refinement Wizard uses artificial intelligence to automatically discover patterns, parties, and topics in your uploaded evidence (PST files, emails, documents). It helps you quickly filter and organize large volumes of correspondence.

## Features

### 1. **Automatic Discovery**
The wizard analyzes your evidence and discovers:
- **Other Projects**: References to other projects mentioned in emails
- **Parties/Organizations**: Companies and organizations involved
- **Key People**: Important individuals in the correspondence
- **Topics**: Main themes and subjects discussed

### 2. **Smart Filtering**
You can refine your evidence by:
- Excluding irrelevant projects
- Confirming which organizations are relevant
- Selecting key people to focus on
- Choosing important topics

### 3. **AI-Powered Analysis**
The system uses pattern recognition to:
- Identify organization roles (Council, Architect, Engineer, etc.)
- Extract email domains and infer company names
- Detect topics from subject lines and content
- Group related correspondence

## How to Use

### Step 1: Access the Wizard
1. Log in to VeriCase
2. Go to your Dashboard
3. Click the **"AI Refinement"** card (purple gradient with sparkles icon)

### Step 2: Discovery Phase
The wizard automatically:
- Scans all uploaded PST files and emails
- Identifies patterns and entities
- Presents findings for your review

### Step 3: Review & Refine
Go through each discovery category:

**Exclude Projects**
- Review other projects found in emails
- Select any you want to exclude from analysis

**Confirm Parties**
- Review discovered organizations
- Confirm their roles (Council, Architect, Contractor, etc.)
- Exclude irrelevant parties

**Select People**
- Review key individuals identified
- Select those relevant to your case

**Choose Topics**
- Review discovered topics
- Select relevant themes to focus on

### Step 4: Apply Refinements
- Click "Apply Refinements" to filter your evidence
- The system updates your correspondence view
- Only relevant emails matching your criteria will be shown

## API Endpoints

The refinement wizard uses these endpoints:

### GET `/api/refinement/{project_id}/discover`
Analyzes evidence and returns discovered entities:
```json
{
  "projects": [...],
  "parties": [...],
  "people": [...],
  "topics": [...]
}
```

### POST `/api/refinement/{project_id}/apply-refinement`
Applies selected filters:
```json
{
  "exclude_projects": ["Project A"],
  "confirmed_parties": {"domain.com": "Architect"},
  "include_people": ["john@example.com"],
  "include_topics": ["Planning Permission"]
}
```

### GET `/api/refinement/{project_id}/active-filters`
Returns currently active filters

### DELETE `/api/refinement/{project_id}/clear-filters`
Removes all filters and shows all evidence

## Benefits

✅ **Save Time**: Automatically discover patterns instead of manual review
✅ **Focus**: Filter out irrelevant correspondence
✅ **Organize**: Categorize parties and topics systematically
✅ **Insight**: Understand the full scope of your evidence quickly

## Tips

1. **Upload First**: Make sure you've uploaded PST files before using refinement
2. **Review Carefully**: AI suggestions are starting points - verify them
3. **Iterate**: You can clear filters and refine multiple times
4. **Combine**: Use refinement with keyword search for best results

## Technical Details

- Built with FastAPI backend
- Uses SQLAlchemy for database queries
- Analyzes email headers, subjects, and content
- Pattern matching for organization detection
- Domain-based role inference
- Topic extraction from subject lines

## Access
- **Dashboard Button**: Purple "AI Refinement" card
- **Direct URL**: `/ui/refinement-wizard.html?projectId={your_project_id}`
- **API Docs**: http://localhost:8010/docs#/refinement

## Status
✅ Fully functional and integrated
✅ Connected to backend API
✅ Accessible from dashboard
✅ Ready to use!

