from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
from datetime import datetime
import configparser

# Read configuration
config = configparser.ConfigParser()
config.read('config.ini')

# Carma settings
url = config['carma']['url']
username = config['carma']['username']
password = config['carma']['password']
start_date = config['carma']['start_date']
sleep_time = int(config['carma']['sleep_time'])

# File settings
data_file = config['files']['data_file']
checkpoint_file = config['files']['scrape_checkpoint_file']

# Initialize WebDriver
# On macOS: download chromedriver from https://googlechromelabs.github.io/chrome-for-testing/#stable
# $ sudo cp ~/Desktop/chromedriver-mac-arm64/chromedriver /usr/local/bin
# $ sudo xattr -d com.apple.quarantine /usr/local/bin/chromedriver
# On LXC: apt install chromium chromium-driver
options = Options()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(options=options)

def scrape():
    try:
        # Open the login page
        driver.get(url)

        # # Locate the username and password fields, and enter login credentials
        username_txt = driver.find_element(By.ID, "username_txt")  # Replace with the actual ID of the username field
        password_txt = driver.find_element(By.ID, "password_txt")  # Replace with the actual ID of the password field

        # # Enter your credentials
        username_txt.send_keys(username)
        password_txt.send_keys(password)

        # # Submit the form
        login_button = driver.find_element(By.ID, "login_btn")
        login_button.click()

        # Wait until the next page loads and a specific element is available
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "UpdatePanel"))
        )

        # either we are on latest page or we are one page back - click on next to check
        # and go to last available page and then start scraping
        next_button = driver.find_element(By.ID, "nextMonth_btn")
        if next_button.is_enabled():
            next_button.click()
            time.sleep(sleep_time)

        checkpoint = get_checkpoint()
        data = scrape_page(checkpoint)
        if len(data) > 0:
            write_data(data)
            save_checkpoint(data[-1][0])
    finally:
        # Close the WebDriver
        driver.quit()

def scrape_page(checkpoint):
    chart_data = driver.execute_script("return chart1.series[0].data.filter(p => p.y != 0).map(p => {return [p.category, p.y]});")

    # if we are at the checkpoint - stop
    for i in range(len(chart_data), 0, -1):
        if chart_data[i-1][0] == checkpoint:
            return list(chart_data[i:])

    # if the entire page is older than the checkpoint, no new data exists yet
    if chart_data and parse_date(chart_data[-1][0]) <= parse_date(checkpoint):
        return []

    prev_button = driver.find_element(By.ID, "prevMonth_btn")
    prev_button.click()

    time.sleep(sleep_time)
    prev_data = scrape_page(checkpoint)
    curr_data = list(chart_data)
    return prev_data + curr_data

def write_data(data):
    file_exists = os.path.isfile(data_file)

    with open(data_file, "a") as f:
        if not file_exists:
            f.write("Epoch Unix Timestamp, sensor value\n")

        for d in data:
            f.write(f"{parse_date(d[0])},{d[1]}\n")

def get_checkpoint():
    try:
        with open(checkpoint_file, "r") as f:
            return f.read().strip()
    except:
        return start_date

def save_checkpoint(checkpoint):
    with open(checkpoint_file, "w") as f:
        f.write(checkpoint)

def parse_date(date_str):
    dt = datetime.strptime(date_str, "%d/%b/%Y")
    return dt.strftime("%s")

if __name__ == "__main__":
    scrape()
