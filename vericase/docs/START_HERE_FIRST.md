# 🚀 START HERE - VeriCase Is Ready!

**Legacy/Archived:** This starter referenced the old `pst-analysis-engine` scripts. For current local dev use `vericase/docs/deployment/LOCAL_DEVELOPMENT.md`; for deployment see `.github/DEPLOYMENT.md` (GitHub OIDC + digest). Set admin credentials in `.env` and avoid shared defaults.

## ✅ Everything is configured and ready to run!

### Quick Start (30 seconds):

1. **Open PowerShell in this folder**
2. **Run (current local dev path):**
   ```cmd
   cd vericase
   docker compose up -d --build
   ```
3. **Wait 30 seconds**
4. **Open:** http://localhost:8010
5. **Login:** use `ADMIN_EMAIL` / `ADMIN_PASSWORD` from your `.env` (choose a strong, unique password)

---

## 📚 Full Documentation

Prefer the current guides:

- **[Local Development](vericase/docs/deployment/LOCAL_DEVELOPMENT.md)**
- **[Deployment Guide](.github/DEPLOYMENT.md)**

---

## ⚙️ Requirements

- **Docker Desktop** installed and running
- That's it!

Don't have Docker? Download here: https://www.docker.com/products/docker-desktop/

---

## 🎯 What This Does

VeriCase analyzes Outlook PST files for legal disputes:
- Extract all emails and attachments
- Full-text search
- Email threading and timeline analysis
- Stakeholder tracking
- AI-powered insights

---

**Ready to start? Just run:**
```cmd
cd pst-analysis-engine
START_DOCKER.bat
```

**Then open:** http://localhost:8010

