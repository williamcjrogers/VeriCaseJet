# VeriCase Analysis - MVP Features

## Overview
VeriCase Analysis is a dispute intelligence platform that processes PST files and manages correspondence, evidence, and case/project data for legal disputes and construction claims.

---

## Core MVP Features

### 1. Project & Case Setup Wizard
- **Project Creation**
  - Project identification (name, code, dates)
  - Stakeholder management (roles, names, organizations)
  - Keyword configuration for auto-tagging
  - Contract type selection (JCT, NEC, FIDIC, PPC, Custom)
  
- **Case Creation**
  - Case identification (name, ID, resolution route)
  - Legal team management
  - Heads of claim definition
  - Keyword configuration
  - Deadline management

- **Wizard Features**
  - Multi-step guided setup
  - Form validation
  - Draft saving (localStorage)
  - Template loading for quick setup
  - Review & confirm step

### 2. PST File Processing
- **File Upload**
  - Support for files up to 50GB
  - Streaming uploads (chunked processing)
  - Progress tracking
  - Background processing
  
- **PST Ingestion**
  - Forensic integrity (PST files remain immutable)
  - Email metadata extraction (subject, from, to, cc, dates)
  - Attachment extraction with SHA-256 deduplication
  - Email threading (Message-ID, In-Reply-To, References)
  - Folder path preservation
  - No email body extraction (stays in PST)

### 3. Correspondence Management
- **Email Index**
  - Searchable email metadata
  - Thread grouping
  - Folder organization
  - Date-based sorting
  - Keyword/stakeholder tagging

- **Attachment Management**
  - Extracted attachments stored separately
  - Deduplication by hash
  - File type detection
  - Size tracking
  - Download/preview functionality

### 4. Dashboard
- **Overview**
  - Project/case summary
  - Quick statistics
  - Recent activity
  - Quick actions

- **Widgets**
  - Evidence summary
  - Programme analysis (placeholder)
  - Deadline tracking
  - Stakeholder overview

### 5. Evidence Management
- **Upload**
  - Multiple file type support (.pst, .eml, .msg, .pdf, .docx, .xlsx, .csv)
  - Drag & drop interface
  - Upload progress tracking
  - Processing status monitoring

- **Storage**
  - AWS S3 for PST files and attachments (production)
  - Local file storage (development)
  - Database indexing (PostgreSQL RDS)
  - OpenSearch for full-text search
  - Evidence source tracking
  - Processing job management (Celery + Redis)

### 6. Database Schema
- **Core Tables**
  - `projects` - Project information
  - `cases` - Case information
  - `stakeholders` - People and organizations
  - `keywords` - Search terms and variations
  - `heads_of_claim` - Legal claim categories
  - `deadlines` - Task and deadline tracking

- **Evidence Tables**
  - `email_index` - Email metadata (no body)
  - `attachments` - Extracted attachments
  - `evidence_sources` - Uploaded files tracking
  - `processing_jobs` - Background job status

- **Programme Tables**
  - `programmes` - Schedule/programme files
  - `delay_events` - Baseline vs actual analysis

- **User & Collaboration Tables**
  - `users` - User accounts and profiles
  - `user_invitations` - Pending user invitations
  - `project_shares` - Project sharing permissions
  - `case_shares` - Case sharing permissions
  - `comments` - User comments on emails/attachments
  - `audit_logs` - User activity tracking

### 7. API Endpoints
- **Project/Case Management**
  - `POST /api/projects` - Create project
  - `POST /api/cases` - Create case
  - `GET /api/projects/<id>` - Get project details
  - `GET /api/cases/<id>` - Get case details

- **Evidence Management**
  - `POST /api/evidence/upload` - Upload files
  - `GET /api/evidence/status/<job_id>` - Check processing status
  - `GET /api/cases/<id>/evidence` - List emails and attachments
  - `GET /api/cases/<id>/evidence/<evidence_id>/attachment/<attachment_id>` - Download attachment

- **Correspondence**
  - `GET /api/correspondence/<profile_id>` - Get correspondence summary

- **Programme Analysis** (Placeholder)
  - `POST /api/cases/<id>/programmes` - Upload programme
  - `GET /api/cases/<id>/programmes` - List programmes
  - `GET /api/programmes/<id>` - Get programme details
  - `POST /api/programmes/compare` - Compare baseline vs actual

- **User & Collaboration**
  - `POST /api/users` - Create user account
  - `POST /api/auth/login` - User login
  - `POST /api/auth/logout` - User logout
  - `GET /api/users/me` - Get current user
  - `POST /api/invitations` - Send user invitation
  - `POST /api/projects/<id>/share` - Share project with user
  - `POST /api/cases/<id>/share` - Share case with user
  - `GET /api/projects/<id>/members` - List project members
  - `GET /api/cases/<id>/members` - List case members
  - `POST /api/comments` - Add comment to email/attachment
  - `GET /api/comments` - Get comments for item
  - `GET /api/activity` - Get activity feed

### 8. User Interface
- **Wizard Interface**
  - Step-by-step navigation
  - Form validation
  - Auto-save drafts
  - Template support

- **Dashboard**
  - Modern, responsive design
  - Quick action buttons
  - Statistics widgets
  - Navigation to key features

- **Correspondence View**
  - AG-Grid Enterprise integration
  - Advanced filtering
  - Email threading display
  - Attachment preview
  - Programme linking (placeholder)
  
- **Collaboration UI**
  - User profile menu
  - Team member list
  - Share project/case dialog
  - Invite user form
  - Activity feed widget
  - Comments panel
  - Permission management interface

### 9. Technical Features
- **Backend**
  - Flask API server
  - PostgreSQL database (RDS) or SQLite (local dev)
  - Celery background workers
  - Redis task queue
  - AWS S3 for object storage
  - OpenSearch for full-text search
  - Streaming file uploads
  - Error handling and logging

- **Frontend**
  - Vanilla JavaScript
  - AG-Grid Enterprise
  - Responsive CSS
  - LocalStorage for drafts
  - Fetch API for communication

- **PST Processing**
  - pypff library integration
  - Threading algorithm
  - Keyword matching
  - Stakeholder matching
  - Attachment extraction

### 10. AWS Cloud Infrastructure
- **AWS Services Integration**
  - **S3 (Simple Storage Service)**
    - Object storage for PST files and attachments
    - IRSA (IAM Roles for Service Accounts) authentication
    - Bucket-based organization by project/case
    - Lifecycle policies for cost optimization
    - Versioning for forensic integrity
  
  - **OpenSearch (AWS OpenSearch Service)**
    - Full-text search for email metadata and attachments
    - Document indexing for instant search
    - Keyword and stakeholder search capabilities
    - Faceted search and filtering
    - TLS/SSL support for secure connections
  
  - **RDS PostgreSQL**
    - Managed relational database
    - High availability and automated backups
    - Connection pooling
    - Multi-AZ deployment for disaster recovery
  
  - **EKS (Elastic Kubernetes Service)**
    - Container orchestration for scalable deployment
    - Auto-scaling based on workload
    - Service mesh for microservices communication
    - Pod security policies
  
  - **ElastiCache Redis**
    - Celery task queue backend
    - Session storage
    - Caching for improved performance
    - Pub/sub for real-time updates

- **Background Processing**
  - **Celery Workers**
    - Distributed task processing
    - PST file ingestion workers
    - OCR and document parsing workers
    - Asynchronous job execution
    - Task retry and error handling
  
  - **Apache Tika Integration**
    - Document content extraction
    - OCR for scanned documents
    - Metadata extraction
    - Content type detection

- **Infrastructure as Code**
  - Docker containerization
  - Kubernetes manifests
  - Environment variable configuration
  - AWS IAM roles and policies
  - VPC and security group configuration

- **Deployment Architecture**
  - API server (Flask) in EKS pods
  - Celery workers as separate deployments
  - Redis cluster for task queuing
  - S3 buckets for evidence storage
  - OpenSearch cluster for search
  - RDS PostgreSQL for metadata

### 11. User Collaboration
- **User Management**
  - User accounts and authentication
  - Role-based access control (Admin, Manager, Viewer)
  - User profiles (name, email, role)
  - Team/organization management
  
- **Project/Case Sharing**
  - Share projects/cases with team members
  - Permission levels (Owner, Editor, Viewer)
  - Invite users via email
  - User invitation system
  
- **Collaborative Features**
  - Multiple users can work on same project/case
  - Real-time activity feed (who did what, when)
  - Comments/notes on emails and attachments
  - Assignment of tasks/deadlines to team members
  - Shared views and saved filters
  
- **Access Control**
  - Project/case-level permissions
  - Folder-level access (if applicable)
  - Audit trail of user actions
  - User activity logging

---

## MVP Limitations / Future Enhancements

### Not in MVP (Planned for Future)
- AI-powered insights (Gemini, Claude, OpenAI)
- Advanced programme analysis (Asta PowerProject parsing)
- PDF watermarking
- Email body search (currently only metadata)
- Real-time notifications
- Export functionality
- Advanced reporting

### Known Limitations
- Basic programme analysis (XML/PDF parsing not fully implemented)
- No email body content in database (forensic integrity requirement)
- Authentication uses simple token-based system (not OAuth/SSO)
- Local development uses SQLite (production uses RDS PostgreSQL)

---

## MVP Success Criteria

✅ **Core Functionality**
- Users can create projects/cases via wizard
- PST files can be uploaded and processed
- Email metadata is indexed and searchable
- Attachments are extracted and accessible
- Correspondence can be viewed and filtered

✅ **Performance**
- Handles PST files up to 50GB
- Streaming uploads prevent memory issues
- Celery workers handle background processing asynchronously
- OpenSearch provides instant full-text search
- S3 provides scalable object storage
- Auto-scaling EKS pods handle variable workloads

✅ **Data Integrity**
- PST files remain unmodified (forensic integrity)
- Email threading works correctly
- Attachment deduplication prevents duplicates
- Database schema supports all required data

✅ **User Experience**
- Intuitive wizard flow
- Clear error messages
- Progress indicators for long operations
- Responsive interface

✅ **Collaboration**
- Multiple users can access shared projects/cases
- Role-based permissions work correctly
- User invitations are sent and processed
- Activity tracking captures user actions
- Comments system allows team communication

---

## Getting Started

1. **Start the Server**
   ```bash
   START_SERVER.bat
   ```

2. **User Authentication**
   - First-time users: Create account via wizard or invitation
   - Existing users: Login at `http://localhost:8010/ui/wizard.html`
   - Admin users can invite team members

3. **Access the Wizard**
   - Navigate to: `http://localhost:8010/ui/wizard.html`
   - Login or create account if prompted

4. **Create a Project or Case**
   - Follow the wizard steps
   - Fill in required information
   - Submit to create
   - Project/case is automatically shared with creator (Owner role)

5. **Share with Team Members**
   - Go to project/case settings
   - Click "Share" or "Invite User"
   - Enter email address and select permission level
   - User receives invitation email

6. **Upload Evidence**
   - Go to dashboard
   - Click "Upload Evidence"
   - Select PST file (up to 50GB)
   - Wait for processing
   - Activity is logged for team visibility

7. **View Correspondence**
   - Click "View Correspondence" on dashboard
   - Browse emails and attachments
   - Filter and search
   - Add comments for team collaboration
   - View activity feed to see team actions

---

## File Structure

```
pst-analysis-engine/
├── src/
│   ├── api_server.py          # Main Flask API server
│   ├── ingestion/             # PST processing engine
│   ├── database/              # Schema definitions
│   └── ...
├── worker_app/
│   ├── worker.py              # Celery worker tasks
│   └── config.py             # AWS/Infrastructure config
├── ui/
│   ├── wizard.html            # Setup wizard
│   ├── dashboard.html         # Main dashboard
│   ├── correspondence-enterprise.html  # Email viewer
│   └── ...
├── uploads/                   # Uploaded files (local dev)
├── evidence/                  # Extracted attachments (local dev)
├── vericase.db               # SQLite database (local dev)
├── Dockerfile                # Container definition
├── api-policy.json           # AWS IAM policy
└── START_SERVER.bat          # Server startup script
```

## AWS Infrastructure Setup

### Required AWS Services

1. **S3 Buckets**
   - `vericase-pst-files` - Original PST files (immutable)
   - `vericase-attachments` - Extracted attachments
   - Lifecycle policies for cost optimization
   - Versioning enabled for forensic integrity

2. **OpenSearch Domain**
   - Managed OpenSearch cluster
   - TLS/SSL enabled
   - Fine-grained access control
   - Index: `documents` (email metadata and attachments)

3. **RDS PostgreSQL**
   - Multi-AZ deployment
   - Automated backups
   - Connection pooling (PgBouncer)
   - Database: `vericase`

4. **EKS Cluster**
   - Kubernetes cluster for container orchestration
   - Node groups for API servers and workers
   - IRSA (IAM Roles for Service Accounts) for S3/OpenSearch access
   - Auto-scaling based on CPU/memory

5. **ElastiCache Redis**
   - Redis cluster for Celery task queue
   - Session storage
   - Caching layer

### Environment Variables

```bash
# AWS Configuration
USE_AWS_SERVICES=true
AWS_REGION=us-east-1

# S3 Configuration
MINIO_BUCKET=vericase-docs  # S3 bucket name when using AWS

# Database
DATABASE_URL=postgresql+psycopg2://user:pass@rds-endpoint:5432/vericase

# OpenSearch
OPENSEARCH_HOST=search-vericase-xxxxx.us-east-1.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USE_SSL=true
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_INDEX=documents

# Redis/Celery
REDIS_URL=redis://elasticache-endpoint:6379/0
CELERY_QUEUE=ocr

# Tika
TIKA_URL=http://tika-service:9998
```

### Deployment

- **Development**: Local SQLite, local file storage
- **Production**: AWS RDS, S3, OpenSearch, EKS, ElastiCache
- **Hybrid**: Can mix local and AWS services via environment variables

---

## Dependencies

- **Backend**: Flask, Flask-CORS, pypff, PostgreSQL (RDS) or SQLite (dev), Celery, Redis, boto3, opensearch-py, Apache Tika
- **Frontend**: AG-Grid Enterprise, Font Awesome
- **Python**: 3.8+
- **AWS Services**: S3, OpenSearch, RDS PostgreSQL, EKS, ElastiCache Redis
- **Infrastructure**: Docker, Kubernetes, IAM roles (IRSA)

---

*Last Updated: Based on current implementation*
*Version: MVP 1.0*

