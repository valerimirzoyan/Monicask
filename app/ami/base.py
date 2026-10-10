class AMIError(Exception):
    """Command was rejected or could not be confirmed."""


class AMIConnectionError(AMIError):
    """AMI transport is unavailable."""


class AMIClient:
    mode = "base"

    def connect(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def is_connected(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def pause(self, queue: str, member: str, reason: str = "") -> None:  # pragma: no cover
        raise NotImplementedError

    def unpause(self, queue: str, member: str, reason: str = "") -> None:  # pragma: no cover
        raise NotImplementedError

    def queue_paused_state(self) -> dict[tuple[str, str], bool]:  # pragma: no cover
        raise NotImplementedError
