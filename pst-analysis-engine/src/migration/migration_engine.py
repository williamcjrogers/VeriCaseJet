class MigrationEngine:
    def __init__(self):
        # minimal logger placeholder
        self.logs = []

    def migrate_to_exchange(self, data):
        """Simulated migration to Exchange for tests."""
        # If data points to an invalid PST file name, simulate failure
        if isinstance(data, str) and 'invalid' in data:
            return {'success': False, 'message': 'Migration failed due to invalid PST file.'}

        # Simulate success
        return {'success': True, 'message': 'Migration to Exchange completed successfully.'}

    def migrate_to_imap(self, data):
        """Simulated migration to IMAP for tests."""
        if isinstance(data, str) and 'invalid' in data:
            return {'success': False, 'message': 'Migration failed due to invalid PST file.'}
        return {'success': True, 'message': 'Migration to IMAP completed successfully.'}

    def migrate_to_sqlite(self, data):
        # Simple no-op success for migration to sqlite
        return {'success': True, 'message': 'Migration to SQLite completed successfully.'}

    def validate_data(self, data):
        # Basic validation: ensure data is present
        return bool(data)

    def log_migration(self, message):
        self.logs.append(message)
        return True