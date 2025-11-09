import unittest
from src.migration.migration_engine import MigrationEngine

class TestMigrationFlow(unittest.TestCase):

    def setUp(self):
        self.migration_engine = MigrationEngine()

    def test_migration_to_exchange(self):
        # Simulate migration to Exchange
        result = self.migration_engine.migrate_to_exchange('test.pst')
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], 'Migration to Exchange completed successfully.')

    def test_migration_to_imap(self):
        # Simulate migration to IMAP
        result = self.migration_engine.migrate_to_imap('test.pst')
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], 'Migration to IMAP completed successfully.')

    def test_migration_failure(self):
        # Simulate a migration failure
        result = self.migration_engine.migrate_to_exchange('invalid.pst')
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], 'Migration failed due to invalid PST file.')

if __name__ == '__main__':
    unittest.main()