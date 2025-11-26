# How to Clear Browser Cache for VeriCase
**Issue:** AG Grid warnings persist because browser is loading cached HTML file  
**Solution:** Force browser to load the updated correspondence-enterprise.html

---

## Quick Fix: Hard Refresh (Recommended) ⚡

**In Chrome/Edge/Brave:**
1. Open the correspondence page:
   ```
   http://localhost:8010/ui/correspondence-enterprise.html?projectId=363b3fd5-b012-47ef-8401-15ebf6f0ee82
   ```

2. **Press:** `Ctrl + Shift + R` (Windows) or `Ctrl + F5`
   - This bypasses cache and forces fresh download

3. **Or:** `Ctrl + Shift + Delete` → Check "Cached images and files" → Clear

---

## Alternative: Clear Browser DevTools Cache

1. **Open DevTools:** Press `F12`
2. **Open Network tab**
3. **Right-click** on the page and select "Empty Cache and Hard Reload"
4. **Or:** Check "Disable cache" in Network tab settings (keeps cache disabled while DevTools open)

---

## Nuclear Option: Clear All localhost Cache

**Chrome/Edge:**
```
Settings → Privacy and security → Clear browsing data
→ Cached images and files → Time range: "All time"
→ Add domain filter: "localhost:8010"
→ Clear data
```

---

## Verify the Fix Worked

After clearing cache and refreshing:

### ✅ Expected Console (Clean)
```
[Kapture] Console listener attached
Correspondence using API URL: http://localhost:8010
VeriCase Configuration: ...
AG Grid License Key Applied
```

### ❌ Should NOT See
```
❌ AG Grid: As of v32.2, checkboxSelection is deprecated...
❌ AG Grid: warning #48 Cell data type is "object"...
```

---

## Why This Happened

**Browser caching behavior:**
- Static HTML files are cached aggressively
- Even though you saved the file, browser uses cached version
- Hard refresh (`Ctrl + Shift + R`) forces fresh download
- DevTools → "Disable cache" prevents this during development

---

## Quick Command

**Windows PowerShell - Force Clear Specific File:**
```powershell
# Add timestamp query parameter to force fresh load
start chrome "http://localhost:8010/ui/correspondence-enterprise.html?projectId=363b3fd5-b012-47ef-8401-15ebf6f0ee82&v=$(Get-Date -Format 'yyyyMMddHHmmss')"
```

Or just add `&nocache=1` to the URL manually:
```
http://localhost:8010/ui/correspondence-enterprise.html?projectId=363b3fd5-b012-47ef-8401-15ebf6f0ee82&nocache=1
```

---

## For Development: Disable Cache Permanently

**In Chrome DevTools:**
1. Press `F12` to open DevTools
2. Go to `Network` tab
3. Check ☑ **"Disable cache"**
4. Keep DevTools open while developing

This prevents caching for ALL requests while DevTools is open!

---

## The Actual Fix is Complete

The code changes are applied:
- ✅ `checkboxSelection: false` removed from Subject column
- ✅ `valueFormatter` added to attachments column  
- ✅ All deprecated code commented/removed

**You just need to refresh to see it!** 🎉

---

## TL;DR - Do This Now

1. **Open the page in Chrome**
2. **Press `Ctrl + Shift + R`** (hard refresh)
3. **Check console** - warnings should be gone!

That's it! 🚀
