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

class RotsvastScraper:
    def __init__(self, base_url: str = "https://www.rotsvast.nl/en/property-listings/", config_file: str = "config.json"):
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        self.listings: List[Dict[str, Any]] = []
        self.session = self._create_session()
        self.history_file = 'listing_history.json'
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

    def get_page_content(self, page_number: int) -> Optional[str]:
        params = {
            'type': 2,
            'office': 'RV014',
            'page': page_number
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
            # Clean up the text - remove newlines and excessive whitespace
            price_text = ' '.join(price_text.split())
            logger.debug(f"Cleaned price text: {price_text}")
            
            # Get the first part that contains the number (before "per month")
            if "per month" in price_text:
                price_text = price_text.split("per month")[0]
            
            # Remove everything except numbers, dots and commas
            price_text = price_text.replace('€', '').strip()
            logger.debug(f"Price after basic cleaning: {price_text}")
            
            # Convert the Dutch number format (1.234,56) to float
            # First, remove the thousand separator (.)
            if '.' in price_text and ',' in price_text:
                price_text = price_text.replace('.', '')
            # Then replace the decimal comma with a dot
            price_text = price_text.replace(',', '.')
            
            logger.debug(f"Final price text to convert: {price_text}")
            price = float(price_text)
            logger.info(f"Successfully parsed price: {price}")
            return price
            
        except ValueError as e:
            logger.error(f"Could not parse price '{price_text}': {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing price '{price_text}': {str(e)}")
            return None

    def parse_listing(self, listing: BeautifulSoup) -> Optional[Dict[str, Any]]:
        try:
            location = listing.find('div', class_='residence-zipcode-place')
            if not location:
                logger.debug("No location found in listing")
                return None
            
            price_element = listing.find('div', class_='residence-price')
            if not price_element:
                logger.debug("No price element found in listing")
                return None
                
            price_text = price_element.text.strip()
            price = self.parse_price(price_text)
            if not price:
                return None
            
            if price > self.config["price_range"]["max"]:
                logger.debug(f"Price {price} above maximum {self.config['price_range']['max']}")
                return None
    
            if price < self.config["price_range"]["min"]:
                logger.debug(f"Price {price} below minimum {self.config['price_range']['min']}")
                return None
                
            street = listing.find('div', class_='residence-street')
            if not street:
                logger.debug("No street found in listing")
                return None
            
            link = listing.find('a', class_='clickable-block')
            if not link:
                logger.debug("No link found in listing")
                return None
                
            properties_div = listing.find('div', class_='residence-properties')
            properties = properties_div.text.strip() if properties_div else "No properties listed"
            
            # Extract image URL from background-image style
            image_div = listing.find('div', class_='residence-image')
            image_url = None
            if image_div and 'style' in image_div.attrs:
                style = image_div['style']
                if 'background-image:url(' in style:
                    image_url = style.split('url(')[1].split(')')[0].strip("'\"")
                    if '?' in image_url:
                        image_url = image_url.split('?')[0]
            
            # Fixing link construction
            href = link['href']
            full_link = href if href.startswith("https://") else f"https://www.rotsvast.nl{'/' if not href.startswith('/') else ''}{href}"
            
            listing_data = {
                'title': f"{street.text.strip()} - {location.text.strip()}",
                'location': location.text.strip(),
                'street': street.text.strip(),
                'price': price,
                'link': full_link,
                'properties': properties,
                'image_url': image_url,
                'found_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'source': 'Rotsvast'
            }
            
            logger.debug(f"Successfully parsed listing: {listing_data['title']}")
            return listing_data

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
                listings_elements = soup.find_all('div', class_='residence-gallery')
                
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
                
                multipage = soup.find('div', class_='multipage')
                if not multipage or multipage.find('span', class_='disabled next'):
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

    def update_readme(self) -> None:
        try:
            all_listings = {}
            
            # Add current listings
            for listing in self.listings:
                all_listings[listing['link']] = listing
                
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
                                    location = section.split(' - ')[1].split('\n')[0]
                                    street = section.split('\n')[0].strip()
                                    
                                    if '**Properties:**\n' in section:
                                        properties = section.split('**Properties:**\n')[1].split('\n* [')[0]
                                    else:
                                        properties = "No properties listed"
                                    
                                    image_url = None
                                    if '<img src="' in section:
                                        image_url = section.split('<img src="')[1].split('"')[0]
                                    
                                    source = "Rotsvast"
                                    if '**Source:**' in section:
                                        source = section.split('**Source:** ')[1].split('\n')[0]
                                    
                                    all_listings[link] = {
                                        'title': f"{street} - {location}",
                                        'location': location,
                                        'street': street,
                                        'price': price,
                                        'link': link,
                                        'properties': properties,
                                        'image_url': image_url,
                                        'found_date': found_date,
                                        'source': source
                                    }
                            except Exception as e:
                                logger.error(f"Error parsing listing section: {str(e)}")
                                continue
                except Exception as e:
                    logger.error(f"Error reading README: {str(e)}")
            
            # Write updated README
            with open('README.md', 'w', encoding='utf-8') as f:
                f.write("# Eindhoven Housing Listings\n\n")
                f.write("#### If you find this project helpful or interesting, please consider giving it a star!⭐ \n\nYour support helps make the project more visible to others who might benefit from it.")
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
                        f.write(f"* **Properties:**\n{listing['properties']}\n")
                        f.write(f"* [View listing]({listing['link']})\n\n")
                else:
                    f.write(f"No listings found between €{self.config['price_range']['min']} and €{self.config['price_range']['max']} at this time.\n")
                
                logger.info(f"Updated README with {len(all_listings_sorted)} listings")
        except Exception as e:
            logger.error(f"Failed to update README: {str(e)}")
            raise

def main():
    try:
        logger.info("Starting Rotsvast scraper")
        scraper = RotsvastScraper()
        scraper.scrape_all_pages()
        scraper.update_readme()
        scraper.save_history()
        logger.info("Scraping completed successfully")
    except Exception as e:
        logger.error(f"Fatal error in main: {str(e)}")
        raise
    finally:
        logger.info("Scraper finished execution")

if __name__ == "__main__":
    main()
