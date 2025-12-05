# VeriCase Deployment Status

**Last Updated**: 2025-12-05 06:50 UTC

## 🚀 Latest Deployment

### Current Version
- **Commit**: `7d2efc20` - "Add enhanced PST processing and MinIO improvements"
- **GitHub**: ✅ Pushed to main branch
- **Docker Hub**: ✅ Published
- **Local Environment**: ✅ Running

### What's New in This Version
- ✅ **PST Processing**: Enhanced async PST processing with Celery tasks (271 new lines)
- ✅ **MinIO**: Added public endpoint configuration for direct file access
- ✅ **File Uploads**: Multipart upload improvements (169 new lines in correspondence.py)
- ✅ **Deep Research**: Added session persistence and better loading states
- ✅ **Evidence**: Enhanced project filtering and error handling
- ✅ **Infrastructure**: New Celery task definitions for background processing
- ✅ **UI Fix**: Fixed infinite loop in evidence page (previous version)
- ✅ **Project Management**: Can delete and rename projects (previous version)
- ✅ **Case Management**: Can delete cases (previous version)

## 📦 Docker Images - Docker Hub

**Repository**: wcjrogers/vericase-api

- ✅ `latest` - Live (11GB) - Points to `7d2efc20`
- ✅ `7d2efc20` - Current version with PST/MinIO improvements
- ✅ `8bba4354` - Previous version (infinite loop fix)
- ✅ `66d2d5b7` - Older version (project delete/edit)

**Pull**: `docker pull wcjrogers/vericase-api:latest`

## 🔄 Deployment Status

| Component | GitHub | Docker Hub | Local | EKS |
|-----------|--------|------------|-------|-----|
| API Code | ✅ 7d2efc20 | ✅ 7d2efc20 | ✅ Running | 🔄 Auto-deploy |
| UI Files | ✅ 2.0.5 | ✅ 2.0.5 | ✅ Running | 🔄 Auto-deploy |
