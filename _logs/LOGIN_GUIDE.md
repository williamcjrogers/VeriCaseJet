# VeriCase Login Guide - Complete Instructions
**Date:** November 24, 2025

---

## 🔐 Your Login Credentials

### Admin Accounts Available

**Account #1 (Primary Admin):**
```
Email:    admin@vericase.com
Password: ChangeThis123!
```

**Account #2 (Manager Admin):**
```
Email:    manager@vericase.com
Password: ChangeThis123!
```

---

## 🌐 Where to Login

### Step 1: Open the Login Page
```
http://localhost:8010/ui/login.html
```

### Step 2: Enter Credentials
- **Email:** `admin@vericase.com`
- **Password:** `ChangeThis123!`
- Click **"Login"** or **"Sign In"**

---

## 📍 Important: Development Mode

Your `.env` file has:
```
DEV_NO_AUTH=true
```

This means **authentication may be bypassed** in development. If login doesn't work or you're already logged in automatically, that's why!

---

## 🎯 Complete User Journey

### 1. Login
```
http://localhost:8010/ui/login.html
```
Use: `admin@vericase.com` / `ChangeThis123!`

### 2. Dashboard (After Login)
```
http://localhost:8010/ui/dashboard.html
```
- View your projects/cases
- Create new projects
- Access correspondence

### 3. Create a Project
**From Dashboard:**
- Click "New Project" or similar button
- Fill in project details
- Save → You'll get a project ID (e.g., `363b3fd5-b012-47ef-8401-15ebf6f0ee82`)

### 4. Upload PST Files
```
http://localhost:8010/ui/pst-upload.html?projectId=YOUR_PROJECT_ID
```
Example:
```
http://localhost:8010/ui/pst-upload.html?projectId=363b3fd5-b012-47ef-8401-15ebf6f0ee82
```

### 5. View Correspondence
```
http://localhost:8010/ui/correspondence-enterprise.html?projectId=YOUR_PROJECT_ID
```
Example:
```
http://localhost:8010/ui/correspondence-enterprise.html?projectId=363b3fd5-b012-47ef-8401-15ebf6f0ee82
```

---

## 🔑 Password Reset (If Needed)

If you need to reset the admin password:

**Option 1: SQL Command**
```powershell
cd "C:\Users\William\Documents\Projects\VeriCase Analysis\pst-analysis-engine"
docker-compose exec postgres psql -U vericase -d vericase -c "UPDATE users SET password_hash = crypt('NewPassword123!', gen_salt('bf')) WHERE email = 'admin@vericase.com';"
```

**Option 2: Python Script**
```powershell
docker-compose exec api python init_admin.py
```
This recreates the admin with default password.

---

## 📊 Quick Database Check

**View all users:**
```powershell
cd "C:\Users\William\Documents\Projects\VeriCase Analysis\pst-analysis-engine"
docker-compose exec postgres psql -U vericase -d vericase -c "SELECT email, role, is_active, created_at FROM users;"
```

**Current users found:**
```
email                 | role  | is_active
----------------------+-------+-----------
admin@vericase.com    | ADMIN | true
manager@vericase.com  | ADMIN | true
```

---

## 🚀 Quick Start Workflow

### Complete Flow from Login to Viewing Emails

```bash
# 1. Start services (if not running)
cd "C:\Users\William\Documents\Projects\VeriCase Analysis\pst-analysis-engine"
docker-compose up -d

# 2. Open login page
start chrome http://localhost:8010/ui/login.html

# 3. Login with:
#    Email: admin@vericase.com
#    Password: ChangeThis123!

# 4. Navigate to dashboard
#    http://localhost:8010/ui/dashboard.html

# 5. Create/select a project (note the project ID)

# 6. Upload PST file
#    http://localhost:8010/ui/pst-upload.html?projectId=YOUR_ID

# 7. View correspondence
#    http://localhost:8010/ui/correspondence-enterprise.html?projectId=YOUR_ID
```

---

## 🛠️ Troubleshooting Login

### Issue #1: "Invalid Credentials"
**Check password:**
```powershell
# The default password is: ChangeThis123!
# If changed, reset using:
docker-compose exec postgres psql -U vericase -d vericase -c "UPDATE users SET password_hash = crypt('ChangeThis123!', gen_salt('bf')) WHERE email = 'admin@vericase.com';"
```

### Issue #2: Login Page Won't Load
**Check API is running:**
```powershell
docker-compose ps api
# Should show: Up
```

**Check API logs:**
```powershell
docker-compose logs api --tail=50
```

### Issue #3: Already Logged In?
**Check localStorage:**
```javascript
// In browser console (F12)
console.log('Token:', localStorage.getItem('token'));
console.log('User:', localStorage.getItem('user'));
```

**Clear session and re-login:**
```javascript
localStorage.clear();
sessionStorage.clear();
window.location.href = '/ui/login.html';
```

---

## 🎨 UI Pages Available

| Page | URL | Purpose |
|------|-----|---------|
| **Login** | `http://localhost:8010/ui/login.html` | User authentication |
| **Dashboard** | `http://localhost:8010/ui/dashboard.html` | Main hub, project list |
| **Wizard** | `http://localhost:8010/ui/wizard.html` | Create project/case |
| **PST Upload** | `http://localhost:8010/ui/pst-upload.html?projectId=ID` | Upload evidence |
| **Correspondence** | `http://localhost:8010/ui/correspondence-enterprise.html?projectId=ID` | View emails |
| **Refinement** | `http://localhost:8010/ui/refinement-wizard.html?projectId=ID` | AI filter refinement |
| **Admin Users** | `http://localhost:8010/ui/admin-users.html` | User management |
| **Admin Settings** | `http://localhost:8010/ui/admin-settings.html` | System settings |

---

## 🔒 Security Notes

### Development Mode
```
DEV_NO_AUTH=true
```
- Authentication might be bypassed
- CSRF might be relaxed
- **DO NOT use in production!**

### Production Mode
When deploying to production:
1. Set `DEV_NO_AUTH=false`
2. Use strong JWT_SECRET (64+ characters)
3. Change admin password immediately
4. Enable HTTPS
5. Set proper CORS_ORIGINS

---

## 📝 Summary

**To login RIGHT NOW:**

1. **Open:** http://localhost:8010/ui/login.html
2. **Email:** admin@vericase.com
3. **Password:** ChangeThis123!
4. **Click:** Login

**Then navigate to:**
- Dashboard → View/create projects
- Upload → Add PST files
- Correspondence → View extracted emails

---

## 🎯 Next Steps After Login

1. **Create a project** (if you haven't already)
2. **Note the project ID** (UUID shown in URL/dashboard)
3. **Upload PST file** to that project
4. **Wait for processing** (background worker extracts emails)
5. **View correspondence** (emails appear in AG Grid)
6. **Use AI features** (optional - requires API keys)

---

## 🆘 Still Stuck?

**Check if you can access the API directly:**
```
http://localhost:8010/api/health
```
Should return: `{"status": "ok"}` or similar

**Check auth endpoint:**
```
http://localhost:8010/api/auth/me
```
With DEV_NO_AUTH=true, might auto-authenticate

**Check logs:**
```powershell
docker-compose logs api --tail=100 | Select-String -Pattern "auth|login|401|403"
```

---

## 🎉 You're All Set!

The system is working, credentials are ready, just login and start using VeriCase! 🚀
