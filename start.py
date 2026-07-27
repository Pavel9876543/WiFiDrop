import uvicorn

from app.config.settings import get_settings
from app.utils.network import get_local_ipv4_addresses


def main() -> None:
    settings = get_settings()
    print(f"\n{settings.app_name} is ready:")
    print(f"  This computer: http://localhost:{settings.port}")
    for address in get_local_ipv4_addresses():
        print(f"  Local network: http://{address}:{settings.port}")
    print("\nPress Ctrl+C to stop the server.\n")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
        workers=1,
    )


if __name__ == "__main__":
    main()
