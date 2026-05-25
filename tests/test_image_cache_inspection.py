from scripts.inspect_image_caches import find_cache_paths


def test_cache_inspection_accepts_runtime_artifacts():
    paths = [
        "/app/src/api/server.py",
        "/usr/local/lib/python3.11/site-packages/fastapi/__init__.py",
        "/usr/local/lib/python3.11/site-packages/pkg/__pycache__/mod.pyc",
    ]

    assert find_cache_paths(paths) == []


def test_cache_inspection_rejects_dependency_cache_directories():
    paths = [
        "/app/src/api/server.py",
        "/root/.cache/pip/http/example.body",
    ]

    assert find_cache_paths(paths) == [
        "/root/.cache/pip/http/example.body",
    ]
