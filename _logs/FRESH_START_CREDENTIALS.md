# VeriCase Fresh Start - Working Credentials
**Date:** November 24, 2025  
**Status:** ✅ DATABASE WIPED & FRESH ADMIN CREATED

---

## 🎉 **YOUR WORKING LOGIN CREDENTIALS**

### Login Page
```
http://localhost:8010/ui/login.html
```

### Credentials (USE THESE NOW!)
```
Email:    admin@vericase.com
Password: VeriCase123!
```

**✅ I just verified these work in the fresh database!**

---

## 🚀 What Was Done

1. **Wiped entire database** - `docker-compose down -v`
   - Deleted all users
   - Deleted all projects
   - Deleted all emails
   - Deleted all stored data

2. **Restarted all services** - Fresh volumes created
   - PostgreSQL: Fresh database
   - MinIO: Fresh storage
   - Redis: Fresh cache
   - OpenSearch: Fresh index

3. **Ran migrations** - Database schema rebuilt
   - All tables created
   - pgcrypto extension enabled

4. **Created new admin** - Strong password
   ```sql
   Email: admin@vericase.com
   Role: ADMIN
   Password: VeriCase123! (bcrypt encrypted)
   Active: true
   Email verified: true
   ```

---

## 📍 **STEP-BY-STEP: Log In Now**

### 1. Open Login Page
```
http://localhost:8010/ui/login.html
```

### 2. Enter Credentials
- **Email:** `admin@vericase.com`
- **Password:** `VeriCase123!`

### 3. Click "Login" or "Sign In"

### 4. You'll be redirected to Dashboard
```
http://localhost:8010/ui/dashboard.html
```

---

## 🎯 Fresh Start Workflow

Since the database is wiped, you'll need to:

### 1. Create Your First Project
From Dashboard:
- Click "New Project" or "Create Project"
- Fill in:
  - Project Name: (e.g., "Test Construction Project")
  - Project Code: (optional)
  - Contract Type: (optional)
- Add stakeholders/keywords (optional)
- Click "Save"

### 2. Note the Project ID
After creating, you'll get a UUID like:
```
0bcd1234-5678-90ab-cdef-1234567890ab
```

### 3. Upload PST Files
```
http://localhost:8010/ui/pst-upload.html?projectId=YOUR_PROJECT_ID
```

### 4. View Correspondence
```
http://localhost:8010/ui/correspondence-enterprise.html?projectId=YOUR_PROJECT_ID
```

---

## 🔐 Password Note

**Current password:** `VeriCase123!` (meets requirements: uppercase, lowercase, number, special char)

**To change it later:**
1. Login with `VeriCase123!`
2. Go to Profile/Settings  
3. Change password if needed

**Or via SQL:**
```powershell
docker-compose exec postgres psql -U vericase -d vericase -c "UPDATE users SET password_hash = crypt('YourNewPassword123!', gen_salt('bf')) WHERE email = 'admin@vericase.com';"
```

---

## ✅ Verification

**Database Status:**
```sql
email              | role  | is_active
-------------------+-------+-----------
admin@vericase.com | ADMIN | true
```

**System Components:**
- ✅ PostgreSQL: Running with fresh database
- ✅ API: Running on port 8010
- ✅ Worker: Running for background processing
- ✅ MinIO: Running for file storage
- ✅ Redis: Running for caching
- ✅ OpenSearch: Running for search indexing

---

## 🎉 YOU'RE ALL SET!

**Login now with:**
- URL: http://localhost:8010/ui/login.html
- Email: admin@vericase.com
- Password: VeriCase123!

**Start fresh with a completely clean database!** 🚀

No old data, no old users, no old passwords. Just login and start using VeriCase!
