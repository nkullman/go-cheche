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

    # Argument to take in the file with the list of customers to visit.
    parser.add_argument(
        'visit',
        type=str,
        help='Name of CSV file with info for customers that need to be visited.'
    )
    
    # Argument to specify where to write solution.
    parser.add_argument(
        "-o",
        "--output",
        type = str,
        default = "solution.txt",
        help = (
            "Name of file to which to write solution. "
            "Default is 'solution.txt'"
        )
    )

    # Argument to take in the file with data on known customers.
    parser.add_argument(
        '-c',
        '--customers',
        type=str,
        default="data/customers_db.json",
        help=(
            'Name of file with info on known customers. '
            "Default is customers_db.json. If the file doesn't exist, a new file is created "
            "to start saving customer info."
        )
    )
    
    # Argument to take in the file with routing constraints (namely, which
    # customers need to be served on which days).
    parser.add_argument(
        '-p',
        '--params',
        type=str,
        default="",
        help='File with run paramaters (e.g., constraints)'
    )

    return parser


def fetch_data(args: argparse.Namespace) -> Tuple[List[str], Dict[str, Customer], Dict[Tuple[str, str], float], RunParams]:
    """Fetches the data in the files located in the locations indicated by `args`."""

    # Loading all data files. We first start with the list of customers to visit
    customers, visits, distances = utils.load_customers(args.visit, args.customers)
    logging.info("Customers and distances retrieved.")
    
    # And lastly the run parameters (constraints).
    params = utils.load_params(args.params)
    logging.info("Constraints file loaded.")
    
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

    # Fetch and check the data in the files given in args.
    visits, customers, distances, params = fetch_data(args)

    logging.info(f"""
        *** GoCheChe input ***

        Received arguments:

            visit: {args.visit}
            output: {args.output}
            customers: {args.customers}
            params: {args.params}

        Customers to visit:

            {[customers[cust_id].name for cust_id in visits]}

    """)

    # Do the routing
    solution = router.get_routing_solution(visits, customers, distances, params, args.output)


if __name__ == "__main__":
    main()
