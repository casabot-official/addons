"""CASABOT Config Flow"""
import voluptuous as vol
from homeassistant import config_entries
from .coordinator import DOMAIN


class CasabotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """CASABOT setup flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """First step - get DB credentials."""
        errors = {}

        if user_input is not None:
            valid = await self.hass.async_add_executor_job(
                _test_db_connection, user_input
            )
            if valid:
                return self.async_create_entry(
                    title="CASABOT - AI Home",
                    data=user_input,
                )
            else:
                errors["base"] = "cannot_connect"

        schema = vol.Schema({
            vol.Optional("db_host", default="127.0.0.1"): str,
            vol.Optional("db_port", default=3306): int,
            vol.Optional("db_user", default="root"): str,
            vol.Optional("db_password", default=""): str,
            vol.Optional("db_name", default="homeassistant"): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )


def _test_db_connection(config: dict) -> bool:
    """Try connecting to MariaDB - returns True if success."""
    try:
        import pymysql
        conn = pymysql.connect(
            host=config.get("db_host", "127.0.0.1"),
            port=int(config.get("db_port", 3306)),
            user=config.get("db_user", "root"),
            password=config.get("db_password", ""),
            database=config.get("db_name", "homeassistant"),
            connect_timeout=5,
        )
        conn.close()
        return True
    except Exception:
        return False