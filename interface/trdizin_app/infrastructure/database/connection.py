from typing import Any

from trdizin_app.application.exceptions import (
    DatabaseUnavailableError,
)
from trdizin_app.infrastructure.config.settings import (
    Settings,
)
from trdizin_app.infrastructure.database.mysql.connection import (
    create_mysql_connection,
)
from trdizin_app.infrastructure.database.sqlite.connection import (
    create_sqlite_connection,
)


def create_database_connection(
    settings: Settings,
) -> Any:
    if settings.database_backend == "mysql":
        return create_mysql_connection(settings)

    if settings.database_backend == "sqlite":
        return create_sqlite_connection(settings)

    raise DatabaseUnavailableError(
        "Desteklenmeyen veritabanı türü: "
        f"{settings.database_backend}"
    )
