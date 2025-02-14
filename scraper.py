import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os

class RotsvastScraper:
    def __init__(self, base_url="https://www.rotsvast.nl/en/property-listings/"):
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        self.listings = []
        self.session = self._create_session()
        self.history_file = 'listing_history.json'
        self.known_listings = self.load_history()

    def _create_session(self):
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

    def load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print("Error reading history file, starting fresh")
                return {}
        return {}

    def save_history(self):
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.known_listings, f, indent=2, ensure_ascii=False)

    def get_page_content(self, page_number):
        params = {
            'type': 2,
            'office': 'RV014',
            'page': page_number
        }
        try:
            time.sleep(2)
            response = self.session.get(
                self.base_url, 
                params=params, 
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"Error fetching page {page_number}: {str(e)}")
            raise

    def parse_price(self, price_text):
        cleaned = ''.join(c for c in price_text if c.isdigit() or c in '.,')
        try:
            if ',' in cleaned:
                cleaned = cleaned.replace('.', '').replace(',', '.')
            return float(cleaned)
        except ValueError:
            print(f"Could not parse price: {price_text}")
            return None

    def parse_listing(self, listing):
        try:
            location = listing.find('div', class_='residence-zipcode-place')
            if not location:
                return None
            
            price_element = listing.find('div', class_='residence-price')
            if not price_element:
                return None
                
            price_text = price_element.text.strip()
            price = self.parse_price(price_text)
            
            if price > 1400:
                return None

            if price < 600:
                return None
                
            street = listing.find('div', class_='residence-street')
            if not street:
                return None
            
            link = listing.find('a', class_='clickable-block')
            if not link:
                return None
                
            properties_div = listing.find('div', class_='residence-properties')
            properties = properties_div.text.strip() if properties_div else "No properties listed"
            
            full_link = f"https://www.rotsvast.nl{link['href']}"
                
            return {
                'title': f"{street.text.strip()} - {location.text.strip()}",
                'location': location.text.strip(),
                'street': street.text.strip(),
                'price': price,
                'link': full_link,
                'properties': properties,
                'found_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        except Exception as e:
            print(f"Error parsing listing: {e}")
            return None

    def scrape_all_pages(self):
        page_number = 1
        max_retries = 3
        retry_count = 0
        has_more_pages = True

        while has_more_pages and retry_count < max_retries:
            try:
                print(f"Scraping page {page_number}...")
                html_content = self.get_page_content(page_number)
                soup = BeautifulSoup(html_content, 'html.parser')
                
                listings_elements = soup.find_all('div', class_='residence-gallery')
                
                if not listings_elements:
                    print(f"No listings found on page {page_number}")
                    break
                
                print(f"Found {len(listings_elements)} listings on page {page_number}")
                for listing in listings_elements:
                    parsed_listing = self.parse_listing(listing)
                    if parsed_listing:
                        listing_id = parsed_listing['link']
                        if listing_id not in self.known_listings:
                            self.listings.append(parsed_listing)
                            self.known_listings[listing_id] = parsed_listing
                
                multipage = soup.find('div', class_='multipage')
                if not multipage or multipage.find('span', class_='disabled next'):
                    has_more_pages = False
                    print("No more pages to scrape")
                    break
                    
                page_number += 1
                retry_count = 0
            except Exception as e:
                print(f"Error on page {page_number}: {str(e)}")
                retry_count += 1
                if retry_count >= max_retries:
                    print(f"Max retries reached for page {page_number}")
                    break
                time.sleep(5)

    def update_readme(self):
        # Get all unique listings, keeping only the most recent version
        all_listings = {}  # Using dict to maintain unique listings by URL
        
        # Add current listings
        for listing in self.listings:
            all_listings[listing['link']] = listing
            
        # Read and parse existing content for previous listings
        if os.path.exists('README.md'):
            try:
                with open('README.md', 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Extract listings from existing content using simple parsing
                listing_sections = content.split('###')[1:]  # Split by listing headers
                for section in listing_sections:
                    if '[View listing](' in section:
                        link = section.split('[View listing](')[1].split(')')[0]
                        # Only keep old listing if we haven't found it in current scrape
                        if link not in all_listings:
                            # Parse the old listing into our format
                            price = float(section.split('**Price:** €')[1].split(' ')[0])
                            found_date = section.split('**Found on:** ')[1].split('\n')[0]
                            location = section.split(' - ')[1].split('\n')[0]
                            street = section.split('\n')[0].strip()
                            properties = section.split('**Properties:**\n')[1].split('\n* [View')[0]
                            
                            all_listings[link] = {
                                'title': f"{street} - {location}",
                                'location': location,
                                'street': street,
                                'price': price,
                                'link': link,
                                'properties': properties,
                                'found_date': found_date
                            }
            except Exception as e:
                print(f"Error parsing existing README: {e}")
        
        # Write updated README with all unique listings
        with open('README.md', 'w', encoding='utf-8') as f:
            f.write("# Eindhoven Housing Listings\n\n")
            f.write(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Write all listings, sorted by date (newest first)
            all_listings_sorted = sorted(
                all_listings.values(),
                key=lambda x: datetime.strptime(x['found_date'], '%Y-%m-%d %H:%M:%S'),
                reverse=True
            )
            
            if all_listings_sorted:
                f.write(f"Found {len(all_listings_sorted)} listings under €1400:\n\n")
                for listing in all_listings_sorted:
                    f.write(f"### {listing['street']} - {listing['location']}\n")
                    f.write(f"* **Price:** €{listing['price']:.2f} per month\n")
                    f.write(f"* **Found on:** {listing['found_date']}\n")
                    f.write(f"* **Properties:**\n{listing['properties']}\n")
                    f.write(f"* [View listing]({listing['link']})\n\n")
            else:
                f.write("No listings found under €1400 at this time.\n")

def main():
    try:
        scraper = RotsvastScraper()
        scraper.scrape_all_pages()
        scraper.update_readme()
        scraper.save_history()
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        raise

if __name__ == "__main__":
    main()
