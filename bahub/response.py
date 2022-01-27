
from abc import ABC as AbstractClass, abstractmethod


class Response(AbstractClass):
    @abstractmethod
    def to_status_message(self) -> str:
        """Formats the response as user-readable to show user as a message"""

        pass

