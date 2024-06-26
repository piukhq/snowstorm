"""FreshService Task."""

from time import sleep

import pendulum
import requests
from loguru import logger
from sqlalchemy.orm import Session

from snowstorm.database import FreshService, engine
from snowstorm.settings import settings


class FreshServiceStats:
    """FreshService Stats Task."""

    def __init__(self, days: int, rate_limit_timeout: int) -> None:
        """Initialize FreshServiceStats."""
        self.status_mapping = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
        self.days = days
        self.api_key = settings.freshservice_api_key
        self.rate_limit_timeout = rate_limit_timeout

    def fetch_stats(self) -> None:
        """Fetch FreshService Stats."""
        rate_limit_status_code = 429
        page = 1
        tickets = []
        while True:
            logger.warning(f"Processing page {page}")
            lookup = requests.get(
                "https://bink.freshservice.com/api/v2/tickets",
                params={
                    "page": page,
                    "per_page": 100,
                    "updated_since": pendulum.today().subtract(days=1, hours=1),
                },
                auth=(self.api_key, "X"),
                timeout=5,
            )
            if lookup.status_code == rate_limit_status_code:
                logger.warning(f"Rate limit hit, sleeping {self.rate_limit_timeout} seconds")
                sleep(self.rate_limit_sleep)
                continue
            if len(lookup.json()["tickets"]) != 0:
                page += 1
                tickets = tickets + lookup.json()["tickets"]
            else:
                logger.warning("No pages remaining", extra={"ticket_count": len(tickets)})
                break

        with Session(engine) as session:
            for ticket in tickets:
                try:
                    sla = ticket["custom_fields"]["incident_sla_resolution"]
                    insert = FreshService(
                        id=ticket["id"],
                        created_at=ticket["created_at"],
                        updated_at=ticket["updated_at"],
                        status=self.status_mapping[ticket["status"]],
                        channel=ticket["custom_fields"]["channel"]
                        if ticket["custom_fields"]["channel"] != "N/A"
                        else None,
                        service=ticket["custom_fields"]["service"],
                        mi=ticket["custom_fields"]["mi"],
                        sla_breached=True if sla == "Breached" else False if sla == "Achieved" else None,
                    )
                    session.merge(insert)
                except KeyError:
                    logger.error(f"KeyError: {ticket['id']}")
                    continue
            session.commit()
