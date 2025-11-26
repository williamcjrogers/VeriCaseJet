# VeriCase Quick Start Guide

## Prerequisites

1. Python 3.8+ with virtual environment activated
2. All dependencies installed: `pip install -r requirements-api.txt`
3. pypff library installed (for PST processing)

## Running VeriCase

1. **Start the API Server**
   ```
   START_SERVER.bat
   ```
   Or manually:
   ```
   python src/api_server.py
   ```

2. **Open the Wizard**
   Navigate to: http://localhost:8010/ui/wizard.html

3. **Create a Project or Case**
   - Choose either "Set up a Project" or "Set up a Case"
   - Fill out all tabs in the wizard
   - Submit to create your profile

4. **Upload Evidence (PST Files)**
   - On the dashboard, click "Upload Evidence"
   - Select a PST file to upload
   - Wait for processing to complete

5. **View Correspondence**
   - Click "View Correspondence" on the dashboard
   - Browse emails, attachments, and evidence

## Key Features

- **PST Processing**: Extracts attachments and indexes emails without modifying the original PST
- **Keyword Matching**: Automatically tags emails based on configured keywords
- **Stakeholder Tracking**: Links emails to relevant stakeholders
- **Email Threading**: Groups related emails into conversations
- **Attachment Deduplication**: Prevents duplicate storage of identical files

## API Endpoints

- `POST /api/projects` - Create a new project
- `POST /api/cases` - Create a new case
- `POST /api/evidence/upload` - Upload PST files
- `GET /api/evidence/status/{job_id}` - Check processing status
- `GET /api/cases/{case_id}/evidence` - List emails and attachments

## Troubleshooting

1. **Import Errors**: Ensure PYTHONPATH includes the src directory
2. **PST Processing Fails**: Check pypff is installed correctly
3. **UI Not Loading**: Verify Flask server is running on port 8010
4. **Database Errors**: Check vericase.db exists and has proper schema

## Testing

Run the complete workflow test:
```
TEST_WORKFLOW.bat
```

This will guide you through the entire process from setup to viewing emails.
