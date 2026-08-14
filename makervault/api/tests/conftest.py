import os


os.environ["MAKERSVAULT_ENV"] = "test"
os.environ["AUTH_USERNAME"] = "admin"
os.environ["AUTH_PASSWORD"] = "test-only-password"
os.environ["AUTH_SECRET"] = (
    "test-only-signing-secret-that-is-never-used-in-production"
)
