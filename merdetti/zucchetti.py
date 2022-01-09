import os
import re
from datetime import datetime

import requests

LOGIN_PATH = "/servlet/cp_login"
SQL_DATA_PROVIDER_PATH = "/servlet/SQLDataProviderServer"
STAMP_PATH = "/servlet/ushp_ftimbrus"
M_CID_PATH = "/jsp/gsmd_container.jsp?containerCode=MYDESK"

REQUEST_TIMEOUT = 16
USER_AGENT = (
    "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:84.0) Gecko/20100101 Firefox/84.0"
)


class ApiError(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class ZucchettiApi:
    def __init__(self, username, password) -> None:
        self._username = username
        self._password = password
        self._session = None

        self._base_url = os.getenv("ZUCCHETTI_BASE_URL")

    def login(self) -> None:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT

        data = {
            "m_cUserName": self._username,
            "m_cPassword": self._password,
            "m_cAction": "login",
        }
        response = session.post(
            self._base_url + LOGIN_PATH, data=data, timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            raise ApiError(f"Invalid status code: {response.status_code}")

        message = response.headers.get("JSURL-Message")
        if message and "non riconosciuto" in message:
            raise InvalidCredentials()

        self._session = session

    def status(self) -> dict:
        data = {
            "rows": "10",
            "startrow": "0",
            "count": "true",
            "sqlcmd": "rows:ushp_fgettimbrus",
            "pDATE": datetime.now().strftime("%Y-%m-%d"),
        }
        response = self._session.post(
            self._base_url + SQL_DATA_PROVIDER_PATH, data, timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            raise ApiError(f"Invalid status code: {response.status_code}")

        result = response.json()
        if "Data" not in result:
            raise ApiError(f"Invalid response from server: {result}")

        stamps = {}
        data = result["Data"]

        if len(data) > 0:
            for stamp in data[:-1]:
                stamps[stamp[2]] = stamp[1]

        return stamps

    def enter(self):
        self._stamp("E")

    def exit(self):
        self._stamp("U")

    def _stamp(self, direction):
        response = self._session.get(
            self._base_url + M_CID_PATH, timeout=REQUEST_TIMEOUT
        )
        if response.status_code != 200:
            raise ApiError(f"Invalid status code: {response.status_code}")

        match = re.search("this.splinker10.m_cID='(.+?)';", response.text)
        if not match:
            raise ApiError(f"Failed to find m_cID in response")

        m_cID = match.group(1)

        data = {"verso": direction, "causale": "", "m_cID": m_cID}
        response = self._session.post(
            self._base_url + STAMP_PATH, data, timeout=REQUEST_TIMEOUT
        )
        if response.status_code != 200:
            raise ApiError(f"Invalid status code: {response.status_code}")

        result = response.text
        if "routine eseguita" not in result:
            raise ApiError(f"Invalid response from server on stamp: {result}")
