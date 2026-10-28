"""Domen xatolari. Servislar ChatError ko'taradi, API/buyruq qatlami uni foydalanuvchiga ko'rsatadi."""


class ChatError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status
