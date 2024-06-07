# Selenium packages
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

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

# Dask packages
from dask import delayed, compute
from dask.diagnostics import ProgressBar

# Function to generate a unique filename
def generate_unique_filename(filename, extension):
    base, ext = os.path.splitext(filename)
    counter = 1
    new_filename = f"{base}{extension}"
    while os.path.exists(new_filename):
        new_filename = f"{base}_{counter}{extension}"
        counter += 1
    return new_filename

def wait_for_page_load(browser, timeout=20):   
    """Wait for the page to load by checking the document.readyState.""" 
    WebDriverWait(browser, timeout).until(
        lambda x: x.execute_script("return document.readyState") == "complete"
    )

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
    
    print("________________________")
    print("li elements: ", li_elements)
    print("________________________")
    
    # for i in range(len(li_elements)):  # Loop through each category
    #     li_elements = browser.find_elements(By.TAG_NAME, "li")
    #     li_elt = li_elements[i]
        
    #     if (li_elt.find_elements(By.TAG_NAME, "h3")  # Check if it contains food items and is not Featured Items
    #         and li_elt.find_elements(By.TAG_NAME, "h3")[0].text != "Artículos destacados" 
    #         and li_elt.find_elements(By.TAG_NAME, "h3")[0].text != "Featured items"):
            
    #         category = li_elt.find_elements(By.TAG_NAME, "h3")[0].text
            
    #         # Locate all matching elements using Selenium's find_elements
    #         span_elements = li_elt.find_elements(By.TAG_NAME, "span")
    #         price_pattern = r"^(USD ?|\$ ?)\d+\.\d{2}$"
    #         review_pattern = r" \d+% \((\d+)\)"
            
    #         print(f"Category: {category}")
    
    price_pattern = r"^(USD ?|\$ ?|MX\$ ?)\d+\.\d{2}$"
    review_pattern = r" \d+% \((\d+)\)"
    
    span_elements = browser.find_elements(By.TAG_NAME, "span")
    category = None
                        
    for index, element in enumerate(span_elements):
        print("Span element found")
        try:
            price = element.text
        except Exception as e:
            span_elements = browser.find_elements(By.TAG_NAME, "span")
            price = span_elements[index].text
        
        calories = None
        rating_percentage = None
        num_reviews = 0
        
        # Check if the current text begins with "USD" or "$"
        if price.startswith("USD") or price.startswith("$") or price.startswith("MX$"):
            if not re.match(price_pattern, price):  # Check if the str matches the price pattern
                continue
            
            print("Price pattern matched")
                                
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

def click_show_more_until_disappear(xpath, browser):
    wait = WebDriverWait(browser, 10)  # wait for up to 10 seconds for the condition
    while True:
        try:
            show_more_button = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            show_more_button.click()
        except TimeoutException:
            break

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
    show_more_button_xpath = '//*[@id="main-content"]/div/div[2]/div/div/button'
    
    print("Clicking show more button...")
    # click_show_more_until_disappear(show_more_button_xpath, browser=browser)
    print("________________________")
    print("Show more button clicked.")
    print("________________________")
    
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
    
    print("______________________")
    print("Stores URL List: ", store_urls_list)
    print("______________________")

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
    
    # Adjust max_stores if necessary
    max_stores = min(max_stores, len(store_urls))

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

# if __name__ == '__main__':
#     search_query = "health food"
#     location = "Dr. Andrade 85, Doctores, Cuauhtémoc, 06720 Ciudad de México, CDMX"
#     locations = [
#         #"Dr. Andrade 85, Doctores, Cuauhtémoc, 06720 Ciudad de México, CDMX",
#         # "Dr. Juan de Dios Treviño 10, San Jerónimo, 64634 Monterrey",
#         # "C. Aurelio Luis Gallardo 64, Ladrón de Guevara, 44650 Guadalajara, Jal., México",
#         # "Av. Adolfo Mateos no. 4604 Local 2, Col. Bosques del Nogalar San Nicolás de los Garza NL CP 66480",
#         # "Blvd Gustavo Díaz Ordaz 104, La Fama, 66100 Santa Catarina, Monterrey",
#         # "Avenida Adolfo López Mateos 1514, San Salvador Tizatlali, Metepec, Estado de México.",
#         # "C. Federico Medrano 3434, San Andrés, 44810 Guadalajara",
#         # "Calle 31 número 682, Cd Caucel, 97300 Mérida",
#         # "Alvaro Obregón 603, Zona Centro, 25000 Saltillo",
#         # "Av. Juan Gil Preciado 4014, Alamitos, 45134 Zapopan",
#         # "Av. 35 Pte. 1106, Los Volcanes, 72410 Puebla"
#     ]
#     max_stores = 400
#     file_name = "prices"
#     headless = True
#     all_stores_df = product_scraper(search_query, location, max_stores=max_stores, filename=location, headless=headless)

# create a jupyter notebook cell

print("Updated IX")