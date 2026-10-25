class KeyrockError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status: int = status
        self.message: str = message


class FiwareError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status: int = status
        self.message: str = message
