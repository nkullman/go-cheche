from typing import Dict, List, Optional, Tuple
import datetime
import logging
import os
import time

from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import folium
import selenium.webdriver

from gocheche import utils
from gocheche.core import Customer, RunParams


DO_PICTURE_OUTPUT = False


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
    """TODO fill me out: docstrings, typing for output, function implementation..."""
    
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
        0,  # no slack TODO
        21600,  # vehicle maximum travel time (in the units of the distance matrix -- seconds)
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
        if DO_PICTURE_OUTPUT:
            write_pict_solution(routes, outname, visits, customers)
    
    else:
        logging.warning("NO SOLUTION COULD BE FOUND")

def write_text_solution(routes: List[List[Customer]], outname: str):
    
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


def write_pict_solution(routes, outname, visits, customers, win_size: Tuple[int, int] = (800, 1080)):

    colors = ['#4E79A7', '#F28E2B', '#E15759', '#76B7B2']
    
    def style_function(color):
        return lambda feature: dict(
            color=color,
            weight=3,
            opacity=1
        )
    

    html_outname = outname[:outname.rfind(".")]+"_map.html"
    pict_outname = outname[:outname.rfind(".")]+".png"

    map_center = utils.get_center_of_custs(visits, customers)

    # Initialize the map
    m = folium.Map(tiles='Stamen Toner', location=map_center, zoom_start = 12)

    # Loop over routes, plotting each
    for i, route_info in enumerate(routes):

        route = route_info[0]
        
        # Get a geo-json representation of our route for plotting with folium
        route_geojson = utils.get_route_geojson(route)

        folium.features.GeoJson(
            data=route_geojson,
            name=f'Route {i}',
            style_function=style_function(colors[i]),
            overlay=True
        ).add_to(m)

    # Loop over the customers we're visiting and add an icon for them as well.
    for i, visit in enumerate(visits):
        lon, lat = customers[visit].get_coords()
        name = customers[visit].name
        popup = f"<strong>{name}</strong><br>Lat: {lat:.3f}<br>Long: {lon:.3f}"
        if i==0:
            # A home icon
            icon = folium.map.Icon(
                color='beige',
                icon_color='white',
                icon='home',
                prefix='fa'
            )
        else:
            # A coffee icon
            icon = folium.map.Icon(
                color='beige',
                icon_color='#4A2C29', # coffee brown
                icon='coffee',
                prefix='fa'
            )
        folium.map.Marker([lat, lon], icon=icon, popup=popup).add_to(m)

    m.save(html_outname)
    
    # prepare the option for the chrome driver
    options = selenium.webdriver.ChromeOptions()
    options.add_argument('headless')
    options.add_argument(f"--window-size={win_size[0]},{win_size[1]}")

    webber = selenium.webdriver.Chrome(options=options)
    webber.get(f"file:///{os.path.abspath(html_outname)}")
    webber.save_screenshot(pict_outname)
    webber.quit()
    os.remove(html_outname)
