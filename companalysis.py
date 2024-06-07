
# General packages
import pandas as pd
import time
import re
import numpy as np
from tqdm import tqdm
import requests
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Selenium packages
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Dask packages
from dask import delayed, compute
from dask.diagnostics import ProgressBar


############################################################################################################
"""Competitive Landscape Analysis Toolkit:
This toolkit contains 3 main functions:

maps_scraper: Scrape maps service for information about places based on search queries and locations.
Ex. Find every Churro place in New York City.

get_closest_locations: After scraping the maps service, find the closest location for each origin-destination pair based on travel time.
Ex. Find the closest Churro place to each hotel in New York City.

product_scraper: Scrape the prices of food products based on a search query and location.
Ex. Find the price, rating, and calories of Churros in New York City.

"""


############################################################################################################
# Maps Scraper


# Helper Function: Extract emails from a website
def extract_emails(browser, website_url):
    """Helper Function: Extract emails from a website using regular expressions."""
    browser.get(website_url)
    
    # Get the regular expressions pattern to match on
    email_pattern = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,4}"
    # Get the html content for the page
    html = browser.page_source
    # Get a list of emails
    emails = re.findall(email_pattern, html)
    # Get a unique array of the emails on the page
    unique_emails_arr = pd.DataFrame(columns=['email'],data=emails)['email'].unique()
    # Convert to string with a comma delimiting them
    unique_emails_str = ','.join(unique_emails_arr)
    return unique_emails_str


# Helper Function: Inner function to extract information about a specific place from its page
def extract_place_info(browser, place_url, location, search_query, all_addresses, all_place_names, debug_mode):
    """Helper Function: Extract information about a specific place from its page."""
    wait = WebDriverWait(browser, 10)
    browser.get(place_url)
    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "lMbq3e")))
            
    # Extract the header information about the place
    header_text = browser.find_element(By.CLASS_NAME,'lMbq3e').text
    header_list = header_text.split("\n")
    
    # Do not include locations that are temporarily closed
    if 'Temporarily closed' in header_list or 'Cerrado temporalmente' in header_list:
        return "skip"
    
    if len(header_list) == 4:  # If there are reviews but no price range
        place_name = header_list[0]
        reviews_stars = header_list[1]
        num_of_reviews = header_list[2].strip('(').strip(')')
        price_range = None
        place_description = header_list[3]
    elif len(header_list) == 5:  # If there are reviews and a price range
        place_name = header_list[0]
        reviews_stars = header_list[1]
        num_of_reviews = header_list[2].strip('(').strip(')')
        price_range = header_list[3]
        place_description = header_list[4]
    elif len(header_list) == 2:  # If there are no reviews
        place_name = header_list[0]
        reviews_stars = None
        num_of_reviews = None
        price_range = None
        place_description = header_list[1]
    elif len(header_list) == 1:  # Edge case with an empty string
        place_name = header_list[0]
        reviews_stars = None
        num_of_reviews = None
        price_range = None
        place_description = None
    else:
        print(f"Error extracting header information {header_list} for place with URL: {place_url}")
        return "skip"
    
    # Extract additional information like address, phone, and website
    info_elements = browser.find_elements(By.CLASS_NAME, "CsEnBe")
    website = None
    phone = None
    address = None
    emails = None
    
    # TODO: Find a way to make this robust against locale differences
    # Check for both English and Spanish labels
    for info_element in info_elements:
        aria_label = info_element.get_attribute("aria-label")
        if aria_label:
            if 'Address:' in aria_label or 'Dirección:' in aria_label:
                address = info_element.text.split('\n')[1] if '\n' in info_element.text else info_element.text
            if 'Phone:' in aria_label or 'Teléfono:' in aria_label:
                phone = info_element.text
            if 'Website:' in aria_label or 'Sitio web:' in aria_label:
                website = info_element.get_attribute("href")
    
    # Check if the place is a duplicate
    if address in all_addresses:
        if place_name in all_place_names:
            return "skip"
    else:
        all_addresses.append(address)
        all_place_names.append(place_name)
    
    if website is not None:
        emails = extract_emails(browser, website)
    
    # Compile the extracted information into a list
    place_info = [
        search_query,
        location,
        place_name,
        place_description,
        reviews_stars,
        num_of_reviews,
        address,
        phone,
        emails,
        website,
        price_range
    ]
    
    if debug_mode:
        print(place_info)
    
    return place_info


# Helper Function: Define a function to extract search results for a given search URL, location, and search_query
def extract_search_results(browser, search_url, location, search_query, max_places_to_find, max_num_scrolls, all_addresses, all_place_names, total_bar, debug_mode, url_update_count):
    """Helper Function: Extract search results for a given search URL, location, and search query."""
    # Navigate to the search URL
    browser.get(search_url)
    wait = WebDriverWait(browser, 10)
    
    # Wait for the page to load
    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "hfpxzc")))
        
    # Find the element to start scrolling from
    start_scroll_element = browser.find_element(By.CLASS_NAME, "hfpxzc")
    scroll_origin = ScrollOrigin.from_element(start_scroll_element)
    
    # Perform scrolling action to reveal more search results
    for i in range(max_num_scrolls):
        ActionChains(browser).scroll_from_origin(scroll_origin, 0, 1500*(i+1)).perform()

        # TODO: Possibly find a way to use selenium WebDriverWait 
        time.sleep(3)
        total_bar.update(1)  # Explicitly update the progress bar
    
    # Find all elements that represent places in the search results
    place_elements = browser.find_elements(By.CLASS_NAME, "hfpxzc")
        
    # Extract the URLs of all places
    place_urls = [element.get_attribute("href") for element in place_elements]
    
    place_info_list = []
    update_count = 0
    iters = len(place_urls) - 1 if len(place_urls) < max_places_to_find else max_places_to_find - 1
    benchmark = iters / url_update_count
    
    # Loop through the URLs to extract information for each place
    for i, url in enumerate(place_urls):
        try: 
            temp_place_info = extract_place_info(browser, 
                                                 url, 
                                                 location, 
                                                 search_query, 
                                                 all_addresses, 
                                                 all_place_names, 
                                                 debug_mode)
            
            if temp_place_info == "skip":  # Skip if the place is a duplicate or contains errors
                continue
            
            place_info_list.append(temp_place_info)
            
        except Exception as e:
            print(f"Error extracting place with url: {url}. Error: {e}")
        
        # Stop if max_places_to_find places have been found
        if len(place_info_list) >= max_places_to_find:
            
            if debug_mode:
                print('Breaking out of the for loop because {max_places_to_find} places were found.')
            break
        
        if i > benchmark:
            update_count += 1
            benchmark += iters / url_update_count
            total_bar.update(1)  # Explicitly update the progress bar
    
    if update_count < url_update_count:
        total_bar.update(url_update_count - update_count)

    return place_info_list


# Define the main function to scrape a maps service for information about places based on search queries and locations
def maps_scraper(search_queries, 
                 locations=[''], 
                 max_places_to_find=10, 
                 max_num_scrolls=3, 
                 headless=True, 
                 export_final_filename=None, 
                 export_by_search_query=False, 
                 debug_mode=False,
                 url_update_count=3):
    """Scrape maps service for information about places based on search queries and locations.
    
    Args:
        search_queries (list): A list of search queries to search for on Google Maps.
        locations (list): A list of locations to search in. Default is [''].
        max_places_to_find (int): The maximum number of places to find for each search query in each location. Default is 10.
        max_num_scrolls (int): The maximum number of times to scroll down the search results page. Default is 3.
        headless (bool): Whether to run the WebDriver in headless mode. Default is True.
        export_final_filename (str): The filename for the CSV file to export the final DataFrame to. Default is None which will not export the final DataFrame.
        export_by_search_query (bool): Whether to export the results to a CSV file for each search query. Default is False.
        debug_mode (bool): Whether to print debug information. Default is False.
        url_update_count (int): The number of times to update the progress bar for each URL. Default is 3.
        
    Returns:
        pandas.DataFrame: A DataFrame containing the information about the places found.
    """
    # Prepare to compile information for multiple locations and search_queries
    final_places_list = []
    all_addresses = []
    all_place_names = []

    # Initialize the WebDriver Options 
    options = Options()
    options.add_experimental_option('prefs', {'intl.accept_languages': 'en,en_US'})  # Set language preferences
    if headless:
        options.add_argument("--headless")

    with tqdm(total=len(search_queries) * len(locations) * (max_num_scrolls + url_update_count), desc="Total Progress", unit="search") as total_bar:
        # Loop through each search_query and location, perform searches, and compile results
        try: 
            for search_query in search_queries:
                if debug_mode:
                    print(search_query)
                for location in locations:  
                    # Initialize the WebDriver for Chrome
                    browser = webdriver.Chrome(options=options)
                    
                    try:  # Search the maps service for the search query in the location
                        if debug_mode:
                            print(location)
                        search = f"{search_query} in {location}"
                        if debug_mode:
                            print(search)
                        search_url = f"https://www.google.com/maps/search/{search}"
                        
                        combo_place_info_list = extract_search_results(
                            browser, 
                            search_url, 
                            location, 
                            search_query, 
                            max_places_to_find, 
                            max_num_scrolls, 
                            all_addresses, 
                            all_place_names,
                            total_bar,
                            debug_mode,
                            url_update_count
                        )
                        
                        if export_by_search_query:  # Export the results to a CSV file for each search query
                            pd.DataFrame(combo_place_info_list).to_csv(f'{search_query} Export.csv', index=False)
                            
                        final_places_list.extend(combo_place_info_list)
                        
                    except Exception as e:
                        print(f"Error extracting search results for {search_query} in {location}: ")
                        print(e)
                    
                    finally:
                        browser.close()
                    
                    total_bar.update(1)  # Explicitly update the progress bar
                    
        except Exception as e:
            print(e)
        finally:
            browser.quit()
            
    # Create a DataFrame from the final_places_list
    places_df = pd.DataFrame(
        columns=['Search Query', 'Location', 'Name', 'Description', 'Stars (out of 5)', 'Number of Reviews', 'Address', 'Phone', 'Emails','Website', 'Price Range'], 
        data=final_places_list
    )
    
    # Export the final DataFrame to a CSV file
    if export_final_filename:
        if export_final_filename.split('.')[-1] == 'csv':
            places_df.to_csv(export_final_filename, index=False)
        else:
            places_df.to_csv(export_final_filename + '.csv', index=False)
    
    return places_df


############################################################################################################
# Proximity Competition


# Helper Function: Get the Unix timestamp for the next 2 a.m. to minimize variance in travel times
def get_next_2am_unix_timestamp():
    """Get the Unix timestamp for the next 2 a.m. to minimize variance in travel times.
    
    WARNING: This function will only work correctly if you are in the local timezone of
    where you are searching.
    
    TODO: Make this robust against different timezones.
    """
    now = datetime.now()
    next_2am = now.replace(hour=2, minute=0, second=0, microsecond=0)

    # If it's already past 2 a.m. today, move to the next day
    if now >= next_2am:
        next_2am += timedelta(days=1)

    return int(time.mktime(next_2am.timetuple()))


# Helper Function: Calculate the travel time to each destination from each origin using the Google Maps API
def time_to_destinations(origin_addresses: np.ndarray, 
                         origin_names: np.ndarray, 
                         destination_addresses: np.ndarray, 
                         destination_names: np.ndarray, 
                         apikey: str) -> pd.DataFrame:
    """Calculate the travel time to each destination from each origin using the Google Maps API.
    
    Parameters:
        origin_addresses (ndarray(n,)): The starting locations.
        origin_names (ndarray(n,)): The names of the starting locations.
        destination_addresses (ndarray(m,)): A numpy array of destination addresses.
        destination_names (ndarray(m,)): A numpy array of destination names.
        apikey (str): The Google Maps API key.
        
    Returns:
        pd.DataFrame: A DataFrame of travel times between origins (rows) and destinations (columns).
    """
    n, m = len(origin_addresses), len(destination_addresses)
    times_arr = np.zeros((n, m), dtype=float)
    
    # Check if the origin and destination addresses are provided
    if type(origin_addresses) != list and type(origin_addresses) != np.ndarray:
        raise TypeError("origin_addresses must be a numpy array.")
    else:
        destination_addresses = np.array(destination_addresses)
    if type(destination_addresses) != list and type(destination_addresses) != np.ndarray:
        raise TypeError("destination_addresses must be a numpy array.")
    else:
        destination_addresses = np.array(destination_addresses)
    if type(origin_addresses) == list:
        origin_addresses = np.array(origin_addresses)
    if type(destination_addresses) == list:
        destination_addresses = np.array(destination_addresses)
    
    # Check if the origin and destination names are provided
    if type(origin_names) != list and type(origin_names) != np.ndarray:
        raise TypeError("origin_names must be a numpy array.")
    if type(destination_names) != list and type(destination_names) != np.ndarray:
        raise TypeError("destination_names must be a numpy array.")
    if type(origin_names) == np.ndarray:
        if origin_names.shape != (n,):
            raise ValueError("origin_names must have the same shape as origin_addresses.")
    if type(destination_names) == np.ndarray:
        if destination_names.shape != (m,):
            raise ValueError("destination_names must have the same shape as destination_addresses.")
    if len(origin_names) != n or len(destination_names) != m:
        raise ValueError("The number of origin and destination names must match the number of addresses.")
    
    # Check if the API key is provided
    if not apikey:
        raise ValueError("A Google Maps API key is required to calculate the travel times.")
    
    # Loop through each origin and destination pair
    for i, origin in enumerate(origin_addresses):
        
        base_url = "https://maps.googleapis.com/maps/api/directions/json"

        # Calculate the Unix timestamp for the next 2 a.m. to minimize variance in travel times
        departure_time = str(get_next_2am_unix_timestamp())

        for j, destination in enumerate(destination_addresses):
            params = {
                "origin": origin,
                "destination": destination,
                "departure_time": departure_time,  # Dynamically calculated 2 a.m. timestamp
                "key": apikey
            }

            response = requests.get(base_url, params=params)
            if response.status_code == 200:
                data = response.json()

                # Check if the API returned a valid route
                if data["status"] == "OK":
                    duration_seconds = data["routes"][0]["legs"][0]["duration"]["value"]
                    times_arr[i, j] = duration_seconds  # Store the travel time

                else:
                    print(f"No valid route for {destination}. \nStatus: {data['status']}")
            else:
                raise Exception(f"Google Maps API error: {response.status_code}")
    
    df_times = pd.DataFrame(data=times_arr, columns=destination_names, index=origin_names)
    
    return df_times


# Define the main function to find the closest location for each origin-destination pair based on travel time
def get_closest_locations(origin_addresses: list, 
      origin_names: list, 
      destination_addresses: list, 
      destination_names: list, 
      max_time=600,
      times_df=None,
      apikey=None) -> pd.DataFrame:
    """Find the closest location for each origin-destination pair based on travel time.
    
    Parameters:
        origin_addresses (list): A list of origin addresses.
        origin_names (list): A list of origin names.
        destination_addresses (list): A list of destination addresses.
        destination_names (list): A list of destination names.
        max_time (int): The maximum travel time in seconds. Default is 600 seconds (10 minutes).
        times_df (pd.DataFrame): A DataFrame of travel times between origins and destinations. If None, and API key 
        is required, and it will be calculated. WARNING: This accesses the Google Maps API and may incur costs.
        apikey (str): The Google Maps API key.
        
    Returns:
        times_df (pd.DataFrame): A DataFrame of travel times between origins (rows) and destinations (columns).
        list: A list of strings containing the closest location for each origin-destination pair.
    """
    
    if not times_df and not apikey:
        raise ValueError("A Google Maps API key is required to calculate the travel times.")
    
    if not times_df:
        times_df = time_to_destinations(origin_addresses, origin_names, destination_addresses, destination_names, apikey)
    
    is_within_time = times_df.values < max_time

    i_arr, j_arr = np.nonzero(is_within_time)
    
    new_i_list = []
    new_j_list = []

    # Find the closest location for each origin-destination pair
    for k in j_arr:
        
        same_loc = i_arr[j_arr == k]
        
        closest_dist = np.inf
        
        for loc in same_loc:
            if times_df.iloc[loc, k] < closest_dist:
                closest_dist = times_df.iloc[loc, k]
                closest_loc = loc
        
        new_i_list.append(closest_loc)
        new_j_list.append(k)

    sort_mask = np.argsort(new_i_list)
    new_i_arr = np.array(new_i_list)[sort_mask]
    new_j_arr = np.array(new_j_list)[sort_mask]
    
    comb_arr = list(map(tuple, np.vstack((new_i_arr, new_j_arr)).T))

    closest_locations = []

    for i, j in comb_arr:
                
        output_string = (f"Origin Name: {origin_names[i]}\n"
              f"Origin Address: {origin_addresses[i]}\n"
              f"Destination Name: {destination_names[j]}\n"
              f"Destination Address: {destination_addresses[j]}\n")

        closest_locations.append(output_string)
    
    return times_df, closest_locations


############################################################################################################
# Pricing Analysis 


# Function to generate a unique filename
def generate_unique_filename(filename, extension):
    base, ext = os.path.splitext(filename)
    counter = 1
    new_filename = f"{base}{extension}"
    while os.path.exists(new_filename):
        new_filename = f"{base}_{counter}{extension}"
        counter += 1
    return new_filename


# Helper Function
def wait_for_page_load(browser, timeout=20):   
    """Wait for the page to load by checking the document.readyState.""" 
    WebDriverWait(browser, timeout).until(
        lambda x: x.execute_script("return document.readyState") == "complete"
    )


# Helper Function
def find_element_by_text(text, tag='li', browser=None, wait=None, timeout=20):
    """
    Find an element by its text content.
    
    Args:
        text (str): The text content to look for.
        tag (str): The tag name to filter (default is 'li').
        browser (webdriver): The browser instance to use.
        wait (WebDriverWait): The WebDriverWait instance.
        timeout (int): Timeout period for waiting.

    Returns:
        WebElement or None: The found element or None if not found.
    """
    # Construct an XPath expression to find the tag with the specific text
    xpath = f"//{tag}[text()='{text}']"

    # Wait until the desired element is located or time out
    try:
        element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        return element
    except Exception as e:
        print(f"Element with text '{text}' not found. Error: {e}")
        return None


# Extract information about a product from a store page
def extract_product_info(url, store_name, headless):
    """Extract information about a product from a store page."""
    
    options = Options()
    if headless:
        options.add_argument("--headless")
        
    browser = webdriver.Chrome(options=options)
    browser.get(url)
    
    try:
        wait_for_page_load(browser)
    except:
        print("Page load failed. Trying again...")
            
    li_elements = browser.find_elements(By.TAG_NAME, "li")
    
    product_info_list = []
    product_names = []
    product_prices = []
    
    for li_elt in li_elements:  # Loop through each category
        if (li_elt.find_elements(By.TAG_NAME, "h3")  # Check if it contains food items and is not Featured Items
            and li_elt.find_elements(By.TAG_NAME, "h3")[0].text != "Artículos destacados" 
            and li_elt.find_elements(By.TAG_NAME, "h3")[0].text != "Featured items"):
            
            category = li_elt.find_elements(By.TAG_NAME, "h3")[0].text
            
            # Locate all matching elements using Selenium's find_elements
            span_elements = li_elt.find_elements(By.TAG_NAME, "span")
            price_pattern = r"^(USD ?|\$ ?|MX\$ ?)\d+\.\d{2}$"
            review_pattern = r" \d+% \((\d+)\)"
                        
            for index, element in enumerate(span_elements):
                price = element.text
                calories = None
                rating_percentage = None
                num_reviews = 0
                
                # Check if the current text begins with "USD" or "$"
                if not re.match(price_pattern, price):  # Check if the str matches the price pattern
                                        
                    # Convert price to float
                    # Adjust for inflated delivery prices (ranges from 10-30% depending on the store so assume 20%)
                    if price.startswith("USD "): 
                        price = round(float(price[4:]) / 1.2, 2)
                    elif price.startswith("$"):
                        price = round(float(price[1:]) / 1.2, 2)
                    else:
                        price = round(float(price[3:]) / 1.2, 2)
                                            
                    # Get the previous element's text (if it exists)
                    product_name = span_elements[index - 1].text if index > 0 else None
                    
                    # Avoid duplicate products 
                    if product_name in product_names:  # Skip if product name and price match 
                        index = product_names.index(product_name)
                        if price == product_prices[index]:
                            continue
                    
                    product_names.append(product_name)
                    product_prices.append(price)
                        

                    # Check if the next element is ' • \n'
                    if index + 1 < len(span_elements) and span_elements[index + 1].text.strip() == '•':
                        
                        if not re.match(review_pattern, span_elements[index + 2].text):
                            rating_percentage = None
                            num_reviews = 0
                            calories = int(span_elements[index + 2].text.split()[0])
                        else:
                            # Get the next-next element's text
                            reviews = span_elements[index + 2].text if index + 2 < len(span_elements) else None

                            # Parse the reviews text
                            reviews_split = reviews.split()
                            rating_percentage = float(reviews_split[0][:-1])
                            num_reviews = int(reviews_split[1][1:-1])
                            
                            if index + 3 < len(span_elements) and span_elements[index + 3].text.strip() == '•':
                                calories = int(span_elements[index + 4].text.split()[0])
                        
                        product_info_list.append([store_name, category, product_name, price, rating_percentage, num_reviews, calories])
                    else:
                        product_info_list.append([store_name, category, product_name, price, None, 0, None])
                                            
    browser.quit()
            
    return product_info_list


# Helper Function: Set up the browser for the extraction phase
def setup_extraction(search_query, location, headless):
    """Helper Function: Set up the browser for the extraction phase."""
    
    # Initialize a `tqdm` object with a total of 10
    setup_bar = tqdm(total=4, desc="Setting up the browser...")
            
    # Set up the browser
    options = Options()
    if headless:
        options.add_argument("--headless")
    
    browser = webdriver.Chrome(options=options)
    wait = WebDriverWait(browser, 20)
    english = True

    # Get the website URL from the environment variables
    # NOTE: You need to set the WEBSITE_URL environment variable to the website you want to scrape. 
    # To do this create a .env file in the same directory as this script and add the line:
    # WEBSITE_URL="https://www.yourwebsite.com"
    load_dotenv()
    website_url = os.getenv("WEBSITE_URL")

    # Open the specific website
    browser.get(website_url)

    # Check if the page is in English or Spanish
    search_bar = browser.find_element(By.XPATH, '//*[@role="combobox"]')
    placeholder = search_bar.get_attribute('placeholder')
    if placeholder == "Ingresa la dirección de entrega":
        english = False

    setup_bar.update(1)

    # Search bar for the location
    wait.until(EC.presence_of_element_located((By.XPATH, '//*[@role="combobox"]')))
        
    # Using XPath to select elements based on the role attribute
    combobox_elements = browser.find_elements(By.XPATH, '//*[@role="combobox"]')

    # Access the first found combobox element
    if combobox_elements:
        search_bar = combobox_elements[0]
        
        # Input the search term into the search bar
        search_bar.send_keys(location)
        time.sleep(1)
        
        # Press "Enter" to trigger the search
        search_bar.send_keys(Keys.RETURN)
    else:
        raise Exception("First search bar not found.")

    # Wait for the page to load
    # TODO: Find a more robust way to wait for the page to load
    time.sleep(3)
    wait_for_page_load(browser)
    time.sleep(3)
    
    setup_bar.update(1)

    # Second search bar for the search term
    combobox_elements = browser.find_elements(By.XPATH, '//*[@role="combobox"]')
    span_elements = browser.find_elements(By.TAG_NAME, 'span')

    # Access the first found combobox element
    if combobox_elements:
        search_bar = combobox_elements[0]
        
        # Input the search term into the search bar
        search_bar.click()
        time.sleep(1)
    elif span_elements:  # Handles the case where the search bar is not a combobox
        search_bar = span_elements[0]
        
        # Input the search term into the search bar
        search_bar.click()
        time.sleep(1)
    else:
        raise Exception("Second search bar not found.")

    # Search for restaurants
    if english:  # Check if the language is set to English
        restaurant_tab = find_element_by_text('Restaurants', tag='li', browser=browser, wait=wait)
    else:
        restaurant_tab = find_element_by_text('Restaurantes', tag='li', browser=browser, wait=wait)

    if restaurant_tab:
        restaurant_tab.click()
        time.sleep(1)

    # Input the search term into the search bar
    search_bar = browser.find_element(By.XPATH, '//*[@role="combobox"]')
    search_bar.send_keys(search_query)
    search_bar.send_keys(Keys.RETURN)
    
    setup_bar.update(1)

    time.sleep(3)
    wait_for_page_load(browser)
    
    setup_bar.update(1)
    setup_bar.close()
    
    return browser 


# Define the main function to scrape the prices, ratings, and calories of food products based on a search query and location
def product_scraper(search_query, location, max_stores=50, filename=None, headless=True, debug_mode=False):
    """Scrape the prices, ratings, and calories of food products based on a search query and location.
    
    Parameters:
        search_query (str): The search query to look for.
        location (str): The location to search in.
        filename (str): The name of the file to store the data in as CSV.
        headless (bool): Whether to run the browser in headless mode.
    
    Returns:
        pandas.DataFrame: A DataFrame containing the information about the products found.
    """
    
    # NOTE: There are multiple different page load possibilities. Some of them provide
    # duplicate or empty "h3" or "a" tags. This code is designed to handle those cases in a 
    # way that will provide the expected number of stores each time.
    
    # Check the input parameters
    if max_stores < 1:
        raise ValueError("max_stores must be greater than 0.")
    if type(search_query) != str:
        raise TypeError("search_query must be a string.")
    if type(location) != str:
        raise TypeError("location must be a string.")
    if filename:
        if filename.split(".")[-1] == "csv":
            filename = ".".join(filename.split(".")[:-1])
    
    # Set up the browser for the extraction phase
    browser = setup_extraction(search_query, location, headless)
    
    # TODO: Add feature for multiple search queries HERE.
    # For multiple locations, call the function multiple times with different locations. 
    
    # Begin the extraction phase
    store_names = []  # Store previous store names to avoid duplicates
    all_stores_info_list = []  # Store all store information

    # Get the list of stores to get the number of stores to iterate through
    stores_list = browser.find_elements(By.TAG_NAME, 'h3')
    
    if len(stores_list) < max_stores:
        max_stores = len(stores_list)
        
    # Get store names all at once by checking h3 elements    
    for store in stores_list:
        name = store.text
        if name != "" and name not in store_names:
            store_names.append(name)
    
    xpath_expression = '//a[@data-testid="store-card"]'
    store_urls_list = browser.find_elements(By.XPATH, xpath_expression)
    store_urls = []

    # Get the store URLs
    for store in store_urls_list:
        store_url = store.get_attribute('href')
        if store_url not in store_urls:
            store_urls.append(store_url)

    if debug_mode:  # Debugging store names and urls
        print(f"Number of Store names: {len(store_names)}")
        print(f"Number of Store URLs: {len(store_urls)}")
        
        for i in range(len(store_names)):  # Loop through each store
            print(f"Store Name: {store_names[i]}")
            print(f"Store URL: {store_urls[i]}")
            
    if len(store_names) != len(store_urls):  # Debugging the store names and URLs
        print(f"Number of store names and URLs do not match: {len(store_names), len(store_urls)}")
        
        try:
            for i in range(len(store_names)):  # Loop through each store
                print(f"Store Name: {store_names[i]}")
                print(f"Store URL: {store_urls[i]}")
                print("______________")
        except Exception as e:
            print(f"Error printing store names and URLs: {e}")
        print("store names: ", store_names)
        print("store urls: ", store_urls)
    
    # Wrap extract_product_info with Dask's delayed
    extract_product_info_dask = delayed(extract_product_info)
    
    # Create a list of delayed tasks
    tasks = [extract_product_info_dask(store_urls[i], store_names[i], headless) for i in range(max_stores)]
    
    # Compute the tasks in parallel
    with ProgressBar():
        results = compute(*tasks, scheduler='processes')
    
    # Aggregate results
    for result in results:
        all_stores_info_list.extend(result)
                    
    # Create a DataFrame from the product info
    all_stores_df = pd.DataFrame(all_stores_info_list, columns=['Store Name', 'Category', 'Product Name', 'Price', 'Rating', 'Number of Reviews', 'Calories'])

    if filename:
        try:  # Handle cases when it might overwrite a file
            # Save the DataFrame to a CSV file with UTF-8 encoding
            all_stores_df.to_csv(f"pricing files/{filename}.csv", index=False, encoding="utf-8")
        except Exception as e:
            print(f"Error saving all store information to CSV: {e}")
            new_filename = generate_unique_filename(f"pricing files/{filename}.csv", ".csv")
            all_stores_df.to_csv(f"pricing files/{new_filename}.csv", index=False, encoding="utf-8")
            print(f"Saved with file name: {new_filename}")
            
    # Close the browser
    browser.quit()

    return all_stores_df


############################################################################################################

# Example Usage
# Example Usage: Maps Scraper
# search_queries = ["Churros", "Coffee", "Pizza"]
# locations = ["New York City", "Los Angeles", "Chicago"]
# max_places_to_find = 10
# max_num_scrolls = 3
# headless = True
# export_final_filename = "places_info.csv"
# export_by_search_query = False
# debug_mode = False
# url_update_count = 3
# places_df = maps_scraper(search_queries, locations, max_places_to_find, max_num_scrolls, headless, export_final_filename, export_by_search_query, debug_mode, url_update_count)
# print(places_df)

# Example Usage: Proximity Competition
# origin_addresses = np.array(["New York City", "Los Angeles", "Chicago"])
# origin_names = np.array(["NYC", "LA", "CHI"])
# destination_addresses = np.array(["Churro Place 1", "Churro Place 2", "Churro Place 3"])
# destination_names = np.array(["Churro 1", "Churro 2", "Churro 3"])
# apikey = "YOUR_API_KEY"
# times_df = time_to_destinations(origin_addresses, origin_names, destination_addresses, destination_names, apikey)
# closest_locations, times_df = get_closest_locations(origin_addresses, origin_names, destination_addresses, destination_names, times_df=times_df, apikey=apikey)

# Example Usage: Pricing Analysis
# search_query = "Churros"
# location = "New York City"
# max_stores = 50
# file_storage = "combined"
# file_name = "churros_pricing"
# headless = True
# all_stores_df = product_scraper(search_query, location, max_stores, file_storage, file_name, headless)
# print(all_stores_df)

############################################################################################################
# End of competitiveLandscapeAnalysis.py




### MORE EXAMPLES ###

# # Here is another example of map scraping
# # Parameters for the search
# max_places_to_find = 10  # Maximum number of places to find for each search
# max_num_scrolls = 5  # Maximum number of times to scroll to reveal more search results

# # Define the locations and search_queries to search for
# locations = ['Los Angeles, CA',] # 'San Francisco, CA','New York, NY','Jacksonville, FL','Portland, OR','Denver, CO']
# search_queries = ['Churros', 'Churro', 'Churrerria']  # Add more search_queries to search for

# places_df = maps_scraper(search_queries, locations, max_places_to_find, max_num_scrolls, headless=True, export_by_search_query=False, debug_mode=False)


# # Here is another example of getting the closest competition
# # times_df.to_csv('times_df.csv', index=False)

# times_df = pd.read_csv('places files/times_df.csv').drop(0)

# df = pd.read_csv('places files/Unique Churro Places LA.csv')

# origin_addresses = [
#     "12405 Washington Blvd, Los Angeles, CA 90066, United States",
#     "131 N Larchmont Blvd, Los Angeles, CA 90004, United States",
#     "4455 Los Feliz Blvd, Los Angeles, CA 90027, United States",
#     "100 S Avenue 64, Highland Park, CA 90042, USA",
#     "1534 Montana Ave, Santa Monica, CA 90403, USA",
#     "600 N Brand Blvd, Glendale, CA 91203, USA",
#     "9615 S Santa Monica Blvd, Beverly Hills, CA 90210, USA",
#     "96 E Colorado Blvd, Pasadena, CA 91105, United States",
# ]
# origin_names = [
#     "Culver city",
#     "Hancock Park", 
#     "Griffith Park",
#     "Highland Park", 
#     "Palisades Park",
#     "Glendale",
#     "Beverly Hills",
#     "Pasadena",
# ]

# destination_addresses = list(df['Address'])
# destination_names = list(df['Name'])

# max_time = 1200

# output = get_closest_locations(times_df, 
#       origin_addresses, 
#       origin_names, 
#       destination_addresses, 
#       destination_names, 
#       max_time)



# # This is the product scraping I was doing so you have another example
# search_query = "coffee shops"
# # location = "1524 Sunset Blvd, Los Angeles, CA 90026, United States"  # Echo Park
# location = "941 Westwood Blvd, Los Angeles, CA 90024, USA"  # Westwood
# max_stores = 3
# file_storage = "combined"
# file_name = "westwood_test_prices"
# headless = False

# final_stores_df = product_scraper(search_query, location, max_stores=max_stores, file_storage=file_storage, file_name=file_name, headless=headless)




