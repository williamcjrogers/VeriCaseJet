# Wizard & Upload Evidence Fix - Implementation Plan

## Problems Identified

1. **Upload Evidence blocked by wizard** - Users can't upload without completing lengthy configuration
2. **Intelligent wizard too verbose** - 4 consecutive messages overwhelm users
3. **AI keys not in settings** - No place to pre-configure API keys
4. **Unclear wizard options** - No explanation of Team/Project/Case choices

## Solutions - Detailed Implementation

### Phase 1: Fix Intelligent Wizard Dialogue ✅

**File: `wizard-logic.js`**

#### Change 1: Simplify `startConversation()` - Lines ~850-900
**Before:** 4 separate messages with artificial delays
**After:** Single welcoming message with 3 clear action buttons

```javascript
async function startConversation() {
    addBotMessage(
        "Welcome to VeriCase! I'll help you get set up quickly. " +
        "Choose what you'd like to configure first, and we'll walk through it together.",
        ["Configure Team", "Set up Project", "Set up Case"]
    );
}
```

#### Change 2: Improve AI Detection - `startIntelligentMode()` function
**Before:** Shows chat then checks for AI (too late)
**After:** Check AI availability BEFORE entering chat mode

```javascript
async function startIntelligentMode() {
    // Check AI first before showing chat
    await checkAIAvailability();
    
    if (!aiAvailable && !hasStoredAIKey()) {
        showAISetupPrompt();
        return;
    }
    
    // Now show chat interface
    // ... rest of function
}
```

#### Change 3: Add friendly quick actions handler
```javascript
function handleIntelligentQuickAction(action) {
    if (action === "Configure Team") {
        document.getElementById('chatInput').value = "I want to add my team members";
        sendIntelligentMessage();
    } else if (action === "Set up Project") {
        document.getElementById('chatInput').value = "I need to set up a project";
        sendIntelligentMessage();
    } else if (action === "Set up Case") {
        document.getElementById('chatInput').value = "I need to set up a case";
        sendIntelligentMessage();
    }
    // ... rest
}
```

### Phase 2: Add API Keys to Dashboard Settings ✅

**File: `dashboard.html`**

#### Change 1: Add API Key Input Forms in Settings Modal
Add functional API key entry fields with:
- OpenAI key field
- Anthropic key field  
- Google Gemini key field
- Save button that stores to localStorage
- Visual indicator showing which keys are configured

#### Change 2: Add API Key Check Function
```javascript
function checkConfiguredKeys() {
    const keys = {
        openai: localStorage.getItem('ai_key_openai'),
        anthropic: localStorage.getItem('ai_key_anthropic'),
        google: localStorage.getItem('ai_key_google')
    };
    
    // Update UI indicators
    updateKeyStatus('openai', !!keys.openai);
    updateKeyStatus('anthropic', !!keys.anthropic);
    updateKeyStatus('google', !!keys.google);
    
    return Object.values(keys).some(k => k);
}
```

### Phase 3: Fix Upload Evidence Blocking ✅

**File: `dashboard.html` & `pst-upload.html`**

#### Change 1: Remove wizard dependency from upload
**Current:** Upload button disabled until profile exists
**New:** Upload button always enabled, creates minimal profile if needed

```javascript
function openPstUpload() {
    let profileId = localStorage.getItem('currentProjectId') || localStorage.getItem('currentCaseId');
    
    if (!profileId) {
        // Create minimal profile automatically
        showQuickProfileDialog();
    } else {
        // Go directly to upload
        window.location.href = `pst-upload.html?profileId=${profileId}`;
    }
}

function showQuickProfileDialog() {
    // Modal with: "Quick Setup" or "Full Wizard"
    // Quick Setup creates a profile with defaults in 2 clicks
}
```

### Phase 4: Improve Wizard Entry Screen ✅

**File: `wizard.html`**

#### Change 1: Make option descriptions clearer
- Intelligent: "Let AI guide you (Recommended for first-time setup)"
- Team: "Add team members manually"
- Project: "For discovery or live projects"
- Case: "For formalized disputes (adjudication, arbitration, etc.)"

#### Change 2: Add visual hierarchy
- Highlight "Intelligent" option as recommended
- Add icons for each option
- Better spacing and typography

## Implementation Order

1. ✅ Fix wizard dialogue (wizard-logic.js)
2. ✅ Add API keys to dashboard settings (dashboard.html)
3. ✅ Fix upload blocking (dashboard.html, pst-upload.html)
4. ✅ Update wizard entry screen (wizard.html)
5. ✅ Test end-to-end flow

## Testing Checklist

- [ ] Can enter API keys in dashboard settings
- [ ] Keys persist in localStorage
- [ ] Intelligent wizard checks for keys before starting
- [ ] Wizard shows friendly single message with 3 options
- [ ] Upload evidence works without completing wizard
- [ ] Quick profile creation works
- [ ] Manual wizard still works as expected
- [ ] Team/Project/Case options are clear
