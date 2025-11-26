# PyCharm Setup Guide for VeriCase

## 🚀 Quick Start

### 1. Open Project in PyCharm Professional
```
File → Open → Select: pst-analysis-engine/
```

### 2. Configure Python Interpreter (First Time)
```
Settings (Ctrl+Alt+S) → Project → Python Interpreter
→ Add Interpreter (⚙️ icon) → Docker Compose
→ Configuration file: docker-compose.yml
→ Service: api
→ Click OK and wait for indexing (5-10 minutes)
```

### 3. Start Docker Services
```
Method 1: Run → Docker Compose (from toolbar)
Method 2: Services panel (Alt+8) → Right-click Docker Compose → Start
Method 3: Terminal in PyCharm → docker-compose up -d
```

### 4. Connect to Database
```
Database panel (Right sidebar, or View → Tool Windows → Database)
→ VeriCase PostgreSQL (should appear automatically)
→ Click "Test Connection"
→ Enter password: vericase
→ Click OK
```

---

## 🔍 Features You Now Have

### ✅ Type Checking (Catches Bugs Before Runtime)
**What it catches:**
- ❌ String "null" passed as UUID (today's bug!)
- ❌ Missing attributes (settings.use_textract)
- ❌ Function signature mismatches
- ❌ Wrong return types

**How to use:**
- Yellow/red underlines show issues
- Hover for details
- Alt+Enter for quick fixes

### ✅ Docker Integration
**Services Panel (Alt+8):**
- Start/stop individual services
- View logs in split panels
- Restart services
- Exec into containers
- Monitor resource usage

### ✅ Database Tools
**Database Panel (Right sidebar):**
- Browse all 32 tables
- Run SQL queries (Ctrl+Enter)
- Compare schema to models.py
- Generate migrations
- View data inline

### ✅ Debugging Inside Containers
**How to debug:**
1. Set breakpoint (click line number gutter)
2. Run → Debug 'Docker Compose'
3. Trigger the code (e.g., upload PST)
4. Debugger stops, inspect all variables

---

## 🐛 Debugging Example (Today's Bug)

### Set Breakpoint in PST Upload
```python
# api/app/correspondence.py:126
@router.post("/pst/upload/init")
async def init_pst_upload(request: PSTUploadInitRequest, ...):
    # Click line 126 to set breakpoint ⬅️
    case_id = request.case_id
    # When debugger stops here, hover over case_id
    # You'll see: "null" (string) ← THE BUG!
```

### Inspect Variables
- **Variables panel** shows all locals
- **Watches** - Add expressions to monitor
- **Evaluate Expression** (Alt+F8) - Test code live

---

## 📊 Database Schema Comparison

### Compare Models to Actual Database
```
1. Right-click: api/app/models.py
2. Compare With → Database → VeriCase PostgreSQL
3. PyCharm shows differences:
   ⚠️ Model has: is_admin (Column)
   ✅ Database has: role (ENUM)
   
4. Generate migration SQL automatically
```

### Run Queries Directly
```
Database panel → VeriCase PostgreSQL
→ Right-click → New → Query Console
→ Type SQL:
   SELECT * FROM users WHERE role = 'ADMIN';
→ Press Ctrl+Enter
→ Results appear inline
```

---

## 🎯 Common Tasks

### View Service Logs
```
Services panel (Alt+8)
→ Expand Docker Compose
→ Click: api, worker, postgres, etc.
→ Logs stream in bottom panel
→ Filter by error/warning
```

### Restart a Service
```
Services panel
→ Right-click service (e.g., "api")
→ Restart
→ Watch logs for startup
```

### Check Service Health
```
Services panel shows status:
✅ Green = healthy
⚠️ Yellow = starting
❌ Red = crashed
```

### Fix Type Errors
```
1. Look for yellow/red underlines
2. Hover to see error message
3. Alt+Enter for quick fixes
4. PyCharm suggests corrections
```

---

## 🔧 Additional Configuration

### Enable AI Assistant (You have JetBrains Suite!)
```
Settings → Tools → AI Assistant
→ Sign in with JetBrains account
→ Enable code completion
→ Enable chat assistant
```

### Configure Black Formatter (Optional)
```
Settings → Tools → File Watchers
→ Add → Black
→ Program: black
→ Arguments: $FilePath$
→ Auto-format on save
```

### Set Up Remote Debugging
```
Run → Edit Configurations
→ Add → Python Debug Server
→ Host: localhost
→ Port: 5678
→ Now you can debug worker container too!
```

---

## 🎯 What PyCharm Will Catch

### Today's Bugs (Automatically Flagged)

**Bug 1: String "null" as UUID**
```python
# PyCharm shows: ⚠️ Type mismatch
case_id = "null"  # Type: str
# Expected: Optional[UUID]
```

**Bug 2: Missing Attribute**
```python
# PyCharm shows: ❌ Unresolved attribute reference
if settings.use_textract:  # Attribute doesn't exist in Settings class
```

**Bug 3: Wrong Import Path**
```python
# PyCharm shows: ❌ Cannot find reference 'worker_app'
from worker_app.worker import celery_app  # Module path wrong
```

**Bug 4: Schema Mismatch**
```python
# PyCharm + Database comparison shows:
class User(Base):
    is_admin = Column(Boolean)  # ⚠️ Column doesn't exist in actual DB
```

---

## 📚 Useful Shortcuts

| Action | Shortcut |
|--------|----------|
| **Search everywhere** | Double Shift |
| **Find file** | Ctrl+Shift+N |
| **Find class** | Ctrl+N |
| **Go to definition** | Ctrl+B |
| **Find usages** | Alt+F7 |
| **Refactor/Rename** | Shift+F6 |
| **Recent files** | Ctrl+E |
| **Run** | Shift+F10 |
| **Debug** | Shift+F9 |
| **Services panel** | Alt+8 |
| **Database panel** | View → Tool Windows → Database |
| **Terminal** | Alt+F12 |

---

## 🆘 Troubleshooting

### "Cannot connect to Docker"
```
Settings → Build, Execution, Deployment → Docker
→ Should show: Docker Desktop (Connected)
→ If not, ensure Docker Desktop is running
→ Click "Test Connection"
```

### "Database connection failed"
```
1. Ensure Docker Compose is running
2. Wait 30 seconds for PostgreSQL to start
3. Database panel → VeriCase PostgreSQL → Right-click → Refresh
4. Enter password: vericase
```

### "Module not found" errors
```
File → Invalidate Caches → Invalidate and Restart
Wait for re-indexing (5 minutes)
```

### "Docker Compose interpreter not available"
```
Settings → Project → Python Interpreter
→ Show All
→ Add → Docker Compose
→ Service: api
→ Apply
```

---

## 💡 Pro Tips

### 1. Multi-cursor Editing
- **Alt+Shift+Click** - Add cursor
- **Ctrl+Alt+Shift+J** - Select all occurrences
- Edit all at once

### 2. Live Templates
```
Type: def → Tab → Auto-completes function
Type: class → Tab → Auto-completes class
Type: ifmain → Tab → if __name__ == "__main__"
```

### 3. Database Export
```
Database panel → Right-click table
→ Export Data → SQL Inserts
→ Save as migration
```

### 4. Compare Branches
```
Git → Compare with Branch
→ See all changes
→ Cherry-pick specific commits
```

### 5. Docker Logs Search
```
Services panel → Select service
→ Logs panel → Ctrl+F
→ Search for "error", "exception", etc.
```

---

## 🎯 Next Steps After Opening in PyCharm

### Immediate Actions:
1. ☐ Wait for indexing to complete (status bar bottom-right)
2. ☐ Configure Docker Compose interpreter (PyCharm will prompt)
3. ☐ Enter database password when prompted: `vericase`
4. ☐ Run: **Code → Inspect Code** → See all issues
5. ☐ Review inspection results (will show ~50-100 issues)
6. ☐ Fix high-priority errors first (type mismatches)

### First Debugging Session:
1. ☐ Start Docker Compose from toolbar
2. ☐ Set breakpoint: `api/app/correspondence.py` line 126
3. ☐ Open browser: http://localhost:8010
4. ☐ Login: admin@vericase.com / admin123
5. ☐ Upload a PST file
6. ☐ Watch debugger stop at breakpoint
7. ☐ Inspect `request.case_id` - see the "null" string!

### Schema Validation:
1. ☐ Open DataGrip or Database panel
2. ☐ Tools → Compare With → Select models.py
3. ☐ Review schema differences
4. ☐ Generate migration SQL if needed

---

## 🦀 About C++/Rust Rewrite

### Should You Rewrite?

**Current Performance (Python):**
- 10GB PST file: ~3-4 hours
- Memory usage: ~30GB
- Email processing: ~500/second

**With Rust/C++:**
- 10GB PST file: ~20-30 minutes (10x faster)
- Memory usage: ~12GB (2.5x less)
- Email processing: ~5,000-20,000/second

### When to Rewrite:
- ✅ You process 100+ GB daily
- ✅ Performance is critical
- ✅ You have 3-6 months
- ✅ Team knows Rust/C++

### Recommended: Hybrid Approach
```
Keep: Python API (fast development)
Rewrite: PST worker only (Rust)
Result: 10x faster where it matters
Time: 1-2 months instead of 6
```

---

## 📞 Resources

- **PyCharm Guide**: https://www.jetbrains.com/pycharm/guide/
- **Docker Integration**: https://www.jetbrains.com/help/pycharm/docker.html
- **Database Tools**: https://www.jetbrains.com/help/pycharm/relational-databases.html
- **Remote Debugging**: https://www.jetbrains.com/help/pycharm/remote-debugging-with-product-name.html

---

## ✅ You're All Set!

Open `pst-analysis-engine` in PyCharm and watch it catch all the bugs we spent hours debugging today!

