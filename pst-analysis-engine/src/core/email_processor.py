class EmailProcessor:
    SIGNATURE_PATTERNS = [
        'image001.png', 'image002.png', 'image003.png',
        'image001.jpg', 'image002.jpg', 'image003.jpg',
        'image001.gif', 'image002.gif', 'image003.gif',
    ]
    
    def __init__(self):
        self._processed_count = 0

    def process_email(self, email_data):
        """Process a single email - one message per row.
        
        Expected shape:
            { 'subject': str, 'body': str, 'attachments': [..], 'message_id': str }
        
        Returns processed dict or None for invalid input.
        """
        if not email_data or not isinstance(email_data, dict):
            return None

        subject = email_data.get('subject')
        body = email_data.get('body')

        if subject is None and body is None:
            return None

        attachments, inline_images = self.handle_attachments(email_data)
        metadata = self.extract_metadata(email_data)

        result = {
            'subject': subject,
            'body': body,
            'attachments': attachments,
            'inline_images': inline_images,
            'metadata': metadata,
            'has_attachments': len(attachments) > 0,
        }

        result['summary'] = self.analyze_content(email_data)
        self._processed_count += 1
        return result

    def handle_attachments(self, email_data):
        """Separate real attachments from signature files.
        
        Returns: (attachments_list, inline_images_list)
        """
        if not email_data or 'attachments' not in email_data:
            return [], []
        
        att = email_data.get('attachments') or []
        if not isinstance(att, list):
            att = [att]
        
        attachments = []
        inline_images = []
        
        for item in att:
            if not isinstance(item, dict):
                continue
            
            filename = item.get('filename', '').lower()
            is_inline = item.get('is_inline', False)
            content_id = item.get('content_id')
            
            is_signature = any(sig in filename for sig in self.SIGNATURE_PATTERNS)
            
            if is_signature or (is_inline and content_id):
                inline_images.append(item)
            else:
                attachments.append(item)
        
        return attachments, inline_images

    def extract_metadata(self, email_data):
        """Extract metadata from email dict."""
        if not email_data or not isinstance(email_data, dict):
            return {}
        return {
            'from': email_data.get('from'),
            'to': email_data.get('to'),
            'cc': email_data.get('cc'),
            'date': email_data.get('date'),
            'message_id': email_data.get('message_id'),
            'in_reply_to': email_data.get('in_reply_to'),
            'thread_topic': email_data.get('thread_topic'),
        }

    def analyze_content(self, email_data):
        """Provide content summary (first 120 chars of body)."""
        body = None
        if isinstance(email_data, dict):
            body = email_data.get('body')
        if not body:
            return ''
        return body[:120]
    
    def is_signature_file(self, filename):
        """Check if filename matches signature file patterns."""
        if not filename:
            return False
        filename_lower = filename.lower()
        return any(sig in filename_lower for sig in self.SIGNATURE_PATTERNS)