/**
 * Comments Panel
 * Document collaboration with @mentions and threaded replies
 * Usage: Add to pdf-viewer.html or evidence.html
 */

class CommentsPanel {
    constructor(documentId, containerId = 'comments-container') {
        this.documentId = documentId;
        this.container = document.getElementById(containerId);
        this.comments = [];
    }

    async init() {
        await this.load();
    }

    async load() {
        try {
            const token = localStorage.getItem('token');
            const response = await fetch(
                `/api/collaboration/documents/${this.documentId}/comments?include_replies=true&page_size=500`,
                {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                }
            );

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            this.comments = await response.json();
            this.render();

        } catch (error) {
            console.error('Error loading comments:', error);
            this.renderError(error.message);
        }
    }

    render() {
        const threadedComments = this.buildCommentTree();

        this.container.innerHTML = `
            <div class="comments-panel">
                <div class="comments-header">
                    <h3>Comments (${this.comments.length})</h3>
                </div>

                <div class="comments-list">
                    ${threadedComments.length > 0 ?
                        threadedComments.map(c => this.renderComment(c)).join('') :
                        '<p class="no-comments">No comments yet. Be the first to comment!</p>'
                    }
                </div>

                <div class="comment-input-container">
                    <textarea
                        id="new-comment-input"
                        placeholder="Add a comment... Use @email to mention someone"
                        rows="3"></textarea>
                    <div class="comment-actions">
                        <button
                            class="btn btn-primary"
                            onclick="commentsPanel.addComment()">
                            Post Comment
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    renderComment(comment, depth = 0) {
        const marginLeft = depth * 20;
        const timeAgo = this.formatTimeAgo(comment.created_at);

        return `
            <div class="comment" style="margin-left: ${marginLeft}px">
                <div class="comment-header">
                    <strong>${comment.author_name}</strong>
                    <span class="comment-time">${timeAgo}</span>
                    ${comment.is_edited ? '<span class="edited-badge">(edited)</span>' : ''}
                </div>
                <div class="comment-content">${this.renderContent(comment.content)}</div>
                <div class="comment-actions">
                    ${comment.replies_count > 0 ?
                        `<span class="replies-count">${comment.replies_count} replies</span>` : ''
                    }
                    <button
                        class="btn-link"
                        onclick="commentsPanel.reply('${comment.id}')">
                        Reply
                    </button>
                </div>
                ${comment.replies ? comment.replies.map(r => this.renderComment(r, depth + 1)).join('') : ''}
            </div>
        `;
    }

    buildCommentTree() {
        // Build parent-child relationships
        const commentsMap = new Map();
        const rootComments = [];

        this.comments.forEach(c => {
            commentsMap.set(c.id, { ...c, replies: [] });
        });

        this.comments.forEach(c => {
            if (c.parent_id) {
                const parent = commentsMap.get(c.parent_id);
                if (parent) {
                    parent.replies.push(commentsMap.get(c.id));
                }
            } else {
                rootComments.push(commentsMap.get(c.id));
            }
        });

        return rootComments;
    }

    renderContent(content) {
        // Convert @mentions to highlighted spans
        return content.replace(
            /@([^\s]+@[^\s]+)/g,
            '<span class="mention">@$1</span>'
        );
    }

    formatTimeAgo(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);

        if (seconds < 60) return 'just now';
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        return date.toLocaleDateString();
    }

    async addComment(parentId = null) {
        const input = document.getElementById('new-comment-input');
        const content = input.value.trim();

        if (!content) return;

        try {
            const token = localStorage.getItem('token');

            // Extract mentions
            const mentions = this.extractMentions(content);

            const response = await fetch(
                `/api/collaboration/documents/${this.documentId}/comments`,
                {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        content,
                        parent_id: parentId,
                        mentions
                    })
                }
            );

            if (!response.ok) {
                throw new Error('Failed to post comment');
            }

            input.value = '';
            await this.load(); // Reload all comments

            // Show success message
            this.showNotification('Comment added successfully!');

        } catch (error) {
            console.error('Error adding comment:', error);
            alert('Failed to add comment: ' + error.message);
        }
    }

    extractMentions(content) {
        // Extract email addresses mentioned with @
        const mentions = [];
        const regex = /@([^\s]+@[^\s]+)/g;
        let match;

        while ((match = regex.exec(content)) !== null) {
            const email = match[1];
            // Note: In production, you'd lookup user ID by email via API
            // For now, just collect the emails
            mentions.push(email);
        }

        return mentions;
    }

    reply(parentId) {
        // Set focus to input and store parent ID
        const input = document.getElementById('new-comment-input');
        input.focus();
        input.placeholder = 'Writing a reply...';

        // Store parent ID for next comment
        this.replyToId = parentId;

        // Update add comment to use this parent
        const addButton = input.nextElementSibling.querySelector('button');
        addButton.onclick = () => {
            this.addComment(this.replyToId);
            this.replyToId = null;
            input.placeholder = 'Add a comment... Use @ to mention someone';
        };
    }

    renderError(message) {
        this.container.innerHTML = `
            <div class="alert alert-danger">
                Failed to load comments: ${message}
            </div>
        `;
    }

    showNotification(message) {
        // Simple notification - can be enhanced with toast library
        const notification = document.createElement('div');
        notification.className = 'notification success';
        notification.textContent = message;
        document.body.appendChild(notification);

        setTimeout(() => notification.remove(), 3000);
    }
}

// Global instance (can be initialized from page)
let commentsPanel = null;

function initCommentPanel(documentId) {
    commentsPanel = new CommentsPanel(documentId);
    commentsPanel.init();
}
