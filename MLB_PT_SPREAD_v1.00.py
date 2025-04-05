import streamlit as st
import pandas as pd
import requests
from datetime import date
import math

st.set_page_config(layout="wide")

# --- Configuration ---
API_KEY = '8c20c59342e07c830e73aa8e6506b1c3'  # Replace with your actual API key
SPORT = 'baseball_mlb'
REGIONS = 'us'  # Regions: us, uk, eu, au
MARKETS = 'spreads,totals'  # Betting markets: h2h, spreads, totals
ODDS_FORMAT = 'american'  # Odds format: decimal or american

# --- Cached API fetch ---
@st.cache_data(ttl=3600)
def fetch_json(url, headers=None):
    try:
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_schedule(selected_date):
    d = selected_date.strftime("%Y-%m-%d")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"
    data = fetch_json(url)
    games = []
    for game in data.get('dates', [{}])[0].get('games', []):
        games.append({
            'game_id': game['gamePk'],
            'away': game['teams']['away']['team']['name'],
            'home': game['teams']['home']['team']['name'],
            'home_id': game['teams']['home']['team']['id'],
            'away_id': game['teams']['away']['team']['id']
        })
    return pd.DataFrame(games)

def get_probable_pitchers(game_id):
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live"
    data = fetch_json(url)
    pp = data.get('gameData', {}).get('probablePitchers', {})
    return {
        'home': pp.get('home', {}).get('id'),
        'away': pp.get('away', {}).get('id'),
        'home_name': pp.get('home', {}).get('fullName', 'N/A'),
        'away_name': pp.get('away', {}).get('fullName', 'N/A'),
    }

@st.cache_data(ttl=3600)
def fetch_stats(player_id, group):
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=career&group={group}"
    data = fetch_json(url)
    if data.get('stats'):
        return data['stats'][0].get('splits', [{}])[0].get('stat', {})
    return {}

def pitcher_score(stat):
    try:
        era = float(stat.get('era', 5.0))
        k9 = float(stat.get('strikeoutsPer9Inn', 6.0))
        bb9 = float(stat.get('walksPer9Inn', 3.0))
        score = (5.0 - era) * 12 + (k9 - 6.0) * 8 + (3.0 - bb9) * 5
        return max(0, min(100, score))
    except:
        return 50

@st.cache_data(ttl=3600)
def fetch_roster(team_id):
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
    data = fetch_json(url)
    return [p['person']['id'] for p in data.get('roster', [])]

def hitter_score(player_ids):
    scores = []
    for pid in player_ids:
        s = fetch_stats(pid, 'hitting')
        try:
            avg = float(s.get('avg', 0.250))
            obp = float(s.get('obp', 0.320))
            slg = float(s.get('slg', 0.400))
            val = (avg - 0.250) * 100 + (obp - 0.320) * 80 + (slg - 0.400) * 60
            scores.append(max(0, min(100, val)))
        except:
            continue
    return sum(scores) / len(scores) if scores else 50

# --- Spread & Total Model ---
def predict_margin(home_p, away_p, home_h, away_h):
    return round((home_p - away_p) * 0.4 + (home_h - away_h) * 0.6, 2)

def predict_total(home_p, away_p, home_h, away_h):
    return round((home_h + away_h) * 0.1 - (home_p + away_p) * 0.08 + 8.5, 2)

# --- Fetch Vegas Lines ---
@st.cache_data(ttl=3600)
def fetch_vegas_lines():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds?regions={REGIONS}&markets={MARKETS}&oddsFormat={ODDS_FORMAT}&apiKey={API_KEY}"
    return fetch_json(url)

def extract_vegas_odds(vegas_data, home_team, away_team):
    for game in vegas_data:
        if game['home_team'] == home_team and game['away_team'] == away_team:
            spreads = None
            totals = None
            for bookmaker in game.get('bookmakers', []):
                for market in bookmaker.get('markets', []):
                    if market['key'] == 'spreads':
                        spreads = market['outcomes']
                    elif market['key'] == 'totals':
                        totals = market['outcomes']
            return spreads, totals
    return None, None

# --- Streamlit App ---
st.title("⚾ MLB Spread & Total Predictor with Vegas Lines")

selected_date = st.date_input("Select Game Date", date.today())
games_df = fetch_schedule(selected_date)

if games_df.empty:
    st.warning("No games found.")
    st.stop()

vegas_data = fetch_vegas_lines()

results = []
team_rosters = {}

def get_cached_roster(team_id):
    if team_id not in team_rosters:
        team_rosters[team_id] = fetch_roster(team_id)
    return team_rosters[team_id]

progress = st.progress(0)

with st.spinner("Running model predictions..."):
    progress = st.progress(0)

    for i, (_, game) in enumerate(games_df.iterrows()):
        # your loop logic...
        progress.progress((i + 1) / len(games_df))



 
