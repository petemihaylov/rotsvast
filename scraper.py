import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime

class RotsvastScraper:
    def __init__(self, base_url="https://www.rotsvast.nl/en/property-listings/"):
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.listings = []

    def get_page_content(self, page_number):
        params = {
            'page': page_number,
            'type': 2,
            'office': 'RV014'
        }
        response = requests.get(self.base_url, params=params, headers=self.headers)
        return response.text

    def parse_listing(self, listing):
        try:
            location = listing.find('div', class_='residence-zipcode-place').text.strip()
            if 'Eindhoven' not in location:
                return None
            
            price_element = listing.find('div', class_='residence-price')
            if not price_element:
                return None
                
            price_text = price_element.text.strip()
            # Extract numeric value from price
            price = float(''.join(filter(str.isdigit, price_text)))
            
            if price > 1400 && pice < 600:
                return None
                
            title = listing.find('div', class_='residence-title').text.strip()
            link = listing.find('a')['href']
            
            return {
                'title': title,
                'location': location,
                'price': price,
                'link': f"https://www.rotsvast.nl{link}",
            }
        except Exception as e:
            print(f"Error parsing listing: {e}")
            return None

    def scrape_all_pages(self):
        page_number = 1
        while True:
            html_content = self.get_page_content(page_number)
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Parse listings on current page
            listings_elements = soup.find_all('div', class_='residence-item')
            
            for listing in listings_elements:
                parsed_listing = self.parse_listing(listing)
                if parsed_listing:
                    self.listings.append(parsed_listing)
            
            # Check if there's a next page
            multipage = soup.find('div', class_='multipage')
            if not multipage or multipage.find('span', class_='disabled next'):
                break
                
            page_number += 1

    def update_readme(self):
        with open('README.md', 'w', encoding='utf-8') as f:
            f.write("# Eindhoven Housing Listings\n\n")
            f.write(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("Listings under €1400 in Eindhoven:\n\n")
            
            for listing in self.listings:
                f.write(f"## {listing['title']}\n")
                f.write(f"* Location: {listing['location']}\n")
                f.write(f"* Price: €{listing['price']:.2f}\n")
                f.write(f"* [View listing]({listing['link']})\n\n")

def main():
    scraper = RotsvastScraper()
    scraper.scrape_all_pages()
    scraper.update_readme()

if __name__ == "__main__":
    main()


