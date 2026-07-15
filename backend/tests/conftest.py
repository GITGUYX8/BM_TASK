import pytest


@pytest.fixture
def sample_order_data():
    return {
        "title": "Laptop won't boot",
        "description": "Dell XPS 15, error 0x800F0922 after Windows update",
        "priority": "high",
    }
