#!/usr/bin/env python3
import os
import json
import time
import requests
import random
import logging
import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, quote_plus, unquote
import google.generativeai as genai
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ai_content_crawler.log"),
        logging.StreamHandler()
    ]
)

# Load environment variables
load_dotenv()

# Google Custom Search constants
GOOGLE_CSE_API_KEY = "Enter Your Google Search API"
GOOGLE_CSE_ID = "Enter Your Search Engine ID"
GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"

class AIContentCrawler:
    """AI-driven crawler that autonomously discovers content based on user queries"""
    
    def __init__(self):
        # Initialize Google Gemini API
        api_key = os.getenv("GOOGLE_API_KEY")
        model_name = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")
        
        if not api_key:
            logging.error("Google API key not found. Please set GOOGLE_API_KEY in .env file")
            raise ValueError("Google API key not found")
            
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        logging.info("Google Gemini AI initialized successfully")
        
        # Create directories for data storage
        os.makedirs("data/content", exist_ok=True)
        
        # User agent list to avoid being blocked
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]
        
        # Track visited URLs to avoid duplicates
        self.visited_urls = set()
        self.content_urls = set()  # URLs that contain relevant content
        self.potential_urls = set()  # URLs that might lead to content
        
        # Track domain counts to ensure diversity
        self.domain_counts = {}
        self.max_per_domain = 5  # Maximum content to scrape from a single domain
        
        # Content similarity detection
        self.content_fingerprints = []  # Store fingerprints of scraped content
        self.similarity_threshold = 0.7  # Threshold for considering content as duplicate
        
        # Available search engines
        self.search_engines = [
            "https://www.google.com/search?q={query}",
            "https://www.bing.com/search?q={query}",
            "https://search.brave.com/search?q={query}",
            "https://duckduckgo.com/?q={query}"
        ]
        
        # Rate limiting for API calls
        self.last_api_call = 0
        self.min_api_interval = 2  # seconds between API calls
        self.backoff_time = 5  # initial backoff time
        self.max_backoff = 60  # maximum backoff in seconds
        
        # Custom Search API properties
        self.last_search_api_call = 0
        self.min_search_api_interval = 1  # seconds between Google Search API calls
        
        # Common content domains
        self.content_domains = [
            'medium.com', 'dev.to', 'towardsdatascience.com', 'hackernoon.com',
            'freecodecamp.org', 'infoworld.com', 'dzone.com', 'stackoverflow.com',
            'stackexchange.com', 'reddit.com', 'habr.com', 'levelup.gitconnected.com',
            'blog.logrocket.com', 'blog.bitsrc.io', 'tds.ai', 'hashnode.com',
            'techcrunch.com', 'wired.com', 'venturebeat.com', 'thenextweb.com',
            'zdnet.com', 'cnet.com', 'theverge.com', 'engadget.com',
            'arstechnica.com', 'mashable.com', 'vox.com', 'forbes.com',
            'businessinsider.com', 'nytimes.com', 'wsj.com', 'bbc.com',
            'reuters.com', 'cnbc.com', 'bloomberg.com', 'ft.com'
        ]
        
        # User query
        self.user_query = None
    
    def get_random_user_agent(self):
        """Get a random user agent to avoid detection"""
        return random.choice(self.user_agents)
    
    def prompt_user_for_query(self):
        """Ask the user what content they want to scrape"""
        print("\n" + "="*50)
        print("WELCOME TO THE AI CONTENT SCRAPER")
        print("="*50)
        print("What type of content would you like to scrape?")
        print("Examples: 'AI news latest', 'climate change research', 'JavaScript frameworks 2025'")
        
        while True:
            query = input("\nEnter your search query: ").strip()
            if query:
                break
            print("Please enter a valid query!")
        
        # Ask for maximum content per domain
        print("\nHow many items maximum would you like to scrape from a single domain?")
        print("(Default is 5, enter a lower number for more diverse results, higher for more comprehensive results from top domains)")
        
        try:
            max_per_domain = input("Maximum content per domain [5]: ").strip()
            if max_per_domain:
                self.max_per_domain = int(max_per_domain)
                print(f"Maximum content per domain set to: {self.max_per_domain}")
            else:
                print("Using default value of 5")
        except ValueError:
            print("Invalid input, using default value of 5")
        
        return query
    
    def api_call_with_backoff(self, func, *args, **kwargs):
        """Make an API call with exponential backoff for rate limiting"""
        # Enforce minimum time between API calls
        current_time = time.time()
        time_since_last_call = current_time - self.last_api_call
        
        if time_since_last_call < self.min_api_interval:
            sleep_time = self.min_api_interval - time_since_last_call
            logging.debug(f"Rate limiting: Sleeping for {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
        
        backoff = self.backoff_time
        max_retries = 5
        retries = 0
        
        while retries < max_retries:
            try:
                self.last_api_call = time.time()
                result = func(*args, **kwargs)
                # Reset backoff on success
                self.backoff_time = 5
                return result
            
            except Exception as e:
                error_str = str(e)
                retries += 1
                
                # Check if this is a rate limit error
                if "429" in error_str or "exceeded your current quota" in error_str:
                    logging.warning(f"Rate limit exceeded, backing off for {backoff} seconds")
                    time.sleep(backoff)
                    # Increase backoff for next time
                    self.backoff_time = min(self.backoff_time * 2, self.max_backoff)
                    backoff = self.backoff_time
                else:
                    # For other errors, just wait a bit and retry
                    logging.error(f"API error: {error_str}, retrying in 5 seconds")
                    time.sleep(5)
                    
                # If we've run out of retries, raise the exception
                if retries >= max_retries:
                    raise
        
        return None
    
    def extract_json_from_response(self, response_text):
        """
        Safely extract JSON from AI response text, handling nested code blocks
        """
        try:
            # Clean up response to extract JSON
            if "```json" in response_text:
                json_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_text = response_text.split("```")[1].split("```")[0]
            else:
                json_text = response_text
            
            json_text = json_text.strip()
            
            # Handle nested code blocks that might break JSON parsing
            cleaned_json_text = ""
            in_code_block = False
            for line in json_text.split("\n"):
                if "```" in line:
                    if in_code_block:
                        in_code_block = False
                        cleaned_json_text += "```\""  # Close string properly
                    else:
                        in_code_block = True
                        cleaned_json_text += "\"```"  # Open string properly
                else:
                    # Escape quotes in code blocks
                    if in_code_block:
                        line = line.replace("\"", "\\\"")
                    cleaned_json_text += line + "\n"
            
            # Parse the cleaned JSON
            return json.loads(cleaned_json_text)
        except json.JSONDecodeError:
            # Fallback: try more aggressive cleaning
            try:
                # Use regex to fix common JSON issues
                # Find all code blocks and replace with placeholders
                code_blocks = re.findall(r'```.*?```', json_text, re.DOTALL)
                for i, block in enumerate(code_blocks):
                    json_text = json_text.replace(block, f'"CODE_BLOCK_{i}"')
                
                # Parse the modified JSON
                return json.loads(json_text)
            except:
                # If all else fails, create a simple JSON with the raw text
                return {"raw_text": response_text}
    
    def fetch_url(self, url):
        """Fetch a URL and return the HTML content"""
        headers = {'User-Agent': self.get_random_user_agent()}
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logging.error(f"Error fetching {url}: {str(e)}")
            return None
    
    def extract_all_links(self, url, html_content):
        """Extract all links from a webpage and normalize them"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            links = []
            
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                
                # Skip empty links, fragments, javascript
                if not href or href.startswith('#') or href.startswith('javascript:'):
                    continue
                
                # Handle relative URLs
                if not href.startswith(('http://', 'https://')):
                    href = urljoin(url, href)
                
                # Clean URL (remove tracking parameters, etc.)
                parsed_url = urlparse(href)
                clean_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
                
                if parsed_url.query:
                    # Keep only essential query parameters (skip tracking, analytics)
                    essential_params = []
                    for param in parsed_url.query.split('&'):
                        if '=' in param:
                            name, value = param.split('=', 1)
                            if name.lower() not in ['utm_source', 'utm_medium', 'utm_campaign', 'ref', 'source']:
                                essential_params.append(param)
                    
                    if essential_params:
                        clean_url += '?' + '&'.join(essential_params)
                
                links.append(clean_url)
            
            return links
            
        except Exception as e:
            logging.error(f"Error extracting links from {url}: {str(e)}")
            return []
    
    def is_likely_content_domain(self, url):
        """Check if URL is likely to be a content site"""
        domain = urlparse(url).netloc
        
        for content_domain in self.content_domains:
            if content_domain in domain:
                return True
                
        return False
    
    def google_custom_search(self, query):
        """
        Use Google Custom Search API to find content pages
        
        Args:
            query (str): Search query
            
        Returns:
            list: URLs of potential content pages
        """
        # Rate limiting for search API
        current_time = time.time()
        time_since_last_call = current_time - self.last_search_api_call
        
        if time_since_last_call < self.min_search_api_interval:
            sleep_time = self.min_search_api_interval - time_since_last_call
            logging.debug(f"Rate limiting Search API: Sleeping for {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
        
        # Add date restrictions for more recent content (when appropriate)
        date_restrict = None
        if any(date_term in query.lower() for date_term in ["latest", "recent", "new", "today", "current", "2025", "2024"]):
            # For queries asking for latest/recent content, restrict to last month
            date_restrict = "m1"  # Last month
        
        # Set up params for the API call
        params = {
            "key": GOOGLE_CSE_API_KEY,
            "cx": GOOGLE_CSE_ID,
            "q": query,
            "num": 10,  # Maximum results per request (1-10)
            "sort": "date"  # Try to sort by date for latest content
        }
        
        # Add date restriction if specified
        if date_restrict:
            params["dateRestrict"] = date_restrict
        
        logging.info(f"Google Custom Search API: Searching for '{query}'")
        if date_restrict:
            logging.info(f"Date restricted to: {date_restrict}")
        
        try:
            self.last_search_api_call = time.time()
            response = requests.get(GOOGLE_CSE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            result_urls = []
            
            # Check if we have search results
            if "items" in data:
                for item in data["items"]:
                    result_urls.append(item["link"])
                    # Log some metadata about the result to verify recency
                    if "snippet" in item and len(item["snippet"]) > 0:
                        snippet_preview = item["snippet"][:100] + "..." if len(item["snippet"]) > 100 else item["snippet"]
                        logging.debug(f"Result: {item['title']} - Snippet: {snippet_preview}")
                    if "pagemap" in item and "metatags" in item["pagemap"] and len(item["pagemap"]["metatags"]) > 0:
                        if "og:updated_time" in item["pagemap"]["metatags"][0]:
                            logging.info(f"Result updated time: {item['pagemap']['metatags'][0]['og:updated_time']}")
                
                logging.info(f"Google Custom Search API: Found {len(result_urls)} results")
                
                # Try a second search without date restriction if first search returned few results
                if len(result_urls) < 3 and date_restrict:
                    logging.info("Few results with date restriction, trying without restriction")
                    params.pop("dateRestrict")
                    
                    # Add a small delay before the second request
                    time.sleep(1)
                    
                    self.last_search_api_call = time.time()
                    response = requests.get(GOOGLE_CSE_URL, params=params, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                    
                    if "items" in data:
                        for item in data["items"]:
                            if item["link"] not in result_urls:  # Avoid duplicates
                                result_urls.append(item["link"])
                        
                        logging.info(f"Additional search: Found {len(result_urls)} total results")
            else:
                logging.warning("Google Custom Search API: No results found")
                if "error" in data:
                    logging.error(f"Google Custom Search API error: {data['error'].get('message')}")
            
            return result_urls
            
        except Exception as e:
            logging.error(f"Error using Google Custom Search API: {str(e)}")
            return []
    
    def search_for_content(self, query):
        """
        Use search engines to find potential content pages
        
        Args:
            query (str): Search query
            
        Returns:
            list: URLs of potential content pages
        """
        potential_content_urls = []
        
        # First try using Google Custom Search API
        search_results = self.google_custom_search(query)
        
        if search_results:
            # Use AI to categorize and rank the Google search results for relevance and recency
            if len(search_results) > 0:
                prompt = f"""
                I'm looking for content about "{self.user_query}", with a focus on the most RECENT and UP-TO-DATE information.
                
                I've found these links from a Google search:
                
                {json.dumps(search_results, indent=2)}
                
                Please analyze these links and:
                1. Determine which ones likely contain recent, relevant content about "{self.user_query}"
                2. Rank them by likely relevance and recency (most recent and relevant first)
                
                Format your response as a JSON object with these fields:
                - "relevant_links": Array of URLs that likely contain relevant content, ranked by relevance and recency
                - "irrelevant_links": Array of URLs that probably don't contain useful/recent content
                
                IMPORTANT: Prioritize links that appear to contain the MOST RECENT information about {self.user_query}.
                Consider publication dates in URLs, terms like "latest", "update", "2024", "2025", etc.
                """
                
                try:
                    response = self.api_call_with_backoff(self.model.generate_content, prompt)
                    
                    # Extract JSON from response
                    response_text = response.text
                    
                    # Parse the response
                    classified_links = self.extract_json_from_response(response_text)
                    
                    # Extract relevant links
                    relevant_links = classified_links.get("relevant_links", [])
                    
                    logging.info(f"AI classified and ranked {len(relevant_links)} URLs from Google Search results")
                    
                    # Add relevant links to potential content URLs
                    potential_content_urls = relevant_links
                    
                except Exception as e:
                    logging.error(f"Error processing AI response for Google search results: {str(e)}")
                    # If AI classification fails, use all search results
                    potential_content_urls = search_results
            
            return potential_content_urls
        
        # Fallback to web scraping search if Google Custom Search API fails
        logging.info("Falling back to web scraping search")
        
        # Choose a random search engine
        search_engine_url = "https://www.google.com/search?q={query}"
        
        # Format the query
        search_url = search_engine_url.format(query=quote_plus(query))
        
        logging.info(f"Fallback searching for: {query}")
        logging.info(f"Search URL: {search_url}")
        
        # Fetch search results
        html_content = self.fetch_url(search_url)
        if not html_content:
            return []
        
        # Extract all links from search results
        raw_links = self.extract_all_links(search_url, html_content)
        
        # Filter links to remove search engine results pages
        links = []
        for link in raw_links:
            # Skip search engine result page links
            if "google.com" in link and any(skip in link for skip in ['/search?', 'webcache', '/preferences', 'accounts.google', 'maps.google', 'policies.google']):
                continue
                
            links.append(link)
        
        # Use AI to categorize links for relevance to the user query
        if links:
            prompt = f"""
            I'm looking for content about "{self.user_query}", with a focus on the most RECENT and UP-TO-DATE information.
            
            I've found these links from a search engine:
            
            {json.dumps(links[:20], indent=2)}
            
            Please analyze these links and:
            1. Determine which ones likely contain recent, relevant content about "{self.user_query}"
            2. Rank them by likely relevance and recency (most recent and relevant first)
            
            Format your response as a JSON object with these fields:
            - "relevant_links": Array of URLs that likely contain relevant content, ranked by relevance and recency
            - "irrelevant_links": Array of URLs that probably don't contain useful/recent content
            
            IMPORTANT: Prioritize links that appear to contain the MOST RECENT information about {self.user_query}.
            Consider publication dates in URLs, terms like "latest", "update", "2024", "2025", etc.
            """
            
            try:
                response = self.api_call_with_backoff(self.model.generate_content, prompt)
                
                # Extract JSON from response
                response_text = response.text
                
                # Parse the response
                classified_links = self.extract_json_from_response(response_text)
                
                # Extract relevant links
                relevant_links = classified_links.get("relevant_links", [])
                
                logging.info(f"Found {len(relevant_links)} potentially relevant content URLs")
                
                # Add all promising URLs to the result
                potential_content_urls = relevant_links
                
            except Exception as e:
                logging.error(f"Error processing AI response for search: {str(e)}")
                # Fallback to domain-based filtering
                for link in links[:10]:
                    if self.is_likely_content_domain(link):
                        potential_content_urls.append(link)
        
        return potential_content_urls
    
    def is_relevant_content(self, url, html_content):
        """
        Use AI to determine if a page contains relevant and recent content for the user query
        
        Args:
            url (str): URL of the page
            html_content (str): HTML content of the page
            
        Returns:
            bool: True if the page contains relevant content, False otherwise
        """
        try:
            # Parse HTML
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract text content
            text_content = soup.get_text()
            
            # Try to extract publication date from meta tags
            publication_date = None
            for meta in soup.find_all('meta'):
                # Check common date meta tags
                if meta.get('property') in ['article:published_time', 'og:updated_time', 'datePublished', 'dateModified']:
                    publication_date = meta.get('content')
                    logging.info(f"Found publication date: {publication_date} for {url}")
                    break
                elif meta.get('name') in ['date', 'pubdate', 'publication_date', 'lastmod']:
                    publication_date = meta.get('content')
                    logging.info(f"Found publication date: {publication_date} for {url}")
                    break
            
            # Create a truncated version for the prompt
            truncated_text = text_content[:5000] + ("..." if len(text_content) > 5000 else "")
            
            # Use AI to determine relevance and recency
            prompt = f"""
            Analyze this webpage and determine if it contains substantial, relevant, and RECENT content about "{self.user_query}".
            
            URL: {url}
            Publication Date (if found): {publication_date if publication_date else "Unknown"}
            
            Content should be:
            1. Directly related to {self.user_query}
            2. Informative and substantial (not just a brief mention)
            3. Useful to someone wanting to learn about {self.user_query}
            4. Preferably RECENT or UP-TO-DATE information
            
            DON'T consider content relevant if it:
            - Only briefly mentions the topic
            - Is primarily about something else
            - Is a generic listing page with minimal information
            - Is a paywall or login page
            - Is clearly outdated (more than 2-3 years old, unless it's still authoritative)
            
            Webpage content:
            ---
            {truncated_text}
            ---
            
            First, answer YES or NO if this page contains substantial relevant content about {self.user_query}.
            Then, briefly explain your reasoning, including an assessment of how recent/up-to-date the content appears to be.
            """
            
            response = self.api_call_with_backoff(self.model.generate_content, prompt)
            response_text = response.text.strip().lower()
            
            # Check if response indicates relevance
            is_relevant = response_text.startswith("yes")
            
            if is_relevant:
                logging.info(f"AI analysis for {url}: Relevant")
            else:
                logging.info(f"AI analysis for {url}: Not Relevant")
                if "outdated" in response_text or "old" in response_text:
                    logging.info(f"Content rejected due to age: {url}")
            
            return is_relevant
            
        except Exception as e:
            logging.error(f"Error analyzing relevance for {url}: {str(e)}")
            return False
    
    def extract_content_data(self, url, html_content):
        """
        Extract comprehensive data about content
        
        Args:
            url (str): URL of the content
            html_content (str): HTML content of the page
            
        Returns:
            dict: Content data
        """
        try:
            # Parse HTML
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract text content
            text_content = soup.get_text()
            
            # Get the page title
            title = soup.find('title').text if soup.find('title') else "Unknown"
            
            # Try to extract publication date from meta tags
            publication_date = None
            for meta in soup.find_all('meta'):
                # Check common date meta tags
                if meta.get('property') in ['article:published_time', 'og:updated_time', 'datePublished', 'dateModified']:
                    publication_date = meta.get('content')
                    break
                elif meta.get('name') in ['date', 'pubdate', 'publication_date', 'lastmod']:
                    publication_date = meta.get('content')
                    break
                elif meta.get('itemprop') in ['datePublished', 'dateModified', 'dateCreated']:
                    publication_date = meta.get('content')
                    break
            
            # Create a truncated version for the prompt
            truncated_text = text_content[:10000] + ("..." if len(text_content) > 10000 else "")
            
            # Use AI to extract content data
            prompt = f"""
            Extract and summarize the key information from this webpage about "{self.user_query}".
            
            URL: {url}
            Title: {title}
            Publication Date (if found in metadata): {publication_date if publication_date else "Not found in metadata"}
            
            Based on the webpage content, please extract:
            
            - title: The main title of the content
            - summary: A concise summary (150-200 words) of the key information
            - key_points: List of the most important points or findings (5-7 bullet points)
            - date_published: The publication or last update date of this content (VERY IMPORTANT - search for date indicators in the text if not in metadata)
            - author: The author(s) if available
            - content_type: Type of content (article, blog post, news, research, etc.)
            - categories: List of categories or topics this content covers
            - relevance_score: On a scale of 1-10, how relevant and recent is this content to the query "{self.user_query}"
            - full_text: The complete main content text, properly formatted (exclude navigation, ads, etc.)
            
            Webpage content:
            ---
            {truncated_text}
            ---
            
            Format your response as a JSON object with these fields.
            For the date_published field, format it as YYYY-MM-DD if possible or otherwise as clearly as you can determine.
            If no specific date is available, estimate approximately how recent the content is (e.g., "Recent - 2024", "Appears to be from 2023", etc.).
            """
            
            response = self.api_call_with_backoff(self.model.generate_content, prompt)
            
            try:
                # Extract and parse JSON from response
                content_data = self.extract_json_from_response(response.text)
                
                # Clean up field names by removing any numbering
                cleaned_content_data = {}
                for key, value in content_data.items():
                    # Remove numbers and dots from the beginning of field names
                    clean_key = re.sub(r'^\d+\.\s*', '', key)
                    cleaned_content_data[clean_key] = value
                
                # If the AI couldn't determine a date but we found it in metadata, use the metadata date
                if (not cleaned_content_data.get("date_published") or 
                    cleaned_content_data.get("date_published") in ["Unknown", "Not found", "N/A"]) and publication_date:
                    cleaned_content_data["date_published"] = publication_date
                    
                # Add metadata
                cleaned_content_data["url"] = url
                cleaned_content_data["scraped_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                cleaned_content_data["search_query"] = self.user_query
                
                return cleaned_content_data
                
            except Exception as json_e:
                logging.error(f"Error parsing AI response as JSON: {str(json_e)}")
                
                # Return basic data
                basic_data = {
                    "url": url,
                    "title": title,
                    "search_query": self.user_query,
                    "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "date_published": publication_date if publication_date else "Unknown",
                    "raw_ai_analysis": response.text
                }
                
                return basic_data
                
        except Exception as e:
            logging.error(f"Error extracting content from {url}: {str(e)}")
            return None
    
    def extract_related_search_terms(self, content_data):
        """
        Extract related search terms from content
        
        Args:
            content_data (dict): Content data
            
        Returns:
            list: Related search terms
        """
        try:
            # Create a summary of the content
            content_summary = f"""
            Title: {content_data.get('title', 'Unknown')}
            Type: {content_data.get('content_type', 'Unknown')}
            Summary: {content_data.get('summary', 'Unknown')}
            Key Points: {content_data.get('key_points', [])}
            Categories: {content_data.get('categories', [])}
            """
            
            # Get domains we already have plenty of content from
            overrepresented_domains = [
                domain for domain, count in self.domain_counts.items() 
                if count >= self.max_per_domain - 1
            ]
            
            # Use AI to generate related search terms
            prompt = f"""
            Original search query: {self.user_query}
            
            Based on this content:
            
            {content_summary}
            
            Generate 5 specific search queries that would help find more DIVERSE content about this topic by:
            
            1. Focusing on subtopics or aspects not covered in this content
            2. Looking for complementary information from different perspectives
            3. Searching for more specialized information related to this topic
            4. Targeting content from different sources than we already have
            
            We already have sufficient content from these domains, so prefer queries that might find content elsewhere:
            {", ".join(overrepresented_domains) if overrepresented_domains else "No overrepresented domains yet"}
            
            IMPORTANT: All search queries must be closely related to the original search query "{self.user_query}".
            Make queries specific and varied to discover diverse content.
            
            Format your response as a JSON array of search queries only. Don't include other text.
            """
            
            response = self.api_call_with_backoff(self.model.generate_content, prompt)
            
            # Extract and parse JSON from response
            related_terms = self.extract_json_from_response(response.text)
            
            # Ensure we have a list
            if not isinstance(related_terms, list):
                related_terms = []
            
            logging.info(f"Generated {len(related_terms)} related search terms")
            return related_terms
            
        except Exception as e:
            logging.error(f"Error generating related search terms: {str(e)}")
            return []
    
    def normalize_url(self, url):
        """
        Normalize a URL to help detect duplicates even with minor differences
        
        Args:
            url (str): URL to normalize
            
        Returns:
            str: Normalized URL
        """
        try:
            # Parse the URL
            parsed_url = urlparse(url)
            
            # Convert to lowercase
            netloc = parsed_url.netloc.lower()
            path = parsed_url.path.lower()
            
            # Remove trailing slashes
            path = path.rstrip('/')
            
            # Remove common tracking parameters
            query_params = {}
            if parsed_url.query:
                for param in parsed_url.query.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        # Skip common tracking parameters
                        if key.lower() not in ['utm_source', 'utm_medium', 'utm_campaign', 
                                              'ref', 'source', 'fbclid', 'gclid']:
                            query_params[key] = value
            
            # Reconstruct query string
            query_string = "&".join([f"{k}={v}" for k, v in sorted(query_params.items())])
            
            # Reconstruct normalized URL
            normalized_url = f"{parsed_url.scheme}://{netloc}{path}"
            if query_string:
                normalized_url += f"?{query_string}"
            
            return normalized_url
        
        except Exception as e:
            logging.error(f"Error normalizing URL {url}: {str(e)}")
            return url
    
    def get_content_fingerprint(self, content_data):
        """
        Generate a fingerprint of content to detect similar content
        
        Args:
            content_data (dict): Content data
            
        Returns:
            dict: Content fingerprint with key features
        """
        try:
            # Extract key features for fingerprinting
            title = content_data.get('title', '').lower()
            summary = content_data.get('summary', '').lower()
            key_points = str(content_data.get('key_points', [])).lower()
            
            # Create a simplified representation of the content
            fingerprint = {
                'title': title,
                'summary_length': len(summary),
                'summary_start': summary[:100] if len(summary) > 100 else summary,
                'key_points_hash': hash(key_points) % 10000000
            }
            
            return fingerprint
            
        except Exception as e:
            logging.error(f"Error generating content fingerprint: {str(e)}")
            return {'error': str(e)}
    
    def is_similar_content(self, content_data):
        """
        Check if content is similar to already scraped content
        
        Args:
            content_data (dict): Content data
            
        Returns:
            bool: True if content is similar to existing content, False otherwise
        """
        try:
            # Generate fingerprint for this content
            new_fingerprint = self.get_content_fingerprint(content_data)
            
            # Compare with existing fingerprints
            for existing_fingerprint in self.content_fingerprints:
                # Check title similarity
                if existing_fingerprint.get('title') and new_fingerprint.get('title'):
                    # If titles are very similar
                    if existing_fingerprint['title'] == new_fingerprint['title']:
                        logging.info(f"Duplicate content detected: Identical title")
                        return True
                    
                    # Check if one title is contained within the other
                    if (len(existing_fingerprint['title']) > 20 and 
                        len(new_fingerprint['title']) > 20 and
                        (existing_fingerprint['title'] in new_fingerprint['title'] or 
                         new_fingerprint['title'] in existing_fingerprint['title'])):
                        logging.info(f"Similar content detected: Similar title")
                        return True
                
                # Check summary similarity
                if (existing_fingerprint.get('summary_start') and 
                    new_fingerprint.get('summary_start') and 
                    len(existing_fingerprint['summary_start']) > 50 and
                    len(new_fingerprint['summary_start']) > 50):
                    
                    # If the start of summaries are similar
                    similarity = self.calculate_text_similarity(
                        existing_fingerprint['summary_start'], 
                        new_fingerprint['summary_start']
                    )
                    
                    if similarity > self.similarity_threshold:
                        logging.info(f"Similar content detected: Summary similarity {similarity:.2f}")
                        return True
                
                # Check key points similarity
                if existing_fingerprint.get('key_points_hash') == new_fingerprint.get('key_points_hash'):
                    logging.info(f"Similar content detected: Identical key points")
                    return True
            
            # No similar content found
            return False
            
        except Exception as e:
            logging.error(f"Error checking content similarity: {str(e)}")
            return False
    
    def calculate_text_similarity(self, text1, text2):
        """
        Calculate similarity between two text strings
        
        Args:
            text1 (str): First text
            text2 (str): Second text
            
        Returns:
            float: Similarity score (0-1)
        """
        try:
            # Convert to sets of words
            words1 = set(text1.split())
            words2 = set(text2.split())
            
            # Calculate Jaccard similarity
            if not words1 or not words2:
                return 0
                
            intersection = len(words1.intersection(words2))
            union = len(words1.union(words2))
            
            return intersection / union
            
        except Exception as e:
            logging.error(f"Error calculating text similarity: {str(e)}")
            return 0
    
    def check_domain_quota(self, url):
        """
        Check if we've reached the quota for a domain
        
        Args:
            url (str): URL to check
            
        Returns:
            bool: True if domain is within quota, False if quota exceeded
        """
        try:
            domain = urlparse(url).netloc.lower()
            
            # Update domain count
            current_count = self.domain_counts.get(domain, 0)
            
            # Check if we've reached the limit for this domain
            if current_count >= self.max_per_domain:
                logging.info(f"Domain quota exceeded for {domain}: {current_count}/{self.max_per_domain}")
                return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error checking domain quota for {url}: {str(e)}")
            return True  # Proceed if there's an error
    
    def save_content_data(self, content_data):
        """Save content data to a file"""
        try:
            # Extract a filename from the title or URL
            if "title" in content_data and content_data["title"] and content_data["title"] != "Unknown":
                filename_base = content_data["title"]
            else:
                # Extract from URL
                url_parts = urlparse(content_data["url"])
                path = url_parts.path.strip('/')
                if path:
                    filename_base = path.split('/')[-1]
                else:
                    filename_base = url_parts.netloc
            
            # Clean up filename
            filename_base = re.sub(r'[^\w\-]', '_', filename_base)
            filename_base = filename_base[:50]  # Limit length
            
            # Create unique filename
            filename = f"{filename_base}_{int(time.time())}.json"
            
            # Save to file
            filepath = f"data/content/{filename}"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(content_data, f, indent=2, ensure_ascii=False)
                
            logging.info(f"Saved content data to {filepath}")
            
            return filepath
            
        except Exception as e:
            logging.error(f"Error saving content data: {str(e)}")
            return None
    
    def find_more_links_on_page(self, url, html_content):
        """
        Find more potentially relevant links on a content page
        
        Args:
            url (str): URL of the page
            html_content (str): HTML content of the page
            
        Returns:
            list: URLs of potential content pages
        """
        try:
            # Extract all links from the page
            all_links = self.extract_all_links(url, html_content)
            
            # Use AI to identify potentially relevant links
            prompt = f"""
            I'm looking for more content about "{self.user_query}".
            
            I've found these links on a relevant page:
            
            {json.dumps(all_links[:30], indent=2)}
            
            Please identify which of these links are most likely to lead to more relevant content about "{self.user_query}".
            Consider:
            - Links to related articles
            - Links to more in-depth information
            - Links to subtopics within the main topic
            
            Format your response as a JSON array of URLs that are most likely to contain relevant content.
            Only include URLs that seem promising for more information about {self.user_query}.
            """
            
            response = self.api_call_with_backoff(self.model.generate_content, prompt)
            
            # Extract JSON from response
            response_text = response.text
            
            # Parse the response
            potential_links = self.extract_json_from_response(response_text)
            
            # Ensure we have a list
            if not isinstance(potential_links, list):
                potential_links = []
                
                # Fallback to domain-based filtering
                for link in all_links[:10]:
                    if self.is_likely_content_domain(link):
                        potential_links.append(link)
            
            logging.info(f"Found {len(potential_links)} potentially relevant links on page")
            
            return potential_links
            
        except Exception as e:
            logging.error(f"Error finding more links on {url}: {str(e)}")
            return []
    
    def crawl_for_content(self, max_content=15, max_pages=50):
        """
        Crawl the web for content based on user query
        
        Args:
            max_content (int): Maximum number of content pieces to collect
            max_pages (int): Maximum number of pages to visit
            
        Returns:
            dict: Crawl statistics
        """
        # First, prompt the user for their query
        self.user_query = self.prompt_user_for_query()
        
        stats = {
            "search_queries_used": 0,
            "pages_visited": 0,
            "content_found": 0,
            "errors": 0,
            "duplicates_skipped": 0,
            "similar_content_skipped": 0,
            "domain_quota_exceeded": 0
        }
        
        print(f"\nSearching for content about: {self.user_query}")
        print("Crawling has started. This may take a few minutes...\n")
        
        # Generate variations of the original query with emphasis on recent content
        current_year = time.strftime("%Y")
        search_queries = [
            self.user_query,
            f"latest {self.user_query} {current_year}",
            f"{self.user_query} recent developments",
            f"{self.user_query} recent research",
            f"{self.user_query} updated {current_year}"
        ]
        
        # Create queues for search queries and potential content URLs
        search_queue = list(search_queries)
        content_url_queue = []
        
        # Track saved content for reporting
        saved_content = []
        
        # Set to track normalized URLs to avoid duplicates
        normalized_urls = set()
        
        # Crawl until we find enough content or run out of pages to visit
        while stats["pages_visited"] < max_pages and stats["content_found"] < max_content and (search_queue or content_url_queue):
            # Priority: First check direct content URLs, then do new searches
            if content_url_queue:
                # Process a potential content URL
                url = content_url_queue.pop(0)
                
                # Normalize the URL to help detect duplicates
                normalized_url = self.normalize_url(url)
                
                # Skip if we've already visited this URL (even if slightly different)
                if normalized_url in normalized_urls:
                    logging.info(f"Skipping duplicate URL: {url}")
                    stats["duplicates_skipped"] += 1
                    continue
                
                # Check domain quota
                if not self.check_domain_quota(url):
                    logging.info(f"Skipping due to domain quota: {url}")
                    stats["domain_quota_exceeded"] += 1
                    continue
                
                # Add to normalized URLs
                normalized_urls.add(normalized_url)
                
                # Mark as visited
                self.visited_urls.add(url)
                stats["pages_visited"] += 1
                
                logging.info(f"Visiting potential content page: {url}")
                print(f"Checking: {url}")
                
                # Fetch the page
                html_content = self.fetch_url(url)
                if not html_content:
                    stats["errors"] += 1
                    continue
                
                # Check if this page has relevant content
                is_relevant = False
                try:
                    is_relevant = self.is_relevant_content(url, html_content)
                except Exception as e:
                    logging.error(f"Error checking if {url} has relevant content: {str(e)}")
                    stats["errors"] += 1
                    continue
                
                if is_relevant:
                    logging.info(f"Found relevant content: {url}")
                    print(f"Found relevant content: {url}")
                    
                    # Extract content data
                    try:
                        content_data = self.extract_content_data(url, html_content)
                        
                        if content_data:
                            # Check for similar content
                            if self.is_similar_content(content_data):
                                logging.info(f"Skipping similar content: {url}")
                                stats["similar_content_skipped"] += 1
                                continue
                                
                            # Save content data
                            filepath = self.save_content_data(content_data)
                            
                            if filepath:
                                # Track content found
                                self.content_urls.add(url)
                                stats["content_found"] += 1
                                
                                # Update domain count
                                domain = urlparse(url).netloc.lower()
                                self.domain_counts[domain] = self.domain_counts.get(domain, 0) + 1
                                
                                # Add content fingerprint to help detect duplicates
                                self.content_fingerprints.append(self.get_content_fingerprint(content_data))
                                
                                saved_content.append({
                                    "title": content_data.get("title", "Unknown"),
                                    "url": url,
                                    "filepath": filepath,
                                    "date_published": content_data.get("date_published", "Unknown date"),
                                    "relevance_score": content_data.get("relevance_score", 0)
                                })
                                
                                # Log progress
                                print(f"Progress: {stats['content_found']}/{max_content} content items found")
                                
                                # Extract related search terms from content
                                related_terms = self.extract_related_search_terms(content_data)
                                for term in related_terms:
                                    if term not in search_queue and not any(term == q for q in search_queries):
                                        search_queue.append(term)
                            
                            # Find more potential content links on this page
                            more_links = self.find_more_links_on_page(url, html_content)
                            for link in more_links:
                                # Skip if we've already visited or queued
                                normalized_link = self.normalize_url(link)
                                if normalized_link not in normalized_urls and link not in content_url_queue:
                                    content_url_queue.append(link)
                    except Exception as e:
                        logging.error(f"Error processing content at {url}: {str(e)}")
                        stats["errors"] += 1
            
            elif search_queue:
                # Do a new search
                query = search_queue.pop(0)
                
                logging.info(f"Processing search query: {query}")
                print(f"Searching for: {query}")
                stats["search_queries_used"] += 1
                
                # Search for potential content
                potential_content_urls = self.search_for_content(query)
                
                # Add discovered URLs to the queue
                for url in potential_content_urls:
                    if url not in self.visited_urls and url not in content_url_queue:
                        content_url_queue.append(url)
            
            # Check if we've reached our limits
            if stats["content_found"] >= max_content or stats["pages_visited"] >= max_pages:
                break
            
            # If both queues are empty but we haven't reached our targets,
            # generate more search queries based on what we've found
            if not search_queue and not content_url_queue:
                if stats["content_found"] > 0:
                    # Use a different variation of the original query
                    logging.info("Generating more search queries...")
                    new_queries = [
                        f"{self.user_query} key insights",
                        f"important information about {self.user_query}",
                        f"{self.user_query} complete guide",
                        f"what you need to know about {self.user_query}"
                    ]
                    
                    for query in new_queries:
                        if query not in search_queries:
                            search_queue.append(query)
                            search_queries.append(query)
                else:
                    # If we haven't found any content yet, try broader variations
                    logging.info("Trying broader search queries...")
                    broader_queries = [
                        f"{self.user_query} overview",
                        f"introduction to {self.user_query}",
                        f"basics of {self.user_query}",
                        f"{self.user_query} for beginners"
                    ]
                    
                    for query in broader_queries:
                        if query not in search_queries:
                            search_queue.append(query)
                            search_queries.append(query)
            
            # Small delay between operations
            time.sleep(random.uniform(0.5, 1))
        
        # Print summary of results
        print("\n" + "="*50)
        print(f"CONTENT SCRAPING SUMMARY FOR: {self.user_query}")
        print("="*50)
        print(f"Pages visited: {stats['pages_visited']}")
        print(f"Search queries used: {stats['search_queries_used']}")
        print(f"Relevant content found: {stats['content_found']}")
        print(f"Duplicates skipped: {stats['duplicates_skipped']}")
        print(f"Similar content skipped: {stats['similar_content_skipped']}")
        print(f"Domain quota exceeded: {stats['domain_quota_exceeded']}")
        print(f"Errors encountered: {stats['errors']}")
        
        # Print domain distribution
        print("\nDOMAIN DISTRIBUTION:")
        for domain, count in sorted(self.domain_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"{domain}: {count} items")
        
        if saved_content:
            # Sort saved content by relevance score (if available) and date (if available)
            # This brings the most relevant and recent content to the top of the list
            sorted_content = sorted(saved_content, key=lambda x: (
                -(x.get("relevance_score", 0) or 0),  # Higher relevance first
                # Try to parse date - items with unparseable dates will go to the end
                0 if x.get("date_published", "").lower() in ["unknown", "unknown date", ""] else -1
            ))
            
            print("\nSCRAPED CONTENT (ordered by relevance and recency):")
            for i, content in enumerate(sorted_content):
                print(f"{i+1}. {content['title']}")
                print(f"   URL: {content['url']}")
                print(f"   Published: {content['date_published']}")
                print(f"   Saved to: {content['filepath']}")
                print()
        
        return stats

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="AI-driven Content Scraper with Google Custom Search API integration")
    parser.add_argument("--max-content", type=int, default=15, help="Maximum number of content pieces to collect")
    parser.add_argument("--max-pages", type=int, default=50, help="Maximum number of pages to visit")
    args = parser.parse_args()
    
    logging.info("Starting AI Content Scraper with Google Custom Search API")
    print("\n" + "="*60)
    print("AI CONTENT SCRAPER WITH GOOGLE CUSTOM SEARCH")
    print("="*60)
    print("This enhanced crawler uses Google Custom Search API")
    print("to find the most relevant and recent content for your query.")
    print("Default content limit increased to 15 items.")
    print("Duplicate detection enabled to avoid repetitive content.")
    print("Domain diversity controls ensure content from various sources.")
    print("="*60 + "\n")
    
    crawler = AIContentCrawler()
    
    # Start crawling based on user query
    stats = crawler.crawl_for_content(
        max_content=args.max_content, 
        max_pages=args.max_pages
    )
    
    logging.info("Crawl completed!")
    logging.info(f"Search queries used: {stats['search_queries_used']}")
    logging.info(f"Pages visited: {stats['pages_visited']}")
    logging.info(f"Content found: {stats['content_found']}")
    logging.info(f"Duplicates skipped: {stats.get('duplicates_skipped', 0)}")
    logging.info(f"Similar content skipped: {stats.get('similar_content_skipped', 0)}")
    logging.info(f"Domain quota exceeded: {stats.get('domain_quota_exceeded', 0)}")
    logging.info(f"Errors: {stats['errors']}")

if __name__ == "__main__":
    main()
