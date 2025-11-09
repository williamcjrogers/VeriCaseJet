class StorageManager:
    def __init__(self, backend):
        self.backend = backend

    def save_data(self, data):
        self.backend.store(data)

    def retrieve_data(self, query):
        return self.backend.fetch(query)

    def delete_data(self, identifier):
        self.backend.remove(identifier)

    def update_data(self, identifier, new_data):
        self.backend.update(identifier, new_data)