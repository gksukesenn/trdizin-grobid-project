from typing import Any

import mysql.connector
from mysql.connector import Error

from trdizin_app.application.exceptions import (
    DatabaseUnavailableError,
)
from trdizin_app.infrastructure.config.settings import (
    Settings,
)


def create_mysql_connection(
    settings: Settings,
) -> Any:
    try:
        return mysql.connector.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            database=settings.mysql_database,
            user=settings.mysql_user,
            password=settings.mysql_password,
            charset="utf8mb4",
            connection_timeout=15,
        )

    except Error as error:
        raise DatabaseUnavailableError(
            "MySQL bağlantısı kurulamadı: "
            f"{error}"
        ) from error
