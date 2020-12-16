import argparse
import datetime
import logging
from typing import Dict, Tuple

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
        self.out_dict = {
            'Name': self.name,
            'ID': self.cust_id,
            'Address': self.address,
        }

    def get_coords(self, lat_first: bool = False) -> Tuple[float, float]:
        """Returns the customer's coordinates.

        Inputs:

            lat_first: Whether the tuple should be returned as (lat, lon) instead of
                the default (lon, lat).

        """
        return (self.lat, self.lon) if lat_first else (self.lon, self.lat)
    

class RunParams():
    """Defines a body of parameters controlling the run of the routing engine."""

    def __init__(
        self,
        constraints: Optional[Dict]=None,
        n_routes: Optional[int]=None,
    ):
        """Creates a RunParams object.
        
        Fields:

            constraints: constraints that the routing solution must ensure
            n_routes: number of routes in the solution.

        """

        self.constraints = constraints if constraints is not None else {}
        self.n_routes = n_routes if n_routes is not None else 1
