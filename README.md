# AI Content Crawler

This smart web crawler finds and collects content based on what you're looking for. It uses Google's Gemini AI and search tools to gather info on any topic while making sure you get diverse and relevant results.

## What it does

- Uses AI to find and analyze good content
- Searches Google to get accurate results
- Checks if content is actually relevant before saving it
- Makes sure you don't get too much stuff from just one website
- Avoids saving duplicate or very similar content
- Comes up with related search terms to find more varied content
- Respects website rate limits
- Tries to figure out how fresh the content is
- Makes sure your results come from different sources

## Getting started

1. Clone this repo:
```bash
git clone [https://github.com/ibedevesh/ai-crawler.git](https://github.com/ibedevesh/AI_Crawler.git)
cd ai-crawler
```

2. Install what you need:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your API keys:
```
GOOGLE_API_KEY=your_gemini_api_key_here
GOOGLE_MODEL=gemini-2.0-flash
```

## How to use it

Run it with default settings:
```bash
python ai_crawler.py
```

Or customize how much it collects:
```bash
python ai_crawler.py --max-content 20 --max-pages 75
```

When you run it:
1. Type in what you're looking for (like "AI news latest")
2. Choose how many articles to grab from each website
3. The tool starts hunting for content
4. Everything gets saved in the `data/content` folder as JSON files
5. You'll see a summary when it's done

## Command options

- `--max-content`: How many articles to collect (default: 15)
- `--max-pages`: How many web pages to check (default: 50)

## What you get

The crawler saves JSON files with:

- Title and link
- When it was published (if available)
- A summary
- Main points
- The full text
- Author info (if available)
- Content type (article, blog post, etc.)
- How relevant it is (1-10)
- Topics covered

## Logs

The tool keeps track of what it's doing in `ai_content_crawler.log`, including:

- Search terms it used
- Pages it visited
- Content it found
- Any errors
- Results from AI analysis

## What you need

- Python 3.7+
- Google Gemini API key
- Internet connection
- Required Python packages

## How it works

1. Starts with your search query
2. Uses Google to find potential content
3. Uses AI to check if each page is relevant
4. Extracts, summarizes and saves good content
5. Comes up with related searches to find more
6. Keeps going until it finds enough content

## License

MIT License

