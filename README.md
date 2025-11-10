# VeriCase - Intelligent Legal Evidence Analysis Platform

![VeriCase](pst-analysis-engine/assets/AuroraRS.png)

**VeriCase** is an AI-powered legal evidence analysis and case management platform designed for construction disputes, litigation, and project forensics. It provides intelligent PST analysis, email threading, document management, and AI-assisted configuration.

## 🚀 Key Features

### Intelligent Configuration
- **AI-Powered Setup Wizard**: Conversational chatbot guides users through configuration
- **Smart ID Generation**: Automatic validation and formatting of project codes and case numbers
- **Team Building**: Extract team members, roles, and relationships from natural language
- **Refinement Workflow**: Two-tier wizard system (initial + data-driven refinement)

### Evidence Analysis
- **PST Forensic Processing**: Extract and analyze email correspondence from Outlook PST files
- **Email Threading**: Intelligent conversation reconstruction and timeline analysis
- **Attachment Extraction**: OCR and text extraction from email attachments
- **Keyword Matching**: Auto-tag emails based on case-specific keywords and stakeholders

### AI-Powered Intelligence
- **Multi-Model Support**: Claude 3.5 Sonnet, GPT-4, Gemini 1.5, Perplexity, Grok
- **Deep Research Mode**: Comprehensive analysis using multiple AI models in parallel
- **Evidence Assistant**: Natural language queries about your case evidence
- **Chronology Builder**: AI-assisted timeline construction from email chains

### Document Management
- **Secure Storage**: AWS S3 with encryption at rest
- **Full-Text Search**: OpenSearch integration for instant document retrieval
- **Version Control**: Track document changes and maintain history
- **Folder Organization**: Hierarchical document structure with sharing capabilities

### Construction-Specific Features
- **Programme Analysis**: Asta Powerproject XML import and delay analysis
- **Contract Intelligence**: Support for FIDIC, JCT, NEC, and other standard forms
- **Dispute Categorization**: Delay, defects, variations, and quantum claims
- **Stakeholder Mapping**: Automatic identification of parties and roles

## 📋 Prerequisites

- **AWS Account** with:
  - RDS PostgreSQL database
  - ElastiCache Redis cluster
  - OpenSearch domain
  - S3 bucket
  - VPC with proper networking

- **API Keys** for AI services (at least one):
  - OpenAI (GPT-4)
  - Anthropic (Claude)
  - Google (Gemini)
  - xAI (Grok)
  - Perplexity

## 🎯 Quick Start

### Option 1: AWS App Runner (Recommended)

Follow our **5-minute quick start guide**:

📖 **[AWS_QUICK_START.md](pst-analysis-engine/AWS_QUICK_START.md)**

Key steps:
1. Connect GitHub repository
2. Configure `apprunner.yaml`
3. Set environment variables
4. Configure VPC networking (CRITICAL!)
5. Deploy

### Option 2: Deploy Script

Use the automated deployment script:

```bash
chmod +x deploy-apprunner.sh
./deploy-apprunner.sh
```

## 📚 Documentation

### Deployment & Infrastructure
- **[AWS_QUICK_START.md](pst-analysis-engine/AWS_QUICK_START.md)** - 5-minute deployment guide
- **[VPC_NETWORKING_GUIDE.md](pst-analysis-engine/VPC_NETWORKING_GUIDE.md)** - Critical VPC configuration (MUST READ)
- **[AWS_DEPLOYMENT_GUIDE.md](pst-analysis-engine/AWS_DEPLOYMENT_GUIDE.md)** - Comprehensive deployment documentation
- **[AWS_CONFIG_CHECKLIST.md](pst-analysis-engine/AWS_CONFIG_CHECKLIST.md)** - Pre-deployment checklist

### Features & Usage
- **[NEW_FEATURES_SUMMARY.md](pst-analysis-engine/NEW_FEATURES_SUMMARY.md)** - Latest features overview
- **[AI_REFINEMENT_GUIDE.md](pst-analysis-engine/AI_REFINEMENT_GUIDE.md)** - AI wizard usage guide
- **[WEBSITE_INTEGRATION.md](pst-analysis-engine/WEBSITE_INTEGRATION.md)** - Integrate with your website

### Security & Maintenance
- **[SECURITY_IMPROVEMENTS.md](pst-analysis-engine/SECURITY_IMPROVEMENTS.md)** - Security measures implemented
- **[BRANDING_UPDATES.md](pst-analysis-engine/BRANDING_UPDATES.md)** - UI/UX customization guide

## 🏗️ Architecture

```
VeriCase Platform
├── Frontend (HTML/CSS/JS)
│   ├── Intelligent Configuration Wizard
│   ├── Dashboard & Case Management
│   ├── Correspondence Viewer
│   └── Document Browser
│
├── Backend API (FastAPI/Python)
│   ├── Authentication & Authorization
│   ├── AI Orchestration (Multi-Model)
│   ├── PST Processing Engine
│   ├── Document Management
│   └── Search & Analytics
│
└── Infrastructure (AWS)
    ├── App Runner (Application hosting)
    ├── RDS PostgreSQL (Primary database)
    ├── ElastiCache Redis (Caching & sessions)
    ├── OpenSearch (Full-text search)
    ├── S3 (Document storage)
    └── VPC (Secure networking)
```

## 🔐 Security

VeriCase implements enterprise-grade security:

- **Authentication**: JWT-based with secure session management
- **Authorization**: Role-based access control (Admin, Manager, User, Viewer)
- **Data Encryption**: At rest (S3, RDS) and in transit (TLS)
- **SQL Injection Prevention**: Parameterized queries throughout
- **XSS Protection**: Content Security Policy and output encoding
- **Log Sanitization**: Prevents log injection attacks
- **HTTPS Enforcement**: Strict Transport Security in production

See [SECURITY_IMPROVEMENTS.md](pst-analysis-engine/SECURITY_IMPROVEMENTS.md) for complete details.

## 🌐 VPC Networking (Critical Setup)

**App Runner MUST be configured with VPC connector to access:**
- PostgreSQL (RDS) - Port 5432
- Redis (ElastiCache) - Port 6379
- OpenSearch - Port 443

**VPC Configuration:**
```
VPC ID: vpc-0880b8ccf488f527e
Region: eu-west-2 (London)
Subnets: 2+ in different AZs
Security Groups: Bidirectional rules required
```

📖 **[VPC_NETWORKING_GUIDE.md](pst-analysis-engine/VPC_NETWORKING_GUIDE.md)** - MUST READ before deployment

## 🛠️ Technology Stack

### Backend
- **Python 3.11** - Core application language
- **FastAPI** - Modern async web framework
- **SQLAlchemy** - Database ORM
- **Alembic** - Database migrations
- **Celery** - Background task processing
- **Anthropic/OpenAI/Google SDKs** - AI integrations

### Frontend
- **Vanilla JavaScript** - No framework dependencies
- **Modern CSS** - Responsive design with VeriCase branding
- **Font Awesome** - Icon library

### Infrastructure
- **PostgreSQL 14+** - Primary database
- **Redis 7+** - Caching and session store
- **OpenSearch 2.x** - Full-text search engine
- **AWS S3** - Object storage
- **Apache Tika** - Document text extraction

## 📊 Database Schema

Key tables:
- `users` - User accounts and authentication
- `companies` - Organization management
- `cases` - Legal cases with dispute details
- `projects` - Construction projects
- `email_messages` - Extracted PST email data
- `documents` - Document metadata and versions
- `stakeholders` - Case parties and contact info
- `keywords` - Case-specific search terms

## 🧪 Environment Variables

See [apprunner.yaml](apprunner.yaml) for complete configuration.

**Essential variables:**
```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# AWS
AWS_REGION=eu-west-2
AWS_STORAGE_BUCKET_NAME=vericase-data

# Redis
REDIS_URL=redis://host:6379/0

# OpenSearch
OPENSEARCH_HOST=vpc-xxx.region.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USER=Admin
OPENSEARCH_PASSWORD=xxx

# AI APIs
OPENAI_API_KEY=sk-proj-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
GEMINI_API_KEY=xxx
```

## 📦 Project Structure

```
VeriCase-Analysis/
├── apprunner.yaml              # App Runner configuration
├── deploy-apprunner.sh         # Deployment automation script
├── README.md                   # This file
│
└── pst-analysis-engine/        # Main application directory
    ├── api/                    # Backend API
    │   ├── app/                # FastAPI application
    │   │   ├── main.py         # API entry point
    │   │   ├── models.py       # Database models
    │   │   ├── correspondence.py   # Email/PST endpoints
    │   │   ├── intelligent_config.py  # AI configuration wizard
    │   │   ├── ai_chat.py      # AI evidence assistant
    │   │   └── ...
    │   ├── alembic/            # Database migrations
    │   └── requirements.txt    # Python dependencies
    │
    ├── ui/                     # Frontend application
    │   ├── dashboard.html      # Main dashboard
    │   ├── intelligent-wizard.html  # AI setup wizard
    │   ├── correspondence-enterprise.html  # Email viewer
    │   ├── brand-styles.css    # VeriCase branding
    │   └── ...
    │
    ├── worker_app/             # Celery background workers
    ├── assets/                 # Images and branding
    ├── migrations/             # SQL migration scripts
    └── k8s/                    # Kubernetes configs (optional)
```

## 🎨 Branding

VeriCase uses Aurora-inspired branding:
- **Primary Color**: Teal (#17B5A3) - Trust and clarity
- **Secondary Color**: Navy (#1E3A5F) - Professional authority
- **Typography**: Inter, SF Pro Display - Modern and readable
- **Logo**: Aurora RS branded assets in `/assets`

See [BRANDING_UPDATES.md](pst-analysis-engine/BRANDING_UPDATES.md) for customization guide.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

Copyright © 2024 VeriCase. All rights reserved.

## 🆘 Support

**Deployment Issues:**
- Review logs in AWS App Runner console
- Check VPC_NETWORKING_GUIDE.md for connection issues
- Verify all security group rules are configured

**Application Issues:**
- Check CloudWatch logs
- Verify database migrations ran successfully
- Confirm all environment variables are set

**Questions:**
Contact: admin@veri-case.com

---

**Ready to deploy?** Start with [AWS_QUICK_START.md](pst-analysis-engine/AWS_QUICK_START.md) 🚀

