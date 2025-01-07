"""Test configuration and shared fixtures."""
from dotenv import load_dotenv
import os
import pytest

# Load test environment before any modules are imported
load_dotenv('.env.test', override=True)
