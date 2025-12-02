class SQLiteBackend:
    def __init__(self, db_name):
        self.db_name = db_name
        self.connection = None

    def connect(self):
        import sqlite3

        self.connection = sqlite3.connect(self.db_name)

    def close(self):
        if self.connection:
            self.connection.close()

    def create_table(self, table_name, columns):
        cursor = self.connection.cursor()
        columns_with_types = ", ".join([f"{col} TEXT" for col in columns])
        cursor.execute(
            f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_with_types})"
        )
        self.connection.commit()

    def insert_data(self, table_name, data):
        cursor = self.connection.cursor()
        placeholders = ", ".join(["?" for _ in data])
        cursor.execute(f"INSERT INTO {table_name} VALUES ({placeholders})", data)
        self.connection.commit()

    def fetch_data(self, table_name):
        cursor = self.connection.cursor()
        cursor.execute(f"SELECT * FROM {table_name}")
        return cursor.fetchall()
