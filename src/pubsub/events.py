from dataclasses import dataclass


@dataclass(frozen=True)
class AllProcessingCompleted:
    payload: bool = True
