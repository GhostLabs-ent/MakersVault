# Synthetic nested-mount fixture

Original minimal manifest, not a vendor file. The isolated verification driver
bind-mounts this directory at `/location-mount` and its `system` child again at
`/location-mount/system` to prove same-device nested-directory rejection. Tests
never mount filesystems themselves or change host privileges.
