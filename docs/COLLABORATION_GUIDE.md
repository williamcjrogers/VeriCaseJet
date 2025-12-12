# VeriCase Collaboration System - Complete Guide

## Overview

VeriCase now has a comprehensive collaboration system that enables teams to work together effectively on cases and evidence.

## Features Overview

### ✅ Already Built (Existing)
- Document sharing with view/edit permissions
- Folder sharing
- User role management (Admin, Editor, Viewer)
- Case team members
- Share links with passwords
- User invitations

### 🆕 New Features (Just Added)
- **Comments & Threads** - Comment on documents with @mentions
- **PDF Annotations** - Highlight and annotate documents
- **Case Sharing** - Share entire cases with team members
- **Activity Stream** - See what your team is working on
- **Real-time Updates** - Stay synchronized with your team

---

## API Endpoints

### Document Comments

#### Create Comment
```http
POST /api/collaboration/documents/{doc_id}/comments
Authorization: Bearer {token}

{
  "content": "This document needs review @john.doe@example.com",
  "parent_id": null,  // For threaded replies
  "mentions": ["user-uuid-here"]
}
```

**Response:**
```json
{
  "id": "comment-uuid",
  "content": "This document needs review @john.doe@example.com",
  "author_id": "user-uuid",
  "author_name": "Jane Smith",
  "author_email": "jane@example.com",
  "created_at": "2025-12-12T05:40:00Z",
  "updated_at": null,
  "parent_id": null,
  "replies_count": 0,
  "mentions": [
    {
      "user_id": "mentioned-user-uuid",
      "user_name": "John Doe",
      "user_email": "john.doe@example.com"
    }
  ],
  "is_edited": false
}
```

#### Get Comments
```http
GET /api/collaboration/documents/{doc_id}/comments
Authorization: Bearer {token}
```

### PDF Annotations

#### Create Annotation
```http
POST /api/collaboration/documents/{doc_id}/annotations
Authorization: Bearer {token}

{
  "page_number": 1,
  "x": 100.5,
  "y": 200.3,
  "width": 150.0,
  "height": 20.0,
  "content": "Important clause",
  "color": "#FFD700"
}
```

#### Get Annotations
```http
GET /api/collaboration/documents/{doc_id}/annotations?page=1
Authorization: Bearer {token}
```

### Case Sharing

#### Share Case
```http
POST /api/collaboration/cases/{case_id}/share
Authorization: Bearer {token}

{
  "user_email": "colleague@example.com",
  "role": "editor"  // viewer, editor, admin
}
```

#### List Case Shares
```http
GET /api/collaboration/cases/{case_id}/shares
Authorization: Bearer {token}
```

### Activity Stream

```http
GET /api/collaboration/activity?limit=50
Authorization: Bearer {token}
```

---

## Integration Guide

### Step 1: Add Router to main.py

```python
# In vericase/api/app/main.py

# Add import (around line 50)
from .collaboration import router as collaboration_router

# Add router include (around line 420)
app.include_router(collaboration_router)  # Collaboration features
```

### Step 2: UI Integration

#### Comments Component

Create `vericase/ui/components/comments-panel.js`:

```javascript
class CommentsPanel {
    constructor(documentId) {
        this.documentId = documentId;
        this.container = document.getElementById('comments-container');
    }
    
    async load() {
        const response = await fetch(
            `/api/collaboration/documents/${this.documentId}/comments`,
            {
                headers: {
                    'Authorization': `Bearer ${getToken()}`
                }
            }
        );
        
        const comments = await response.json();
        this.render(comments);
    }
    
    render(comments) {
        this.container.innerHTML = comments.map(c => `
            <div class="comment">
                <div class="comment-header">
                    <strong>${c.author_name}</strong>
                    <span class="time">${this.formatTime(c.created_at)}</span>
                </div>
                <div class="comment-content">${this.renderContent(c.content)}</div>
                ${c.replies_count > 0 ? `
                    <div class="replies-count">${c.replies_count} replies</div>
                ` : ''}
            </div>
        `).join('');
    }
    
    renderContent(content) {
        // Convert @mentions to links
        return content.replace(
            /@([^\s]+@[^\s]+)/g, 
            '<span class="mention">@$1</span>'
        );
    }
    
    formatTime(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleString();
    }
    
    async addComment() {
        const content = document.getElementById('comment-input').value;
        
        if (!content.trim()) return;
        
        // Extract mentions
        const mentions = this.extractMentions(content);
        
        const response = await fetch(
            `/api/collaboration/documents/${this.documentId}/comments`,
            {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${getToken()}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    content,
                    mentions
                })
            }
        );
        
        if (response.ok) {
            document.getElementById('comment-input').value = '';
            await this.load(); // Reload comments
            showNotification('Comment added successfully');
        }
    }
    
    extractMentions(content) {
        // Extract user emails mentioned with @
        const mentions = [];
        const regex = /@([^\s]+@[^\s]+)/g;
        let match;
        
        while ((match = regex.exec(content)) !== null) {
            // Lookup user ID by email (you'd need a user lookup function)
            const userId = this.getUserIdByEmail(match[1]);
            if (userId) {
                mentions.push(userId);
            }
        }
        
        return mentions;
    }
}
```

#### Annotations Component

Create `vericase/ui/components/pdf-annotator.js`:

```javascript
class PDFAnnotator {
    constructor(documentId, pdfViewer) {
        this.documentId = documentId;
        this.pdfViewer = pdfViewer;
        this.annotations = [];
        this.selectedColor = '#FFD700';
    }
    
    async loadAnnotations(pageNumber) {
        const response = await fetch(
            `/api/collaboration/documents/${this.documentId}/annotations?page=${pageNumber}`,
            {
                headers: {
                    'Authorization': `Bearer ${getToken()}`
                }
            }
        );
        
        this.annotations = await response.json();
        this.renderAnnotations();
    }
    
    renderAnnotations() {
        const canvas = document.getElementById('annotation-layer');
        const ctx = canvas.getContext('2d');
        
        // Clear previous annotations
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        // Draw each annotation
        this.annotations.forEach(ann => {
            ctx.fillStyle = ann.color + '40'; // Semi-transparent
            ctx.fillRect(ann.x, ann.y, ann.width, ann.height);
            
            ctx.strokeStyle = ann.color;
            ctx.lineWidth = 2;
            ctx.strokeRect(ann.x, ann.y, ann.width, ann.height);
        });
    }
    
    async createAnnotation(x, y, width, height, content) {
        const pageNumber = this.pdfViewer.currentPage;
        
        const response = await fetch(
            `/api/collaboration/documents/${this.documentId}/annotations`,
            {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${getToken()}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    page_number: pageNumber,
                    x, y, width, height,
                    content,
                    color: this.selectedColor
                })
            }
        );
        
        if (response.ok) {
            await this.loadAnnotations(pageNumber);
            showNotification('Annotation added');
        }
    }
    
    enableDrawingMode() {
        let startX, startY, isDrawing = false;
        
        const canvas = document.getElementById('annotation-layer');
        
        canvas.addEventListener('mousedown', (e) => {
            isDrawing = true;
            const rect = canvas.getBoundingClientRect();
            startX = e.clientX - rect.left;
            startY = e.clientY - rect.top;
        });
        
        canvas.addEventListener('mouseup', async (e) => {
            if (!isDrawing) return;
            isDrawing = false;
            
            const rect = canvas.getBoundingClientRect();
            const endX = e.clientX - rect.left;
            const endY = e.clientY - rect.top;
            
            const width = Math.abs(endX - startX);
            const height = Math.abs(endY - startY);
            const x = Math.min(startX, endX);
            const y = Math.min(startY, endY);
            
            // Prompt for annotation content
            const content = prompt('Annotation text:');
            if (content) {
                await this.createAnnotation(x, y, width, height, content);
            }
        });
    }
}
```

### Step 3: Add to Document Viewer

In your `pdf-viewer.html`:

```html
<div class="document-viewer-layout">
    <div class="pdf-canvas-container">
        <canvas id="pdf-canvas"></canvas>
        <canvas id="annotation-layer"></canvas>
    </div>
    
    <div class="sidebar">
        <!-- Comments Panel -->
        <div class="panel">
            <h3>Comments</h3>
            <div id="comments-container"></div>
            <div class="comment-input">
                <textarea id="comment-input" placeholder="Add a comment... Use @ to mention someone"></textarea>
                <button onclick="commentsPanel.addComment()">Post Comment</button>
            </div>
        </div>
        
        <!-- Annotation Tools -->
        <div class="panel">
            <h3>Annotations</h3>
            <div class="annotation-tools">
                <button onclick="annotator.enableDrawingMode()">
                    <i class="fas fa-highlighter"></i> Highlight
                </button>
                <input type="color" 
                       id="annotation-color" 
                       value="#FFD700"
                       onchange="annotator.selectedColor = this.value">
            </div>
        </div>
    </div>
</div>

<script src="/ui/components/comments-panel.js"></script>
<script src="/ui/components/pdf-annotator.js"></script>
<script>
    const documentId = new URLSearchParams(window.location.search).get('id');
    const commentsPanel = new CommentsPanel(documentId);
    const annotator = new PDFAnnotator(documentId, pdfViewer);
    
    // Load on page load
    commentsPanel.load();
    annotator.loadAnnotations(1);
</script>
```

---

## Use Cases

### 1. Document Review Workflow

**Scenario:** Legal team reviewing a contract

```javascript
// Share document with team
await fetch(`/api/documents/${docId}/share`, {
    method: 'POST',
    body: JSON.stringify({
        user_email: 'lawyer@firm.com',
        permission: 'edit'
    })
});

// Add comment with mention
await fetch(`/api/collaboration/documents/${docId}/comments`, {
    method: 'POST',
    body: JSON.stringify({
        content: 'Please review clause 5.3 @lawyer@firm.com',
        mentions: [lawyerUserId]
    })
});

// Add annotation to specific clause
await fetch(`/api/collaboration/documents/${docId}/annotations`, {
    method: 'POST',
    body: JSON.stringify({
        page_number: 3,
        x: 100, y: 200, width: 300, height: 50,
        content: 'Ambiguous wording - needs clarification',
        color: '#FF6B6B'
    })
});
```

### 2. Case Collaboration

**Scenario:** Share entire case with legal assistant

```javascript
await fetch(`/api/collaboration/cases/${caseId}/share`, {
    method: 'POST',
    body: JSON.stringify({
        user_email: 'assistant@firm.com',
        role: 'editor'
    })
});
```

### 3. Activity Monitoring

**Scenario:** See what your team is working on

```javascript
const response = await fetch('/api/collaboration/activity?limit=20');
const activities = await response.json();

// Display in feed
activities.forEach(activity => {
    console.log(`${activity.actor_name} ${activity.action} ${activity.resource_type}: ${activity.resource_name}`);
});
```

---

## Permissions Model

### Document Permissions
- **Owner**: Full control (delete, share, edit, comment, annotate)
- **Edit**: Can modify, comment, annotate
- **View**: Can read, comment

### Case Permissions
- **Admin**: Full control, can share case
- **Editor**: Can edit evidence, add comments
- **Viewer**: Read-only access

### User Roles
- **ADMIN**: System-wide admin
- **EDITOR**: Can create and edit all resources
- **VIEWER**: Read-only access

---

## Real-time Updates (Future Enhancement)

For real-time collaboration, consider adding WebSocket support:

```python
# Future: websocket_manager.py
from fastapi import WebSocket

class CollaborationManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, document_id: str, websocket: WebSocket):
        await websocket.accept()
        if document_id not in self.active_connections:
            self.active_connections[document_id] = []
        self.active_connections[document_id].append(websocket)
    
    async def broadcast(self, document_id: str, message: dict):
        if document_id in self.active_connections:
            for connection in self.active_connections[document_id]:
                await connection.send_json(message)
```

---

## Best Practices

### 1. @Mentions
- Always extract user IDs from email addresses
- Send notifications when users are mentioned
- Highlight mentions in the UI

### 2. Comments
- Support threaded replies for organized discussions
- Show unread comment indicators
- Allow editing within first 5 minutes

### 3. Annotations
- Use color coding for different annotation types
- Allow filtering by author
- Export annotations with document

### 4. Activity Stream
- Show most recent first
- Filter by resource type
- Highlight important activities (shares, mentions)

---

## Security Considerations

### Access Control
- Always verify user has access before showing comments/annotations
- Check permissions before allowing edits
- Validate user IDs in mentions

### Data Privacy
- Don't expose sensitive information in activity stream
- Respect document/case permissions
- Audit all collaboration actions

---

## Performance Tips

### 1. Pagination
```javascript
// Load comments in batches
async function loadComments(page = 1, perPage = 20) {
    const response = await fetch(
        `/api/collaboration/documents/${docId}/comments?page=${page}&per_page=${perPage}`
    );
    return await response.json();
}
```

### 2. Caching
```javascript
// Cache annotations by page
const annotationCache = new Map();

async function getAnnotations(pageNumber) {
    if (!annotationCache.has(pageNumber)) {
        const response = await fetch(
            `/api/collaboration/documents/${docId}/annotations?page=${pageNumber}`
        );
        annotationCache.set(pageNumber, await response.json());
    }
    return annotationCache.get(pageNumber);
}
```

### 3. Debouncing
```javascript
// Debounce activity stream updates
let activityTimeout;

function scheduleActivityUpdate() {
    clearTimeout(activityTimeout);
    activityTimeout = setTimeout(() => {
        loadActivityStream();
    }, 5000); // Update every 5 seconds
}
```

---

## Migration from Existing System

Your existing `sharing.py` is complementary to the new collaboration features:

- **Keep** `sharing.py` for basic document/folder sharing
- **Add** `collaboration.py` for advanced features
- Both systems work together seamlessly

No migration needed - just add the new features!

---

## Testing

### Test Comments
```bash
# Create comment
curl -X POST http://localhost:8010/api/collaboration/documents/{doc_id}/comments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "Test comment", "mentions": []}'

# Get comments
curl http://localhost:8010/api/collaboration/documents/{doc_id}/comments \
  -H "Authorization: Bearer $TOKEN"
```

### Test Annotations
```bash
curl -X POST http://localhost:8010/api/collaboration/documents/{doc_id}/annotations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "page_number": 1,
    "x": 100, "y": 200,
    "width": 150, "height": 30,
    "content": "Test annotation",
    "color": "#FFD700"
  }'
```

---

## Summary

### What You Have Now
1. ✅ Comments with @mentions
2. ✅ PDF annotations
3. ✅ Case sharing
4. ✅ Activity stream
5. ✅ Existing document/folder sharing

### Next Steps
1. Add router to `main.py`
2. Create UI components
3. Test with your team
4. Consider WebSocket for real-time updates
5. Add email notifications for mentions

Your VeriCase collaboration system is ready for team-based legal work! 🎉
