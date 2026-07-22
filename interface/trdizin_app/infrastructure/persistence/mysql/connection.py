import logging

import mysql.connector

from trdizin_app.application.ports.persistence import RepositoryUnavailableError


LOGGER = logging.getLogger(__name__)


class MySqlConnectionFactory:
    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self.options = dict(host=host, port=port, database=database, user=user, password=password)

    def connect(self):
        try:
            return mysql.connector.connect(**self.options)
        except mysql.connector.Error as error:
            LOGGER.exception("MySQL bağlantısı kurulamadı")
            raise RepositoryUnavailableError("Kalıcılık veritabanına erişilemiyor.") from error
