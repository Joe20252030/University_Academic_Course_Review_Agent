from importlib.metadata import version as _version, PackageNotFoundError as _PackageNotFoundError

try:
    __version__: str = _version("uacragent")
except _PackageNotFoundError:
    # Running directly from source without `pip install`
    __version__ = "0.3.1"
