import os
import re
from datetime import datetime, timedelta

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

    def last_stamps(self, interval=12) -> list:
        now = datetime.now()
        limit = now - timedelta(hours=interval)

        stamps = []

        def add_stamps(day):
            for stamp in self._get_stamps(day):
                stamp_time = datetime.strptime(stamp[1], "%H:%M")
                if day.replace(hour=stamp_time.hour, minute=stamp_time.minute) > limit:
                    stamps.append(stamp)

        if limit.day != now.day:
            add_stamps(limit)
        add_stamps(now)

        return stamps

    def _get_stamps(self, day) -> list:
        data = {
            "rows": "10",
            "startrow": "0",
            "count": "true",
            "sqlcmd": "rows:ushp_fgettimbrus",
            "pDATE": day.strftime("%Y-%m-%d"),
        }
        response = self._session.post(
            self._base_url + SQL_DATA_PROVIDER_PATH, data, timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            raise ApiError(f"Invalid status code: {response.status_code}")

        result = response.json()
        if "Data" not in result:
            raise ApiError(f"Invalid response from server: {result}")

        if len(result["Data"]) > 0:
            return [(stamp[2], stamp[1]) for stamp in result["Data"][:-1]]

        return []

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
        return
        response = self._session.post(
            self._base_url + STAMP_PATH, data, timeout=REQUEST_TIMEOUT
        )
        if response.status_code != 200:
            raise ApiError(f"Invalid status code: {response.status_code}")

        result = response.text
        if "routine eseguita" not in result:
            raise ApiError(f"Invalid response from server on stamp: {result}")
