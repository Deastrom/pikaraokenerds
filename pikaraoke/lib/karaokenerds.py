#!/usr/bin/env python

import os
import json
import asyncio
import requests
import subprocess
from bs4 import BeautifulSoup
from dataclasses import dataclass
import re
from typing import List, Dict, Any
from pikaraoke.lib.current_app import get_karaoke_instance
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Function to fetch and parse JSON data asynchronously with retries
async def fetch_json(url, retries=3):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=120.0)  # Increase the timeout value
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                print(f"Timeout occurred while fetching {url}. Retrying... ({attempt + 1}/{retries})")
                await asyncio.sleep(2)  # Wait before retrying
            else:
                print(f"Failed to fetch {url} after {retries} attempts.")
                raise

# Function to extract song data from JSON response
def extract_karaokenerds_data(data):
    songs = []
    for item in data['data']:
        artist_html, title_html, _, brand_html, youtube_html = item[1:6]
        artist = BeautifulSoup(artist_html, 'html.parser').get_text(strip=True)
        title = BeautifulSoup(title_html, 'html.parser').get_text(strip=True)
        brand = BeautifulSoup(brand_html, 'html.parser').get_text(strip=True)
        youtube_url = youtube_html.split('|')[0].split('&')[0]
        songs.append({
            'Title': title,
            'Artist': artist,
            'Watch': youtube_url,
            'Brand': brand
        })
    return songs

@dataclass
class ChannelPattern:
    name: str
    url: str
    patterns: list[str]  # Multiple patterns per channel
    brand: str

CHANNEL_PATTERNS = {
    'karafun': ChannelPattern(
        name='karafun',
        url='https://www.youtube.com/@karafun',
        patterns=[
            r'^(?P<title>.*?)\s*-\s*(?P<artist>.*?)\s*\|\s*Karaoke Version',
        ],
        brand='KaraFun'
    ),
    'singking': ChannelPattern(
        name='singking',
        url='https://www.youtube.com/@singkingkaraoke',
        patterns=[
            r'^(?P<artist>.*?)\s*-\s*(?P<title>.*?)\s*\(Karaoke Version\)',
        ],
        brand='Sing King'
    ),
    'seauxphie5765': ChannelPattern(
        name='seauxphie5765',
        url='https://www.youtube.com/@seauxphie5765',
        patterns=[
            r'^(?P<artist>.*?)\s*-\s*(?P<title>.*?)\s*\(Karaoke Version\)',
        ],
        brand='Seauxphie5765'
    )
}

def extract_song_data(item: dict, pattern: ChannelPattern) -> dict:
    logger.debug(f"Processing title: {item['title']}")
    
    for p in pattern.patterns:
        match = re.match(p, item['title'], re.IGNORECASE)
        if match:
            groups = match.groupdict()
            logger.debug(f"Matched {pattern.name} with: {p}")
            return {
                'Title': groups['title'].strip(),
                'Artist': groups['artist'].strip(),
                'Watch': f"https://www.youtube.com/watch?v={item['id']}",
                'Brand': pattern.brand
            }
    
    logger.debug(f"No match for {pattern.name}: {item['title']}")
    return None

def extract_channel_songs(data: list, pattern: ChannelPattern) -> list:
    return [song for item in data 
            if (song := extract_song_data(item, pattern)) is not None]

async def run_ytdlp(url: str) -> List[Dict[str, Any]]:
    logger.info(f"Fetching playlist data from {url}...")
    cmd = [
        'yt-dlp',
        '--flat-playlist',
        '--dump-json',
        url
    ]
    
    try:
        # Run yt-dlp command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"yt-dlp failed: {stderr.decode()}")
            
        # Parse JSON output (one JSON object per line)
        entries = []
        for line in stdout.decode().splitlines():
            if line.strip():
                entries.append(json.loads(line))
                
        logger.info(f"Found {len(entries)} videos for {url}")
        return entries
        
    except Exception as e:
        logger.error(f"Failed to fetch playlist: {str(e)}")
        raise

async def fetch_and_extract_channel(pattern: ChannelPattern):
    """Fetch and extract songs for a single channel"""
    try:
        data = await run_ytdlp(pattern.url)
        return extract_channel_songs(data, pattern)
    except Exception as e:
        logger.error(f"Error processing {pattern.name}: {e}")
        return []

async def fetch_karaokenerds_songs(base_url, total_records, length, semaphore):
    tasks = []
    for start in range(0, total_records, length):
        async with semaphore:
            tasks.append(fetch_json(base_url + str(start)))

    results = await asyncio.gather(*tasks)
    return [song for result in results for song in extract_karaokenerds_data(result)]

async def _scrape():
    # Fetch the initial page to get the total number of records
    base_url = 'https://karaokenerds.com/Community/BrowseJson/?length=1&start='
    initial_data = await fetch_json(base_url + '0')
    total_records = initial_data['recordsTotal']

    length = 5000
    base_url = f'https://karaokenerds.com/Community/BrowseJson/?length={length}&start='
    semaphore = asyncio.Semaphore(15)

    # Fetch and extract songs from Karaokenerds
    logger.info("Fetching songs from Karaokenerds...")
    karaokenerds_songs_task = fetch_karaokenerds_songs(base_url, total_records, length, semaphore)

    # Fetch and process YouTube channels in parallel
    channel_tasks = [fetch_and_extract_channel(pattern) for pattern in CHANNEL_PATTERNS.values()]
    all_results = await asyncio.gather(karaokenerds_songs_task, *channel_tasks)
    
    # Combine all songs
    all_songs = []
    for songs in all_results:
        all_songs.extend(songs)
    
    # Sort the songs by artist, then by title, then by brand
    all_songs.sort(key=lambda x: (x['Artist'], x['Title'], x['Brand']))

    # Save the extracted data to a JSON file
    output_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'karaokenerds-songs.json')
    with open(output_file, 'w', encoding='utf-8') as jsonfile:
        json.dump({'Items': all_songs}, jsonfile, ensure_ascii=False, indent=4)
    logger.info("Songs data saved to karaokenerds-songs.json")

def scrape():
    try:
        asyncio.run(_scrape())
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" in str(e):
            print("Refresh is already running.")
        else:
            raise
