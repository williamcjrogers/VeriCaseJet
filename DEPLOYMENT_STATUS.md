# VeriCase Deployment Status

**Last Updated**: 2025-12-05 07:15 UTC

## 🚀 Latest Deployment

### Current Version
- **Commit**: `951a89d4` - "Fix deep research session state and MinIO presigned URLs"
- **GitHub**: ✅ Pushed to main branch
- **Docker Hub**: ✅ Published
- **Local Environment**: ✅ Running

### What's New in This Version
- ✅ **Deep Research State**: Fixed cross-worker desynchronization in session approval
- ✅ **MinIO URLs**: Fixed presigned URLs to use public endpoint (localhost:9000) for browser access
- ✅ **Error Handling**: Improved error messages for plan approval and modification failures
- ✅ **Debugging**: Enhanced logging for public endpoint configuration
- ✅ **PST Processing**: Enhanced async PST processing with Celery tasks (previous version)
- ✅ **MinIO**: Added public endpoint configuration for direct file access (previous version)
- ✅ **File Uploads**: Multipart upload improvements (previous version)
- ✅ **UI Fix**: Fixed infinite loop in evidence page (previous version)
- ✅ **Project Management**: Can delete and rename projects (previous version)
- ✅ **Case Management**: Can delete cases (previous version)

## 📦 Docker Images - Docker Hub

**Repository**: wcjrogers/vericase-api

- ✅ `latest` - Live (11GB) - Points to `951a89d4`
- ✅ `951a89d4` - Current version with deep research fixes
- ✅ `7d2efc20` - Previous version (PST/MinIO improvements)
- ✅ `8bba4354` - Older version (infinite loop fix)
- ✅ `66d2d5b7` - Older version (project delete/edit)

**Pull**: `docker pull wcjrogers/vericase-api:latest`

## 🔄 Deployment Status

| Component | GitHub | Docker Hub | Local | EKS |
|-----------|--------|------------|-------|-----|
| API Code | ✅ 951a89d4 | ✅ 951a89d4 | ✅ Running | 🔄 Auto-deploy |
| UI Files | ✅ 2.0.5 | ✅ 2.0.5 | ✅ Running | 🔄 Auto-deploy |
