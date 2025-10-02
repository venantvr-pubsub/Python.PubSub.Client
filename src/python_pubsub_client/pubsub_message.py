from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional
from uuid import uuid4


@dataclass
class PubSubMessage:
    topic: str
    message_id: str
    message: Any
    producer: str

    @staticmethod
    def new(
            topic: str, message: Any, producer: str, message_id: Optional[str] = None
    ) -> "PubSubMessage":
        """
        Create a new PubSubMessage instance.

        :param topic: Topic of the message
        :param message: Message content
        :param producer: Producer name
        :param message_id: Unique message ID (optional, defaults to UUID)
        :return: PubSubMessage instance
        """
        return PubSubMessage(
            topic=topic, message_id=message_id or str(uuid4()), message=message, producer=producer
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the message to a dictionary.

        :return: Dictionary representation of the message
        """
        return asdict(self)
