class IMAPAdapter:
    def __init__(self, server, username, password):
        self.server = server
        self.username = username
        self.password = password

    def connect(self):
        # Code to connect to the IMAP server
        pass

    def fetch_emails(self):
        # Code to fetch emails from the IMAP server
        pass

    def migrate_email(self, email):
        # Code to migrate a single email to the desired format
        pass

    def disconnect(self):
        # Code to disconnect from the IMAP server
        pass
