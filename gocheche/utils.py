from typing import Any, Dict, List, Optional, Tuple, Union
import ast
import csv
import glob
import json
import logging
import os

from openrouteservice import client, distance_matrix
import geocoder
import usaddress

from gocheche.core import Customer, RunParams


DEPOT_CUST_ID = "000000"
NAME_COL_IDX = 0
ADDRESS_COL_IDX = 1


def load_json(filename: str) -> Dict:
    """Returns the JSON file's contents as a dict."""
    
    with open(filename, 'r') as json_file:
        return json.load(json_file)


def write_json(obj_to_write: Any, filename: str):
    """Writes the object to a JSON file."""
    
    with open(filename, 'w') as json_file:
        json.dump(obj_to_write, json_file, indent=4)


def ordinal(n: Union[str, int]) -> str:
    return "%d%s" % (int(n),"tsnrhtdd"[(int(n)//10%10!=1)*(int(n)%10<4)*int(n)%10::4])

def get_address(address: str) -> Tuple[str, str, str]:
    """Gets a geocodable version of `address`, plus its latitude and longitude."""

    # Try to geocode the address as given
    g = geocoder.osm(address)

    if g.json is not None:

        # Geocoding was successful. Return the result
        return (
            # First part is a nicely formatted address
            f"{g.json['housenumber']} {g.json['street']}, {g.json['city']}, {g.json['state']} {g.json['postal']}",
            # Second is the latitude
            g.json['lat'],
            # And third is the longitude
            g.json['lng']
        )

    # Geocoding was unsuccessful.
    # Let's try to create a cleaner address by first parsing out the pieces we need, then try again.
    
    # Parsing the address components...
    parsed, addr_type = usaddress.tag(address)
    if addr_type != "Street Address":
        raise ValueError(f"Address could not be properly parsed. Resulting type: {addr_type}. Result: \n{parsed}")
    
    # Trim off any whitespace from the parsed components.
    for part in parsed:
        parsed[part] = parsed[part].strip()

    reqd_address_parts = ['AddressNumber', 'StreetName', 'PlaceName']
    if any(address_part not in parsed for address_part in reqd_address_parts):
        raise ValueError(f"The address must have at least a house number, street, and city.")
    
    # Initialize the resulting address string with the address number (aka house/street number)
    new_address = parsed['AddressNumber']
    
    # If the streetname is just a number, make it ordinal
    if parsed['StreetName'].isnumeric():
        parsed['StreetName'] = ordinal(parsed['StreetName'])
    
    # Get the whole street name
    for k, v in [(k, v) for k, v in parsed.items() if k.startswith("StreetName")]:
        new_address += f" {v}"
    
    # Add the city...
    new_address += f", {parsed['PlaceName']}"
    # Add the state, if it exists
    if 'StateName' in parsed:
        new_address += f", {parsed['StateName']}"
    # And the zip code, if it exists
    if 'ZipCode' in parsed:
        new_address += f" {parsed['ZipCode']}"
    
    # Now try to geocode this improved address
    g = geocoder.osm(new_address)

    if g.json is not None:

        # Geocoding was successful. Return the result
        return (
            # First part is a nicely formatted address
            f"{g.json['housenumber']} {g.json['street']}, {g.json['city']}, {g.json['state']} {g.json['postal']}",
            # Second is the latitude
            g.json['lat'],
            # And third is the longitude
            g.json['lng']
        )
    
    # Still can't geocode the address. Throw an error
    else:
        raise ValueError(f"Could not geocode this address: {address}")


def get_known_customer(name: str, address: str, customers: List[Customer], visit: bool=True) -> Optional[Customer]:
    """If customers contains a Customer with the given name and address, returns
    that customer, with its visit field set to the value of `visit`.
    """

    for customer in customers:
        if customer.name == name and customer.address == address:
            customer.visit = visit
            return customer
    
    # No such customer found.
    return None


def get_known_customer_by_id(id: str, customers: List[Customer]) -> Optional[Customer]:
    for customer in customers:
        if customer.cust_id == id:
            return customer
    
    # No such customer found.
    return None


def load_known_customer_data(customers_filename: str) -> Tuple[List[Customer], Dict[Tuple[str, str], float]]:
    """Loads the list of known customers from customers_filename."""

    if not customers_filename or not os.path.exists(customers_filename):
        # empty list of customers, empty dict of distances
        return [], {}

    else:
        all_cust_data = load_json(customers_filename)
        custs = [Customer(**customer) for customer in all_cust_data['customers']]
        dists = dist_dict_from_json(all_cust_data['distances'])
        return custs, dists


def load_customers(
    api_key: str,
    visits_filename: str,
    customers_filename: Optional[str],
) -> Tuple[Dict[str, Customer], List, Dict[Tuple[str, str], float]]:
    """Loads customer-related data objects from file:
        element 0: dict from customer IDs to customer objects
        element 1: *sorted* list of customer IDs (depot first) that need to be visited
        element 2: distances matrix

    The visits_filename points to a CSV file with a row for each customer that needs to be visited
        in the current route. Must have columns for customers' names and addresses.

    The customers_filename points to a JSON file that contains a list of known customers, as well as
    the distances between them.
        If the filename is None or empty, we do not read any customer info from file.
        If a filename is provided but it does not exist, we write a new file containing
            the customers in visits_filename, along with the distances between them.
        If the file exists and any customers in visits_filename are not already in this file,
            then we add them to the file, along with their distances.

    """

    # If no visits filename was provided, we assume it was the last modified CSV
    # in the downloads directory:
    if len(visits_filename) == 0:
        visits_filename = get_last_modded_csv(get_known_path(path_type="downloads"))

    # Read in the file that contains known customers and their details.
    known_customers, distances_dict = load_known_customer_data(customers_filename)
    
    # Initialize the dict of current customers and the list of customer IDs to visit
    cust_dict = {}
    visits = [] 

    # Note what will be the next ID that we assign to a customer if we encounter
    # a new one.
    # If the list of customers is empty, then we start at 0.
    next_cust_id = (
        0 if not known_customers
        else max(int(customer.cust_id) for customer in known_customers) + 1
    )

    # Read in the CSV that contains the details of the customers to be visited
    with open(visits_filename) as csvfile:
        rowreader = csv.reader(csvfile)
        for row in rowreader:

            # Read its information from the row
            name = row[NAME_COL_IDX]
            address, lat, lon = get_address(row[ADDRESS_COL_IDX])

            # It's in the visits file, so we know it needs to be visited.
            visit = True
            
            cust = get_known_customer(name, address, known_customers)
            
            if cust is None:
                # We're dealing with a new customer
                logging.info(f"Found new customer: {name}, located at:\n{address}")
                
                # Get a new ID for the customer
                cust_id = f"{next_cust_id:06d}"
                next_cust_id += 1
                logging.info(f"{name} given customer ID {cust_id}")
                
                # Create a Customer object for this customer
                cust = Customer(cust_id, name, address, lat, lon, True)

                # Get the distances to/from this new customer from/to the known customers
                new_dists = get_dists_to_from_new_cust(cust, known_customers, api_key)
                logging.info(f"Distances for {name} retrieved.")
                
                # Write this new customer to the customer file
                add_to_known_customer_data(cust, new_dists, customers_filename)

                # Add this customer to our list of known customers
                known_customers.append(cust)

                # Add these new-customer distances to our distances dict
                distances_dict.update(new_dists)
            
            else:
                logging.info(f"Loading existing customer:\n{cust.out_dict}")

            cust_dict[cust.cust_id] = cust

            visits.append(cust.cust_id)

    # Sort the list of customers to visit by their IDs.
    visits = sorted(visits)

    # If the depot is not already included in the list of customers to visit, add it in now
    if DEPOT_CUST_ID not in visits:
        visits.insert(0, DEPOT_CUST_ID)
    # ^^ NOTE: Other methods (router.create_model_data) assume depot is in the first slot.
    # Beware of changing this in the future.

    # Similarly, if the depot is not in our dictionary of customers, then add it now
    if DEPOT_CUST_ID not in cust_dict.keys():
        depot_cust = get_known_customer_by_id(DEPOT_CUST_ID, known_customers)
        if depot_cust is None:
            raise ValueError(f"Customer info is required but could not be found for the depot location (ID {DEPOT_CUST_ID}).")
        cust_dict[DEPOT_CUST_ID] = depot_cust
    
    if len(visits) != len(set(visits)):
        return ValueError("Some customers are duplicated in the visits file.")
    
    logging.info(f"IDs of customers to be visited: {visits}")
    
    return cust_dict, visits, distances_dict


def add_to_known_customer_data(
    customer: Customer,
    new_distances: Dict[Tuple[str, str], float],
    customers_filename: Optional[str],
):

    # If we're trying to read/write from memory, nothing to do
    if not customers_filename:
        return
        
    # If a file was specified but doesn't yet exist, create an empty one
    if not file_exists(customers_filename):
        new_cust_file_json = {"customers":[], "distances":{}}
        write_json(new_cust_file_json, customers_filename)

    # Load the known customer data from file
    cust_file_json = load_json(customers_filename)

    # Add the customer to our known customer data
    custs_data = cust_file_json["customers"]
    custs_data.append({
        "cust_id": customer.cust_id,
        "name": customer.name,
        "address": customer.address,
        "latitude": customer.lat,
        "longitude": customer.lon
    })

    # Add the new distances to our distance matrix
    dists_data = dist_dict_from_json(cust_file_json["distances"])
    dists_data.update(new_distances)

    # Write the new data back to file
    output_json = {"customers": custs_data, "distances": dist_dict_to_json(dists_data)}
    write_json(output_json, customers_filename)


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


def file_exists(filename: str) -> bool:
    """Checks whether the specified file exists."""

    return os.path.exists(filename)


def load_params(params_filename: str) -> Dict:
    """Loads parameters and constraints from file."""
    
    # If no params filename is specified, return the default parameter setting.
    if not params_filename:
        return RunParams()

    return RunParams(**load_json(params_filename))


def get_dists_to_from_new_cust(
    customer: Customer,
    known_customers: List[Customer],
    osr_api_key: str,
) -> Dict[Tuple[str, str], float]:
    """Gets distances to/from a new customer from/to the list of known customers.

    Args:
        customer: the new customer
        known_customers: known customers
        osr_api_key: API key to access openservice routing 

    Returns:
        Distances dictionary with pairwise distances between the new and known customers.
    """

    # If there are no existing customers, just return a 0-distance dict for the
    # single self-directed arc.
    if not known_customers:
        return {(customer.cust_id, customer.cust_id): 0.0}

    # Instantiate our client to pull the distance matrix.
    osr_client = client.Client(key=osr_api_key)

    # Get the list of customer coordinates, along with their IDs.
    # Note that they're in (lon, lat) order instead of (lat, lon).
    cust_coords_w_id = [(known_cust.cust_id, (known_cust.lon, known_cust.lat)) for known_cust in known_customers]

    # Append the new customer.
    cust_coords_w_id.append((customer.cust_id, (customer.lon, customer.lat)))

    # Note the number of total customers, along with the index of the new customer that we need distances for.
    n = len(cust_coords_w_id)
    new_cust_idx = n-1

    # Define the basic request we'll make to fetch the distance matrix.
    request = {
        'locations': [cust_coords[1] for cust_coords in cust_coords_w_id],
        'profile': 'driving-car',
        'metrics': ['duration'],
    }

    # First, get the distances FROM the new customer to all the existing customers
    request['sources'] = [new_cust_idx]
    response = osr_client.distance_matrix(**request)['durations']
    logging.info("Distances *FROM* new customer retrieved")
    new_distances = {
        (cust_coords_w_id[new_cust_idx][0], cust_coords_w_id[i][0]): response[0][i]
        for i in range(n) # This also includes the distance from the new customer to itself
    }

    # Next, get the distances TO the new customer from all the existing customers
    request.pop('sources')                    # no longer want to specify a single source
    request['destinations'] = [new_cust_idx]  # but we do want to specify a destination
    response = osr_client.distance_matrix(**request)['durations']
    logging.info("Distances *TO* new customer retrieved")
    new_distances.update({
        (cust_coords_w_id[i][0], cust_coords_w_id[new_cust_idx][0]): response[i][0]
        for i in range(new_cust_idx) # don't include the dist to itself this time
    })
    
    return new_distances


def get_distance_matrix(visits: List[str], distances: Dict[Tuple[str, str], float]) -> List[List[float]]:
    """Produces a distance matrix for the customers in `visits`."""

    return [[distances[i,j] for j in visits] for i in visits]


def stringify_route(route:[List[Customer]]) -> str:
    stringified_route = [cust.out_dict for cust in route]
    return stringified_route


def get_api_key(filename: str) -> str:
    """Gets the API key stored in the JSON file under key "key"."""
    file_contents = load_json(filename)
    return file_contents["key"]


def get_last_modded_csv(directory: str) -> str:
    """Returns the name of the most recently modified CSV in `directory`."""
    glob_pattern = os.path.join(directory,"*.csv")
    list_of_files = glob.glob(glob_pattern)
    return max(list_of_files, key=os.path.getmtime)


def get_known_path(path_type: str = "downloads") -> str:
    """Returns known default paths for Linux or Windows"""
    
    if path_type.lower() not in ['desktop', 'downloads']:
        raise ValueError("Invalid path_type. Must be either 'desktop' or 'downloads'.")
    
    return os.path.join(os.path.expanduser("~"), path_type.lower())
