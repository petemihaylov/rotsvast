import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os

class StienstraScraper:
    def __init__(self, base_url="https://www.stienstra.nl/uitgebreid-zoeken"):
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        self.listings = []
        self.session = self._create_session()
        self.history_file = 'stienstra_history.json'
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
            'location': '',
            'keyword': 'Eindhoven',
            'page': page_number
        }
        try:
            time.sleep(2)  # Polite delay between requests
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
            # Extract basic information
            title = listing.find('h2', class_='property-title')
            if not title or not title.find('a'):
                return None

            # Get address and link
            address = title.find('a').text.strip()
            link = "https://www.stienstra.nl" + title.find('a')['href']

            # Get price
            price_elem = listing.find('span', class_='item-price')
            if not price_elem:
                return None
            price_text = price_elem.text.strip()
            price = self.parse_price(price_text)

            if not price or price > 1400:
                return None

            # Get property type
            property_type = listing.find('p', class_='item-type')
            property_type = property_type.text.strip() if property_type else "Not specified"

            # Get amenities
            amenities = listing.find('div', class_='info-row amenities')
            features = []
            if amenities:
                # Get basic features
                features_p = amenities.find('p')
                if features_p:
                    for span in features_p.find_all('span'):
                        if span.text.strip():
                            features.append(span.text.strip())
                
                # Get additional features with checkmarks
                for p in amenities.find_all('p'):
                    for item in p.find_all('font'):
                        text = item.text.strip()
                        if text and text not in features:
                            features.append(text)

            # Get image
            img_tag = listing.find('img', class_='attachment-stienstra-property-thumb-image')
            image_url = None
            if img_tag and 'src' in img_tag.attrs:
                image_url = "https://www.stienstra.nl" + img_tag['src']

            return {
                'title': address,
                'link': link,
                'price': price,
                'property_type': property_type,
                'features': features,
                'image_url': image_url,
                'found_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'source': 'Stienstra'
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
                
                listings_elements = soup.find_all('div', class_='property-item')
                
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
                
                # Check for next page
                next_page = soup.find('a', class_='next')
                if not next_page:
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

    def append_to_readme(self):
        all_listings = {}
        
        # Read existing README content
        if os.path.exists('README.md'):
            with open('README.md', 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Keep the header section
            header_section = content.split("Found")[0]
            
            # Parse existing listings
            listing_sections = content.split('###')[1:]
            for section in listing_sections:
                if '[View listing](' in section:
                    link = section.split('[View listing](')[1].split(')')[0]
                    if link not in all_listings:
                        # Parse existing listing data
                        price = float(section.split('**Price:** €')[1].split(' ')[0])
                        found_date = section.split('**Found on:** ')[1].split('\n')[0]
                        title = section.split('\n')[0].strip()
                        
                        # Try to extract source if it exists
                        source = "Rotsvast"  # Default for old listings
                        if '**Source:** ' in section:
                            source = section.split('**Source:** ')[1].split('\n')[0]
                        
                        # Try to extract features
                        features = []
                        if '**Features:**\n' in section:
                            features_text = section.split('**Features:**\n')[1].split('\n* [')[0]
                            features = [f.strip() for f in features_text.split('\n') if f.strip()]
                        
                        # Try to extract image URL
                        image_url = None
                        if '<img src="' in section:
                            image_url = section.split('<img src="')[1].split('"')[0]
                        
                        all_listings[link] = {
                            'title': title,
                            'price': price,
                            'features': features,
                            'link': link,
                            'image_url': image_url,
                            'found_date': found_date,
                            'source': source
                        }
        
        # Add new listings
        for listing in self.listings:
            all_listings[listing['link']] = listing
        
        # Write updated README
        with open('README.md', 'w', encoding='utf-8') as f:
            # Write header
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
                    f.write(f"### {listing['title']}\n")
                    if listing.get('image_url'):
                        f.write(f'<img src="{listing["image_url"]}" alt="Property Image" width="400"/>\n\n')
                    f.write(f"* **Price:** €{listing['price']:.2f} per month\n")
                    f.write(f"* **Found on:** {listing['found_date']}\n")
                    f.write(f"* **Source:** {listing.get('source', 'Unknown')}\n")
                    if listing.get('property_type'):
                        f.write(f"* **Type:** {listing['property_type']}\n")
                    if listing.get('features'):
                        f.write("* **Features:**\n")
                        for feature in listing['features']:
                            f.write(f"  - {feature}\n")
                    f.write(f"* [View listing]({listing['link']})\n\n")
            else:
                f.write("No listings found under €1400 at this time.\n")

def main():
    try:
        scraper = StienstraScraper()
        scraper.scrape_all_pages()
        scraper.append_to_readme()
        scraper.save_history()
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        raise

if __name__ == "__main__":
    main()
