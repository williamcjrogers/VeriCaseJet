class EmailProcessor:
    def __init__(self):
        # minimal state if needed later
        self._processed_count = 0

    def process_email(self, email_data):
        """Process a single email represented as a dict.

        Expected minimal shape:
            { 'subject': str, 'body': str, 'attachments': [..] }

        Returns a processed dict or None for empty/invalid input.
        """
        if not email_data or not isinstance(email_data, dict):
            return None

        subject = email_data.get('subject')
        body = email_data.get('body')

        if subject is None and body is None:
            return None

        attachments = self.handle_attachments(email_data)
        metadata = self.extract_metadata(email_data)

        result = {
            'subject': subject,
            'body': body,
            'attachments': attachments,
            'metadata': metadata,
        }

        # simple content analysis placeholder
        result['summary'] = self.analyze_content(email_data)

        self._processed_count += 1
        return result

    def handle_attachments(self, email_data):
        """Return list of attachments (or empty list)."""
        if not email_data or 'attachments' not in email_data:
            return []
        att = email_data.get('attachments') or []
        # normalize to list
        if isinstance(att, list):
            return att
        return [att]

    def extract_metadata(self, email_data):
        """Extract minimal metadata from email dict."""
        if not email_data or not isinstance(email_data, dict):
            return {}
        return {
            'from': email_data.get('from'),
            'to': email_data.get('to'),
            'date': email_data.get('date')
        }

    def analyze_content(self, email_data):
        """Provide a tiny content summary (first 120 chars of body)."""
        body = None
        if isinstance(email_data, dict):
            body = email_data.get('body')
        if not body:
            return ''
        return body[:120]