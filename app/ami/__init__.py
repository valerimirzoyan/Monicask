from app.ami.base import AMIClient, AMIConnectionError, AMIError
from app.ami.client import RealAMI
from app.ami.manager import AMIManager, SyncResult
from app.ami.mock import MockAMI


def build_ami(settings) -> AMIClient:
    if settings.ami_host:
        return RealAMI(
            host=settings.ami_host,
            port=settings.ami_port,
            username=settings.ami_username,
            secret=settings.ami_secret,
            timeout=settings.ami_timeout,
        )
    return MockAMI()


__all__ = [
    "AMIClient",
    "AMIConnectionError",
    "AMIError",
    "AMIManager",
    "MockAMI",
    "RealAMI",
    "SyncResult",
    "build_ami",
]
