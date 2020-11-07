from typing import Any, Dict, List, Optional, Tuple
import ast
import json
import logging

from openrouteservice import client, directions, distance_matrix
import geocoder

from data import address_fixes, api_key
from gocheche.core import Customer, RunParams

DEPOT_CUST_ID = "000000"
OSR_API_KEY = api_key.MY_OSR_API_KEY


def groom_address(address: str) -> str:
    """Makes an address amenable to geocoding."""

    # TODO currently just using a manual mapping, but regex or something similar
    # would be more robust.
    return address_fixes.addr_mappings.get(address, address)
    

def get_latlon(address: str) -> Tuple[float, float]:
    """Retrieves (latitude, longitude) for the given customer."""
    
    if not address:
        raise ValueError(
            f"No (lat, lon) can be generated from address '{address}'."
        )

    logging.info(f"Geocoding the following address:\n\t{address}")
    groomed_address = groom_address(address)
    
    g = geocoder.osm(groomed_address)

    return (g.json['lat'], g.json['lng'])


def load_json(filename: str) -> Dict:
    """Returns the JSON file's contents as a dict."""
    
    with open(filename, 'r') as json_file:
        return json.load(json_file)


def write_json(obj_to_write: Any, filename: str):
    """Writes the object to a JSON file."""
    
    with open(filename, 'w') as json_file:
        json.dump(obj_to_write, json_file, indent=4)


def load_visits(visits_filename: str) -> List:
    """Loads the file of customer IDs to visit into a *sorted* list."""
    
    visits = load_json(visits_filename)['visit']
    visits.insert(0, DEPOT_CUST_ID)
    # ^^ NOTE: Other methods (router.create_model_data) assume depot is in the first slot.
    # Beware of changing this in the future.
    if len(visits) != len(set(visits)):
        return ValueError("Some customers are duplicated in the visits file.")
    return sorted(visits)


def load_customers(customers_filename: str, to_visit: List[str], keep_all: bool = False, refresh_latlon: bool = False) -> Dict[str, Customer]:
    """Loads the address file into a dict of customers, keyed on their cust_id.
    
    Inputs:
        to_visit: Subset of customers that need to be visited (should be a list of cust_ids).

        refresh_latlon: Whether to refresh all customers' lat/lon coords (by default we only refresh
            those that are missing).

        keep_all: Whether to return ALL customers (including those that don't need to visited).
            
    """

    customers = load_json(customers_filename)['customers']
    updated = False
    for customer in customers:
        if (
            refresh_latlon
            or customer.get('latitude', None) is None
            or customer.get('longitude', None) is None
        ):
            logging.info(f"Updating customer's lat/lon coords: {customer}")
            updated = True
            lat, lon = get_latlon(customer['address'])
            customer['latitude'] = lat
            customer['longitude'] = lon
            customer['visit'] = customer['cust_id'] in to_visit
    
    if updated:
        logging.info(f"Writing an updated customers file: {customers_filename}")
        to_write = {
            'customers': [
                {k:v for k,v in customer.items() if k != 'visit'} # Don't want to write the to-visit field to file
                for customer in customers
            ]
        }
        write_json(to_write, customers_filename)

    if keep_all:
        return {
            customer['cust_id']: Customer(**customer)
            for customer in cutomers
        }
    else:
        return {
            customer['cust_id']: Customer(**customer)
            for customer in customers
            if customer['cust_id'] in to_visit
        }


def dist_dict_from_json(json_dists: Dict[str, float]) -> Dict[Tuple[str, str], float]:
    """Converts a JSON-compatible distances dictionary into our desired format where
    keys are Tuples instead of strings.
    """

    return {ast.literal_eval(custs_key): dist for custs_key, dist in json_dists.items()}


def dist_dict_to_json(dist_dict: Dict[Tuple[str, str], float]) -> Dict[str, float]:
    """Converts a JSON-compatible distances dictionary into our desired format where
    keys are Tuples instead of strings.
    """
    
    return {str(custs_key): dist for custs_key, dist in dist_dict.items()}


def load_distances(distances_filename: str) -> Dict[Tuple[str, str], float]:
    """Loads the distances file into a dict of distances, keyed on (origin, destination) tuples,
    where origin and destination are customers' cust_ids.
    """

    raw_distances_dict = load_json(distances_filename)['distances']
    distances_dict = dist_dict_from_json(raw_distances_dict)
    return distances_dict


def load_params(params_filename: str) -> Dict:
    """Loads parameters and constraints from file."""
    return RunParams(**load_json(params_filename))


def _ensure_no_missing_customers(visits: List[str], customers: Dict[str, Customer]):
    """Raises a ValueError if any IDs on the list of customers to visit are missing from the customers file."""
    missing_customers = [cust_id for cust_id in visits if cust_id not in {customer.cust_id for customer in customers.values()}]
    if missing_customers:
        raise ValueError(f"Not all to-visit customers are listed in the customer file:\n\t{missing_customers}")


def _find_missing_distances(visits: List[str], distances: Dict[Tuple[str, str], float]):
    """Raises a ValueError if any customer pairs are missing from the distances file."""

    missing_distance_pairs = []
    for i, cust_1 in enumerate(visits):
        for cust_2 in visits[i+1: ]:
            if (cust_1, cust_2) not in distances:
                missing_distance_pairs.append((cust_1, cust_2))
            if (cust_2, cust_1) not in distances:
                missing_distance_pairs.append((cust_2, cust_1))
    if len(missing_distance_pairs) > 0:
        raise ValueError(f"Not all pairs of the to-visit customers are covered by the distances file:\n\t{missing_distance_pairs}")


def _check_for_missing_distances(visits: List[str], distances: Dict[Tuple[str, str], float]) -> bool:
    """Specifies whether any customer pairs are missing from the distances file."""

    for i, cust_1 in enumerate(visits):
        for cust_2 in visits[i+1: ]:
            if (cust_1, cust_2) not in distances or (cust_2, cust_1) not in distances:
                return True
    return False


def get_distances(customers: Dict[str, Customer], filename: Optional[str] = None) -> Dict[Tuple[str, str], float]:
    """Uses OpenRouteService to compute the distance matrix.

    For each pair of customers in `customers`, computes the distance of the shortest route between them.

    Inputs:

        customers: The list of customers (importantly, with lat/lon coords) for which to get the
            distance matrix

        filename: The name of the file to which to write the resulting distance matrix.

    Outputs:

        The distance matrix as a dict, where a key is a tuple (i,j) of customer IDs, and its value
            is the distance from i to j.

    """

    # Instantiate our client to pull the distance matrix.
    osr_client = client.Client(key=OSR_API_KEY)

    # Get the list of customer coordinates that we want to get the distance matrix for, along with
    # their IDs.
    # Note that they're in (lon, lat) order instead of (lat, lon).
    cust_coords_w_id = [(customer.cust_id, (customer.lon, customer.lat)) for customer in customers.values()]

    # Number of customers.
    n = len(cust_coords_w_id)
    
    # Define the request we'll make to fetch the distance matrix.
    request = {
        'locations': [cust_coords[1] for cust_coords in cust_coords_w_id],
        'profile': 'driving-car',
        'metrics': ['duration'],
    }
    
    # Get the matrix
    distance_matrix = osr_client.distance_matrix(**request)['durations']
    logging.info(f"Distance matrix retrieved ({n} x {n}).")
    print(distance_matrix)

    # Convert it to the format we want to save it in.
    distance_dict = {
        (cust_coords_w_id[i][0], cust_coords_w_id[j][0]): distance_matrix[i][j]
        for i in range(n) for j in range(n) 
    }

    if filename:
        writable_dict = dist_dict_to_json(distance_dict)
        write_json({'distances': writable_dict}, filename)

    return distance_dict


def get_distance_matrix(visits: List[str], distances: Dict[Tuple[str, str], float]) -> List[List[float]]:
    """Produces a distance matrix for the customers in `visits`."""

    return [[distances[i,j] for j in visits] for i in visits]


def get_route_geojson(route: List[Customer]):
    
    # Get the coordinates of our route, turn them into directions
    coords = [(cust.lon, cust.lat) for cust in route]

    # Instantiate our client to pull the directions.
    osr_client = client.Client(key=OSR_API_KEY)
    
    request = {
        'coordinates': coords,
        'profile': 'driving-car',
        'geometry': 'true',
        'format_out': 'geojson',          
    }

    # Make the request, getting the directions as a geojson
    result = osr_client.directions(**request)

    return result


def stringify_route(route:[List[Customer]]) -> str:
    strd_route = [cust.out_dict for cust in route]
    return strd_route


def get_center_of_custs(visits: List[str], customers: Dict[str, Customer]) -> Tuple[float, float]:
    """Gets the (lat, lon) of the center of the to-visit customers."""

    to_visit = [(customers[cust_id].lat, customers[cust_id].lon) for cust_id in visits]
    
    # Tidy, but not super efficient implementation here.
    # Could just do one sweep through, but unless we add way more customers, it
    # shouldn't be a problem.
    return (
        (max(coords[0] for coords in to_visit) + min(coords[0] for coords in to_visit)) / 2,
        (max(coords[1] for coords in to_visit) + min(coords[1] for coords in to_visit)) / 2,
    )