"""Experimental image endpoints remain absent on standard production import."""
import importlib


def test_worker_entrypoint_keeps_experimental_images_unmounted():
    module = importlib.import_module("app.entrypoint")
    paths = {route.path for route in module.fastapi_app.routes}
    assert not any(path.startswith("/experimental/images") for path in paths)
