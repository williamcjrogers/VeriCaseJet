class MetadataExtractor:
    def __init__(self, email_data):
        self.email_data = email_data

    def extract_metadata(self):
        metadata = {
            'subject': self.email_data.get('subject'),
            'from': self.email_data.get('from'),
            'to': self.email_data.get('to'),
            'date': self.email_data.get('date'),
            'cc': self.email_data.get('cc'),
            'bcc': self.email_data.get('bcc'),
        }
        return metadata

    def validate_metadata(self, metadata):
        # Implement validation logic if necessary
        return True if metadata['subject'] else False