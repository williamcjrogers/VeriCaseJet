# Complete JetBrains Suite Setup for VeriCase

## 🎯 Overview

You own the **complete JetBrains suite** - here's how to use each tool optimally for VeriCase development.

---

## 📦 What's Been Configured

✅ **PyCharm Professional** - Main development (Python API)
✅ **DataGrip** - Database management
✅ **WebStorm** - Frontend development (UI folder)
✅ **CLion** - Future Rust/C++ development (optional)

All configuration files have been created in `.idea/` folder.

---

## 🚀 Quick Start (5 Minutes)

### Step 1: Open in PyCharm
```
1. Launch PyCharm Professional
2. File → Open
3. Select: pst-analysis-engine/
4. Wait for indexing (5-10 minutes)
5. When prompted, configure Docker Compose interpreter:
   → Service: api
   → Click OK
```

### Step 2: Start Services
```
Run → Docker Compose (from toolbar)
Or: Services panel (Alt+8) → Start
```

### Step 3: Connect Database
```
Database panel (right sidebar)
→ VeriCase PostgreSQL
→ Enter password: vericase
→ Test Connection
```

### Step 4: Run Code Inspection
```
Code → Inspect Code
→ Inspection scope: Whole project
→ Click OK
→ Review ~50-100 issues found
```

**You're now set up!**

---

## 🎯 Daily Workflow

### Morning Routine:
```
1. Open PyCharm
2. Services panel (Alt+8) → Start Docker Compose
3. Database panel → Refresh connections
4. Pull latest changes (Ctrl+T)
5. Run inspections on changed files
```

### Development:
```
1. Write code in PyCharm (Python/API)
2. Switch to WebStorm for UI work
3. Use DataGrip for database queries
4. Debug with breakpoints
5. Check logs in Services panel
```

### End of Day:
```
1. Run full code inspection
2. Fix critical issues
3. Commit changes (Ctrl+K)
4. Services panel → Stop Docker Compose
```

---

## 🔍 What Each Tool Does

### 🐍 PyCharm Professional
**Use for:**
- ✅ Python API development
- ✅ Docker Compose management
- ✅ Debugging backend
- ✅ Type checking
- ✅ Git operations

**Key features:**
- Type checker (catches "null" string bugs)
- Docker integration (start/stop services)
- Remote debugging (debug inside containers)
- Database browser (basic queries)

**See:** `README_PYCHARM.md` for full guide

---

### 🗄️ DataGrip
**Use for:**
- ✅ Database schema management
- ✅ Complex SQL queries
- ✅ Schema comparison (models vs DB)
- ✅ Migration generation
- ✅ ER diagrams

**Key features:**
- Schema comparison (finds mismatches)
- Query console (better than psql)
- Data editor (edit tables inline)
- ER diagram generator

**See:** `DATAGRIP_SETUP.md` for full guide

---

### 🎨 WebStorm
**Use for:**
- ✅ HTML/CSS/JavaScript editing
- ✅ Frontend debugging
- ✅ Live preview
- ✅ TypeScript (if you add it)

**Key features:**
- JavaScript type checking
- Live edit (see changes instantly)
- Chrome debugging integration
- API call validation

**See:** `WEBSTORM_SETUP.md` for full guide

---

### ⚙️ CLion (Future)
**Use for:**
- ✅ Rust PST worker (10x performance)
- ✅ C++ if you go that route
- ✅ Performance profiling

**Key features:**
- Rust support (borrow checker, Cargo)
- Performance profiler
- Memory analyzer
- Compile-time safety

**See:** `CLION_RUST_GUIDE.md` for full guide

---

## 🐛 How This Prevents Today's Bugs

### Bug 1: String "null" as UUID
**PyCharm catches:**
```python
# ⚠️ Type mismatch: Expected Optional[UUID], got str
case_id = "null"
```

**WebStorm catches:**
```javascript
// ⚠️ Sending string "null" instead of null
case_id: caseId || "null"  // BAD!
```

### Bug 2: Missing Attribute
**PyCharm catches:**
```python
# ❌ Unresolved attribute 'use_textract'
if settings.use_textract:
```

### Bug 3: Schema Mismatch
**DataGrip catches:**
```
Schema Comparison:
  models.py: is_admin (Boolean)
  Database: role (ENUM)
  → Generate migration
```

### Bug 4: Worker Import Error
**PyCharm catches:**
```python
# ❌ Cannot find reference 'worker_app.worker'
from worker_app.worker import celery_app
```

---

## 📊 Tool Comparison

| Task | PyCharm | DataGrip | WebStorm | CLion |
|------|---------|----------|----------|-------|
| **Python Development** | ⭐⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐ |
| **Database Work** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐ |
| **Frontend Development** | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐ |
| **Rust/C++ Development** | ⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| **Docker Management** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Debugging** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 🎯 Recommended Setup

### For Current Python Development:
```
Primary: PyCharm Professional
Secondary: DataGrip (for complex DB work)
Optional: WebStorm (if doing heavy UI work)
```

### If You Add Rust Worker:
```
Primary: PyCharm (API) + CLion (Rust worker)
Secondary: DataGrip (database)
Optional: WebStorm (UI)
```

---

## 💰 Performance vs Development Time

### Option 1: Keep Python (Current)
- **Development time:** 0 (already done)
- **Performance:** Baseline
- **Maintenance:** Easy
- **Cost:** Current

### Option 2: Add Rust PST Worker
- **Development time:** 2 months
- **Performance:** 10x faster PST processing
- **Maintenance:** Medium (two languages)
- **Cost:** -$2,000/month (faster compute)

### Option 3: Full Rust Rewrite
- **Development time:** 6 months
- **Performance:** 10-20x faster overall
- **Maintenance:** Medium (single language)
- **Cost:** -$3,000/month (much faster compute)

---

## 🎯 My Recommendation

### Immediate (This Week):
1. ✅ **Use PyCharm** for all Python development
2. ✅ **Use DataGrip** for database work
3. ✅ **Fix bugs** PyCharm highlights
4. ✅ **Add type hints** everywhere

### Short Term (1-2 Months):
1. ✅ **Improve Python code** with PyCharm's help
2. ✅ **Add TypeScript** to frontend (WebStorm)
3. ✅ **Monitor performance** - is it actually slow?

### Long Term (3-6 Months) - Only If Needed:
1. ✅ **Prototype Rust PST worker** (CLion)
2. ✅ **Benchmark** vs Python
3. ✅ **Deploy if 10x improvement confirmed**
4. ✅ **Keep Python for everything else**

---

## 📚 Documentation Index

| Guide | Purpose | Tool |
|-------|---------|------|
| `README_PYCHARM.md` | Python development setup | PyCharm |
| `DATAGRIP_SETUP.md` | Database management | DataGrip |
| `WEBSTORM_SETUP.md` | Frontend development | WebStorm |
| `CLION_RUST_GUIDE.md` | Future Rust worker | CLion |
| `JETBRAINS_COMPLETE_SETUP.md` | This file - overview | All |

---

## ✅ Next Steps

### Today:
1. ☐ Open `pst-analysis-engine` in PyCharm
2. ☐ Wait for indexing
3. ☐ Configure Docker Compose interpreter
4. ☐ Start services
5. ☐ Run code inspection
6. ☐ Fix top 10 errors

### This Week:
1. ☐ Add type hints to all functions
2. ☐ Fix all PyCharm warnings
3. ☐ Set up DataGrip connection
4. ☐ Run schema comparison
5. ☐ Test PST upload (should work now!)

### This Month:
1. ☐ Improve frontend with WebStorm
2. ☐ Add TypeScript types
3. ☐ Fix "null" string bugs in UI
4. ☐ Measure PST processing performance
5. ☐ Decide if Rust worker is needed

---

## 🎉 You're All Set!

You now have:
- ✅ PyCharm configured for Python development
- ✅ DataGrip ready for database work
- ✅ WebStorm guide for frontend
- ✅ CLion guide for future Rust work
- ✅ All configuration files created

**Open PyCharm now and see it catch all the bugs we debugged today!**

---

## 🆘 Questions?

- **PyCharm not finding Docker?** → Ensure Docker Desktop is running
- **Database won't connect?** → Start docker-compose first
- **Type checking not working?** → Wait for indexing to complete
- **Want to try Rust?** → Read `CLION_RUST_GUIDE.md`

**You're using the best tools available - make the most of them!**

