import argparse
import datetime
import logging
from typing import Dict

import geocoder


class Customer():
    """Defines a customer: address, customer number, lat/long, whether it is in need of delivery, delivery date, delivery order."""

    def __init__(
        self,
        cust_id: str,
        name: str,
        address: str,
        latitude: float,
        longitude: float,
        visit: bool = False,
        delivery_day: str = None,
        delivery_order: int = -1,
    ):
        """Creates a customer.
        
        Fields:

            cust_id: unique customer identifier
            name: customer's name
            address: customer's address
            lat: customer's latitude
            lon: customer's longitude
            visit: whether the customer needs to be visited
            delivery_day: the required day on which the customer is to be visited
            delivery_order: the required position in the route in which the customer should be visited

        """

        self.cust_id = cust_id
        self.name = name
        self.address = address
        self.lat = latitude
        self.lon = longitude
        self.visit = visit
        self.delivery_day = delivery_day
        self.delivery_order = delivery_order
        
