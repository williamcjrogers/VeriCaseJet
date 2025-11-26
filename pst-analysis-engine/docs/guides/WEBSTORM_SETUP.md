# WebStorm Setup Guide for VeriCase UI

## 🎨 Frontend Development with WebStorm

Use WebStorm for the `ui/` folder - better JavaScript/HTML/CSS support than PyCharm.

---

## 🚀 Quick Setup

### 1. Open UI Folder in WebStorm
```
File → Open → Select: pst-analysis-engine/ui/
```

### 2. Configure JavaScript Version
```
Settings (Ctrl+Alt+S) → Languages & Frameworks → JavaScript
→ JavaScript language version: ECMAScript 6+
→ ☑️ Enable strict mode warnings
```

### 3. Set Up API Proxy (for local development)
```
Settings → Build, Execution, Deployment → Debugger
→ Built-in server port: 63342
→ Can accept external connections: ☑️

Create: package.json (if doesn't exist)
{
  "name": "vericase-ui",
  "version": "1.0.0",
  "proxy": "http://localhost:8010"
}
```

---

## 🔍 What WebStorm Catches

### ✅ JavaScript Type Errors

**Today's Bug (Frontend Side):**
```javascript
// correspondence-enterprise.html
const caseId = null;  // JavaScript null

// But sent as:
fetch('/api/pst/upload/init', {
    body: JSON.stringify({
        case_id: caseId || "null"  // ❌ STRING "null"!
    })
});

// WebStorm would flag:
// ⚠️ Type mismatch: Expected null, got "null" (string)
```

**Fix:**
```javascript
// Correct way
fetch('/api/pst/upload/init', {
    body: JSON.stringify({
        case_id: caseId || null  // ✅ Actual null
    })
});
```

### ✅ Undefined Variables
```javascript
// WebStorm flags:
const projectId = getProjectId();  // ⚠️ Function not defined
```

### ✅ API Contract Violations
```javascript
// WebStorm with TypeScript would catch:
interface PSTUploadRequest {
    case_id: string | null;  // Should be UUID or null
    project_id: string | null;
    filename: string;
    file_size: number;
}

// This would be flagged:
const request = {
    case_id: "null",  // ❌ String literal, not null
    filename: file.name,
    file_size: file.size
};
```

---

## 🎯 Recommended: Add TypeScript

### Convert to TypeScript (Gradual)

**1. Create tsconfig.json:**
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "lib": ["ES2020", "DOM"],
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "allowJs": true,
    "checkJs": true,
    "noEmit": true
  },
  "include": ["**/*.js", "**/*.ts"],
  "exclude": ["node_modules"]
}
```

**2. Create type definitions:**

**File: `ui/types.ts`**
```typescript
// API Types
export interface User {
    id: string;
    email: string;
    display_name: string;
    role: 'ADMIN' | 'EDITOR' | 'VIEWER';
}

export interface PSTUploadInitRequest {
    case_id: string | null;  // UUID or null (NOT "null" string!)
    project_id: string | null;
    filename: string;
    file_size: number;
}

export interface PSTUploadInitResponse {
    pst_file_id: string;
    upload_url: string;
    s3_bucket: string;
    s3_key: string;
}

export interface EmailMessage {
    id: string;
    subject: string | null;
    sender_email: string | null;
    sender_name: string | null;
    date_sent: string | null;
    has_attachments: boolean;
    matched_stakeholders: string[] | null;
    matched_keywords: string[] | null;
}

export interface Project {
    id: string;
    project_name: string;
    project_code: string;
    created_at: string;
}

export interface Case {
    id: string;
    name: string;
    case_number: string;
    status: string;
    created_at: string;
}
```

**3. Use in JavaScript files:**

**File: `ui/api-client.js` (or convert to .ts)**
```javascript
// @ts-check
/// <reference path="types.ts" />

/**
 * @typedef {import('./types').PSTUploadInitRequest} PSTUploadInitRequest
 * @typedef {import('./types').PSTUploadInitResponse} PSTUploadInitResponse
 */

class APIClient {
    constructor() {
        this.baseUrl = 'http://localhost:8010';
    }
    
    /**
     * Initialize PST upload
     * @param {PSTUploadInitRequest} request
     * @returns {Promise<PSTUploadInitResponse>}
     */
    async initPSTUpload(request) {
        // WebStorm now validates this!
        if (request.case_id === "null") {  // ⚠️ WebStorm flags this!
            throw new Error("case_id should be null, not 'null' string");
        }
        
        const response = await fetch(`${this.baseUrl}/api/correspondence/pst/upload/init`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${this.getToken()}`
            },
            body: JSON.stringify(request)
        });
        
        if (!response.ok) {
            throw new Error(`Upload init failed: ${response.statusText}`);
        }
        
        return response.json();
    }
    
    getToken() {
        return localStorage.getItem('token');
    }
}

export const apiClient = new APIClient();
```

---

## 🔍 WebStorm Features for VeriCase

### 1. Live Edit (See Changes Instantly)
```
Run → Edit Configurations → Add → JavaScript Debug
→ URL: http://localhost:8010/ui/dashboard.html
→ Now edit HTML/CSS/JS and see changes live
```

### 2. Find API Calls
```
Search (Ctrl+Shift+F) → "fetch.*api"
→ Find all API calls across UI
→ Verify they match backend endpoints
```

### 3. Unused Code Detection
```
Code → Inspect Code
→ WebStorm finds:
  - Unused functions
  - Dead code
  - Unreachable branches
```

### 4. Refactoring Across Files
```
Right-click function → Refactor → Rename
→ WebStorm updates:
  - All HTML files
  - All JavaScript files
  - All CSS selectors (if applicable)
```

---

## 🐛 Debug Frontend Issues

### Debug in Chrome
```
1. Run → Debug 'Dashboard'
2. WebStorm opens Chrome with debugger attached
3. Set breakpoints in JavaScript
4. Inspect variables
5. Step through code
```

### Console Errors
```
WebStorm shows console.error() inline:
→ Red markers in gutter
→ Click to see error details
```

---

## 🎯 Fix Today's "null" Bug in Frontend

### Find the Bug:
```
Search (Ctrl+Shift+F):
  Pattern: case_id.*"null"|caseId.*"null"
  
WebStorm finds:
  correspondence-enterprise.html:1234
  → case_id: caseId || "null"  // ❌ BUG!
```

### Fix Suggestion (WebStorm AI):
```javascript
// Before (BAD):
const payload = {
    case_id: caseId || "null",  // ❌ String "null"
    project_id: projectId || "null"
};

// After (GOOD):
const payload = {
    case_id: caseId || null,  // ✅ Actual null
    project_id: projectId || null
};

// Or even better:
const payload = {
    case_id: caseId ?? null,  // ✅ Nullish coalescing
    project_id: projectId ?? null
};
```

---

## 📊 Code Quality Checks

### ESLint Configuration

**File: `ui/.eslintrc.json`**
```json
{
  "env": {
    "browser": true,
    "es2021": true
  },
  "extends": "eslint:recommended",
  "parserOptions": {
    "ecmaVersion": 12,
    "sourceType": "module"
  },
  "rules": {
    "no-unused-vars": "warn",
    "no-console": "off",
    "eqeqeq": ["error", "always"],
    "no-implicit-coercion": "error"
  }
}
```

### Prettier Configuration

**File: `ui/.prettierrc`**
```json
{
  "semi": true,
  "trailingComma": "es5",
  "singleQuote": true,
  "printWidth": 100,
  "tabWidth": 2
}
```

---

## 🎯 Next Steps

1. ☐ Open `ui/` folder in WebStorm
2. ☐ Add TypeScript types
3. ☐ Enable type checking in JavaScript
4. ☐ Run inspection: Code → Inspect Code
5. ☐ Fix "null" string bugs in frontend
6. ☐ Set up live debugging
7. ☐ Link to PyCharm project (optional)

**WebStorm will catch frontend bugs before they reach the backend!**

