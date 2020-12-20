from typing import Dict, List, Optional, Tuple
import datetime
import logging
import os
import time

from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

from gocheche import utils
from gocheche.core import Customer, RunParams


def create_model_data(
    visits: List[str],
    distances: Dict[Tuple[str, str], float],
    params: RunParams
) -> Dict:
    """Create the data object necessary to execute the routing engine."""
    data = {}
    data['num_vehicles'] = params.n_routes
    data['depot'] = 0  # Since we insert it into the zeroth index in utils.load_visits
    data['distance_matrix'] = utils.get_distance_matrix(visits, distances)
    return data


def get_routes(data, manager, routing, solution, visits: List[str], customers: Dict[str, Customer]) -> List[List[Customer]]:
    """Retrieves the routes from the solution."""
    
    max_route_duration = 0
    result = []
    
    # Loop over routes.
    for vehicle_id in range(data['num_vehicles']):

        route = []

        index = routing.Start(vehicle_id)
        plan_output = f'Route {vehicle_id}:\n'
        
        route_duration = 0
        while not routing.IsEnd(index):

            # For the current stop in the route
            route.append(customers[visits[manager.IndexToNode(index)]])
            plan_output += f' {route[-1].name} -> '
            previous_index = index

            # And the next stop in the route.
            index = solution.Value(routing.NextVar(index))
            route_duration += routing.GetArcCostForVehicle(
                previous_index,
                index,
                vehicle_id
            )
        
        route.append(customers[visits[manager.IndexToNode(index)]])
        plan_output += f'{route[-1].name}\n'
        plan_output += f'Duration of the route: {str(datetime.timedelta(seconds=route_duration))}\n'
        
        # Log the result for this route.
        logging.info(plan_output)
        max_route_duration = max(route_duration, max_route_duration)

        # Append it to our solution
        result.append((route, route_duration))
    
    # Note the longest route
    logging.info(f'Maximum route duration: {str(datetime.timedelta(seconds=max_route_duration))}')

    return result


def get_routing_solution(
    visits: List[str],
    customers: Dict[str, Customer],
    distances: Dict[Tuple[str, str], float],
    params: RunParams,
    outname: str,
):
    """Performs routing and prints a solution.

    Minimizes travel time, ensuring that each customer in visits is visited
    exactly once.
    
    Inputs:

        visits: List of customer IDs that need to be visited
        
        customers: Dict of customers, keyed on their IDs.
        
        distances: Dict of distances, keyed on (origin, destination) customer ID pairs
        
        params: RunParams object noting parameters for the run
        
        outname: Name of the file where results should be stored.

    """
    
    data = create_model_data(visits, distances, params)

    # Create the routing index manager.
    manager = pywrapcp.RoutingIndexManager(
        len(data['distance_matrix']),
        data['num_vehicles'],
        data['depot']
    )

    # Create Routing Model.
    routing = pywrapcp.RoutingModel(manager)

    # Create and register a transit callback.
    def distance_callback(from_index, to_index):
        """Returns the distance between the two nodes."""
        # Convert from routing variable Index to distance matrix NodeIndex.
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return data['distance_matrix'][from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)

    # Define cost of each arc.
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Add duration constraint.
    dimension_name = 'duration'
    routing.AddDimension(
        transit_callback_index,
        0,  # no slack
        28800,  # vehicle maximum travel time (8 hr in s, the unit used in the distance matrix)
        True,
        dimension_name)
    duration_dimension = routing.GetDimensionOrDie(dimension_name)
    duration_dimension.SetGlobalSpanCostCoefficient(100)

    # Setting first solution heuristic.
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )

    # Solve the problem.
    solution = routing.SolveWithParameters(search_parameters)

    # If a solution was found...
    if solution:
        
        # First log it and get the list-ified version.
        routes = get_routes(data, manager, routing, solution, visits, customers)

        # Then, save it to file
        write_text_solution(routes, outname)
    
    else:
        logging.warning("NO SOLUTION COULD BE FOUND")

def write_text_solution(routes: List[List[Customer]], outname: str):

    # If no output name was passed, then we'll be dumping a "Coffee Route.txt" file on the desktop
    if len(outname) == 0:
        outname = os.path.join(utils.get_known_path(path_type="desktop"), "Coffee Route.txt")
    
    if outname.endswith('.json'):
        
        writeable_sol_json = {
            "solution": [
                {
                    "route": utils.stringify_route(route),
                    "duration": duration
                }
                for route, duration in routes
            ]
        }
        utils.write_json(writeable_sol, outname)

        logging.info(writeable_sol_json)
        print(writeable_sol_json)
    
    else:
        writeable_sol_txt = ""
        
        for i, route in enumerate(routes):
            writeable_sol_txt += f"""

            *******************
            *** ROUTE {i+1}
            *******************
            """

            for j, cust in enumerate(route[0]):
                # Don't need to print the return to the depot
                if j >= len(route[0]) - 1:
                    break
                
                writeable_sol_txt += f"""
                    {j+1}.
                        Name: {cust.name}
                        Address: {cust.address}
                
                """

            writeable_sol_txt += """

            --- end of route ---

            """

        with open(outname, 'w') as outfile:
            outfile.write(writeable_sol_txt)

        logging.info(writeable_sol_txt)
        print(writeable_sol_txt)
