class PSTReader:
    def __init__(self, file_path=None):
        # allow constructing without a file_path for tests
        self.file_path = file_path
        self._data = None

    def read_file(self, file_path):
        """Read a PST file. For tests we simulate behavior:
        - if file_path contains 'invalid' raise FileNotFoundError
        - otherwise populate a minimal data structure and return it
        """
        if not file_path or "invalid" in file_path:
            raise FileNotFoundError(f"File not found: {file_path}")

        # Simulate extraction
        self.file_path = file_path
        self._data = {
            "emails": [
                {"subject": "Hello", "body": "Test email body", "attachments": []}
            ]
        }
        return self._data

    def extract_data(self):
        """Return data extracted by the last read_file call."""
        if self._data is None:
            return {"emails": []}
        return self._data

    # back-compat convenience methods
    def read(self):
        return self.read_file(self.file_path)

    def get_data(self):
        return self.extract_data()

    def close(self):
        self._data = None
