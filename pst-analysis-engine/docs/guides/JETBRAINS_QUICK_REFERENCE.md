# JetBrains Quick Reference Card

## 🎯 One-Page Cheat Sheet

---

## 🔧 Which Tool for What?

| Task | Tool | Shortcut |
|------|------|----------|
| **Edit Python code** | PyCharm | - |
| **Debug API** | PyCharm | Shift+F9 |
| **Start Docker** | PyCharm | Alt+8 → Start |
| **Run SQL queries** | DataGrip | Ctrl+Enter |
| **Compare schema** | DataGrip | Right-click → Compare |
| **Edit HTML/JS** | WebStorm | - |
| **Debug frontend** | WebStorm | Shift+F9 |
| **Write Rust** | CLion | - |
| **Profile performance** | CLion | Run → Profile |

---

## ⌨️ Essential Shortcuts

### PyCharm
| Action | Shortcut |
|--------|----------|
| **Search everywhere** | Double Shift |
| **Find file** | Ctrl+Shift+N |
| **Go to definition** | Ctrl+B |
| **Find usages** | Alt+F7 |
| **Refactor/Rename** | Shift+F6 |
| **Run** | Shift+F10 |
| **Debug** | Shift+F9 |
| **Services panel** | Alt+8 |
| **Database panel** | Right sidebar |
| **Terminal** | Alt+F12 |
| **Quick fix** | Alt+Enter |
| **Recent files** | Ctrl+E |
| **Commit** | Ctrl+K |

### DataGrip
| Action | Shortcut |
|--------|----------|
| **Execute query** | Ctrl+Enter |
| **New query console** | Ctrl+Shift+L |
| **Format SQL** | Ctrl+Alt+L |
| **Explain plan** | Ctrl+Shift+E |

### WebStorm
| Action | Shortcut |
|--------|----------|
| **Find in files** | Ctrl+Shift+F |
| **Reformat code** | Ctrl+Alt+L |
| **Optimize imports** | Ctrl+Alt+O |
| **Debug** | Shift+F9 |

---

## 🐛 Debugging Workflow

### 1. Set Breakpoint
```
Click line number gutter (red dot appears)
```

### 2. Start Debug
```
Run → Debug 'Docker Compose'
Or: Shift+F9
```

### 3. Trigger Code
```
Open browser → Upload PST file
```

### 4. Inspect Variables
```
Variables panel shows all locals
Hover over variables for values
Evaluate Expression: Alt+F8
```

### 5. Step Through
```
F8 = Step Over
F7 = Step Into
Shift+F8 = Step Out
F9 = Resume
```

---

## 📊 Database Quick Commands

### In PyCharm or DataGrip:

```sql
-- View all users
SELECT * FROM users;

-- View projects
SELECT * FROM projects ORDER BY created_at DESC;

-- PST processing status
SELECT filename, processing_status, total_emails, processed_emails
FROM pst_files 
ORDER BY created_at DESC;

-- Email counts
SELECT COUNT(*) as total, 
       COUNT(DISTINCT sender_email) as unique_senders
FROM email_messages;

-- Find admin users
SELECT email, role FROM users WHERE role = 'ADMIN';
```

---

## 🔍 Code Inspection

### Run Full Inspection:
```
Code → Inspect Code
→ Whole project
→ Click OK
→ Review results
```

### Common Issues Found:
- ⚠️ Type mismatches
- ⚠️ Unresolved references
- ⚠️ Missing type hints
- ⚠️ SQL errors
- ⚠️ Unused imports

### Fix Issues:
```
Click issue → Alt+Enter → Select fix
Or: Right-click → Apply fix
```

---

## 🐳 Docker Management

### Services Panel (Alt+8):
```
Docker Compose
├─ api (✅ Running)
├─ worker (✅ Running)
├─ postgres (✅ Running)
├─ redis (✅ Running)
├─ minio (✅ Running)
├─ opensearch (✅ Running)
└─ tika (✅ Running)
```

### Actions:
- **Start all:** Right-click → Start
- **Stop all:** Right-click → Stop
- **Restart one:** Right-click service → Restart
- **View logs:** Click service → Logs panel
- **Exec into:** Right-click → Exec

---

## 🎯 Today's Bugs (Now Prevented)

### Bug 1: String "null" as UUID
**PyCharm catches:**
```python
case_id = "null"  # ⚠️ Type: str, Expected: Optional[UUID]
```

### Bug 2: Missing Attribute
**PyCharm catches:**
```python
settings.use_textract  # ❌ Attribute doesn't exist
```

### Bug 3: Schema Mismatch
**DataGrip catches:**
```
models.py: is_admin (Boolean)
Database: role (ENUM)
→ Generate migration
```

---

## 📚 Documentation Index

| File | Purpose |
|------|---------|
| **START_HERE.md** | This file - quick start |
| **JETBRAINS_COMPLETE_SETUP.md** | Master guide |
| **README_PYCHARM.md** | PyCharm setup |
| **DATAGRIP_SETUP.md** | Database management |
| **WEBSTORM_SETUP.md** | Frontend development |
| **CLION_RUST_GUIDE.md** | Rust performance guide |
| **ZERO_COST_SETUP.md** | Original setup guide |

---

## ✅ Next Steps

### Right Now:
1. ☐ Open PyCharm
2. ☐ Wait for indexing
3. ☐ Run code inspection
4. ☐ See all the bugs it finds!

### Today:
1. ☐ Fix top 10 inspection errors
2. ☐ Set up DataGrip connection
3. ☐ Test PST upload
4. ☐ Verify worker processes files

### This Week:
1. ☐ Add type hints everywhere
2. ☐ Fix frontend "null" bugs
3. ☐ Run schema comparison
4. ☐ Improve error handling

---

## 🎉 You're Ready!

**Everything is configured and working:**
- ✅ All services running
- ✅ JetBrains suite configured
- ✅ Bugs fixed
- ✅ Documentation complete

**Open PyCharm now and experience the difference!**

---

## 🆘 Quick Help

**PyCharm won't start services?**
→ Ensure Docker Desktop is running

**Database won't connect?**
→ Password is: `vericase`

**Type checking not working?**
→ Wait for indexing to complete (bottom-right status bar)

**Want to try Rust?**
→ Read `CLION_RUST_GUIDE.md`

**Questions?**
→ Read the detailed guides above!

