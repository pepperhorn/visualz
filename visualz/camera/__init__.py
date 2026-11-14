"""T2 seam: interval still capture, no camera activity in T1."""


class Worker:
    """Worker(store): start()/close() own worker; snap(set_id) requests a still.

    latest(set_id) returns Pillow image or None without waiting; clear(set_id)
    removes captured photos. devices() returns [{id,name}]. All calls nonblocking.
    """

    def __init__(self, store):
        self.store = store

    def start(self):
        pass

    def snap(self, set_id):
        pass

    def latest(self, set_id):
        return None

    def clear(self, set_id):
        pass

    def devices(self):
        return []

    def close(self):
        pass
