"""Public deployment identity, identical in source and EXE. No credentials here."""

# Temporarily suspended at the owner's request. Preserve implementation/data.
# This is a release policy, not a user setting or environment override.
ONLINE_ACCESS_ENABLED = False

# Before re-enabling: deploy access_server, set its HTTPS URL and rebuild.
# When enabled, empty/malformed configuration still fails CLOSED.
AUTH_SERVER_URL = ""
POLL_SECONDS = 15
CONNECTION_GRACE_SECONDS = 45
