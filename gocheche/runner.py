import argparse
import datetime
import logging
from typing import Dict, List, Tuple

from gocheche.core import Customer, RunParams
from gocheche import router, utils


def get_arg_parser() -> argparse.ArgumentParser:
    """Builds our argument parser."""

    # Initialize an argument parser.
    parser = argparse.ArgumentParser(description="Does some CheChe routing.")

    # Argument to take in the file with customer info (namely, addresses).
    parser.add_argument(
        '-c',
        '--customers',
        type=str,
        default="data/customers.json",
        help='Filename with customer info'
    )

    # Argument to take in the file with the list of customers to visit.
    parser.add_argument(
        '-v',
        '--visit',
        type=str,
        default="data/visit.json",
        help='Filename with the customers to be visited'
    )
    
    # Argument to take in the file with routing constraints (namely, which
    # customers need to be served on which days).
    parser.add_argument(
        '-p',
        '--params',
        type=str,
        default="data/run_params.json",
        help='File with run paramaters (e.g., constraints)'
    )
    
    # Argument to take in the file with the distance (duration) matrix.
    parser.add_argument(
        '-d',
        '--distances',
        type=str,
        default="data/distances.json",
        help='Distance matrix file'
    )

    parser.add_argument(
        '--get-distances',
        action="store_true",
        help="Whether to fetch a new distance matrix if any customers are missing in the distances file."
    )

    # Argument to determine whether to write the solution to file.
    parser.add_argument(
        "-w",
        "--write",
        action="store_true",
        help="Write output to file (specify name with -o)"
    )

    # Argument to specify where to write solution.
    parser.add_argument(
        "-o",
        "--output",
        type = str,
        default = "data/solution.json",
        help = (
            "Name of file to which to write solution. "
            "Default is '../data/solution.json'"
        )
    )

    return parser


def fetch_data(args: argparse.Namespace) -> Tuple[List[str], Dict[str, Customer], Dict[Tuple[str, str], float], RunParams]:
    """Fetches the data in the files located in the locations indicated by `args`."""

    # Loading all data files. We first start with the list of customers to visit
    visits = utils.load_visits(args.visit)
    logging.info("List of customers to visit retrieved.")
    # Next we load all customer details.
    customers = utils.load_customers(args.customers, to_visit=visits)
    logging.info("Customer set retrieved.")
    # Then the distances.
    distances = utils.load_distances(args.distances)
    logging.info("Distances retrieved.")
    # And lastly the run parameters (constraints).
    params = utils.load_params(args.params)
    logging.info("Constraints file loaded.")
    
    # Make sure our customers file contains all those we're trying to visit.
    utils._ensure_no_missing_customers(visits, customers)
    logging.info("Confirmed that all required customers are in the customers file.")

    # Making sure our distances file contains distances for all customer pairs.
    are_missing_distances = utils._check_for_missing_distances(visits, distances)
    if are_missing_distances:
        # If any distances are missing, we'll either fetch a new distances matrix.
        # or just raise an error; whichever the user specified in args.
        logging.info("Some distances were missing from the distances file.")
        if args.get_distances:
            logging.info("Fetching a new distance matrix for the customer set...")
            distances = utils.get_distances(customers, args.distances)
        else:
            utils._find_missing_distances(visits, distances)

    return visits, customers, distances, params


def main():
    """Does some CheChe routing."""

    # Grab the timestamp for when the run was initialized
    now = datetime.datetime.now().strftime("%Y%m%d")

    # Initialize a logger.
    logging.basicConfig(filename=f'gocheche_{now}.log', level=logging.INFO)

    # Initialize the argument parser and retrieve the passed arguments
    parser = get_arg_parser()
    args = parser.parse_args()

    # If we don't want to write the output, then set the output file to None.
    if not args.write:
        args.output = None

    # Fetch and check the data in the files given in args.
    visits, customers, distances, params = fetch_data(args)

    logging.info(f"""
        *** GoCheChe input ***

        Received arguments:

            customers: {args.customers}
            visit: {args.visit}
            params: {args.params}
            distances: {args.distances}
            write: {args.write}
            output: {args.output}

        Customers to visit:

            {[customers[cust_id].name for cust_id in visits]}

    """)

    # Do the routing
    solution = router.get_routing_solution(visits, customers, distances, params, args.output)


if __name__ == "__main__":
    main()
