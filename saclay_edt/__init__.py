"""Client for the Université Paris-Saclay Celcat Calendar (edt.universite-paris-saclay.fr): login + endpoints."""
from .auth import AuthError, login
from .client import (
    ApiError, ENTITIES, GROUP, MODULE, ROOM, STAFF, STUDENT, CelcatClient, Event, Resource, credentials_from_env,
)

__all__ = [
    "ApiError", "AuthError", "login", "CelcatClient", "Event", "Resource", "credentials_from_env",
    "ENTITIES", "GROUP", "MODULE", "ROOM", "STAFF", "STUDENT",
]
