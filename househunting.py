import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os
import logging
from typing import Optional, Dict, List, Any
from urllib.parse import urljoin

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HouseHuntingScraper:
    def __init__(self, config_file: str = "config.json"):
        self.base_url = "https://househunting.nl/en/housing-offer/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        self.listings = []
        self.session = self._create_session()
        self.history_file = 'househunting_history.json'
        self.known_listings = self.load_history()
        self.config = self.load_config(config_file)

    def _create_session(self) -> requests.Session:
        try:
            session = requests.Session()
            retry_strategy = Retry(
                total=5,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            return session
        except Exception as e:
            logger.error(f"Failed to create session: {str(e)}")
            raise

    def load_config(self, config_file: str) -> Dict[str, Any]:
        try:
            if not os.path.exists(config_file):
                logger.warning(f"Config file {config_file} not found, using defaults")
                return {
                    "price_range": {"min": 600, "max": 1400},
                    "locations": ["Eindhoven"],
                    "refresh_delay": 2,
                    "max_retries": 3
                }
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info(f"Loaded configuration from {config_file}")
                return config
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing config file: {str(e)}")
            logger.info("Using default configuration")
            return {
                "price_range": {"min": 600, "max": 1400},
                "locations": ["Eindhoven"],
                "refresh_delay": 2,
                "max_retries": 3
            }

    def load_history(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    logger.info(f"Loaded {len(history)} listings from history")
                    return history
        except json.JSONDecodeError as e:
            logger.error(f"Error reading history file: {str(e)}")
            logger.info("Starting fresh with empty history")
        except Exception as e:
            logger.error(f"Unexpected error reading history: {str(e)}")
        return {}

    def save_history(self) -> None:
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.known_listings, f, indent=2, ensure_ascii=False)
                logger.info(f"Saved {len(self.known_listings)} listings to history")
        except Exception as e:
            logger.error(f"Failed to save history: {str(e)}")

    def get_page_content(self, page_number: int = 1) -> Optional[str]:
        params = {
            'type': 'for-rent',
            'filter_location': 'Eindhoven',
            'lat': '51.4431492',
            'lng': '5.4815366',
            'km': '10',
            'min-price': str(self.config["price_range"]["min"]),
            'max-price': str(self.config["price_range"]["max"]),
            'page': str(page_number)
        }
        try:
            time.sleep(self.config["refresh_delay"])
            response = self.session.get(
                self.base_url,
                params=params,
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching page {page_number}: {str(e)}")
            return None

    def parse_price(self, price_text: str) -> Optional[float]:
        try:
            # Remove currency symbol and clean up
            price_text = price_text.replace('€', '').replace(',-', '').replace('/mth', '').strip()
            logger.debug(f"Cleaned price text: {price_text}")
            
            # Convert to float
            price = float(price_text)
            logger.info(f"Successfully parsed price: {price}")
            return price
        except ValueError as e:
            logger.error(f"Could not parse price '{price_text}': {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing price '{price_text}': {str(e)}")
            return None

    def parse_listing(self, listing) -> Optional[Dict[str, Any]]:
        try:
            # Get street name
            street_elem = listing.find('h3', class_='location_street')
            if not street_elem:
                logger.debug("No street found in listing")
                return None
            street = street_elem.text.strip()

            # Get city
            city_elem = listing.find('p', class_='location_city')
            if not city_elem:
                logger.debug("No city found in listing")
                return None
            city = city_elem.text.strip()

            # Get price
            price_elem = listing.find('p', class_='location_price')
            if not price_elem:
                logger.debug("No price found in listing")
                return None
            
            price = self.parse_price(price_elem.text.strip())
            if not price:
                return None

            if price > self.config["price_range"]["max"]:
                logger.info(f"Price {price} above maximum {self.config['price_range']['max']}")
                return None

            if price < self.config["price_range"]["min"]:
                logger.info(f"Price {price} below minimum {self.config['price_range']['min']}")
                return None

            # Get link
            link_elem = listing.find('a')
            if not link_elem or not link_elem.get('href'):
                logger.debug("No link found in listing")
                return None
            link = link_elem['href']

            # Get image
            img_elem = listing.find('img', class_='location_image')
            image_url = None
            if img_elem and img_elem.get('src'):
                image_url = img_elem['src']

            # Get additional info if available
            label_elem = listing.find('div', class_='location_lable')
            status = label_elem.text.strip() if label_elem else None

            return {
                'title': f"{street} - {city}",
                'street': street,
                'location': city,
                'price': price,
                'link': link,
                'image_url': image_url,
                'status': status,
                'found_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'source': 'HouseHunting'
            }

        except Exception as e:
            logger.error(f"Error parsing listing: {str(e)}")
            return None

    def scrape_all_pages(self) -> None:
        page_number = 1
        retry_count = 0
        has_more_pages = True

        while has_more_pages and retry_count < self.config["max_retries"]:
            try:
                logger.info(f"Scraping page {page_number}...")
                html_content = self.get_page_content(page_number)
                
                if not html_content:
                    retry_count += 1
                    logger.warning(f"Failed to get page {page_number}, attempt {retry_count} of {self.config['max_retries']}")
                    continue

                soup = BeautifulSoup(html_content, 'html.parser')
                listings_elements = soup.find_all('li', class_='location')
                
                if not listings_elements:
                    logger.info(f"No listings found on page {page_number}")
                    break
                
                logger.info(f"Found {len(listings_elements)} listings on page {page_number}")
                new_listings = 0
                for listing in listings_elements:
                    parsed_listing = self.parse_listing(listing)
                    if parsed_listing:
                        listing_id = parsed_listing['link']
                        if listing_id not in self.known_listings:
                            self.listings.append(parsed_listing)
                            self.known_listings[listing_id] = parsed_listing
                            new_listings += 1
                
                logger.info(f"Added {new_listings} new listings from page {page_number}")
                
                # Check for next page - you might need to adjust this based on the site's pagination
                next_page = soup.find('a', class_='next')
                if not next_page:
                    has_more_pages = False
                    logger.info("No more pages to scrape")
                    break
                    
                page_number += 1
                retry_count = 0
            except Exception as e:
                logger.error(f"Error on page {page_number}: {str(e)}")
                retry_count += 1
                if retry_count >= self.config["max_retries"]:
                    logger.error(f"Max retries reached for page {page_number}")
                    break
                time.sleep(5)

    def append_to_readme(self) -> None:
        try:
            all_listings = {}
            
            # Read existing README content
            if os.path.exists('README.md'):
                try:
                    with open('README.md', 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    # Parse existing listings
                    listing_sections = content.split('###')[1:]
                    for section in listing_sections:
                        if '[View listing](' in section:
                            try:
                                link = section.split('[View listing](')[1].split(')')[0]
                                if link not in all_listings:
                                    price = float(section.split('**Price:** €')[1].split(' ')[0])
                                    found_date = section.split('**Found on:** ')[1].split('\n')[0]
                                    title = section.split('\n')[0].strip()
                                    
                                    image_url = None
                                    if '<img src="' in section:
                                        image_url = section.split('<img src="')[1].split('"')[0]
                                    
                                    source = "HouseHunting"
                                    if '**Source:**' in section:
                                        source = section.split('**Source:** ')[1].split('\n')[0]
                                    
                                    status = None
                                    if '**Status:**' in section:
                                        status = section.split('**Status:** ')[1].split('\n')[0]
                                    
                                    all_listings[link] = {
                                        'title': title,
                                        'price': price,
                                        'link': link,
                                        'image_url': image_url,
                                        'found_date': found_date,
                                        'source': source,
                                        'status': status
                                    }
                            except Exception as e:
                                logger.error(f"Error parsing listing section: {str(e)}")
                                continue
                except Exception as e:
                    logger.error(f"Error reading README: {str(e)}")
            
            # Add new listings
            for listing in self.listings:
                all_listings[listing['link']] = listing
            
            # Write updated README
            with open('README.md', 'w', encoding='utf-8') as f:
                f.write("# Eindhoven Housing Listings\n\n")
                f.write(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                all_listings_sorted = sorted(
                    all_listings.values(),
                    key=lambda x: datetime.strptime(x['found_date'], '%Y-%m-%d %H:%M:%S'),
                    reverse=True
                )
                
                if all_listings_sorted:
                    f.write(f"Found {len(all_listings_sorted)} listings between €{self.config['price_range']['min']} and €{self.config['price_range']['max']}:\n\n")
                    for listing in all_listings_sorted:
                        f.write(f"### {listing['title']}\n")
                        if listing.get('image_url'):
                            f.write(f'<img src="{listing["image_url"]}" alt="Property Image" width="400"/>\n\n')
                        f.write(f"* **Price:** €{listing['price']:.2f} per month\n")
                        f.write(f"* **Found on:** {listing['found_date']}\n")
                        f.write(f"* **Source:** {listing['source']}\n")
                        if listing.get('status'):
                            f.write(f"* **Status:** {listing['status']}\n")
                        f.write(f"* [View listing]({listing['link']})\n\n")
                else:
                    f.write(f"No listings found between €{self.config['price_range']['min']} and €{self.config['price_range']['max']} at this time.\n")
                
                logger.info(f"Updated README with {len(all_listings_sorted)} listings")
        except Exception as e:
            logger.error(f"Failed to update README: {str(e)}")
            raise

def main():
    try:
        logger.info("Starting HouseHunting scraper")
        scraper = HouseHuntingScraper()
        scraper.scrape_all_pages()
        scraper.append_to_readme()
        scraper.save_history()
        logger.info("Scraping completed successfully")
    except Exception as e:
        logger.error(f"Fatal error in main: {str(e)}")
        raise
    finally:
        logger.info("Scraper finished execution")

if __name__ == "__main__":
    main()
